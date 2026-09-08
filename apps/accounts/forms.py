from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.forms import modelformset_factory
from .models import User, Role, Designation, Department, Team, EmployeeAssignment

# Reporting-person accounts lean on `designation` for scoping (see
# accounts/permissions.py DESIGNATION_DEPARTMENT_MAP), so it isn't
# meaningfully optional for that role the way it is for Employee/Intern.
# (Enforced via the assignment formset in the view, not here — this form no
# longer carries a standalone designation field; see EmployeeAssignmentFormSet.)
_DESIGNATION_REQUIRED_ROLES = (Role.REPORTING_PERSON,)


class EmployeeAssignmentForm(forms.ModelForm):
    """One row: a (designation, team) combination. Repeated via
    EmployeeAssignmentFormSet so an employee can hold several at once — e.g.
    Software Developer on the Backend team AND Trainer with no team. This is
    the ONLY place designation/team are set — there's no separate single
    designation dropdown anywhere else in the registration/edit forms.
    Department is derived automatically from the chosen team
    (EmployeeAssignment.save()), so it isn't asked for here. The first
    filled-in row becomes the "primary" one automatically (see
    views._save_employee_assignments) — no manual toggle needed."""

    class Meta:
        model = EmployeeAssignment
        fields = ["designation", "team"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["designation"].choices = [("", "Select Designation")] + list(Designation.choices)
        self.fields["designation"].required = False
        self.fields["team"].queryset = Team.objects.all()
        self.fields["team"].required = False
        self.fields["team"].empty_label = "No team"

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("designation"):
            cleaned["_skip"] = True
        return cleaned


EmployeeAssignmentFormSet = modelformset_factory(
    EmployeeAssignment,
    form=EmployeeAssignmentForm,
    fields=["designation", "team"],
    extra=1,
    can_delete=True,
)

from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }


class ProfilePhotoForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['photo']

class EmployeeLoginForm(AuthenticationForm):
    """Same as Django's default login form, just labelled to match the UI."""
    username = forms.CharField(label="Employee ID")


