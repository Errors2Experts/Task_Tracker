from rest_framework.routers import DefaultRouter
from .api_views import TaskAttachmentViewSet, TaskCommentViewSet, TaskNotificationViewSet, TaskViewSet

# DRF REST API routes -> mounted under /api/ in task_tracker/urls.py
router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")
router.register(r"task-comments", TaskCommentViewSet, basename="task-comment")
router.register(r"task-attachments", TaskAttachmentViewSet, basename="task-attachment")
router.register(r"task-notifications", TaskNotificationViewSet, basename="task-notification")

urlpatterns = router.urls
