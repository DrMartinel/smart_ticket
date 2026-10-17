# 1. Executive summary

## 1.1 Why this phase

Today Smart Ticket is good at the **first five minutes** of a ticket: it masks
PII, finds the right KB page, and decides who should act. It is weak at
**everything after that**:

- Once a ticket lands with support, nothing measures how long it waits. There
  is no SLA clock, no business-hours calendar, no breach warning.
- "Assigned team" is the category name copied into a text field. There are no
  teams, no members, no workload.
- A requester asks once and sees one answer. They cannot see their tickets,
  reply, reopen, or rate the help.
- Nobody is told anything. There are no notifications except an email action
  no workflow uses yet.
- People sign in with accounts made by hand in a Django shell.
- Raw PII can be stored but never read, so the `pii_verify` queue cannot do its
  job.

A real IT organization cannot run a service desk without these. Phase 2 adds
them, on top of the triage core, without loosening any of its guardrails.

## 1.2 Goals

| ID | Goal |
|---|---|
| G1 | Every ticket handed to support has a business-hours SLA clock, and breaches are seen before they happen |
| G2 | Every ticket handed to support reaches a named person in a named team, with balanced load |
| G3 | Requesters can follow, answer, reopen and rate their own tickets from the chat |
| G4 | The right people hear about the right events, through channels they chose, except notices they must not miss |
| G5 | Raw PII can be read only with a reason, by an allowed person, and every read leaves a log row |
| G6 | People sign in with their company identity; leaving the company ends access at once |
| G7 | Governance stays visible: KB authority, security alerts, rollout switches and thresholds each have an owner, an approval and an audit trail |

## 1.3 KPIs

"Today" is what the system can measure now. "Not measured" means the data
does not exist yet; the feature that creates it is named.

| KPI | Goal | Definition | Today | Target | Source after phase 2 |
|---|---|---|---|---|---|
| K1 Response SLA compliance | G1 | Tickets with first human response within the response target ÷ tickets with a response target, per calendar month | Not measured (F1) | **≥ 95 %** [ASSUMPTION: ITIL-typical] | F1 SLA clocks |
| K2 Resolution SLA compliance | G1 | Tickets resolved within the resolution target ÷ tickets resolved, per month | Not measured (F1) | **≥ 90 %** [ASSUMPTION] | F1 |
| K3 Breach warned in time | G1 | Breached tickets that got a warning at ≥ 75 % elapsed ÷ breached tickets | Not measured | **100 %** | F1 + F4 |
| K4 Time to assign | G2 | Business minutes from handoff to support until `assigned_to` is set, median | Not measured (F2) | **≤ 15 business min** median, ≤ 60 p90 [ASSUMPTION] | F2 |
| K5 Reassignment rate | G2 | Tickets reassigned to another team ÷ tickets assigned | `reroute_rate` on review decisions only | **< 15 %** (matches P3 gate, README) | F2 + existing metric |
| K6 Requester CSAT | G3 | Mean rating 1–5 on resolved tickets | Not measured (F3) | **≥ 4.2**, response rate ≥ 20 % [ASSUMPTION] | F3 |
| K7 Reopen after auto-reply | G3 | `reopen_rate_after_autoreply` (spec §11.1, metric number one) | Measured; 0 reopens possible today (no reopen surface) | **< 5 %** for 1 month (P4 gate) | F3 makes it real |
| K8 Notification latency | G4 | Event to in-app row readable p95 (shown on the next poll, ≤ 15 s); event to email handed to SMTP p95 | Not measured (F4) | **≤ 5 s** in-app row, **≤ 2 min** email | F4 |
| K9 Unlogged PII reads | G5 | Plaintext reads of `pii_quarantine` without a `pii_access_log` row | 0 (no reads possible) | **0, always** (invariant, not a target) | F5 + test |
| K10 SSO coverage | G6 | Active staff and employee accounts that sign in through Keycloak ÷ active accounts | 0 % | **100 %** except ≤ 2 break-glass accounts | F13 |
| K11 Deprovision time | G6 | Disable in directory → all sessions refused | Manual | **≤ 5 min** [ASSUMPTION: Keycloak event or sync interval] | F13 |
| K12 Security alert acknowledgement | G7 | Critical security alerts acknowledged by `security` within the target, per month | Not measured (F8) | **≤ 1 business hour**, 100 % | F8 |
| K13 Mass-incident broadcast | G7 | Incident declared → first broadcast to every linked requester | Not possible | **≤ 15 min**, 100 % of linked requesters | F7 |
| K14 Guardrail integrity | G7 | Threshold or shadow-mode changes without an approved, audited change | Possible today (edit file, redeploy) | **0** | F9 |

KPIs **not** chosen as targets, on purpose: `automation_rate`. The spec
(§11.1, §14) warns it erodes ADR-0006 once it becomes a goal. F10 reports it;
no one is measured on it.

## 1.4 What does not change

These hold for every feature. Each feature's §6i repeats the ones it touches.

- The LLM proposes; `router.py` decides (ADR-0001). No feature reads a
  `proposed_*` field to decide anything.
- Auto-reply authority lives on KB rows with a named approver and reason
  (ADR-0002). High-risk pages are never bulk-approved (ADR-0027).
- Trust is scored in core-api from external signals only (ADR-0003).
- Runbooks always go through a person (ADR-0006).
- The router's hard-gate order is fixed. Nothing added after the router may
  override its decision more quietly than a person would.
- Masking stays inline and synchronous. `mask_failed` always goes to a person.
- `audit_log` stays append-only. Every new decision-making feature writes it.
- Every failure degrades toward a person.
- ai-engine gains no write access to business tables.
