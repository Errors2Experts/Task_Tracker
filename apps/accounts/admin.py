from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Team, EmployeeAssignment


class EmployeeAssignmentInline(admin.TabularInline):
    model = EmployeeAssignment
    fk_name = "employee"
    extra = 0


@admin.action(description="Approve selected users (allow them to sign in)")
def approve_users(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{updated} user(s) approved.")


class CustomUserAdmin(UserAdmin):
    """
    Everyone here is managed through the normal Role/Designation fields
    except for one thing: "Admin" status. Admin == is_superuser, and only an
    existing superuser is allowed to view or change that flag (or the
    related permissions/groups fields) for any account, including their own.
    A non-superuser staff member with access to this admin page cannot
    promote anyone — including themselves — to Admin.
    """
    actions = [approve_users]
    inlines = [EmployeeAssignmentInline]
    fieldsets = UserAdmin.fieldsets + (
        ("Role Info", {"fields": ("role", "designation", "team", "reporting_person")}),
    )
    list_display = ("username", "email", "role", "designation", "team", "reporting_person", "is_active", "is_superuser")
    list_filter = ("role", "designation", "team", "is_active", "is_superuser")

    SUPERUSER_ONLY_FIELDS = ("is_superuser", "user_permissions")

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets

        trimmed = []
        for name, options in fieldsets:
            fields = tuple(f for f in options.get("fields", ()) if f not in self.SUPERUSER_ONLY_FIELDS)
            trimmed.append((name, {**options, "fields": fields}))
        return trimmed

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.extend(self.SUPERUSER_ONLY_FIELDS)
        return readonly

    def has_change_permission(self, request, obj=None):
        # A non-superuser must never be able to edit an existing Admin
        # account, even fields unrelated to permissions (defense in depth —
        # this admin page is not where Admin accounts get managed).
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)


admin.site.register(User, CustomUserAdmin)
admin.site.register(Team)
admin.site.register(EmployeeAssignment)