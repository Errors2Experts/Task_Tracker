import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.forms import formset_factory
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from django.conf import settings
from django.views.decorators.http import require_GET, require_POST

import cloudinary.uploader
from django.urls import reverse

from apps.accounts.models import Designation, Role
from apps.accounts.permissions import (
    get_assignable_employees, can_assign_to, get_roster_scope_message,
    get_visible_tasks_queryset, is_employee_tier,
    get_team_lead_reviewers, can_review_team_lead_approval,
    can_view_my_team, get_my_team_queryset, get_my_team_scope_message,
)
from .forms import TaskAttachmentForm, TaskCommentForm, TaskEditForm, TaskRowForm, TaskStatusProgressForm
from .models import (
    PushSubscription, Task, TaskActivity, TaskNotification, TaskPriority, TaskStatus, TaskAttachment,
    TeamLeadApprovalStatus,
)
from .permissions import (
    can_comment_or_attach, can_delete_attachment, can_edit_task_fields,
    can_update_status_progress, can_view_task,
)

User = get_user_model()

TaskRowFormSet = formset_factory(TaskRowForm, extra=1, can_delete=True)

PAGE_SIZE = 20


def _attach_overdue_flag(tasks):
    return list(tasks)


def _recent_activity(tasks_qs, limit=6):
    """Recent activity feed, built from real logged events (TaskActivity) —
    not guessed from timestamps, so multiple events on one task each show up,
    and the verb shown is exactly what happened."""
    entries = (
        TaskActivity.objects.filter(task__in=tasks_qs)
        .select_related("task", "task__assigned_to")
        .order_by("-created_at")[:limit]
    )
    activity = []
    for entry in entries:
        who = entry.task.assigned_to
        if not who:
            continue
        # A freshly-created task is "Pending" in the feed regardless of its
        # current status (which may have moved on since).
        pill_status = TaskStatus.PENDING if entry.verb == "CREATED" else entry.verb
        if pill_status not in TaskStatus.values:
            pill_status = entry.task.status
        activity.append({
            "user": who,
            "action": entry.description(),
            "status": pill_status,
            "status_display": dict(TaskStatus.choices).get(pill_status, pill_status),
            "created_at": entry.created_at,
        })
    return activity


def _task_previews(tasks_qs, limit=3):
    """Lightweight preview rows for the dashboard's "Recent tasks" list —
    newest first, with just enough fields to render a roster-style row."""
    tasks = list(
        tasks_qs.select_related("assigned_to", "team").order_by("-created_at")[:limit]
    )
    return _attach_overdue_flag(tasks)


def _overdue_previews(tasks_qs, limit=3):
    """Preview rows for the dashboard's "Overdue tasks" list — soonest-missed
    due date first, so the most urgent items surface at the top."""
    flagged = _attach_overdue_flag(
        tasks_qs.select_related("assigned_to", "team").exclude(due_date=None)
    )
    overdue = [t for t in flagged if t.is_overdue]
    overdue.sort(key=lambda t: t.due_date)
    return overdue[:limit]


def _employee_summary(user, limit=3):
    """Per-employee open/completed task counts for the dashboard's "Employee
    summary" panel. Reuses the same roster scoping as the Task assign page,
    so nobody sees a workload breakdown for people outside their access."""
    employees = get_assignable_employees(user, User).select_related("team").annotate(
        open_count=Count(
            "assigned_tasks",
            filter=Q(assigned_tasks__status__in=[TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS]),
        ),
        completed_count=Count(
            "assigned_tasks", filter=Q(assigned_tasks__status=TaskStatus.COMPLETED),
        ),
    ).order_by("-open_count", "first_name", "last_name")[:limit]
    return employees


def _priority_breakdown(tasks_qs):
    """Open (not-yet-completed) task counts by priority, for the priority chart."""
    counts = (
        tasks_qs.exclude(status=TaskStatus.COMPLETED)
        .values("priority").annotate(n=Count("id"))
    )
    by_priority = {row["priority"]: row["n"] for row in counts}
    return [by_priority.get(value, 0) for value, _ in TaskPriority.choices]


