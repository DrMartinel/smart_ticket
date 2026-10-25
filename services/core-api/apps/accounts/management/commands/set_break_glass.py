"""Turns an account's break-glass flag on or off (F13, BR-F13-06)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import AuthSource, User, UserRole
from apps.audit.models import AuditLog


class Command(BaseCommand):
    help = "Flag a manager as a break-glass account (local password sign-in), or unflag one."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("username")
        parser.add_argument("--off", action="store_true", help="remove the flag")

    def handle(self, *args: object, **options: object) -> None:
        username, off = str(options["username"]), bool(options["off"])
        limit = settings.THRESHOLDS.identity.max_break_glass_accounts
        with transaction.atomic():
            user = User.objects.select_for_update().filter(username=username).first()
            if user is None:
                raise CommandError(f"no user {username!r}")
            if not off:
                if user.external_id or user.auth_source != AuthSource.LOCAL.value:
                    raise CommandError(
                        "a break-glass account must be local, not linked to Keycloak; "
                        "create a separate local manager"
                    )
                if user.role != UserRole.MANAGER.value:
                    raise CommandError("only a manager can be a break-glass account")
                others = User.objects.filter(is_break_glass=True).exclude(pk=user.pk).count()
                if others >= limit:
                    raise CommandError(
                        f"already {others} break-glass account(s); the limit is {limit}"
                    )
            user.is_break_glass = not off
            user.save(update_fields=["is_break_glass"])
            AuditLog.objects.record(
                "break_glass_changed",
                actor_type="system",
                actor_id=user.id,
                payload={"is_break_glass": user.is_break_glass},
            )
        self.stdout.write(f"{username}: break-glass {'off' if off else 'on'}")
