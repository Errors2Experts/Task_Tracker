from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Designation, Role, Team, User
from .models import Task, TaskActivity, TaskAttachment, TaskComment, TaskNotification, TaskPriority, TaskStatus
from .permissions import can_comment_or_attach, can_edit_task_fields, can_update_status_progress


class TaskAssignmentAdminExclusionTests(TestCase):
    """RBAC requirement: nobody can assign a task to the Admin, via any route."""

    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.admin = User.objects.create_user(
            username="admin1", password="x", is_superuser=True, is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="mgr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.MANAGER,
        )
        self.employee = User.objects.create_user(
            username="emp1", password="x", role=Role.EMPLOYEE, team=self.team,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.manager)

    def test_api_rejects_task_creation_assigned_to_admin(self):
        response = self.client.post(
            "/api/tasks/",
            {
                "title": "Sneaky task",
                "team": self.team.id,
                "assigned_to": self.admin.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned_to", response.data)

    def test_api_allows_task_creation_assigned_to_regular_employee(self):
        response = self.client.post(
            "/api/tasks/",
            {
                "title": "Normal task",
                "team": self.team.id,
                "assigned_to": self.employee.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Task.objects.get(id=response.data["id"]).assigned_to_id, self.employee.id)


class TaskProgressStatusSyncTests(TestCase):
    """Progress and status are kept in lockstep by Task.save()."""

    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.employee = User.objects.create_user(username="emp1", password="x", role=Role.EMPLOYEE, team=self.team)
        self.task = Task.objects.create(title="Ship feature", team=self.team, assigned_to=self.employee)

    def test_completing_status_snaps_progress_to_100(self):
        self.task.status = TaskStatus.COMPLETED
        self.task.save()
        self.assertEqual(self.task.progress, 100)

    def test_reaching_100_progress_marks_completed(self):
        self.task.progress = 100
        self.task.save()
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)

    def test_moving_off_100_reopens_task(self):
        self.task.progress = 100
        self.task.save()
        self.task.refresh_from_db()
        self.task.progress = 60
        self.task.save()
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)


class TaskRBACHelperTests(TestCase):
    """apps.tasks.permissions composes accounts RBAC correctly for the new
    comment/attachment/edit surfaces."""

    def setUp(self):
        self.dev_team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.marketing_team = Team.objects.create(name="Growth", department="MARKETING")
        self.hr = User.objects.create_user(
            username="hr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.HR,
        )
        self.tech_lead = User.objects.create_user(
            username="lead1", password="x", role=Role.REPORTING_PERSON, designation=Designation.TECHNICAL_LEAD,
        )
        self.employee = User.objects.create_user(
            username="emp1", password="x", role=Role.EMPLOYEE, team=self.dev_team,
        )
        self.other_employee = User.objects.create_user(
            username="emp2", password="x", role=Role.EMPLOYEE, team=self.dev_team,
        )
        self.task = Task.objects.create(title="Fix bug", team=self.dev_team, assigned_to=self.employee)

    def test_hr_cannot_comment_or_edit(self):
        self.assertFalse(can_comment_or_attach(self.hr, self.task))
        self.assertFalse(can_edit_task_fields(self.hr, self.task))

    def test_department_lead_can_edit_and_comment(self):
        self.assertTrue(can_edit_task_fields(self.tech_lead, self.task))
        self.assertTrue(can_comment_or_attach(self.tech_lead, self.task))

    def test_assignee_can_update_status_and_comment_on_own_task(self):
        self.assertTrue(can_update_status_progress(self.employee, self.task))
        self.assertTrue(can_comment_or_attach(self.employee, self.task))

    def test_employee_cannot_edit_or_touch_others_task(self):
        self.assertFalse(can_edit_task_fields(self.employee, self.task))
        self.assertFalse(can_update_status_progress(self.other_employee, self.task))
        self.assertFalse(can_comment_or_attach(self.other_employee, self.task))

    def test_marketing_lead_scoped_out_of_dev_task(self):
        marketing_lead = User.objects.create_user(
            username="mlead1", password="x", role=Role.REPORTING_PERSON,
            designation=Designation.DIGITAL_MARKETING_LEAD,
        )
        self.assertFalse(can_edit_task_fields(marketing_lead, self.task))


class TaskCommentAttachmentAPITests(TestCase):
    """Comments and attachments respect the same RBAC as the task itself,
    and every write is logged to TaskActivity (and triggers notifications)."""

    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.manager = User.objects.create_user(
            username="mgr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.MANAGER,
        )
        self.employee = User.objects.create_user(
            username="emp1", password="x", role=Role.EMPLOYEE, team=self.team,
        )
        self.hr = User.objects.create_user(
            username="hr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.HR,
        )
        self.task = Task.objects.create(
            title="Deploy service", team=self.team, assigned_to=self.employee, created_by=self.manager,
        )
        self.client = APIClient()

    def test_assignee_can_comment_and_manager_is_notified(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.post(
            "/api/task-comments/", {"task": self.task.id, "body": "Started this."}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(TaskComment.objects.count(), 1)
        self.assertTrue(TaskActivity.objects.filter(task=self.task, verb="COMMENTED").exists())
        self.assertTrue(
            TaskNotification.objects.filter(recipient=self.manager, task=self.task, verb="COMMENTED").exists()
        )

    def test_hr_cannot_comment(self):
        self.client.force_authenticate(user=self.hr)
        response = self.client.post(
            "/api/task-comments/", {"task": self.task.id, "body": "Trying to comment."}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_empty_comment_rejected(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.post("/api/task-comments/", {"task": self.task.id, "body": "   "}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_attachment_upload_and_extension_validation(self):
        self.client.force_authenticate(user=self.employee)
        good_file = SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake content", content_type="application/pdf")
        response = self.client.post(
            "/api/task-attachments/", {"task": self.task.id, "file": good_file}, format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(TaskAttachment.objects.count(), 1)
        self.assertTrue(TaskActivity.objects.filter(task=self.task, verb="ATTACHMENT_ADDED").exists())

        bad_file = SimpleUploadedFile("virus.exe", b"binary", content_type="application/octet-stream")
        response = self.client.post(
            "/api/task-attachments/", {"task": self.task.id, "file": bad_file}, format="multipart",
        )
        self.assertEqual(response.status_code, 400)


class TaskNotificationScopeTests(TestCase):
    """Notifications are strictly per-recipient — nobody can read or mark
    another person's notifications as read."""

    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.employee = User.objects.create_user(username="emp1", password="x", role=Role.EMPLOYEE, team=self.team)
        self.other_employee = User.objects.create_user(username="emp2", password="x", role=Role.EMPLOYEE, team=self.team)
        self.task = Task.objects.create(title="Task A", team=self.team, assigned_to=self.employee)
        self.note = TaskNotification.objects.create(
            recipient=self.employee, task=self.task, verb="CREATED", message="New task assigned",
        )
        self.client = APIClient()

    def test_user_only_sees_own_notifications(self):
        self.client.force_authenticate(user=self.other_employee)
        response = self.client.get("/api/task-notifications/")
        self.assertEqual(response.status_code, 200)
        ids = [n["id"] for n in response.data["results"]] if "results" in response.data else response.data
        self.assertNotIn(self.note.id, [n["id"] if isinstance(n, dict) else n for n in ids])

    def test_recipient_can_mark_own_notification_read(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.patch(f"/api/task-notifications/{self.note.id}/", {"is_read": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)


class TaskActivityLoggingTests(TestCase):
    """Priority/progress/due-date/reassignment changes made through the API
    are all recorded in the activity history."""

    def setUp(self):
        self.team = Team.objects.create(name="Backend", department="DEVELOPER")
        self.manager = User.objects.create_user(
            username="mgr1", password="x", role=Role.REPORTING_PERSON, designation=Designation.MANAGER,
        )
        self.employee = User.objects.create_user(username="emp1", password="x", role=Role.EMPLOYEE, team=self.team)
        self.task = Task.objects.create(
            title="Refactor module", team=self.team, assigned_to=self.employee, priority=TaskPriority.MEDIUM,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.manager)

    def test_priority_change_logged(self):
        response = self.client.patch(f"/api/tasks/{self.task.id}/", {"priority": "HIGH"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(TaskActivity.objects.filter(task=self.task, verb="PRIORITY_CHANGED").exists())

    def test_progress_change_logged(self):
        response = self.client.patch(f"/api/tasks/{self.task.id}/", {"progress": 40}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(TaskActivity.objects.filter(task=self.task, verb="PROGRESS_UPDATED").exists())

    def test_invalid_progress_rejected(self):
        response = self.client.patch(f"/api/tasks/{self.task.id}/", {"progress": 150}, format="json")
        self.assertEqual(response.status_code, 400)