def _weekly_completion_trend(tasks_qs, days=7):
    """Completed-task count for each of the last `days` days, oldest first —
    powers the dashboard's completion trend chart."""
    today = timezone.localdate()
    start = today - timezone.timedelta(days=days - 1)
    counts = (
        tasks_qs.filter(status=TaskStatus.COMPLETED, updated_at__date__gte=start)
        .values("updated_at__date").annotate(n=Count("id"))
    )
    by_day = {row["updated_at__date"]: row["n"] for row in counts}
    labels, series = [], []
    for i in range(days):
        day = start + timezone.timedelta(days=i)
        labels.append(day.strftime("%d %b"))
        series.append(by_day.get(day, 0))
    return labels, series


@login_required
def dashboard(request):
    user = request.user
    context = {}
    today = timezone.localdate()
    week_ago = today - timezone.timedelta(days=7)
    soon = today + timezone.timedelta(days=3)

    if is_employee_tier(user):
        my_tasks_qs = Task.objects.filter(assigned_to=user)
        counts = my_tasks_qs.values("status").annotate(n=Count("id"))
        by_status = {row["status"]: row["n"] for row in counts}
        stats = {
            "total": my_tasks_qs.count(),
            "pending": by_status.get(TaskStatus.PENDING, 0),
            "in_progress": by_status.get(TaskStatus.IN_PROGRESS, 0),
            "blocked": by_status.get(TaskStatus.BLOCKED, 0),
            "completed": by_status.get(TaskStatus.COMPLETED, 0),
            "overdue": sum(1 for t in _attach_overdue_flag(my_tasks_qs) if t.is_overdue),
            "due_soon": my_tasks_qs.filter(due_date__gte=today, due_date__lte=soon).exclude(status=TaskStatus.COMPLETED).count(),
            "completed_this_week": my_tasks_qs.filter(status=TaskStatus.COMPLETED, updated_at__date__gte=week_ago).count(),
        }
        context["my_stats"] = stats
        context["recent_activity"] = _recent_activity(my_tasks_qs)
        context["recent_tasks"] = _task_previews(my_tasks_qs)
        context["overdue_tasks"] = _overdue_previews(my_tasks_qs)
        trend_labels, trend_series = _weekly_completion_trend(my_tasks_qs)
        status_counts = [stats["pending"], stats["in_progress"], stats["blocked"], stats["completed"]]
        priority_counts = _priority_breakdown(my_tasks_qs)
    else:
        visible = get_visible_tasks_queryset(user, Task)
        counts = visible.values("status").annotate(n=Count("id"))
        by_status = {row["status"]: row["n"] for row in counts}
        stats = {
            "total": visible.count(),
            "pending": by_status.get(TaskStatus.PENDING, 0),
            "in_progress": by_status.get(TaskStatus.IN_PROGRESS, 0),
            "blocked": by_status.get(TaskStatus.BLOCKED, 0),
            "completed": by_status.get(TaskStatus.COMPLETED, 0),
            "overdue": sum(1 for t in _attach_overdue_flag(visible) if t.is_overdue),
            "due_soon": visible.filter(due_date__gte=today, due_date__lte=soon).exclude(status=TaskStatus.COMPLETED).count(),
            "completed_this_week": visible.filter(status=TaskStatus.COMPLETED, updated_at__date__gte=week_ago).count(),
        }
        context["team_stats"] = stats
        if user.designation != "HR":
            context["team_size"] = get_assignable_employees(user, User).count()
            context["employee_summary"] = _employee_summary(user)
        context["access_scope_message"] = get_roster_scope_message(user) if user.designation != "HR" else "You can view every task in the company, read-only."
        context["recent_activity"] = _recent_activity(visible)
        context["recent_tasks"] = _task_previews(visible)
        context["overdue_tasks"] = _overdue_previews(visible)
        trend_labels, trend_series = _weekly_completion_trend(visible)
        status_counts = [stats["pending"], stats["in_progress"], stats["blocked"], stats["completed"]]
        priority_counts = _priority_breakdown(visible)

    context["chart_data"] = json.dumps({
        "statusLabels": ["Pending", "In Progress", "Blocked", "Completed"],
        "statusCounts": status_counts,
        "priorityLabels": [label for _, label in TaskPriority.choices],
        "priorityCounts": priority_counts,
        "trendLabels": trend_labels,
        "trendCounts": trend_series,
    })

    return render(request, "tasks/dashboard.html", context)


