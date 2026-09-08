from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from cloudinary.models import CloudinaryField


class Department(models.TextChoices):
    DEVELOPER = "DEVELOPER", "Development"
    TESTING = "TESTING", "Testing"
    MARKETING = "MARKETING", "Marketing"
    HR = "HR", "HR"
    TRAINER = "TRAINER", "Trainer"
    BDE = "BDE", "Business Development"
    UI_UX = "UI_UX", "UI/UX"
    OTHER = "OTHER", "Other"


class Team(models.Model):
    """A team belongs to a department. e.g. 'Backend Team' -> Development dept"""
    name = models.CharField(max_length=100)
    department = models.CharField(max_length=20, choices=Department.choices)

    def __str__(self):
        return f"{self.name} ({self.department})"


class Role(models.TextChoices):
    """Broad permission tier — decides the SHAPE of access.

    There is deliberately no ADMIN entry here. "Admin" is not a role a user
    can be given through the app — it is derived entirely from Django's
    built-in `is_superuser` flag (see `User.is_admin` below). Keeping it out
    of this enum means no form, serializer, or admin dropdown fed by
    `Role.choices` can ever offer "Admin" as a selectable value.
    """
    REPORTING_PERSON = "REPORTING_PERSON", "Reporting person"
    EMPLOYEE = "EMPLOYEE", "Employee"
    INTERN = "INTERN", "Intern"


class Designation(models.TextChoices):
    """Specific job title — used for display, and (for Reporting person) to
    decide WHICH scope of tasks a user can see/assign within their tier."""
    
    MANAGER = "MANAGER", "Manager"
    HR = "HR", "HR"
    TECHNICAL_LEAD = "TECHNICAL_LEAD", "Technical Lead"
    TEAM_LEAD_DEVELOPER = "TEAM_LEAD_DEVELOPER", "Team Lead (Developer)"
    SOFTWARE_DEVELOPER = "SOFTWARE_DEVELOPER", "Software Developer"
    TESTING_LEAD = "TESTING_LEAD", "Testing Lead"
    TESTING = "TESTING", "QA Analyst "
    MARKETING_LEAD = "MARKETING_LEAD", "Marketing Lead"
    DIGITAL_MARKETING_EXECUTIVE = "DIGITAL_MARKETING_EXECUTIVE", "Digital Marketing Executive"
    TRAINER = "TRAINER", "Technical Trainer"
    BDE = "BDE", "Business Development Executive"
    UI_UX_LEAD = "UI_UX_LEAD", "UI/UX Lead"
    UI_UX_DESIGNER = "UI/UX_DESIGNER","UI/UX Designer"
    INTERN = "INTERN", "Intern"

    FOUNDER_TECHNICAL_MENTOR = ("FOUNDER_TECHNICAL_MENTOR","Founder & Technical Mentor",)


