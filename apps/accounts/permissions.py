from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.accounts.models import Role, Designation, Department

# Designation -> department scoping, for Reporting persons whose access is
# limited to one department's tasks/employees.
DESIGNATION_DEPARTMENT_MAP = {
    Designation.TECHNICAL_LEAD: Department.DEVELOPER,
    Designation.TESTING_LEAD: Department.TESTING,
    Designation.DIGITAL_MARKETING_LEAD: Department.MARKETING,
}

EMPLOYEE_TIER_ROLES = (Role.EMPLOYEE, Role.INTERN)


def is_employee_tier(user):
    """True for Employee/Intern — but never for the Admin (superuser), even
    if their `role` field happens to hold "EMPLOYEE" (the model default)."""
    return not user.is_superuser and user.role in EMPLOYEE_TIER_ROLES


def is_manager(user):
    return user.role == Role.REPORTING_PERSON and user.designation == Designation.MANAGER


def has_full_access(user):
    """Admin (Django superuser) and Manager both get unrestricted,
    full RBAC access — everything else is scoped."""
    return user.is_superuser or is_manager(user)


class RoleBasedTaskPermission(BasePermission):
    """
    ADMIN (is_superuser)                      -> all tasks, full access
    REPORTING_PERSON, designation=MANAGER     -> all tasks, full access
    REPORTING_PERSON, designation=HR          -> all tasks, VIEW ONLY
    REPORTING_PERSON, designation=TECHNICAL_LEAD    -> full access, Development dept only
    REPORTING_PERSON, designation=TESTING_LEAD      -> full access, Testing dept only
    REPORTING_PERSON, designation=DIGITAL_MARKETING_LEAD -> full access, Marketing dept only
    REPORTING_PERSON, designation=TEAM_LEAD    -> full access, own team only
    EMPLOYEE / INTERN                        -> own tasks, STATUS UPDATE ONLY
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if user.role == Role.REPORTING_PERSON and user.designation == Designation.HR:
            if request.method not in SAFE_METHODS:
                return False

        if is_employee_tier(user) and request.method in ("POST", "DELETE", "PUT"):
            return False

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        if user.role == Role.REPORTING_PERSON:
            if user.designation == Designation.MANAGER:
                return True
            if user.designation == Designation.HR:
                return request.method in SAFE_METHODS
            department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
            if department:
                return obj.team and obj.team.department == department
            if user.designation == Designation.TEAM_LEAD_DEVELOPER:
                return obj.team_id == user.team_id and user.team_id is not None
            return False

        if is_employee_tier(user):
            allowed_methods = SAFE_METHODS + ("PATCH",)
            return obj.assigned_to_id == user.id and request.method in allowed_methods

        return False


def get_visible_tasks_queryset(user, Task):
    """Central place for list-level (queryset) scoping — used in TaskViewSet.get_queryset()."""
    if has_full_access(user):
        return Task.objects.all()

    if user.role == Role.REPORTING_PERSON:
        if user.designation == Designation.HR:
            return Task.objects.all()
        department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
        if department:
            return Task.objects.filter(team__department=department)
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            if not user.team_id:
                return Task.objects.none()
            return Task.objects.filter(team_id=user.team_id)
        return Task.objects.none()

    if is_employee_tier(user):
        return Task.objects.filter(assigned_to_id=user.id)

    return Task.objects.none()


# --- Roster / task-assignment scoping (used by the "Task assign" page) ---
#
# Every queryset below excludes superusers (`is_superuser=True`). The Admin
# is never a valid task-assignment target and must never appear in any
# employee-selection dropdown, regardless of who's asking.

def get_assignable_employees(user, User):
    """Returns the queryset of employees a given user is allowed to assign tasks to."""
    base = User.objects.exclude(is_superuser=True)

    if has_full_access(user):
        return base.exclude(id=user.id)

    if user.role == Role.REPORTING_PERSON:
        department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
        if department:
            return base.filter(team__department=department).exclude(id=user.id)
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            if not user.team_id:
                return User.objects.none()
            return base.filter(team_id=user.team_id).exclude(id=user.id)

    return User.objects.none()


def can_assign_to(user, employee):
    """Object-level check: can `user` assign a task to `employee`?"""
    # The Admin can never be assigned a task, by anyone, under any scope.
    if employee.is_superuser:
        return False

    if has_full_access(user):
        return employee.id != user.id

    if user.role == Role.REPORTING_PERSON:
        department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
        if department:
            return bool(employee.team) and employee.team.department == department
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            return user.team_id is not None and employee.team_id == user.team_id

    return False


# --- "My Team" roster scoping ---
#
# Distinct from get_assignable_employees() above: that one is about *task
# assignment* targets (Admin/Manager can assign to anyone). "My Team" is a
# people-management roster, so the Admin's scope here is deliberately
# narrower — the leadership layer (Reporting persons) rather than every
# employee in the company.

MY_TEAM_DESIGNATIONS = (
    Designation.TECHNICAL_LEAD,
    Designation.TESTING_LEAD,
    Designation.DIGITAL_MARKETING_LEAD,
    Designation.TEAM_LEAD_DEVELOPER,
)


def can_view_my_team(user):
    """Who is allowed onto the My Team page at all."""
    if has_full_access(user):
        return True
    return user.role == Role.REPORTING_PERSON and user.designation in MY_TEAM_DESIGNATIONS


def get_my_team_queryset(user, User):
    """Returns the queryset of team members visible to `user` on My Team.

    Admin (is_superuser) / Manager -> all Reporting persons.
    Technical/Testing/Digital Marketing Lead -> everyone in that department
                                                  (every team under it, not
                                                  just their own).
    Team Lead (Developer)          -> members of their own team only.
    Everyone else                  -> nothing.
    """
    base = User.objects.exclude(is_superuser=True).exclude(id=user.id)

    if has_full_access(user):
        return base.filter(role=Role.REPORTING_PERSON)

    if user.role == Role.REPORTING_PERSON:
        department = DESIGNATION_DEPARTMENT_MAP.get(user.designation)
        if department:
            return base.filter(team__department=department)
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            if not user.team_id:
                return User.objects.none()
            return base.filter(team_id=user.team_id)

    return User.objects.none()


def get_my_team_scope_message(user):
    """Human-readable banner text shown at the top of the My Team page."""
    if has_full_access(user):
        return "Showing all Reporting Persons across the company."

    if user.role == Role.REPORTING_PERSON:
        if user.designation == Designation.TECHNICAL_LEAD:
            return "Showing your team members in the Development department."
        if user.designation == Designation.TESTING_LEAD:
            return "Showing your team members in the Testing department."
        if user.designation == Designation.DIGITAL_MARKETING_LEAD:
            return "Showing your team members in the Marketing department."
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            return "Showing the members of your team."

    return "You don't have a team to view."


def get_roster_scope_message(user):
    """Human-readable banner text shown at the top of the Task assign page."""
    if has_full_access(user):
        return "Full access — you can assign and view tasks for every employee in the company."

    if user.role == Role.REPORTING_PERSON:
        if user.designation == Designation.TECHNICAL_LEAD:
            return "You can assign and view tasks for everyone in the Development department."
        if user.designation == Designation.TESTING_LEAD:
            return "You can assign and view tasks for everyone in the Testing department."
        if user.designation == Designation.DIGITAL_MARKETING_LEAD:
            return "You can assign and view tasks for everyone in the Marketing department."
        if user.designation == Designation.TEAM_LEAD_DEVELOPER:
            return "You can assign and view tasks for your team only."

    return "You don't have access to assign tasks."


# --- Cross-team assignment approval ---
#
# When a task is assigned to someone outside the assigner's own team, the
# *target* team's lead needs to know and sign off on it — not the assigner
# self-declaring approval. These two helpers find who that is and check
# whether a given user is one of them.

def get_team_lead_reviewers(team):
    """Users who can approve/reject a cross-team assignment into `team`:
    first choice is that specific team's own lead (TEAM_LEAD_DEVELOPER
    scoped by team_id — the only team-scoped lead designation this app
    has); department-wide leads (Technical/Testing/Digital Marketing Lead)
    are included too, since they also have full oversight of the team's
    department. If neither exists for that department, Managers are the
    fallback, so a pending approval is never left with nobody able to act."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()

    if not team:
        return User.objects.none()

    dept_designations = [
        designation for designation, department in DESIGNATION_DEPARTMENT_MAP.items()
        if department == team.department
    ]

    scope = Q(designation=Designation.TEAM_LEAD_DEVELOPER, team_id=team.id)
    if dept_designations:
        scope |= Q(designation__in=dept_designations)

    reviewers = User.objects.filter(scope, is_active=True)
    if not reviewers.exists():
        reviewers = User.objects.filter(designation=Designation.MANAGER, is_active=True)
    return reviewers


def can_review_team_lead_approval(user, task):
    """Object-level check: can `user` approve/reject this task's pending
    cross-team assignment?"""
    if user.is_superuser:
        return True
    if not task.team_id:
        return False
    return get_team_lead_reviewers(task.team).filter(pk=user.pk).exists()