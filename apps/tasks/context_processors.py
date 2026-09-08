from apps.accounts.permissions import (
    can_view_my_team,
    is_hr,
    is_manager,
)
from apps.tasks.models import TaskNotification


def unread_task_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    if user.is_superuser or is_manager(user):
        count = TaskNotification.objects.filter(is_read=False).count()
    else:
        count = user.task_notifications.filter(is_read=False).count()

    return {
        "unread_task_notification_count": count,
    }


def rbac_nav_flags(request):
    """Sidebar/nav visibility flags, computed once here instead of the
    templates comparing `request.user.designation` (the single PRIMARY
    field) directly. Every flag below checks across ALL of a user's
    designation assignments (see accounts/permissions.py), so a designation
    held only as a secondary assignment — e.g. Manager alongside Digital
    Marketing Lead — still lights up the right nav links."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    return {
        "nav_is_manager": is_manager(user),
        "nav_is_hr": is_hr(user),
        "nav_can_view_my_team": can_view_my_team(user),
    }