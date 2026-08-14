from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.forms import EmployeeEditForm, EmployeeRegistrationForm, RegisterForm
from apps.accounts.models import Designation, Role, Team, User
from apps.accounts.permissions import (
    can_assign_to,
    get_assignable_employees,
    get_roster_scope_message,
    get_visible_tasks_queryset,
    has_full_access,
    is_employee_tier,
)
from apps.accounts.utils import next_employee_id
from apps.tasks.models import Task


class RegisterFormAdminLockdownTests(TestCase):
    """RBAC requirement: Admin cannot be created from the application."""

    def _valid_data(self, **overrides):
        data = {
            "full_name": "Test Person",
            "employee_id": "E2E-TEST-1",
            "role": Role.EMPLOYEE,
            "designation": "",
            "password": "correct-horse-1",
        }
        data.update(overrides)
        return data

    def test_admin_is_not_an_offered_role_choice(self):
        choice_values = [value for value, _ in Role.choices]
        self.assertNotIn("ADMIN", choice_values)

    def test_role_admin_is_rejected_even_if_posted_directly(self):
        form = RegisterForm(data=self._valid_data(role="ADMIN"))
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    def test_successful_registration_never_grants_superuser_or_staff(self):
        form = RegisterForm(data=self._valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_active)  # still pending admin approval


class IsAdminPropertyTests(TestCase):
    def test_is_admin_mirrors_is_superuser_only(self):
        regular = User.objects.create_user(username="regular", password="x", role=Role.EMPLOYEE)
        admin = User.objects.create_user(
            username="root", password="x", is_superuser=True, is_staff=True,
        )
        self.assertFalse(regular.is_admin)
        self.assertTrue(admin.is_admin)

    def test_model_rejects_a_hand_written_admin_role(self):
        user = User(username="tamper", role="ADMIN")
        with self.assertRaises(Exception):
            user.full_clean()


class RbacHelperTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")

        self.admin = User.objects.create_user(
            username="admin1", password="x", is_superuser=True, is_staff=True,
        )
        # Mirrors real-world data: a superuser whose `role` defaults to EMPLOYEE.
        self.admin.role = Role.EMPLOYEE
        self.admin.save()

        self.manager = User.objects.create_user(
            username="mgr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.MANAGER,
        )
        self.lead = User.objects.create_user(
            username="lead1", password="x", role=Role.REPORTING_PERSON,
            designation=Designation.TECHNICAL_LEAD, team=self.team,
        )
        self.employee = User.objects.create_user(
            username="emp1", password="x", role=Role.EMPLOYEE, team=self.team,
        )

    def test_admin_never_in_any_assignable_employee_list(self):
        for actor in (self.admin, self.manager, self.lead):
            with self.subTest(actor=actor.username):
                queryset = get_assignable_employees(actor, User)
                self.assertFalse(queryset.filter(is_superuser=True).exists())

    def test_nobody_can_assign_a_task_to_the_admin(self):
        for actor in (self.admin, self.manager, self.lead, self.employee):
            with self.subTest(actor=actor.username):
                self.assertFalse(can_assign_to(actor, self.admin))

    def test_admin_and_manager_have_full_access(self):
        self.assertTrue(has_full_access(self.admin))
        self.assertTrue(has_full_access(self.manager))
        self.assertFalse(has_full_access(self.lead))
        self.assertFalse(has_full_access(self.employee))

    def test_admin_is_not_misclassified_as_employee_tier(self):
        # self.admin.role == "EMPLOYEE" by default, but is_superuser=True
        # must always win.
        self.assertFalse(is_employee_tier(self.admin))
        self.assertTrue(is_employee_tier(self.employee))

    def test_admin_sees_every_task(self):
        Task.objects.create(title="T1", team=self.team, assigned_to=self.employee, created_by=self.admin)
        visible = get_visible_tasks_queryset(self.admin, Task)
        self.assertEqual(visible.count(), Task.objects.count())

    def test_roster_scope_message_reports_full_access_for_admin(self):
        self.assertIn("Full access", get_roster_scope_message(self.admin))


