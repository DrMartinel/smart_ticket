# Simulated working day

Acts out one day at a small company against the local stack, through the same
HTTP calls the admin console and the chat app make. Every person signs in
through Keycloak's login page (authorization code with PKCE), holds a real
ADR-0029 session, refreshes it, and signs in again when an access change
ends it. Nothing writes to the database directly.

```bash
uv run python -m tools.simulate --scale smoke --think 0.2   # a few of each, ~2 min
uv run python -m tools.simulate --scale day                 # ~40 requests, ~15–25 min
```

Needs the full stack with the `vllm` and `sso` profiles up, a `JEV_API_KEY`
and a DeepSeek key: each ticket calls DeepSeek and Jev, so a day costs real
API credit. It writes to the dev database like real users would; run it on a
stack you don't mind filling.

## Who and what

`cast.py` holds the people (eight IT staff, two of them new hires; eight
employees in four departments, three of them heads) and the 35 requests they
make: chat questions on the twelve AWS guides in the KB, form tickets with
personal data, a pasted password, a prompt injection, and a Client VPN outage
five people report within a minute.

`day.py` is the day, in order:

| Time | Who | What |
|---|---|---|
| 07:30 | IT, IT manager | Keycloak accounts for new hires; HR's departments and people CSV, checked then applied; base roles, teams, department heads |
| 09:00 | Employees | Chat questions; follow-ups in the same conversation; clarifying answers; asking for a person |
| 09:20 | Employees | Ticket form, then the VPN outage |
| 10:00 | Security | Acknowledge, reveal personal data with a reason, notify the requester, end sessions, close and release |
| 10:00 | Incident manager | Confirm the detector's incident or declare one, link tickets, broadcast |
| 10:00 | Technicians | Claim review items and decide; take team tickets; ask for detail; resolve |
| 11:30 | Employees, a head | Reply, rate, reopen a poor fix; the head reads the department's tickets |
| 13:30 | Everyone | Afternoon questions; a KB draft, sent back, edited and approved by a second manager; the incident resolved with close-all |
| 16:30 | Managers | Dashboard and reports, workload, a reassignment, an access review answered from the inbox; a technician books leave; everyone reads notifications and signs out |

A refusal never stops the day: it becomes a **finding** in the report.

## Output

`tools/simulate/runs/<timestamp>/` (git-ignored): `report.md` (tickets and
how triage decided them, findings, action counts, the day's story) and
`calls.jsonl` (every request, its status and time).

Settings come from the root `.env`: `OIDC_SERVER_URL` and the
`KEYCLOAK_BOOTSTRAP_ADMIN_*` pair for creating accounts; `SIM_API_URL`,
`SIM_ADMIN_ORIGIN` and `SIM_CHAT_ORIGIN` override the local defaults.
