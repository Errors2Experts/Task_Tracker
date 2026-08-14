from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.permissions import can_assign_to
from .models import Task, TaskAttachment, TaskComment, TaskNotification
from .validators import validate_attachment_file, validate_comment_body

User = get_user_model()


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    comments_count = serializers.IntegerField(source="comments.count", read_only=True)
    attachments_count = serializers.IntegerField(source="attachments.count", read_only=True)

    # The Admin (superuser) is excluded from the valid-choices queryset, so
    # it can never appear in an API client's assignment dropdown and can
    # never be accepted as a value even if a client sends its id directly.
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_superuser=False), required=False, allow_null=True,
    )

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "status", "priority", "progress",
            "team", "team_name", "assigned_to", "assigned_to_username",
            "reporting_to", "due_date", "due_time", "is_overdue",
            "comments_count", "attachments_count",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def validate_progress(self, value):
        if not (0 <= value <= 100):
            raise serializers.ValidationError("Progress must be between 0 and 100.")
        return value

    def validate_assigned_to(self, value):
        if value is None:
            return value
        # Belt-and-braces on top of the restricted queryset above, and the
        # place that actually enforces "who can assign to whom" scope.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if value.is_superuser:
            raise serializers.ValidationError("Tasks cannot be assigned to an Admin account.")
        if user is not None and not can_assign_to(user, value):
            raise serializers.ValidationError("You don't have permission to assign tasks to this employee.")
        return value


class EmployeeTaskStatusSerializer(serializers.ModelSerializer):
    """
    Used ONLY for Employee/Intern update/partial_update actions.
    Every field except `status` and `progress` is read-only here, so even if
    an employee sends title/team/priority/assigned_to in the request body,
    only those two fields ever get saved.
    """
    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "status", "progress", "priority",
            "team", "assigned_to", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "title", "description", "priority",
            "team", "assigned_to", "created_by", "created_at", "updated_at",
        ]

    def validate_progress(self, value):
        if not (0 <= value <= 100):
            raise serializers.ValidationError("Progress must be between 0 and 100.")
        return value


class TaskCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ["id", "task", "author", "author_name", "body", "created_at"]
        read_only_fields = ["author", "created_at"]

    def get_author_name(self, obj):
        if not obj.author:
            return None
        return obj.author.get_full_name() or obj.author.username

    def validate_body(self, value):
        return validate_comment_body(value)


class TaskAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    size_display = serializers.CharField(read_only=True)

    class Meta:
        model = TaskAttachment
        fields = [
            "id", "task", "file", "original_filename", "size", "size_display",
            "uploaded_by", "uploaded_by_name", "uploaded_at",
        ]
        read_only_fields = ["uploaded_by", "uploaded_at", "size", "original_filename"]

    def get_uploaded_by_name(self, obj):
        if not obj.uploaded_by:
            return None
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username

    def validate_file(self, value):
        validate_attachment_file(value)
        return value


class TaskNotificationSerializer(serializers.ModelSerializer):
    task_title = serializers.CharField(source="task.title", read_only=True, default=None)

    class Meta:
        model = TaskNotification
        fields = ["id", "task", "task_title", "verb", "message", "is_read", "created_at"]
        read_only_fields = ["task", "verb", "message", "created_at"]
