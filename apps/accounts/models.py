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
    TESTING = "TESTING", "Testing"
    DIGITAL_MARKETING_LEAD = "DIGITAL_MARKETING_LEAD", "Digital Marketing Lead"
    DIGITAL_MARKETING_EXECUTIVE = "DIGITAL_MARKETING_EXECUTIVE", "Digital Marketing Executive"
    TRAINER = "TRAINER", "Trainer"
    BDE = "BDE", "Business Development Executive"
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