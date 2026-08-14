# from django.contrib.auth.management.commands.createsuperuser import Command as BaseCommand
# from apps.accounts.models import User


# class Command(BaseCommand):
#     help = "Create a superuser with Admin ID, Full Name and Email."

#     def handle(self, *args, **options):
#         self.stdout.write(self.style.SUCCESS("=== Create Super Admin ==="))

#         while True:
#             admin_id = input("Admin ID: ").strip()

#             if not admin_id:
#                 self.stdout.write(self.style.ERROR("Admin ID is required."))
#                 continue

#             if User.objects.filter(username=admin_id).exists():
#                 self.stdout.write(self.style.ERROR("Admin ID already exists."))
#                 continue

#             break

#         full_name = input("Full Name: ").strip()
#         email = input("Email: ").strip()

#         while True:
#             password = input("Password: ")
#             confirm_password = input("Confirm Password: ")

#             if password != confirm_password:
#                 self.stdout.write(self.style.ERROR("Passwords do not match."))
#                 continue

#             if len(password) < 8:
#                 self.stdout.write(self.style.ERROR("Password must be at least 8 characters."))
#                 continue

#             break

#         name_parts = full_name.split(maxsplit=1)

#         user = User.objects.create_superuser(
#             username=admin_id,
#             email=email,
#             password=password,
#         )

#         user.first_name = name_parts[0] if name_parts else ""
#         user.last_name = name_parts[1] if len(name_parts) > 1 else ""
#         user.save()

#         self.stdout.write(
#             self.style.SUCCESS(f"\nSuperuser '{admin_id}' created successfully.")
#         )

import os
from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create Super Admin from Environment Variables"

    def handle(self, *args, **options):
        admin_id = os.getenv("ADMIN_ID")
        full_name = os.getenv("ADMIN_FULL_NAME")
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")

        if not all([admin_id, full_name, email, password]):
            self.stdout.write(
                self.style.ERROR("Admin environment variables are missing.")
            )
            return

        if User.objects.filter(username=admin_id).exists():
            self.stdout.write(
                self.style.WARNING(f"Superuser '{admin_id}' already exists.")
            )
            return

        name_parts = full_name.split(maxsplit=1)

        user = User.objects.create_superuser(
            username=admin_id,
            email=email,
            password=password,
        )

        user.first_name = name_parts[0] if name_parts else ""
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.save()

        self.stdout.write(
            self.style.SUCCESS(f"Superuser '{admin_id}' created successfully.")
        )