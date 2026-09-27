import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the database is accepting connections."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args: Any, **options: Any) -> None:
        deadline = time.time() + options["timeout"]
        while time.time() < deadline:
            try:
                connections["default"].cursor()
                self.stdout.write(self.style.SUCCESS("database is up"))
                return
            except OperationalError:
                self.stdout.write("database unavailable, waiting 1s...")
                time.sleep(1)
        raise SystemExit("database never became available within timeout")