class EmployeeIdGenerationTests(TestCase):
    """Employee Management: auto-generated, sequential, unique Employee IDs."""

    def test_first_id_is_e2e_001(self):
        self.assertEqual(next_employee_id(User), "E2E-001")

    def test_id_increments_from_highest_existing(self):
        User.objects.create_user(username="E2E-001", password="x")
        User.objects.create_user(username="E2E-002", password="x")
        self.assertEqual(next_employee_id(User), "E2E-003")

    def test_non_matching_usernames_are_ignored(self):
        # Free-form self-registration IDs (see RegisterForm) shouldn't
        # confuse the sequential generator.
        User.objects.create_user(username="E2E-TEST-1", password="x")
        User.objects.create_user(username="somebody", password="x")
        self.assertEqual(next_employee_id(User), "E2E-001")

    def test_ids_go_beyond_three_digits_without_breaking(self):
        User.objects.create_user(username="E2E-999", password="x")
        self.assertEqual(next_employee_id(User), "E2E-1000")


class EmployeeRegistrationFormTests(TestCase):
    """Admin-only employee registration: auto ID, no path to Admin status."""

    def _valid_data(self, **overrides):
        data = {
            "full_name": "Jordan Lee",
            "email": "jordan@example.com",
            "role": Role.EMPLOYEE,
            "designation": "",
            "team": "",
            "password": "correct-horse-1",
            "confirm_password": "correct-horse-1",
        }
        data.update(overrides)
        return data

    def test_valid_registration_generates_employee_id_and_activates_immediately(self):
        form = EmployeeRegistrationForm(data=self._valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertEqual(employee.username, "E2E-001")
        self.assertTrue(employee.is_active)
        self.assertFalse(employee.is_superuser)
        self.assertFalse(employee.is_staff)

    def test_role_admin_is_rejected_even_if_posted_directly(self):
        form = EmployeeRegistrationForm(data=self._valid_data(role="ADMIN"))
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    def test_mismatched_passwords_are_rejected(self):
        form = EmployeeRegistrationForm(data=self._valid_data(confirm_password="something-else"))
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_password", form.errors)

    def test_reporting_person_requires_designation(self):
        form = EmployeeRegistrationForm(
            data=self._valid_data(role=Role.REPORTING_PERSON, designation="")
        )
        self.assertFalse(form.is_valid())
        self.assertIn("designation", form.errors)

    def test_sequential_ids_across_multiple_registrations(self):
        for _ in range(3):
            form = EmployeeRegistrationForm(data=self._valid_data())
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        usernames = set(User.objects.values_list("username", flat=True))
        self.assertEqual(usernames, {"E2E-001", "E2E-002", "E2E-003"})


class EmployeeManagementViewAccessTests(TestCase):
    """Employee Management pages are Admin-only, end to end."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="admin1", password="pw", is_superuser=True, is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="emp1", password="pw", role=Role.EMPLOYEE,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("employee_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_non_admin_employee_is_forbidden(self):
        self.client.login(username="emp1", password="pw")
        response = self.client.get(reverse("employee_list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_employee_list(self):
        self.client.login(username="admin1", password="pw")
        response = self.client.get(reverse("employee_list"))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_register_an_employee_via_the_view(self):
        self.client.login(username="admin1", password="pw")
        response = self.client.post(reverse("employee_register"), data={
            "full_name": "Casey Kim",
            "email": "",
            "role": Role.EMPLOYEE,
            "designation": "",
            "team": "",
            "password": "correct-horse-1",
            "confirm_password": "correct-horse-1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="E2E-001").exists())

    def test_admin_account_never_appears_in_employee_list_queryset(self):
        self.client.login(username="admin1", password="pw")
        response = self.client.get(reverse("employee_list"))
        self.assertNotIn(self.admin, response.context["employees"].object_list)

    def test_non_admin_cannot_edit_employees(self):
        self.client.login(username="emp1", password="pw")
        response = self.client.get(reverse("employee_edit", args=[self.employee.pk]))
        self.assertEqual(response.status_code, 403)