class User(AbstractUser):
    """
    Custom user model with a two-part RBAC scheme:
      role         -> broad tier (Reporting person / Employee / Intern)
      designation  -> specific title (Manager, Technical Lead, Team Lead, ...)

    For a Reporting person, `designation` decides the exact scope
    (see accounts/permissions.py DESIGNATION_DEPARTMENT_MAP).

    Admin is intentionally NOT part of `role`. "Admin" means Django's own
    `is_superuser` flag, full stop — see `is_admin` below. That flag can only
    ever be set by an existing superuser (via Django admin) or by someone
    with server/shell access (`manage.py createsuperuser`). It is never
    exposed on any form or serializer this app controls, so an Admin account
    can never be created *from* the application itself.

    New registrations are created with is_active=False and must be approved
    by an admin (in Django admin, tick "Active" or use the "Approve selected
    users" action) before they can sign in — Django's auth backend already
    blocks inactive users from logging in, so no extra flag is needed.
    """
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.REPORTING_PERSON)
    designation = models.CharField(max_length=30, choices=Designation.choices, null=True, blank=True)
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )

    photo=CloudinaryField('employee_photos/',null=True, blank=True)

    # set: self-registration, admin registration, and the Employee Edit
    # "Reset password" field. Not used for authentication anywhere — auth
    # always goes through the normal hashed `password` field.
    plain_password = models.CharField(max_length=128, null=True, blank=True)

    # Explicit reporting line. This is what "My Team" scoping is actually
    # keyed on now (see accounts/permissions.py get_my_team_queryset) —
    # rather than only inferring "who manages whom" from matching
    # department/team, an Admin/Manager/Lead can directly assign who an
    # employee reports to, and that employee then shows up ONLY in that
    # person's My Team roster.
    reporting_person = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="direct_reports",
        limit_choices_to={"role": Role.REPORTING_PERSON},
        help_text="The Reporting Person this employee reports to. Determines whose 'My Team' this employee appears in.",
    )

    def __str__(self):
        label = "Admin" if self.is_admin else self.role
        return f"{self.username} ({label})"

    @property
    def is_admin(self):
        """The one and only definition of "Admin" in this system.

        There is no stored "ADMIN" role — Admin status is Django's own
        `is_superuser` flag. Use this property everywhere the app needs to
        ask "is this user the Admin?" instead of comparing against `role`.
        """
        return self.is_superuser

    def clean(self):
        super().clean()
        # Defense in depth: even though "ADMIN" no longer exists as a Role
        # choice, guard against it ever being written directly (fixtures,
        # data migrations, a stray shell command) so it can't silently
        # resurrect a second notion of "admin" alongside is_superuser.
        if self.role not in Role.values:
            raise ValidationError({"role": "Invalid role. Admin status is granted via is_superuser only."})

    def get_initials(self):
        name = self.get_full_name().strip()
        if name:
            parts = name.split()
            return "".join(p[0].upper() for p in parts[:2])
        return self.username[:2].upper()

    @property
    def employee_code(self):
        """Display alias for the Employee ID.

        The Employee ID *is* the username — that's what self-registration
        (RegisterForm) and admin-driven registration (EmployeeRegistrationForm)
        both store it as, and it's what the login form labels "Employee ID".
        This property just lets templates say `employee.employee_code`
        without needing to know that detail.
        """
        return self.username

    def all_assignments(self):
        """Every (designation, department, team) combination this employee
        holds, primary first. Falls back to the single legacy
        designation/team fields for employees who predate the
        EmployeeAssignment model (or were never given an explicit row)."""
        rows = list(self.assignments.select_related("team").order_by("-is_primary", "id"))
        if rows:
            return rows
        if self.designation or self.team_id:
            return [EmployeeAssignment(
                employee=self, designation=self.designation, team=self.team,
                department=self.team.department if self.team_id else "",
                is_primary=True,
            )]
        return []

    def designations_display(self):
        """Designation labels across all assignments, joined with '&', for
        list/roster/detail pages. e.g. 'Team Lead (Developer) & Software Developer'."""
        labels = []
        for row in self.all_assignments():
            label = row.get_designation_display() if row.designation else None
            if label and label not in labels:
                labels.append(label)
        return " & ".join(labels) if labels else "—"

    def teams_display(self):
        names = []
        for row in self.all_assignments():
            if row.team and row.team.name not in names:
                names.append(row.team.name)
        return ", ".join(names) if names else "No team"

    def assignment_summary(self):
        """Each designation paired with ITS OWN team, so a person who holds
        several designations doesn't have their designations and teams shown
        as two separately-flattened, uncorrelated lists (which — for anyone
        holding more than one designation where only some have a team —
        makes it impossible to tell which team belongs to which designation).
        e.g. 'Manager & Digital Marketing Lead (Marketing team)' or
        'Software Developer (Backend) & Trainer'."""
        parts = []
        for row in self.all_assignments():
            if not row.designation:
                continue
            label = row.get_designation_display()
            if row.team:
                label = f"{label} ({row.team.name})"
            if label not in parts:
                parts.append(label)
        return " & ".join(parts) if parts else "—"


class EmployeeAssignment(models.Model):
    """One designation/department/team combination held by an employee.

    An employee can hold several of these at once (e.g. Software Developer
    on the Backend team AND Trainer with no team) — this is what makes
    "multiple designations/departments/teams per employee" possible without
    breaking every existing piece of code that still reads the single
    `User.designation` / `User.team` fields: those two fields keep working
    as the *primary* assignment (is_primary=True), kept in sync whenever the
    primary row here is saved (see forms.py).
    """
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments")
    designation = models.CharField(max_length=30, choices=Designation.choices)
    department = models.CharField(max_length=20, choices=Department.choices, null=True, blank=True)
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_employees"
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="The main designation shown everywhere the app expects a single value.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]

    def __str__(self):
        parts = [self.get_designation_display()]
        if self.team:
            parts.append(self.team.name)
        elif self.department:
            parts.append(self.get_department_display())
        return f"{self.employee} — {' / '.join(parts)}"

    def save(self, *args, **kwargs):
        # Department follows the team when a team is picked, so the two
        # never disagree; department-only rows (no team, e.g. HR/Manager)
        # keep whatever department was explicitly selected.
        if self.team_id and not self.department:
            self.department = self.team.department
        super().save(*args, **kwargs)