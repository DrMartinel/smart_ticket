"""
Clients for systems outside core-api's process. There is one: ai-engine,
which is also the only way core-api reaches a model (ADR-0012). Not a Django
app — no models, no migrations, nothing in INSTALLED_APPS.

What belongs here is transport, never judgement: each client either returns
the other side's answer or raises a documented exception, and the caller in
`apps/` decides what that failure means (always toward a human — spec §10.3).
PII NER, for instance, is called from `apps/tickets/utils/masking.py`, next
to the rule that its failure is MASK_FAILED and never "no PII found", inside
the module whose 100% branch coverage is a release gate.
"""
