from django.urls import path
from . import views

urlpatterns = [
    path("register/", views.register, name="register"),

    # Employee Management (Admin-only)
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/register/", views.employee_register, name="employee_register"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("profile/", views.profile, name="profile"),
    path("api/mentions/", views.mention_feed, name="mention_feed"),
]