from django.db.models import Q
from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.accounts.models import Role, Designation, Department

# Designation -> department scoping, for Reporting persons whose access is
# limited to one department's tasks/employees.
DESIGNATION_DEPARTMENT_MAP = {
    Designation.TECHNICAL_LEAD: Department.DEVELOPER,
    Designation.TESTING_LEAD: Department.TESTING,
    Designation.MARKETING_LEAD: Department.MARKETING,
    Designation.UI_UX_LEAD: Department.UI_UX,
}

EMPLOYEE_TIER_ROLES = (Role.EMPLOYEE, Role.INTERN)


# --- Multi-assignment helpers ---
#
# An employee can now hold several (designation, department, team) rows via
# EmployeeAssignment. Everywhere below that used to look only at the single
# `user.designation` / `user.team` now checks across ALL of an employee's
# rows (falling back to the legacy single fields for anyone with no
# EmployeeAssignment rows at all, e.g. pre-existing accounts).

def _employee_assignment_rows(employee):
    rows = list(employee.assignments.all())
    if rows:
        return rows
    if employee.designation or employee.team_id:
        from apps.accounts.models import EmployeeAssignment
        return [EmployeeAssignment(
            employee=employee, designation=employee.designation, team=employee.team,
            department=employee.team.department if employee.team_id else "",
        )]
    return []


def _employee_team_ids(employee):
    return {row.team_id for row in _employee_assignment_rows(employee) if row.team_id}


def _employee_departments(employee):
    depts = set()
    for row in _employee_assignment_rows(employee):
        if row.department:
            depts.add(row.department)
        elif row.team_id and row.team:
            depts.add(row.team.department)
    return depts


def user_has_designation(user, designation):
    """True if ANY of the user's (possibly several) designation assignments
    matches `designation` — not just their primary one. This is the one
    check every "does this user hold role X" test in the app should go
    through, so a designation held only as a secondary assignment (e.g.
    Manager picked up alongside Digital Marketing Lead) is never silently
    invisible to a check that only ever looked at `user.designation`."""
    return any(row.designation == designation for row in _employee_assignment_rows(user))


def is_hr(user):
    """True if HR is (one of) this user's designations."""
    return user.role == Role.REPORTING_PERSON and user_has_designation(user, Designation.HR)


def is_employee_tier(user):
    """True for Employee/Intern — but never for the Admin (superuser), even
    if their `role` field happens to hold "EMPLOYEE" (the model default)."""
    return not user.is_superuser and user.role in EMPLOYEE_TIER_ROLES


def is_manager(user):
    """True if Manager is (one of) this user's designations — checked
    across ALL assignment rows, so Manager held as a secondary designation
    (e.g. Manager & Digital Marketing Lead) still grants full access."""
    return user.role == Role.REPORTING_PERSON and user_has_designation(user, Designation.MANAGER)


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

        if is_hr(user):
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
            if is_manager(user):
                return True
            if is_hr(user):
                return request.method in SAFE_METHODS
            if obj.assigned_to_id and obj.assigned_to.reporting_person_id == user.id:
                return True
            departments, team_ids = _user_authority_scope(user)
            if departments and obj.team and obj.team.department in departments:
                return True
            if team_ids and obj.team_id in team_ids:
                return True
            return False

        if is_employee_tier(user):
            allowed_methods = SAFE_METHODS + ("PATCH",)
            return obj.assigned_to_id == user.id and request.method in allowed_methods

        return False


def get_visible_tasks_queryset(user, Task):
    """Central place for list-level (queryset) scoping — used in TaskViewSet.get_queryset().

    Checks every one of a Reporting person's (possibly several) designation
    assignments, not just their primary one — so e.g. someone who holds
    Technical Lead only as a secondary assignment still sees every task in
    the Development department, not none. Also always includes tasks
    assigned to anyone EXPLICITLY reporting to this user (reporting_person),
    even if that employee sits in a different department/team — the same
    exception get_assignable_employees() makes, so a lead can actually see
    and manage tasks for a cross-department direct report they were allowed
    to assign in the first place."""
    if has_full_access(user):
        return Task.objects.all()

    if user.role == Role.REPORTING_PERSON:
        if is_hr(user):
            return Task.objects.all()
        departments, team_ids = _user_authority_scope(user)
        scope = Q(assigned_to__reporting_person_id=user.id)
        if departments:
            scope |= Q(team__department__in=departments)
        if team_ids:
            scope |= Q(team_id__in=team_ids)
        return Task.objects.filter(scope).distinct()

    if is_employee_tier(user):
        return Task.objects.filter(assigned_to_id=user.id)

    return Task.objects.none()


