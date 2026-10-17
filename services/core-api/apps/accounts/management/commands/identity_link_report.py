"""Lists local users with no Keycloak `sub`, to link or deactivate after the cut-over (F13)."""

from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = "List local users that no Keycloak identity is linked to."

    def handle(self, *args: object, **options: object) -> None:
        users = User.objects.filter(external_id__isnull=True).order_by("username")
        for user in users:
            flags = ["active" if user.is_active else "inactive"]
            if user.is_break_glass:
                flags.append("break-glass")
            self.stdout.write(
                f"{user.username}\t{user.email or '-'}\t{user.role}\t{', '.join(flags)}"
            )
        self.stdout.write(f"{users.count()} local user(s) without a Keycloak link")
