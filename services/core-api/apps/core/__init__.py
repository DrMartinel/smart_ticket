"""
Shared foundation for all apps. Every app may import from `core`; `core`
imports from no app — if it needs one, the code is in the wrong place.

What belongs here: abstract base models (no tables), cross-cutting request
plumbing, ops commands, and generic test helpers. What stays out: concrete
models, business rules, and helpers only one app uses.

`tests/test_boundary.py` pins the one-way rule: delete every domain app and
`core` still imports cleanly.
"""
