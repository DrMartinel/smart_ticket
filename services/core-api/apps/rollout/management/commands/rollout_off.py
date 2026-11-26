"""Turns every rollout flag off, as the system (ADR-0051)."""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.rollout.domain.vocabulary import RolloutError
from apps.rollout.services.rollout import rollout


class Command(BaseCommand):
    help = "Turn every rollout flag that is on off at once, holding back every flagged branch."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--reason", required=True, help="why, recorded on each flag")

    def handle(self, *args: object, **options: object) -> None:
        try:
            turned_off = rollout.turn_all_off(None, str(options["reason"]))
        except RolloutError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"off: {', '.join(turned_off) or 'nothing was on'}")
