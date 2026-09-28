"""
Clients for systems outside core-api's process: ai-engine and the self-hosted
vLLM servers (ADR-0009). Not a Django app — no models, no migrations, nothing
in INSTALLED_APPS.

What belongs here is transport, never judgement: each client either returns
the other side's answer or raises a documented exception, and the caller in
`apps/` decides what that failure means (always toward a human — spec §10.3).

The PII NER call is the one deliberate exception. It stays in
`apps/tickets/services/masking.py`, next to the rule that its failure is
MASK_FAILED and never "no PII found", inside the module whose 100% branch
coverage is a release gate.
"""