@login_required
def task_assign_list(request):
    employees = get_assignable_employees(request.user, User).select_related("team")

    query = request.GET.get("q", "").strip()
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
        )

    employees = employees.annotate(
        open_count=Count(
            "assigned_tasks",
            filter=Q(assigned_tasks__status__in=[TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS]),
        )
    ).order_by("first_name", "last_name")

    paginator = Paginator(employees, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "employees": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "scope_message": get_roster_scope_message(request.user),
    }
    return render(request, "tasks/task_assign_list.html", context)


@login_required
def my_team(request):
    if not can_view_my_team(request.user):
        raise PermissionDenied("You don't have permission to view a team roster.")

    members = get_my_team_queryset(request.user, User).select_related("team")

    query = request.GET.get("q", "").strip()
    if query:
        members = members.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
        )

    members = members.annotate(
        open_count=Count(
            "assigned_tasks",
            filter=Q(assigned_tasks__status__in=[TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS]),
        )
    ).order_by("first_name", "last_name")

    paginator = Paginator(members, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "members": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "scope_message": get_my_team_scope_message(request.user),
    }
    return render(request, "tasks/my_team.html", context)


@login_required
def task_assign_form(request, employee_id):
    employee = get_object_or_404(User, pk=employee_id)

    if not can_assign_to(request.user, employee):
        raise PermissionDenied("You don't have permission to assign tasks to this employee.")

    # "Team Lead Approved" checkbox is only relevant for a cross-team
    # assignment made by a Team Lead — if the assigner and the employee are
    # already on the same team, there's nobody else who needs to sign off.
    # Admin, Manager, HR, and dept-scoped leads already have company-wide or
    # department-wide assign authority, so this checkbox never applies to
    # them regardless of team_id (which is often None for those roles and
    # would otherwise make is_same_team falsely evaluate to False for them,
    # incorrectly showing the checkbox).
    is_same_team = (
        request.user.team_id is not None
        and employee.team_id == request.user.team_id
    )
    is_team_lead_assigner = (
        request.user.role == Role.REPORTING_PERSON
        and request.user.designation == Designation.TEAM_LEAD_DEVELOPER
    )
    show_team_lead_checkbox = is_team_lead_assigner and not is_same_team

    if request.method == "POST":
        formset = TaskRowFormSet(request.POST, request.FILES, prefix="tasks")
        reporting_to_id = request.POST.get("reporting_to") or None

        # Team Lead approval is a single checkbox for the whole submission —
        # applies to every task row created here, not per-row. Only a real
        # cross-team Team Lead assignment can ever set this; same-team
        # assignments and non-Team-Lead assigners (Admin/Manager/HR/dept
        # leads) never need it, regardless of what (if anything) got
        # POSTed for the field.
        team_lead_approved = (
            is_team_lead_assigner and not is_same_team
            and request.POST.get("team_lead_approved") == "on"
        )

        # Snapshot *before* creating anything below — today's other tasks for
        # this employee that still have a due date and aren't done yet. If any
        # of the tasks being assigned now turns out to be HIGH/URGENT, these
        # get pushed out by a day (their day just got busier).
        todays_other_tasks = list(
            Task.objects.filter(
                assigned_to=employee,
                created_at__date=timezone.localdate(),
                due_date__isnull=False,
            ).exclude(status__in=[TaskStatus.COMPLETED, TaskStatus.CANCELLED])
            .exclude(priority__in=[TaskPriority.HIGH, TaskPriority.URGENT])
        )

        if formset.is_valid():
            created = 0
            urgent_task_added = False
            for form in formset:
                data = form.cleaned_data
                if not data or data.get("_skip") or data.get("DELETE"):
                    continue
                task = Task.objects.create(
                    title=data["task_title"][:200],
                    description=data.get("task_description") or "",
                    priority=data.get("priority") or "MEDIUM",
                    due_date=data.get("due_date"),
                    due_time=data.get("due_time"),
                    team=employee.team,
                    assigned_to=employee,
                    reporting_to_id=reporting_to_id,
                    created_by=request.user,
                    team_lead_approval_status=(
                        TeamLeadApprovalStatus.APPROVED if team_lead_approved
                        else TeamLeadApprovalStatus.NOT_REQUIRED
                    ),
                )
                uploaded_file = data.get("attachment")
                if uploaded_file:
                    TaskAttachment.objects.create(
                        task=task,
                        file=uploaded_file,
                        original_filename=uploaded_file.name,
                        size=uploaded_file.size,
                        uploaded_by=request.user,
                    )

                TaskActivity.objects.create(task=task, actor=request.user, verb="CREATED")

                if team_lead_approved:
                    # Pre-approved via the "Team Lead Approved" checkbox —
                    # record who signed off on the team lead's behalf and
                    # tell that team's lead(s) about it, instead of leaving
                    # them to notice it only via the generic CREATED feed.
                    task.team_lead_decided_by = request.user
                    task.team_lead_decided_at = timezone.now()
                    task.save(update_fields=["team_lead_decided_by", "team_lead_decided_at"])
                    TaskActivity.objects.create(
                        task=task, actor=request.user, verb="APPROVAL_PRE_GRANTED",
                    )

                if task.priority in (TaskPriority.HIGH, TaskPriority.URGENT):
                    urgent_task_added = True

                if uploaded_file:
                    TaskActivity.objects.create(
                        task=task, actor=request.user, verb="ATTACHMENT_ADDED", detail=uploaded_file.name,
                    )

                created += 1

            if urgent_task_added and todays_other_tasks:
                for other_task in todays_other_tasks:
                    other_task.due_date = other_task.due_date + timezone.timedelta(days=1)
                    other_task.save(update_fields=["due_date"])
                    TaskActivity.objects.create(
                        task=other_task,
                        actor=request.user,
                        verb="DUE_DATE_CHANGED",
                        detail="Pushed out by 1 day — a higher-priority task was just assigned today.",
                    )

            if created:
                messages.success(
                    request,
                    f"{created} task(s) assigned to {employee.get_full_name() or employee.username}.",
                )
            else:
                messages.warning(request, "No tasks were added — every row was empty.")
            return redirect("task_assign_list")
    else:
        formset = TaskRowFormSet(prefix="tasks")

    # "Reporting to" dropdown: people this employee's assignment could report into
    # (their own team lead / department lead / admins & managers)
    reporting_persons = User.objects.filter(
        role=Role.REPORTING_PERSON,
        team__department=employee.team.department,
    )

    if reporting_persons.exists():
        reporting_filter = Q(
        role=Role.REPORTING_PERSON,
        team__department=employee.team.department,
    )
    else:
        reporting_filter = Q(role=Role.REPORTING_PERSON)

    # The Admin (superuser) is deliberately excluded here too — this is an
    # employee-selection dropdown, and the Admin should never appear in one.

    # reporting_to_choices = User.objects.filter(
    #     Q(designation=Designation.MANAGER)
    #     | reporting_filter
    # ).exclude(id=employee.id).exclude(is_superuser=True).distinct()

    reporting_to_choices = User.objects.filter(
        Q(is_superuser=True)                  
        | Q(designation=Designation.MANAGER) 
        | reporting_filter                 
    ).exclude(id=employee.id).distinct()

    context = {
        "employee": employee,
        "formset": formset,
        "reporting_to_choices": reporting_to_choices,
        "show_team_lead_checkbox": show_team_lead_checkbox,
    }
    return render(request, "tasks/task_assign_form.html", context)


