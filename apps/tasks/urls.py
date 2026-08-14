from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

# Server-rendered page routes -> mounted at root ("") in task_tracker/urls.py
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("task-assign/", views.task_assign_list, name="task_assign_list"),
    path("my-team/", views.my_team, name="my_team"),
    path("task-assign/<int:employee_id>/", views.task_assign_form, name="task_assign_form"),
    path("view-tasks/", views.view_tasks, name="view_tasks"),
    path("view-tasks/export/", views.export_tasks_csv, name="export_tasks_csv"),
    path("my-tasks/", views.my_tasks, name="my_tasks"),
    path("my-tasks/<int:task_id>/status/", views.update_task_status, name="update_task_status"),

    path("tasks/<int:task_id>/", views.task_detail, name="task_detail"),
    path("tasks/<int:task_id>/edit/", views.task_edit, name="task_edit"),
    path("tasks/<int:task_id>/attachments/<int:attachment_id>/delete/", views.task_delete_attachment, name="task_delete_attachment"),

    path("notifications/", views.notifications_list, name="notifications"),
    path("notifications/<int:notification_id>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("notifications/mark-all-read/", views.notifications_mark_all_read, name="notifications_mark_all_read"),
    path("tasks/<int:task_id>/team-lead-decision/<str:decision>/", views.task_team_lead_decision, name="task_team_lead_decision"),
    path("tasks/<int:task_id>/delete/", views.task_delete, name="task_delete"),
    
    path("notifications/poll/", views.notifications_poll, name="notifications_poll"),
    path("push/public-key/", views.push_public_key, name="push_public_key"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)