# --- Roster / task-assignment scoping (used by the "Task assign" page) ---
#
# Every queryset below excludes superusers (`is_superuser=True`). The Admin
# is never a valid task-assignment target and must never appear in any
# employee-selection dropdown, regardless of who's asking.

def _user_authority_scope(user):
    """(departments:set, team_ids:set) a Reporting person has dept/team-scoped
    authority over, unioned across ALL of their own designation assignments
    — a Reporting person can now hold more than one designation, so e.g.
    someone who is both Technical Lead AND Team Lead (Developer) for a
    specific team gets the union of both scopes, not just one."""
    departments = set()
    team_ids = set()
    for row in _employee_assignment_rows(user):
        department = DESIGNATION_DEPARTMENT_MAP.get(row.designation)
        if department:
            departments.add(department)
        if row.designation == Designation.TEAM_LEAD_DEVELOPER and row.team_id:
            team_ids.add(row.team_id)
    return departments, team_ids


def get_assignable_employees(user, User):
    """Returns the queryset of employees a given user is allowed to assign tasks to.

    An employee counts as "in scope" if ANY one of their (possibly several)
    designation/department/team assignments falls inside the assigner's
    scope — not only their primary one. Also always includes anyone
    EXPLICITLY set to report to this user (User.reporting_person), even
    if that employee's own department/team falls outside the assigner's
    normal dept/team scope — e.g. a Technical Lead (Development) who has
    been explicitly given a Marketing-department employee as a direct
    report can still assign tasks to them, same as they already show up
    in that lead's "My Team" roster.
    """
    from django.db.models import Q

    base = User.objects.exclude(is_superuser=True)

    if has_full_access(user):
        return base.exclude(id=user.id)

    if user.role == Role.REPORTING_PERSON:
        departments, team_ids = _user_authority_scope(user)

        scope = Q(reporting_person=user)
        if departments:
            scope |= (
                Q(assignments__department__in=departments)
                | Q(assignments__isnull=True, team__department__in=departments)
            )
        if team_ids:
            scope |= (
                Q(assignments__team_id__in=team_ids)
                | Q(assignments__isnull=True, team_id__in=team_ids)
            )
        return base.filter(scope).exclude(id=user.id).distinct()

    return User.objects.none()


def can_assign_to(user, employee):
    """Object-level check: can `user` assign a task to `employee`?
    Checks across every assignment row `employee` holds, not just their
    primary designation/team. Also allows it whenever `employee` has been
    explicitly set to report to `user`, regardless of department/team —
    same explicit-reporting-line exception as get_assignable_employees()."""
    # The Admin can never be assigned a task, by anyone, under any scope.
    if employee.is_superuser:
        return False

    if has_full_access(user):
        return employee.id != user.id

    if user.role == Role.REPORTING_PERSON:
        if employee.reporting_person_id == user.id:
            return True
        departments, team_ids = _user_authority_scope(user)
        if departments and (_employee_departments(employee) & departments):
            return True
        if team_ids and (_employee_team_ids(employee) & team_ids):
            return True

    return False


# --- "My Team" roster scoping ---
#
# Distinct from get_assignable_employees() above: that one is about *task
# assignment* targets (Admin/Manager can assign to anyone). "My Team" is a
# people-management roster, so the Admin's scope here is deliberately
# narrower — the leadership layer (Reporting persons) rather than every
# employee in the company.

MY_TEAM_DESIGNATIONS = tuple(
    designation for designation in Designation if "LEAD" in designation.value
)


def can_view_my_team(user):
    """Who is allowed onto the My Team page at all."""
    if has_full_access(user):
        return True
    if user.role != Role.REPORTING_PERSON:
        return False
    designations = {row.designation for row in _employee_assignment_rows(user)}
    return bool(designations & set(MY_TEAM_DESIGNATIONS))


