import os

from django.core.management.base import BaseCommand
from apps.accounts.models import User, Role, Designation


class Command(BaseCommand):
    help = "Create Super Admin from Environment Variables"

    def handle(self, *args, **options):
        admin_id = os.getenv("ADMIN_ID")
        full_name = os.getenv("ADMIN_FULL_NAME")
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")

        if not all([admin_id, full_name, email, password]):
            self.stdout.write(self.style.ERROR("Admin environment variables are missing."))
            return

        if User.objects.filter(username=admin_id).exists():
            self.stdout.write(
                self.style.WARNING(f"Superuser '{admin_id}' already exists."))
            return

        name_parts = full_name.strip().split(maxsplit=1)

        user = User.objects.create_superuser(
            username=admin_id,
            email=email,
            password=password,
        )

        user.first_name = name_parts[0] if name_parts else ""
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""

        # Admin-specific designation
        user.designation = Designation.FOUNDER_TECHNICAL_MENTOR

        user.save()

        self.stdout.write(self.style.SUCCESS(f"Superuser '{admin_id}' created successfully."))