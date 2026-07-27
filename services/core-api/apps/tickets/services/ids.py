"""
Public-facing IDs (TKT-2026-000123, INC-2026-0007). Backed by dedicated
Postgres sequences (created in apps/tickets/migrations/0002_sequences_and_sql.py)
rather than by counting rows, so IDs stay monotonic and collision-free even
under concurrent ticket submission.
"""

from django.db import connection
from django.utils import timezone


def next_ticket_public_id() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('ticket_public_id_seq')")
        n = cur.fetchone()[0]
    return f"TKT-{timezone.now().year}-{n:06d}"


def next_incident_public_id() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('incident_public_id_seq')")
        n = cur.fetchone()[0]
    return f"INC-{timezone.now().year}-{n:04d}"