def get_my_team_queryset(user, User):
    """Returns the queryset of team members visible to `user` on My Team.

    Admin (is_superuser):
        - Can see all Reporting Persons.
        - Can also see employees/interns explicitly reporting to them.
        - Can see department/team scoped members based on their own
          leadership assignments.

    Manager:
        - Does NOT automatically see all Reporting Persons.
        - Can see employees/interns explicitly reporting to them.
        - Can see department/team scoped members based on their own
          leadership assignments.

    Other Reporting Persons:
        - Can see employees/interns explicitly reporting to them.
        - Legacy department/team fallback is used only when reporting_person
          is not assigned.
    """
    from django.db.models import Q

    base = (
        User.objects
        .exclude(is_superuser=True)
        .exclude(id=user.id)
    )

    # -------------------------------------------------
    # ADMIN ONLY
    # -------------------------------------------------
    if user.is_superuser:
        # Admin can see every Reporting Person.
        # Also include anyone explicitly reporting to Admin.
        scope = (
            Q(role=Role.REPORTING_PERSON)
            | Q(reporting_person=user)
        )

        # Admin may also have leadership designations
        # with department/team authority.
        departments, team_ids = _user_authority_scope(user)

        if departments:
            scope |= (
                Q(assignments__department__in=departments)
                | Q(
                    assignments__isnull=True,
                    team__department__in=departments,
                )
            )

        if team_ids:
            scope |= (
                Q(assignments__team_id__in=team_ids)
                | Q(
                    assignments__isnull=True,
                    team_id__in=team_ids,
                )
            )

        return base.filter(scope).distinct()

    # -------------------------------------------------
    # MANAGER
    # -------------------------------------------------
    if user.role == Role.REPORTING_PERSON:
        # Manager / Reporting Person should NOT automatically
        # see other Reporting Persons.
        #
        # Only employees/interns explicitly reporting to them
        # should appear through this relationship.
        explicit = Q(
            reporting_person=user
        ) & ~Q(
            role=Role.REPORTING_PERSON
        )

        departments, team_ids = _user_authority_scope(user)

        legacy = Q(pk__in=[])

        if departments:
            legacy |= (
                Q(
                    reporting_person__isnull=True,
                    assignments__department__in=departments,
                )
                | Q(
                    reporting_person__isnull=True,
                    assignments__isnull=True,
                    team__department__in=departments,
                )
            )

        if team_ids:
            legacy |= (
                Q(
                    reporting_person__isnull=True,
                    assignments__team_id__in=team_ids,
                )
                | Q(
                    reporting_person__isnull=True,
                    assignments__isnull=True,
                    team_id__in=team_ids,
                )
            )

        if not departments and not team_ids:
            return base.filter(explicit).distinct()

        return base.filter(
            explicit | legacy
        ).distinct()

    # -------------------------------------------------
    # Everyone else
    # -------------------------------------------------
    return User.objects.none()

def get_my_team_scope_message(user):
    """Human-readable banner text shown at the top of the My Team page."""
    if has_full_access(user):
        departments, team_ids = _user_authority_scope(user)
        parts = []
        if departments:
            dept_labels = [Department(d).label for d in departments]
            parts.append("everyone in " + ", ".join(dept_labels))
        if team_ids:
            parts.append("your team(s)")
        if parts:
            return "Showing all Reporting Persons across the company, plus " + " and ".join(parts) + "."
        return "Showing all Reporting Persons across the company."

    if user.role == Role.REPORTING_PERSON:
        departments, team_ids = _user_authority_scope(user)
        parts = []
        if departments:
            dept_labels = [Department(d).label for d in departments]
            parts.append("everyone in " + ", ".join(dept_labels))
        if team_ids:
            parts.append("your team(s)")
        if parts:
            return "Showing employees who report to you, plus " + " and ".join(parts) + "."
        return "Showing employees who report to you."

    return "You don't have a team to view."


def get_roster_scope_message(user):
    """Human-readable banner text shown at the top of the Task assign page."""
    if has_full_access(user):
        return "Full access — you can assign and view tasks for every employee in the company."

    if user.role == Role.REPORTING_PERSON:
        departments, team_ids = _user_authority_scope(user)
        parts = []
        if departments:
            dept_labels = [Department(d).label for d in departments]
            parts.append("everyone in " + ", ".join(dept_labels))
        if team_ids:
            parts.append("your team(s)")
        if parts:
            return "You can assign and view tasks for " + " and ".join(parts) + "."

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

    # Match either the legacy single designation/team fields OR any one of
    # a reviewer's (possibly several) EmployeeAssignment rows — a Team Lead
    # who holds that designation on this specific team via an assignment
    # row (rather than as their primary designation) should still see this.
    scope = (
        Q(designation=Designation.TEAM_LEAD_DEVELOPER, team_id=team.id)
        | Q(assignments__designation=Designation.TEAM_LEAD_DEVELOPER, assignments__team_id=team.id)
    )
    if dept_designations:
        scope |= Q(designation__in=dept_designations) | Q(assignments__designation__in=dept_designations)

    reviewers = User.objects.filter(scope, is_active=True).distinct()
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