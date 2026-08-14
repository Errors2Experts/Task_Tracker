from django.db import migrations, models


def migrate_legacy_admins_forward(apps, schema_editor):
    """
    Any user that was previously given role="ADMIN" is now promoted to a
    real Django superuser (is_superuser=True, is_staff=True) and re-tagged
    as a Reporting person / Manager, since "ADMIN" is no longer a valid
    value for the `role` field. This preserves their full-access privileges
    without leaving a dangling, no-longer-valid role on the row.
    """
    User = apps.get_model("accounts", "User")
    legacy_admins = User.objects.filter(role="ADMIN")
    for user in legacy_admins:
        user.is_superuser = True
        user.is_staff = True
        user.role = "REPORTING_PERSON"
        user.designation = "MANAGER"
        user.save(update_fields=["is_superuser", "is_staff", "role", "designation"])


def migrate_legacy_admins_backward(apps, schema_editor):
    # Intentionally a no-op: there's no reliable way (or reason) to tell
    # which superusers were originally "role=ADMIN" rows versus superusers
    # created directly via createsuperuser, so reversing this migration
    # does not attempt to recreate the old ADMIN role value.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_alter_user_designation"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_admins_forward, migrate_legacy_admins_backward),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("REPORTING_PERSON", "Reporting person"),
                    ("EMPLOYEE", "Employee"),
                    ("INTERN", "Intern"),
                ],
                default="EMPLOYEE",
                max_length=30,
            ),
        ),
    ]
