from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from apps.accounts.models import Department, Designation, Team
from cloudinary.models import CloudinaryField
from django_ckeditor_5.fields import CKEditor5Field


class TaskStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    BLOCKED = "BLOCKED", "Blocked"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TeamLeadApprovalStatus(models.TextChoices):
    """Tracks the cross-team approval workflow on a Task.

    NOT_REQUIRED — ordinary same-team assignment, nothing to approve.
    PENDING      — assigned across teams; the target team's lead has been
                   notified and hasn't decided yet. The task exists and is
                   visible to the assignee right away, just flagged.
    APPROVED / REJECTED — the target team's lead (or someone with full
                   access) has made a decision.
    """
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


# Attachment validation limits — enforced both here (model-level, so it also
# protects the Django admin and any future entry point) and in forms/serializers
# (so the person gets a friendly error before the file is ever saved).
ALLOWED_ATTACHMENT_EXTENSIONS = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "png", "jpg", "jpeg", "gif", "webp",
    "txt", "csv", "zip", "log",
]
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class Task(models.Model):
    title = models.CharField(max_length=200)
    description = CKEditor5Field('Description', config_name='extends')
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    priority = models.CharField(max_length=10, choices=TaskPriority.choices, default=TaskPriority.MEDIUM)

    # 0-100, kept in lockstep with `status` (see save() below): reaching 100
    # marks the task completed, and completing a task fills the bar.
    progress = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="tasks")

    # Which of the assignee's (possibly several) designations/departments
    # this particular task was assigned under — set from the Designation
    # dropdown on the "Assign a task" page (see tasks/views.py
    # task_assign_form). Optional/blank for tasks created before this field
    # existed, or where the assignee only ever had one assignment anyway.
    designation = models.CharField(max_length=30, choices=Designation.choices, blank=True, default="")
    department = models.CharField(max_length=20, choices=Department.choices, blank=True, default="")

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="assigned_tasks"
    )
    reporting_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks_reported_to_me"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="created_tasks"
    )

    due_date = models.DateField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)

    # Set when this task was assigned to someone outside the assigner's own
    # team — the target team's lead is notified and must Approve/Reject from
    # their Notifications page before it's considered signed off. Ordinary
    # same-team assignments stay NOT_REQUIRED and are never gated on this.
    team_lead_approval_status = models.CharField(
        max_length=20,
        choices=TeamLeadApprovalStatus.choices,
        default=TeamLeadApprovalStatus.NOT_REQUIRED,
    )
    team_lead_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
        help_text="Team Lead who approved or rejected this cross-team assignment.",
    )
    team_lead_decided_at = models.DateTimeField(null=True, blank=True)

    # Snapshot of task.status right before a rejection cancels it, so that if
    # the Team Lead later reverses the decision to Approved, the task's real
    # progress (e.g. it was already IN_PROGRESS) is restored instead of being
    # reset to a blank PENDING.
    pre_cancel_status = models.CharField(max_length=20, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Keep status and progress consistent no matter which one was changed:
        #   - Marking the task Completed always snaps progress to 100.
        #   - Dragging progress to 100 always marks the task Completed.
        #   - Moving progress off 100 while it was Completed reopens it to
        #     In Progress rather than leaving a contradictory 100%/blocked state.
        # Compared against what's actually in the database (not just the
        # in-memory object) so the two rules above don't fight each other
        # when only one of the two fields was actually touched.
        if self.team_id and not self.department:
            self.department = self.team.department

        previous = Task.objects.filter(pk=self.pk).values("status", "progress").first() if self.pk else None

        if previous is None:
            if self.status == TaskStatus.COMPLETED:
                self.progress = 100
            elif self.progress == 100:
                self.status = TaskStatus.COMPLETED
        else:
            status_changed = self.status != previous["status"]
            progress_changed = self.progress != previous["progress"]

            if status_changed and self.status == TaskStatus.COMPLETED:
                self.progress = 100
            elif progress_changed and self.progress == 100:
                self.status = TaskStatus.COMPLETED
            elif (
                progress_changed
                and self.progress != 100
                and previous["status"] == TaskStatus.COMPLETED
                and not status_changed
            ):
                self.status = TaskStatus.IN_PROGRESS

        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(
            self.due_date
            and self.due_date < timezone.localdate()
            and self.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )

    @property
    def is_pending_team_lead_approval(self):
        return self.team_lead_approval_status == TeamLeadApprovalStatus.PENDING


class TaskActivity(models.Model):
    """
    One row per meaningful event on a task (created, status changed, priority
    changed, progress updated, reassigned, commented, attachment added).
    Powers the dashboard's "Recent activity" feed and the task detail page's
    history tab — kept as an explicit model rather than derived from
    Task.updated_at so multiple events on the same task don't collapse into
    one, and so we can show what actually happened.
    """
    VERB_CHOICES = (
        [("CREATED", "Created")]
        + TaskStatus.choices
        + [
            ("PRIORITY_CHANGED", "Priority changed"),
            ("PROGRESS_UPDATED", "Progress updated"),
            ("DUE_DATE_CHANGED", "Due date changed"),
            ("REASSIGNED", "Reassigned"),
            ("COMMENTED", "Commented"),
            ("ATTACHMENT_ADDED", "Attachment added"),
            ("ATTACHMENT_REMOVED", "Attachment removed"),
            ("APPROVAL_REQUESTED", "Team lead approval requested"),
            ("APPROVAL_GRANTED", "Team lead approval granted"),
            ("APPROVAL_REJECTED", "Team lead approval rejected"),
            ("APPROVAL_PRE_GRANTED", "Team lead approval granted at assignment"),
        ]
    )

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="task_activity"
    )
    verb = models.CharField(max_length=20, choices=VERB_CHOICES)
    # Short free-text detail for verbs whose message needs a value baked in,
    # e.g. "HIGH", "40% -> 70%", "12 Aug". Kept short and optional; the verb
    # alone is always enough to render a sensible line even without it.
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Task activity"

    def __str__(self):
        return f"{self.task.title} — {self.verb}"

    def description(self):
        """Human-readable line for the activity feed, e.g. 'New task assigned: ...'"""
        title = self.task.title
        base = {
            "CREATED": f'New task assigned: "{title}"',
            "PENDING": f'Set "{title}" back to pending',
            "IN_PROGRESS": f'Started working on "{title}"',
            "BLOCKED": f'Flagged "{title}" as blocked',
            "COMPLETED": f'Marked "{title}" as completed',
            "CANCELLED": f'Cancelled "{title}" — Team Lead rejected the cross-team assignment',
            "PRIORITY_CHANGED": f'Changed priority of "{title}"',
            "PROGRESS_UPDATED": f'Updated progress on "{title}"',
            "DUE_DATE_CHANGED": f'Changed due date of "{title}"',
            "REASSIGNED": f'Reassigned "{title}"',
            "COMMENTED": f'Commented on "{title}"',
            "ATTACHMENT_ADDED": f'Added an attachment to "{title}"',
            "ATTACHMENT_REMOVED": f'Removed an attachment from "{title}"',
            "APPROVAL_REQUESTED": f'Approval requested for cross-team assignment: "{title}"',
            "APPROVAL_GRANTED": f'Approved cross-team assignment: "{title}"',
            "APPROVAL_REJECTED": f'Rejected cross-team assignment: "{title}"',
            "APPROVAL_PRE_GRANTED": f'You approved this task — cross-team assigned task: "{title}"',
        }.get(self.verb, f'Updated "{title}"')
        if self.detail:
            return f"{base} ({self.detail})"
        return base


class TaskComment(models.Model):
    """A single comment on a task. Anyone who can act on the task (assignee,
    reporting persons in scope, admin/manager) can leave one; HR (view-only)
    cannot, matching the read-only access it has everywhere else."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="task_comments"
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.task.title}"


def task_attachment_path(instance, filename):
    return f"task_attachments/{instance.task_id}/{filename}"


class TaskAttachment(models.Model):
    """A file uploaded against a task. Extension and size are validated at
    the model level (defense in depth) and again in the form/serializer that
    receives the upload, so invalid files never reach storage."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    file = CloudinaryField('id_proofs/', resource_type="raw")
    original_filename = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0, help_text="Size in bytes")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="task_attachments"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.original_filename or self.file.name

    def size_display(self):
        size = self.size or 0
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class TaskNotification(models.Model):
    """In-app notification generated automatically (see signals.py) whenever
    a TaskActivity is recorded. Each notification is scoped to a single
    recipient, who is the only person allowed to read/dismiss it."""
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_notifications"
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="notifications", null=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    verb = models.CharField(max_length=20, choices=TaskActivity.VERB_CHOICES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.recipient}: {self.message}"


class PushSubscription(models.Model):
    """A single browser/device subscribed to Web Push."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Push subscription for {self.user}"