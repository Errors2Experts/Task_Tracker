from django.contrib import admin
from .models import PushSubscription, Task, TaskActivity, TaskAttachment, TaskComment, TaskNotification


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "team", "assigned_to", "status", "priority", "progress", "due_date", "created_by", "created_at")
    list_filter = ("status", "priority", "team")
    search_fields = ("title", "description")


@admin.register(TaskActivity)
class TaskActivityAdmin(admin.ModelAdmin):
    list_display = ("task", "verb", "detail", "actor", "created_at")
    list_filter = ("verb",)
    readonly_fields = ("task", "actor", "verb", "detail", "created_at")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("task", "author", "created_at")
    search_fields = ("body",)
    readonly_fields = ("created_at",)


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("task", "original_filename", "size_display", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_at",)


@admin.register(TaskNotification)
class TaskNotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "verb", "message", "is_read", "created_at")
    list_filter = ("verb", "is_read")
    readonly_fields = ("recipient", "task", "actor", "verb", "message", "created_at")


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "endpoint", "created_at")
    readonly_fields = ("user", "endpoint", "p256dh", "auth", "created_at")
    actions = ["send_test_push"]

    @admin.action(description="Send a test push notification")
    def send_test_push(self, request, queryset):
        import json
        from django.conf import settings
        from django.contrib import messages
        from pywebpush import webpush, WebPushException

        for subscription in queryset:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=json.dumps({
                        "title": "Test notification",
                        "body": "If you see this, push is working correctly.",
                        "priority": "MEDIUM",
                        "url": "/dashboard/",
                    }),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"},
                )
                self.message_user(
                    request,
                    f"Sent to {subscription.user} ({subscription.endpoint[:60]}...)",
                    level=messages.SUCCESS,
                )
            except WebPushException as exc:
                self.message_user(
                    request,
                    f"Failed for {subscription.user}: {exc}",
                    level=messages.ERROR,
                )