class RegisterForm(forms.Form):
    """
    Plain Form (not ModelForm) so field order matches the reference page exactly:
    Employee name -> Employee ID -> Role -> Designation -> Password.

    Self-registration can only ever produce a Reporting person, Employee, or
    Intern — `role`'s choices come straight from `Role.choices`, which has no
    "Admin" entry (see accounts/models.py). There is no code path in this
    form, or anywhere else in the app, that can set `is_superuser=True` —
    that flag is Django's alone to grant, from outside the application
    (createsuperuser, or an existing superuser in Django admin).
    """
    full_name = forms.CharField(label="Employee name", max_length=150)
    employee_id = forms.CharField(label="Employee ID", max_length=150)
    role = forms.ChoiceField(label="Role", choices=Role.choices)
    designation = forms.ChoiceField(
        label="Designation", choices=[("", "Select Designation")] + list(Designation.choices), required=False
    )
    password = forms.CharField(
        label="Password", widget=forms.PasswordInput, min_length=8
    )

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"]
        if User.objects.filter(username=employee_id).exists():
            raise forms.ValidationError("This Employee ID is already registered.")
        return employee_id  

    def clean_role(self):
        # Belt-and-braces: reject anything outside Role.values even if a
        # request is crafted by hand with a role value that isn't one of the
        # rendered <option>s (e.g. a raw POST of role=ADMIN).
        role = self.cleaned_data["role"]
        if role not in Role.values:
            raise forms.ValidationError("Invalid role selected.")
        return role

    def save(self):
        data = self.cleaned_data
        user = User(
            username=data["employee_id"],
            role=data["role"],
            designation=data["designation"] or None,
            is_active=False,  # requires admin approval before first sign-in
            is_superuser=False,  # self-registration can never create an Admin
            is_staff=False,
        )
        name_parts = data["full_name"].split(maxsplit=1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.set_password(data["password"])
        user.plain_password = data["password"]
        user.save()
        return user


class EmployeeRegistrationForm(forms.Form):
    """
    Admin-only employee registration (Employee Management module).

    Unlike RegisterForm (self-registration), the Employee ID is never typed
    by anyone — it's auto-generated as E2E-001, E2E-002, ... at save time
    (see accounts/utils.py) — and the account is active immediately, since
    an Admin vouching for it replaces the "pending approval" step.

    Same admin-lockdown guarantee as RegisterForm: `role`'s choices come
    from Role.choices, which has no "Admin" entry, and is_superuser/is_staff
    are hard-coded False here — there is no path from this form to an Admin
    account.
    """
    full_name = forms.CharField(label="Employee name", max_length=150)
    employee_id = forms.CharField(max_length=20, label="Employee ID")
    email = forms.EmailField(label="Email", required=False)
    role = forms.ChoiceField(label="Role", choices=Role.choices)
    reporting_person = forms.ModelChoiceField(
        label="Reporting Person",
        queryset=User.objects.filter(Q(role=Role.REPORTING_PERSON) | Q(is_superuser=True)),
        required=False,
        empty_label="No reporting person",
        help_text="This employee will appear ONLY in this person's My Team roster.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["reporting_person"].label_from_instance = lambda user: (
        f"{user.get_full_name() or user.username} - "
        f"{user.employee_code} - "
        f"{user.get_role_display()}"
    )
        
    photo = forms.ImageField(label="Employee Photo", required=False, widget=forms.FileInput)
    password = forms.CharField(
    label="Initial password",
    min_length=8,
    widget=forms.PasswordInput(attrs={
        "class": "password-input",
        "autocomplete": "new-password",
    }),
)

    confirm_password = forms.CharField(
    label="Confirm password",
    widget=forms.PasswordInput(attrs={
        "class": "password-input",
        "autocomplete": "new-password",
    }),
)

    

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role not in Role.values:
            raise forms.ValidationError("Invalid role selected.")
        return role
    
    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"]

        if User.objects.filter(username=employee_id).exists():
            raise forms.ValidationError("This Employee ID already exists.")

        return employee_id

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirm_password = cleaned.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned

    def save(self):
        data = self.cleaned_data
        name_parts = data["full_name"].split(maxsplit=1)

        
        user = User(
            username=data["employee_id"],
            email=data.get("email") or "",
            role=data["role"],
            reporting_person=data.get("reporting_person"),
            photo=data.get("photo"),
            is_active=True,      # Admin-registered -> no approval step needed
            is_superuser=False,  # This form can never create an Admin
            is_staff=False,
        )
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.set_password(data["password"])
        user.plain_password = data["password"]
        user.save()
        return user

        


class EmployeeEditForm(forms.ModelForm):
    """
    Admin-only edit of an existing employee (Employee Management module).

    Deliberately excludes `username` (the Employee ID is permanent, never
    editable after registration) and `is_superuser`/`is_staff`/`password`
    entirely — this form can neither create nor touch an Admin account,
    mirroring the same lockdown CustomUserAdmin already enforces.
    """
    full_name = forms.CharField(label="Employee name", max_length=150)

    password = forms.CharField(
        label="Password",
        required=False,
        widget=forms.PasswordInput(attrs={
            "class": "password-input",
            "autocomplete": "off",
        },
        render_value=True,
        ),
        help_text="Shown as currently set. Leave it exactly as-is to keep it unchanged.",
    )

    class Meta:
        model = User
        fields = ["email", "role", "reporting_person", "photo", "is_active"]
        widgets = {
            "photo": forms.FileInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].initial = self.instance.get_full_name()
        self.fields["password"].initial = self.instance.plain_password or ""
        self.fields["reporting_person"].required = False
        self.fields["reporting_person"].empty_label = "No reporting person"
        self.fields["reporting_person"].queryset = (
            User.objects.filter(Q(role=Role.REPORTING_PERSON) | Q(is_superuser=True))
            .exclude(pk=self.instance.pk)
        )

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role not in Role.values:
            raise forms.ValidationError("Invalid role selected.")
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        name_parts = self.cleaned_data["full_name"].split(maxsplit=1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        new_password = self.cleaned_data.get("password")
        if new_password and new_password != (self.instance.plain_password or ""):
            user.set_password(new_password)
            user.plain_password = new_password
        if commit:
            user.save()
        return user