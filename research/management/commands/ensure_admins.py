import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Ensure admin users exist and reset passwords from environment variables"

    def handle(self, *args, **options):
        User = get_user_model()

        admins = [
            (os.getenv("ADMIN_USER_1"), os.getenv("ADMIN_PASS_1")),
            (os.getenv("ADMIN_USER_2"), os.getenv("ADMIN_PASS_2")),
        ]

        for username, password in admins:
            if not username or not password:
                continue

            user, created = User.objects.get_or_create(username=username)

            user.is_staff = True
            user.is_superuser = True
            user.set_password(password)
            user.save()

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created admin: {username}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Updated admin: {username}"))
