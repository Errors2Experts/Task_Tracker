"""
Task-management RBAC helpers.

These compose the existing rules in `apps.accounts.permissions` (the single
source of truth for who can see/assign what) rather than redefining them, so
comments, attachments, and notifications all stay consistent with the roles
already enforced on the Task itself:

    ADMIN (is_superuser)                       -> full access to every task
    REPORTING_PERSON, designation=MANAGER      -> full access to every task
    REPORTING_PERSON, designation=HR           -> every task, VIEW ONLY (no
                                                   comments/attachments/edits)
    REPORTING_PERSON, dept-scoped designations -> full access within their
                                                   department (Technical/
                                                   Testing/Digital Marketing Lead)
    REPORTING_PERSON, designation=TEAM_LEAD_DEVELOPER -> full access, own team
    EMPLOYEE / INTERN                          -> own tasks only; may update
                                                   status/progress and post
                                                   comments/attachments on
                                                   their own tasks, but cannot
                                                   change priority, due date,
                                                   or reassign
"""
from apps.accounts.models import Designation, Role
from apps.accounts.permissions import (
    DESIGNATION_DEPARTMENT_MAP,
    get_visible_tasks_queryset,
    has_full_access,
    is_employee_tier,
)
from .models import TaskStatus


def can_view_task(user, task):
    """Whether `user` may see this task at all (list or detail)."""
    if has_full_access(user):
        return True
    return get_visible_tasks_queryset(user, type(task)).filter(pk=task.pk).exists()


def can_edit_task_fields(user, task):
    """Full field edits: priority, due date, description, reassignment.
    Deliberately excludes HR (view-only) and the Employee/Intern tier
    (who only ever touch status, progress, comments, attachments)."""
    if user.is_superuser:
        return True

    if user.role == Role.REPORTING_PERSON:
        if user.designation == Designation.HR:
            return False
        if user.designation == Designation.MANAGER:
            return True
        department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
        if department:
            return bool(task.team) and task.team.department == department
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            return task.team_id == user.team_id and user.team_id is not None

    return False


def can_update_status_progress(user, task):
    """Status + progress updates: the assignee only. Everyone else — Admin,
    Manager, department/team Leads, HR — can still view the task, but the
    "Update Status & Progress" panel is for the person the task is actually
    assigned to; nobody else moves it along on their behalf.

    A Cancelled task (Team Lead rejected the cross-team assignment) is
    frozen even for the assignee — only someone with full edit rights
    (e.g. a lead reassigning/cleaning it up) can still act on it then.
    """
    if task.status == TaskStatus.CANCELLED:
        return can_edit_task_fields(user, task)

    return task.assigned_to_id == user.id


def can_comment_or_attach(user, task):
    """Comments and attachments: the assignee, or anyone with full edit
    rights on the task. HR remains read-only, consistent with the rest of
    the RBAC model. Deliberately broader than can_update_status_progress —
    leads/managers can still discuss and attach files even though moving
    the task's status is assignee-only."""
    if task.status == TaskStatus.CANCELLED and not can_edit_task_fields(user, task):
        return False

    # Employees/Interns and HR: own tasks only
    if is_employee_tier(user) or (
        user.role == Role.REPORTING_PERSON and user.designation == Designation.HR
    ):
        return task.assigned_to_id == user.id

    return can_edit_task_fields(user, task)


def can_delete_attachment(user, attachment):
    """The person who uploaded it, or anyone with full edit rights on the
    parent task (so a lead/manager can clean up a mistaken upload)."""
    task = attachment.task
    if attachment.uploaded_by_id == user.id:
        return True
    return can_edit_task_fields(user, task)