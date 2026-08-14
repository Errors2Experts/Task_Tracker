from apps.tasks.models import TaskNotification

def unread_task_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    if user.is_superuser or user.designation == "MANAGER":
        count = TaskNotification.objects.filter(is_read=False).count()
    else:
        count = user.task_notifications.filter(is_read=False).count()

    return {
        "unread_task_notification_count": count,
    }