def _filtered_visible_tasks(request):
    """Shared filtering logic (search + status + priority) over the tasks a
    user is allowed to see. Used by the on-screen list and the CSV export so
    the export always matches whatever is currently filtered/searched."""
    tasks = (
        get_visible_tasks_queryset(request.user, Task)
        .select_related("team", "assigned_to", "reporting_to", "created_by")
    )

    query = request.GET.get("q", "").strip()
    if query:
        tasks = tasks.filter(
            Q(title__icontains=query)
            | Q(assigned_to__first_name__icontains=query)
            | Q(assigned_to__last_name__icontains=query)
            | Q(assigned_to__username__icontains=query)
        )

    status_filter = request.GET.get("status", "")
    if status_filter in TaskStatus.values:
        tasks = tasks.filter(status=status_filter)

    from .models import TaskPriority
    priority_filter = request.GET.get("priority", "")
    if priority_filter in TaskPriority.values:
        tasks = tasks.filter(priority=priority_filter)

    assigned_to_id = request.GET.get("assigned_to", "")
    assigned_to_user = None
    if assigned_to_id.isdigit():
        tasks = tasks.filter(assigned_to_id=assigned_to_id)
        assigned_to_user = User.objects.filter(pk=assigned_to_id).first()

    return tasks.order_by("-created_at", "-id"), query, status_filter, priority_filter, assigned_to_user


