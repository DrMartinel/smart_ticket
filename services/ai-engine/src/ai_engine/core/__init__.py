"""
Infrastructure the rest of ai-engine builds on: settings, prompts, the
read-only DB, and the model providers and clients.

`graph/`, `schemas.py` and `main.py` import from `core`; nothing in `core`
imports from them (tests/test_boundary.py).
"""
