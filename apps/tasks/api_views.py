from rest_framework import mixins, permissions, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.permissions import RoleBasedTaskPermission, get_visible_tasks_queryset, is_employee_tier
from .models import Task, TaskActivity, TaskAttachment, TaskComment, TaskNotification
from .permissions import can_comment_or_attach, can_delete_attachment, can_view_task
from .serializers import (
    EmployeeTaskStatusSerializer,
    TaskAttachmentSerializer,
    TaskCommentSerializer,
    TaskNotificationSerializer,
    TaskSerializer,
)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedTaskPermission]

    def get_serializer_class(self):
        # Employees AND Interns can only ever touch status/progress, on
        # update/partial_update. Swapping the serializer class (rather than
        # trusting request data) means there's no way to sneak other fields
        # through the API. `is_employee_tier` also makes sure a superuser
        # (whose `role` defaults to "EMPLOYEE") is never mistaken for one.
        if (
            self.request.user.is_authenticated
            and is_employee_tier(self.request.user)
            and self.action in ("update", "partial_update")
        ):
            return EmployeeTaskStatusSerializer
        return TaskSerializer

    def get_queryset(self):
        # Every user only ever sees the tasks their role is allowed to see.
        # This handles the LIST endpoint. has_object_permission (in permissions.py)
        # handles the single-object GET/PUT/PATCH/DELETE endpoints.
        return get_visible_tasks_queryset(self.request.user, Task).select_related(
            "team", "assigned_to", "reporting_to", "created_by"
        )

    def perform_create(self, serializer):
        task = serializer.save(created_by=self.request.user)
        TaskActivity.objects.create(task=task, actor=self.request.user, verb="CREATED")

    def perform_update(self, serializer):
        before = serializer.instance
        old_status = before.status
        old_priority = before.priority
        old_progress = before.progress
        old_due_date = before.due_date
        old_assigned_to_id = before.assigned_to_id

        task = serializer.save()

        actor = self.request.user
        if task.status != old_status:
            TaskActivity.objects.create(task=task, actor=actor, verb=task.status)
        if task.priority != old_priority:
            TaskActivity.objects.create(
                task=task, actor=actor, verb="PRIORITY_CHANGED", detail=task.get_priority_display(),
            )
        if task.progress != old_progress:
            TaskActivity.objects.create(
                task=task, actor=actor, verb="PROGRESS_UPDATED",
                detail=f"{old_progress}% \u2192 {task.progress}%",
            )
        if task.due_date != old_due_date:
            TaskActivity.objects.create(
                task=task, actor=actor, verb="DUE_DATE_CHANGED",
                detail=task.due_date.isoformat() if task.due_date else "cleared",
            )
        if task.assigned_to_id != old_assigned_to_id:
            TaskActivity.objects.create(
                task=task, actor=actor, verb="REASSIGNED",
                detail=task.assigned_to.get_full_name() or task.assigned_to.username if task.assigned_to else "unassigned",
            )


class TaskCommentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                          mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Nested under a task: filter by ?task=<id>. Visibility and posting
    rights both follow the same RBAC as the parent task."""
    serializer_class = TaskCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        visible_task_ids = get_visible_tasks_queryset(self.request.user, Task).values_list("id", flat=True)
        qs = TaskComment.objects.filter(task_id__in=visible_task_ids).select_related("author", "task")
        task_id = self.request.query_params.get("task")
        if task_id:
            qs = qs.filter(task_id=task_id)
        return qs

    def perform_create(self, serializer):
        task = serializer.validated_data["task"]
        user = self.request.user
        if not can_view_task(user, task):
            raise PermissionDenied("You don't have access to this task.")
        if not can_comment_or_attach(user, task):
            raise PermissionDenied("You don't have permission to comment on this task.")
        comment = serializer.save(author=user)
        TaskActivity.objects.create(task=task, actor=user, verb="COMMENTED")


class TaskAttachmentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                             mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                             viewsets.GenericViewSet):
    """Nested under a task: filter by ?task=<id>."""
    serializer_class = TaskAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        visible_task_ids = get_visible_tasks_queryset(self.request.user, Task).values_list("id", flat=True)
        qs = TaskAttachment.objects.filter(task_id__in=visible_task_ids).select_related("uploaded_by", "task")
        task_id = self.request.query_params.get("task")
        if task_id:
            qs = qs.filter(task_id=task_id)
        return qs

    def perform_create(self, serializer):
        task = serializer.validated_data["task"]
        user = self.request.user
        if not can_view_task(user, task):
            raise PermissionDenied("You don't have access to this task.")
        if not can_comment_or_attach(user, task):
            raise PermissionDenied("You don't have permission to attach files to this task.")

        uploaded_file = serializer.validated_data["file"]
        attachment = serializer.save(
            uploaded_by=user,
            original_filename=uploaded_file.name,
            size=uploaded_file.size,
        )
        TaskActivity.objects.create(task=task, actor=user, verb="ATTACHMENT_ADDED", detail=attachment.original_filename)

    def perform_destroy(self, instance):
        user = self.request.user
        if not can_delete_attachment(user, instance):
            raise PermissionDenied("You don't have permission to remove this attachment.")
        task, filename = instance.task, instance.original_filename
        instance.file.delete(save=False)
        instance.delete()
        TaskActivity.objects.create(task=task, actor=user, verb="ATTACHMENT_REMOVED", detail=filename)


class TaskNotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                               mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Every user's own notification feed. Strictly scoped to
    `recipient=request.user` — there is no way to read or mark another
    person's notifications through this endpoint."""
    serializer_class = TaskNotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TaskNotification.objects.filter(recipient=self.request.user).select_related("task")

    def perform_update(self, serializer):
        # is_read is the only field a client can ever change here.
        serializer.save(is_read=True)
