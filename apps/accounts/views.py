from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from .forms import RegisterForm, EmployeeRegistrationForm, EmployeeEditForm
from .models import Role, Designation, Team
from .forms import ProfileEditForm, ProfilePhotoForm
from apps.tasks.models import Task, TaskStatus

User = get_user_model()

EMPLOYEE_PAGE_SIZE = 20


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Account created. An admin needs to approve your account before you can sign in.",
            )
            return redirect("login")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})



    
from django.core.exceptions import PermissionDenied
from functools import wraps

def require_admin_or_manager(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (
            request.user.is_superuser or
            request.user.designation == Designation.MANAGER
        ):
            raise PermissionDenied(
                "Only Admin and Manager can access this page."
            )
        return view_func(request, *args, **kwargs)
    return wrapper

def _employee_queryset():
    """Employee Management never lists, shows, or edits Admin (superuser)
    accounts — mirrors the same exclusion used throughout
    accounts/permissions.py for roster/assignment scoping."""
    return User.objects.exclude(is_superuser=True)


@login_required
@require_admin_or_manager
def employee_register(request):
    """Admin and Manager-only: register a new employee. The Employee ID is generated
    automatically (E2E-001, E2E-002, ...) — nobody types it in."""

    if request.method == "POST":
        form = EmployeeRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            employee = form.save()
            messages.success(
                request,
                f"Employee registered with ID {employee.employee_code}.",
            )
            return redirect("employee_detail", pk=employee.pk)
    else:
        form = EmployeeRegistrationForm()

    return render(request, "accounts/employee_register.html", {"form": form})


@login_required
@require_admin_or_manager
def employee_list(request):
    """Admin and Manager-only: searchable, filterable, paginated employee directory."""
    

    employees = _employee_queryset().select_related("team")

    query = request.GET.get("q", "").strip()
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
        )

    role_filter = request.GET.get("role", "")
    if role_filter in Role.values:
        employees = employees.filter(role=role_filter)

    designation_filter = request.GET.get("designation", "")
    if designation_filter in Designation.values:
        employees = employees.filter(designation=designation_filter)

    team_filter = request.GET.get("team", "")
    if team_filter.isdigit():
        employees = employees.filter(team_id=team_filter)

    status_filter = request.GET.get("status", "")
    if status_filter == "active":
        employees = employees.filter(is_active=True)
    elif status_filter == "inactive":
        employees = employees.filter(is_active=False)

    employees = employees.order_by("first_name", "last_name", "username")

    paginator = Paginator(employees, EMPLOYEE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "employees": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "role_filter": role_filter,
        "designation_filter": designation_filter,
        "team_filter": team_filter,
        "status_filter": status_filter,
        "role_choices": Role.choices,
        "designation_choices": Designation.choices,
        "teams": Team.objects.all(),
    }
    return render(request, "accounts/employee_list.html", context)


@login_required
@require_admin_or_manager
def employee_detail(request, pk):
    """Admin and Manager-only: read-only view of a single employee's details."""
    employee = get_object_or_404(_employee_queryset(), pk=pk)
    return render(request, "accounts/employee_detail.html", {"employee": employee})


@login_required
@require_admin_or_manager
def employee_edit(request, pk):
    """Admin and Manager-only: edit an existing employee's details. Employee ID
    (username) is permanent and is never offered as an editable field."""
    
    employee = get_object_or_404(_employee_queryset(), pk=pk)

    if request.method == "POST":
        form = EmployeeEditForm(request.POST,request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"{employee.get_full_name() or employee.employee_code}'s details were updated.",
            )
            return redirect("employee_detail", pk=employee.pk)
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, "accounts/employee_edit.html", {"form": form, "employee": employee})


def _task_counts_for(user):
    tasks = Task.objects.filter(assigned_to=user)
    completed = tasks.filter(status=TaskStatus.COMPLETED).count()
    active = tasks.exclude(status__in=[TaskStatus.COMPLETED, TaskStatus.CANCELLED]).count()
    return completed, active


def _team_member_count_for(user):
    if not user.team_id:
        return None
    return User.objects.filter(team_id=user.team_id).count()

@login_required
def profile(request):
    is_admin = request.user.is_superuser or request.user.is_staff

    if request.method == "POST":
        if 'photo' in request.FILES:
            if not is_admin:
                messages.error(request, "You don't have permission to change the profile photo.")
                return redirect('profile')

            photo_form = ProfilePhotoForm(request.POST, request.FILES, instance=request.user)
            if photo_form.is_valid():
                photo_form.save()
                messages.success(request, "Profile photo updated.")
            else:
                messages.error(request, "Couldn't update photo. Please upload a valid image.")
            return redirect('profile')

        if not is_admin:
            messages.error(request, "You don't have permission to edit this profile.")
            return redirect('profile')

        edit_form = ProfileEditForm(request.POST, instance=request.user)
        if edit_form.is_valid():
            edit_form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('profile')
        else:
            messages.error(request, "Please fix the errors below.")
            tasks_completed_count, tasks_active_count = _task_counts_for(request.user)
            return render(request, "accounts/profile.html", {
                "edit_form": edit_form,
                "open_edit_modal": True,
                "is_admin": is_admin,
                "tasks_completed_count": tasks_completed_count,
                "tasks_active_count": tasks_active_count,
                "team_member_count": _team_member_count_for(request.user),
            })

    edit_form = ProfileEditForm(instance=request.user)
    tasks_completed_count, tasks_active_count = _task_counts_for(request.user)

    return render(request, "accounts/profile.html", {
        "edit_form": edit_form,
        "is_admin": is_admin,
        "tasks_completed_count": tasks_completed_count,
        "tasks_active_count": tasks_active_count,
        "team_member_count": _team_member_count_for(request.user),
    })


@login_required
def mention_feed(request):
    """@mention autocomplete feed for CKEditor 5's Mention plugin.

    Called as /api/mentions/?query=<typed text>. Returns a JSON array of
    items the frontend renders in the dropdown; `id` must include the
    marker ("@") since that's what gets inserted into the editor.
    """
    query = request.GET.get("query", "").strip()
    users = User.objects.all()
    if query:
        users = users.filter(
            Q(username__istartswith=query)
            | Q(first_name__istartswith=query)
            | Q(last_name__istartswith=query)
        )
    users = users.order_by("username")[:10]

    results = [
        {
            "id": f"@{user.username}",
            "text": f"@{user.username}",
            "name": user.get_full_name() or user.username,
        }
        for user in users
    ]
    return JsonResponse(results, safe=False)