@login_required
def view_tasks(request):
    """Read-only, task-level list — for HR (view-only, no roster access) and
    anyone else who wants to see tasks directly rather than via the roster."""
    tasks, query, status_filter, priority_filter, assigned_to_user = _filtered_visible_tasks(request)

    paginator = Paginator(tasks, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _attach_overdue_flag(page_obj.object_list)

    from .models import TaskPriority
    context = {
        "tasks": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "status_filter": status_filter,
        "priority_filter": priority_filter,
        "assigned_to_user": assigned_to_user,
        "status_choices": TaskStatus.choices,
        "priority_choices": TaskPriority.choices,
    }
    return render(request, "tasks/view_tasks.html", context)


@login_required
def my_tasks(request):
    """Employee/Intern view: only the tasks assigned to the logged-in user,
    with buttons to update status (the only thing they're allowed to change)."""
    tasks = (
        Task.objects.filter(assigned_to=request.user)
        .select_related("created_by", "team")
        .order_by("-created_at", "-id")
    )
    tasks = _attach_overdue_flag(tasks)
    return render(request, "tasks/my_tasks.html", {"tasks": tasks})


@login_required
def export_tasks_csv(request):
    """Downloads the current user's visible tasks (honouring the same search,
    status, and priority filters as the View tasks page) as a CSV file."""
    tasks, _, _, _, _ = _filtered_visible_tasks(request)
    tasks = _attach_overdue_flag(tasks)

    response = HttpResponse(content_type="text/csv")
    filename = f"tasks_{timezone.localdate().isoformat()}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "Title", "Description", "Status", "Priority", "Progress (%)", "Team", "Assigned To",
        "Reporting To", "Created By", "Due Date", "Due Time",
        "Overdue", "Comments", "Attachments", "Created At", "Updated At",
    ])
    for task in tasks:
        writer.writerow([
            task.title,
            task.description,
            task.get_status_display(),
            task.get_priority_display(),
            task.progress,
            task.team.name if task.team else "",
            task.assigned_to.get_full_name() or task.assigned_to.username if task.assigned_to else "",
            task.reporting_to.get_full_name() or task.reporting_to.username if task.reporting_to else "",
            task.created_by.get_full_name() or task.created_by.username if task.created_by else "",
            task.due_date.isoformat() if task.due_date else "",
            task.due_time.strftime("%H:%M") if task.due_time else "",
            "Yes" if task.is_overdue else "No",
            task.comments.count(),
            task.attachments.count(),
            timezone.localtime(task.created_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(task.updated_at).strftime("%Y-%m-%d %H:%M"),
        ])

    return response


@login_required
def update_task_status(request, task_id):
    """Kept as the simple one-tap status buttons on the "My tasks" cards.
    For a combined status + progress update, see task_detail below."""
    task = get_object_or_404(Task, pk=task_id)

    if not can_update_status_progress(request.user, task):
        raise PermissionDenied("You can only update the status of your own tasks.")

    if request.method == "POST":
         # Prevent changing status once completed or cancelled
        if task.status == TaskStatus.COMPLETED:
            messages.error(request, "Completed tasks cannot be modified.")
            return redirect("my_tasks")
        if task.status == TaskStatus.CANCELLED:
            messages.error(request, "This task was cancelled — the Team Lead rejected the cross-team assignment.")
            return redirect("my_tasks")
        new_status = request.POST.get("status")
        if new_status == TaskStatus.CANCELLED:
            # Cancelling is never a self-service action — it only happens
            # through the Team Lead reject decision.
            messages.error(request, "You can't cancel a task yourself.")
            return redirect("my_tasks")
        if new_status in TaskStatus.values:
            task.status = new_status
            task.save()
            TaskActivity.objects.create(task=task, actor=request.user, verb=new_status)
            messages.success(request, "Task status updated successfully.")
        else:
            messages.error(request, "Invalid status.")

    return redirect("my_tasks")

def _task_detail_redirect(request, task):
    next_url = request.POST.get("next", "")
    url = reverse("task_detail", args=[task.id])
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        url += f"?next={next_url}"
    return redirect(url)

@login_required
def task_detail(request, task_id):
    """Single-task hub: full details, priority/progress bar, comment thread,
    attachments, and the activity/history timeline. What the user can act on
    from here is entirely governed by the RBAC helpers in permissions.py."""
    task = get_object_or_404(
        Task.objects.select_related("team", "assigned_to", "reporting_to", "created_by"),
        pk=task_id,
    )

    next_url = request.GET.get("next", "")

    if not can_view_task(request.user, task):
        raise PermissionDenied("You don't have access to this task.")

    can_edit = can_edit_task_fields(request.user, task)
    can_update = can_update_status_progress(request.user, task)
    can_collaborate = can_comment_or_attach(request.user, task)

    status_form = TaskStatusProgressForm(instance=task) if can_update else None
    comment_form = TaskCommentForm() if can_collaborate else None
    attachment_form = TaskAttachmentForm() if can_collaborate else None

    if request.method == "POST":
        section = request.POST.get("section")

        if section == "status" and can_update:

            if task.status == TaskStatus.COMPLETED:
                messages.error(request, "Completed tasks cannot be modified.")
                return redirect("task_detail", task_id=task.id)
            if task.status == TaskStatus.CANCELLED:
                messages.error(request, "This task was cancelled — the Team Lead rejected the cross-team assignment.")
                return redirect("task_detail", task_id=task.id)
    
            status_form = TaskStatusProgressForm(request.POST, instance=task)
            if status_form.is_valid():
                old_status, old_progress = task.status, task.progress
                task = status_form.save()
                if task.status != old_status:
                    TaskActivity.objects.create(task=task, actor=request.user, verb=task.status)
                if task.progress != old_progress:
                    TaskActivity.objects.create(
                        task=task, actor=request.user, verb="PROGRESS_UPDATED",
                        detail=f"{old_progress}% \u2192 {task.progress}%",
                    )
                messages.success(request, "Task updated.")
                return _task_detail_redirect(request, task)

        elif section == "comment" and can_collaborate:
            comment_form = TaskCommentForm(request.POST)
            if comment_form.is_valid():
                comment_form.instance.task = task
                comment_form.instance.author = request.user
                comment_form.save()
                TaskActivity.objects.create(task=task, actor=request.user, verb="COMMENTED")
                messages.success(request, "Comment added.")
                return _task_detail_redirect(request, task)

        elif section == "attachment" and can_collaborate:
            attachment_form = TaskAttachmentForm(request.POST, request.FILES)
            if attachment_form.is_valid():
                uploaded_file = attachment_form.cleaned_data["file"]
                attachment = attachment_form.save(commit=False)
                attachment.task = task
                attachment.uploaded_by = request.user
                attachment.original_filename = uploaded_file.name
                attachment.size = uploaded_file.size
                attachment.save()
                TaskActivity.objects.create(
                    task=task, actor=request.user, verb="ATTACHMENT_ADDED", detail=attachment.original_filename,
                )
                messages.success(request, "Attachment uploaded.")
                return _task_detail_redirect(request, task)
        else:
            return HttpResponseForbidden("You don't have permission to do that.")

    context = {
        "task": task,
        "next_url": next_url,
        "is_overdue": task.is_overdue,
        "comments": task.comments.select_related("author"),
        "attachments": task.attachments.select_related("uploaded_by"),
        "activity": task.activity.select_related("actor"),
        "status_form": status_form,
        "comment_form": comment_form,
        "attachment_form": attachment_form,
        "can_edit": can_edit,
        "can_update": can_update,
        "can_collaborate": can_collaborate,
    }
    return render(request, "tasks/task_detail.html", context)


@login_required
def task_edit(request, task_id):
    """Full-field edit: priority, due date/time, description, reassignment.
    Gated entirely on can_edit_task_fields — HR and the assignee-only tier
    never reach this view."""
    task = get_object_or_404(Task, pk=task_id)

    if not can_edit_task_fields(request.user, task):
        raise PermissionDenied("You don't have permission to edit this task.")

    assignable_employees = get_assignable_employees(request.user, User).select_related("team")
    reporting_choices = User.objects.filter(role=Role.REPORTING_PERSON).exclude(is_superuser=True)

    if request.method == "POST":
        form = TaskEditForm(
            request.POST, instance=task,
            assignable_employees=assignable_employees, reporting_choices=reporting_choices,
        )
        if form.is_valid():
            old_priority = task.priority
            old_due_date = task.due_date
            old_assigned_to_id = task.assigned_to_id

            new_assigned_to = form.cleaned_data.get("assigned_to")
            if new_assigned_to and new_assigned_to.id != old_assigned_to_id:
                if not can_assign_to(request.user, new_assigned_to):
                    form.add_error("assigned_to", "You don't have permission to assign tasks to this employee.")
                    return render(request, "tasks/task_edit.html", {"task": task, "form": form})

            task = form.save()

            if task.priority != old_priority:
                TaskActivity.objects.create(
                    task=task, actor=request.user, verb="PRIORITY_CHANGED", detail=task.get_priority_display(),
                )
            if task.due_date != old_due_date:
                TaskActivity.objects.create(
                    task=task, actor=request.user, verb="DUE_DATE_CHANGED",
                    detail=task.due_date.isoformat() if task.due_date else "cleared",
                )
            if task.assigned_to_id != old_assigned_to_id:
                TaskActivity.objects.create(
                    task=task, actor=request.user, verb="REASSIGNED",
                    detail=(task.assigned_to.get_full_name() or task.assigned_to.username) if task.assigned_to else "unassigned",
                )
            messages.success(request, "Task updated.")
            return redirect("task_detail", task_id=task.id)
    else:
        form = TaskEditForm(
            instance=task,
            assignable_employees=assignable_employees, reporting_choices=reporting_choices,
        )

    return render(request, "tasks/task_edit.html", {"task": task, "form": form})


@login_required
def task_delete(request, task_id):
    """Permanently deletes a task. Gated on the same permission as full field
    edits (can_edit_task_fields), so the assignee-only tier and HR (view-only)
    can never delete a task — only creators/managers with edit rights can.
    Requires a POST (confirmation page) to actually delete; a GET just shows
    the confirmation prompt."""
    task = get_object_or_404(
        Task.objects.select_related("team", "assigned_to"), pk=task_id,
    )

    if not can_edit_task_fields(request.user, task):
        raise PermissionDenied("You don't have permission to delete this task.")

    if request.method == "POST":
        title = task.title
        task.delete()
        messages.success(request, f'Task "{title}" was deleted.')
        return redirect("view_tasks")

    return render(request, "tasks/task_delete_confirm.html", {"task": task})


@login_required
def task_delete_attachment(request, task_id, attachment_id):
    task = get_object_or_404(Task, pk=task_id)
    attachment = get_object_or_404(task.attachments, pk=attachment_id)

    if not can_delete_attachment(request.user, attachment):
        raise PermissionDenied("You don't have permission to remove this attachment.")

    if request.method == "POST":
        filename = attachment.original_filename

        # Delete file from Cloudinary
        if attachment.file:
            cloudinary.uploader.destroy(
                attachment.file.public_id,
                resource_type="raw"
            )

        # Delete database record
        attachment.delete()

        TaskActivity.objects.create(
            task=task,
            actor=request.user,
            verb="ATTACHMENT_REMOVED",
            detail=filename
        )

        messages.success(request, "Attachment removed.")

    return redirect("task_detail", task_id=task.id)


@login_required
@require_POST
def task_team_lead_decision(request, task_id, decision):
    """The target team's lead (or Admin/Manager) approves or rejects a
    cross-team assignment — reached via the Approve/Reject buttons on their
    Notifications page (first decision) or the Cross-Team Approval panel on
    the task detail page (to reconsider an earlier decision)."""
    task = get_object_or_404(Task, pk=task_id)

    if not can_review_team_lead_approval(request.user, task):
        raise PermissionDenied("You're not authorized to decide on this cross-team assignment.")

    if task.team_lead_approval_status == TeamLeadApprovalStatus.NOT_REQUIRED:
        messages.info(request, "This task doesn't need Team Lead approval.")
        return redirect(request.POST.get("next") or "notifications")

    if decision == "approve":
        if task.team_lead_approval_status == TeamLeadApprovalStatus.APPROVED:
            messages.info(request, f'"{task.title}" is already approved.')
            return redirect(request.POST.get("next") or "notifications")

        task.team_lead_approval_status = TeamLeadApprovalStatus.APPROVED
        # Reopen it if an earlier rejection had cancelled it — restore
        # whatever status it actually had right before cancellation instead
        # of blindly resetting to PENDING (it may have already been
        # IN_PROGRESS, BLOCKED, etc.).
        was_reinstated = task.status == TaskStatus.CANCELLED
        if was_reinstated:
            task.status = task.pre_cancel_status or TaskStatus.PENDING
            task.pre_cancel_status = ""
        verb = "APPROVAL_GRANTED"
        messages.success(
            request,
            f'Approved: "{task.title}" for {task.assigned_to.get_full_name() or task.assigned_to.username}.',
        )
    elif decision == "reject":
        if task.team_lead_approval_status == TeamLeadApprovalStatus.REJECTED:
            messages.info(request, f'"{task.title}" is already rejected.')
            return redirect(request.POST.get("next") or "notifications")

        task.pre_cancel_status = task.status
        task.team_lead_approval_status = TeamLeadApprovalStatus.REJECTED
        task.status = TaskStatus.CANCELLED
        was_reinstated = False
        verb = "APPROVAL_REJECTED"
        messages.warning(
            request,
            f'Rejected the cross-team assignment "{task.title}" — the task has been cancelled.',
        )
    else:
        return HttpResponseForbidden("Unknown decision.")

    task.team_lead_decided_by = request.user
    task.team_lead_decided_at = timezone.now()
    task.save(update_fields=[
        "team_lead_approval_status", "team_lead_decided_by", "team_lead_decided_at",
        "status", "pre_cancel_status",
    ])

    TaskActivity.objects.create(task=task, actor=request.user, verb=verb)
    if decision == "reject":
        TaskActivity.objects.create(task=task, actor=request.user, verb="CANCELLED")
    elif decision == "approve" and was_reinstated:
        TaskActivity.objects.create(
            task=task, actor=request.user, verb=task.status, detail="Reinstated after Team Lead approval",
        )

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("notifications")


@login_required
def notifications_list(request):
    notifications = request.user.task_notifications.select_related("task", "task__assigned_to")
    paginator = Paginator(notifications, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "tasks/notifications.html", {
        "notifications": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "unread_count": request.user.task_notifications.filter(is_read=False).count(),
    })


@login_required
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(TaskNotification, pk=notification_id, recipient=request.user)
    if request.method == "POST":
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        if notification.task_id:
            next_url = request.POST.get("next", "")
            redirect_url = reverse("task_detail", args=[notification.task_id])
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                redirect_url += f"?next={next_url}"
            return redirect(redirect_url)
    return redirect("notifications")


@login_required
def notifications_mark_all_read(request):
    if request.method == "POST":
        request.user.task_notifications.filter(is_read=False).update(is_read=True)
    return redirect("notifications")

@login_required
def push_public_key(request):
    return JsonResponse({"publicKey": settings.VAPID_PUBLIC_KEY})


@login_required
@require_POST
def push_subscribe(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        endpoint = data["endpoint"]
        keys = data["keys"]
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
            },
        )
        return JsonResponse({"ok": True})
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid subscription payload."}, status=400)


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        endpoint = data.get("endpoint")
    except (ValueError, json.JSONDecodeError):
        endpoint = None
    if endpoint:
        PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    return JsonResponse({"ok": True})


@login_required
@require_GET
def notifications_poll(request):
    since = request.GET.get("since", "0")
    since_id = int(since) if since.isdigit() else 0

    qs = (
        request.user.task_notifications
        .select_related("task", "task__assigned_to")
        .filter(id__gt=since_id)
        .order_by("id")[:20]
    )

    def _assigned_to_name(notification):
        task = notification.task
        # Redundant to tell someone a task is "assigned to" themselves.
        if not task or not task.assigned_to_id or task.assigned_to_id == request.user.id:
            return None
        return task.assigned_to.get_full_name() or task.assigned_to.username

    notifications = [
        {
            "id": n.id,
            "verb": n.verb,
            "message": n.message,
            "task_id": n.task_id,
            "priority": n.task.priority if n.task_id else None,
            "assigned_to": _assigned_to_name(n),
        }
        for n in qs
    ]
    last_id = notifications[-1]["id"] if notifications else since_id

    return JsonResponse({
        "notifications": notifications,
        "last_id": last_id,
        "unread_count": request.user.task_notifications.filter(is_read=False).count(),
    })