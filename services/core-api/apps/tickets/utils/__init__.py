"""
Ticket logic that is not one model's behaviour, so it does not live on a
model:

- `router.py`: the routing decision. A pure function with thresholds passed
  in, and the only place a `Branch` is chosen (ADR-0001).
- `trust_scorer.py`: the trust score, pure maths over signals, kept in
  core-api so the LLM cannot score itself (ADR-0003).
- `masking.py` and `patterns.py`: PII masking, which runs before any
  `Ticket` exists. 100% branch coverage of masking and router is a release
  gate.
- `crypto.py`: encryption for the PII quarantine.
- `pipeline.py`: the per-ticket pipeline, which coordinates several models.
"""
