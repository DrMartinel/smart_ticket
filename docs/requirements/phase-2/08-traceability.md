# 8. Traceability

Generated from the feature files by `tools/build_traceability.py`, so it can't drift
from them silently. Re-run it after any spec change. IDs are defined in each
feature's §d–§j.

## 8.1 Goal → feature → requirements → tests

| Goal | KPI | Feature | MoSCoW | Use cases | FRs | BRs | ADRs | Acceptance | Regression tests |
|---|---|---|---|---|---|---|---|---|---|
| G5, G7 | K9, K14 | [PRE-1](06-PRE-prerequisites.md) | Must | UC-PRE1-01 | FR-PRE1-001 … FR-PRE1-005 (5) | BR-PRE1-01, BR-PRE1-02, BR-PRE1-03 | 0006, 0029 | AC-PRE1-01 … AC-PRE1-04 (4) | 4 |
| G1, G2, G4, G6 | — | [PRE-2](06-PRE-prerequisites.md) | Must | — | FR-PRE2-001 | — | 0028, 0029 | AC-PRE2-01 | 0 |
| G1 | K1, K2, K3 | [F1](06-F1-sla.md) | Must | UC-F1-01 … UC-F1-06 (6) | FR-F1-001 … FR-F1-017 (17) | BR-F1-01 … BR-F1-15 (15) | 0001, 0028, 0030 | AC-F1-01 … AC-F1-12 (12) | 8 |
| G2 | K4, K5 | [F2](06-F2-teams-assignment.md) | Must | UC-F2-01 … UC-F2-06 (6) | FR-F2-001 … FR-F2-016 (16) | BR-F2-01 … BR-F2-08 (8) | 0001, 0028, 0031 | AC-F2-01 … AC-F2-08 (8) | 5 |
| G3 | K6, K7 | [F3](06-F3-requester-chat.md) | Must | UC-F3-01 … UC-F3-06 (6) | FR-F3-001 … FR-F3-016 (16) | BR-F3-01 … BR-F3-11 (11) | 0001, 0003, 0023, 0028, 0034 | AC-F3-01 … AC-F3-12 (12) | 8 |
| G4 | K8 | [F4](06-F4-notifications.md) | Must | UC-F4-01 … UC-F4-06 (6) | FR-F4-001 … FR-F4-013 (13) | BR-F4-01 … BR-F4-08 (8) | 0028, 0033 | AC-F4-01 … AC-F4-10 (10) | 5 |
| G5 | K9 | [F5](06-F5-pii-reveal.md) | Must | UC-F5-01, UC-F5-02 | FR-F5-001 … FR-F5-010 (10) | BR-F5-01 … BR-F5-08 (8) | — | AC-F5-01 … AC-F5-10 (10) | 6 |
| G7 | — | [F6](06-F6-kb-governance.md) | Should | UC-F6-01 … UC-F6-07 (7) | FR-F6-001 … FR-F6-015 (15) | BR-F6-01 … BR-F6-09 (9) | 0002, 0025, 0027, 0036 | AC-F6-01 … AC-F6-08 (8) | 6 |
| G7 | K13 | [F7](06-F7-mass-incident.md) | Should | UC-F7-01 … UC-F7-05 (5) | FR-F7-001 … FR-F7-013 (13) | BR-F7-01 … BR-F7-10 (10) | 0001, 0028 | AC-F7-01 … AC-F7-10 (10) | 7 |
| G7 | K12 | [F8](06-F8-security-inbox.md) | Should | UC-F8-01 … UC-F8-04 (4) | FR-F8-001 … FR-F8-010 (10) | BR-F8-01 … BR-F8-08 (8) | 0001, 0028, 0029 | AC-F8-01 … AC-F8-07 (7) | 5 |
| G7 | K14 | [F9](06-F9-rollout-control.md) | Should | UC-F9-01 … UC-F9-04 (4) | FR-F9-001 … FR-F9-011 (11) | BR-F9-01 … BR-F9-10 (10) | 0001, 0006, 0035 | AC-F9-01 … AC-F9-10 (10) | 7 |
| G1, G2, G3, G7 | — | [F10](06-F10-reporting.md) | Should | UC-F10-01 … UC-F10-07 (7) | FR-F10-001 … FR-F10-015 (15) | BR-F10-01 … BR-F10-10 (10) | 0006 | AC-F10-01 … AC-F10-10 (10) | 6 |
| G7 | — | [F11](06-F11-graph-retrieval.md) | Could | UC-F11-01 … UC-F11-04 (4) | FR-F11-001 … FR-F11-008 (8) | BR-F11-01 … BR-F11-06 (6) | 0002, 0005, 0018, 0019, 0025, 0037 | AC-F11-01 … AC-F11-05 (5) | 4 |
| G7 | — | [F12](06-F12-itsm-iam-integration.md) | Could | UC-F12-01 … UC-F12-04 (4) | FR-F12-001 … FR-F12-008 (8) | BR-F12-01 … BR-F12-08 (8) | 0006, 0028, 0038 | AC-F12-01 … AC-F12-06 (6) | 5 |
| G6 | K10, K11 | [F13](06-F13-identity.md) | Must | UC-F13-01 … UC-F13-04 (4) | FR-F13-001 … FR-F13-012 (12) | BR-F13-01 … BR-F13-08 (8) | 0029, 0031, 0032 | AC-F13-01 … AC-F13-10 (10) | 5 |

Goals and KPIs are defined in [§1](01-executive-summary.md). ADR numbers ≥ 0030 are proposed ([§9.4](09-risks-open-questions.md#94-proposed-adrs)).

## 8.2 Use case → rules → screens

Screens link to their Figma frames (stage 5, [mockups.md](mockups.md)).

| Feature | Use case | Name | Rules | Screens |
|---|---|---|---|---|
| PRE-1 | UC-PRE1-01 | Refuse a call outside the caller's role | BR-PRE1-01, BR-PRE1-02, BR-PRE1-03 | None (API) |
| F1 | UC-F1-01 | Start clocks at handoff | BR-F1-01, BR-F1-02, BR-F1-03, BR-F1-04, BR-F1-05, BR-F1-11 | [`F1 · SLA badge`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-604) on queue and ticket (CHANGED `queue`, `review/[id]`) |
| F1 | UC-F1-02 | Pause while waiting for the requester | BR-F1-06, BR-F1-07 | [`F1 · SLA badge`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-604) |
| F1 | UC-F1-03 | Resume when the requester replies | BR-F1-07 | — |
| F1 | UC-F1-04 | Warn, breach, escalate | BR-F1-08, BR-F1-09 | [`F1 · Breach list`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-685) |
| F1 | UC-F1-05 | Change priority | BR-F1-02, BR-F1-10 | [`F1 · Priority dialog`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-677) |
| F1 | UC-F1-06 | Maintain policies, calendars, holidays | BR-F1-03, BR-F1-05, BR-F1-12, BR-F1-14 | [`F1 · SLA policies`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-57), [`F1 · Business calendars`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-283), [`F1 · Holidays`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-435) |
| F2 | UC-F2-01 | Assign at handoff | BR-F2-01, BR-F2-02, BR-F2-03, BR-F2-04, BR-F2-05, BR-F2-06, BR-F2-07 | — |
| F2 | UC-F2-02 | Take a ticket from the team queue | BR-F2-04 | [`F2 · Team queue`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-237) |
| F2 | UC-F2-03 | Reassign with a reason | BR-F2-04, BR-F2-05, BR-F2-06 | [`F2 · Reassign dialog`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-442) (on `review/[id]` CHANGED and ticket page) |
| F2 | UC-F2-04 | See and balance team workload | BR-F2-04 | [`F2 · Team workload`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-450) |
| F2 | UC-F2-05 | Set my availability and leave | BR-F2-03, BR-F2-07 | [`F2 · My availability`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-603), [`F2 · Team workload`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-450) |
| F2 | UC-F2-06 | Configure teams | BR-F2-01 | [`F2 · Teams`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-646) |
| F3 | UC-F3-01 | Ask a follow-up in the same conversation | BR-F3-01, BR-F3-02, BR-F3-03 | [`F3 · Chat conversation`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-426) (CHANGED chat page) |
| F3 | UC-F3-02 | See my tickets | BR-F3-04, BR-F3-05 | [`F3 · My tickets`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-517) |
| F3 | UC-F3-03 | Read the thread and reply | BR-F3-06, BR-F3-07, BR-X-06 | [`F3 · Ticket thread`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-580) |
| F3 | UC-F3-04 | Reopen | BR-F3-08, BR-F3-09 | [`F3 · Ticket thread`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-580), [`F3 · Answer card`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-500) (CHANGED `TurnView` answered state) |
| F3 | UC-F3-05 | Rate the help | BR-F3-10 | [`F3 · Rating`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-623) |
| F3 | UC-F3-06 | Technician writes to the requester | BR-F3-06, BR-F1-06 | [`F3 · Comment box`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-665) (CHANGED `review/[id]` and ticket page in admin-console) |
| F4 | UC-F4-01 | Notify on an event | BR-F4-01, BR-F4-02, BR-F4-03, BR-F4-04, BR-F4-05, BR-F4-06, BR-F4-07, BR-F4-08 | — |
| F4 | UC-F4-02 | Read my notifications | BR-F4-07 | [`F4 · Notification bell`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-480) (admin-console NavBar CHANGED, chat header CHANGED), [`F4 · Notification panel`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-531) |
| F4 | UC-F4-03 | Set my preferences | BR-F4-03 | [`F4 · My notification settings`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-564) |
| F4 | UC-F4-04 | Edit the notification matrix | BR-F4-02, BR-F4-03 | [`F4 · Notification matrix`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-710) |
| F4 | UC-F4-05 | Handle failed deliveries | BR-F4-05 | [`F4 · Delivery log`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-890) |
| F4 | UC-F4-06 | Subscribe an external system (webhook) | BR-F4-06 | [`F4 · Webhook subscriptions`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-1047) |
| F5 | UC-F5-01 | Reveal one masked value | BR-F5-01, BR-F5-02, BR-F5-03, BR-F5-04, BR-F5-05, BR-F5-06, BR-F5-07, BR-F5-08 | [`F5 · Reveal dialog`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=12-677) (CHANGED `review/[id]`), [`F5 · Access log`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=12-734) |
| F5 | UC-F5-02 | Review the access log | BR-F5-06 | [`F5 · Access log`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=12-734) |
| F6 | UC-F6-01 | Write and submit a draft | BR-F6-01, BR-F6-02 | [`F6 · KB editor`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-737), [`F6 · KB drafts`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-828) |
| F6 | UC-F6-02 | Review and publish | BR-F6-02, BR-F6-03, BR-F6-04 | [`F6 · Draft review`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-981) |
| F6 | UC-F6-03 | Revoke authority on a content change | BR-F6-04, ADR-0002 | [`F6 · Authority queue`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1049) |
| F6 | UC-F6-04 | Grant or re-grant auto-reply authority | BR-F6-05, BR-F6-06 | [`F6 · Authority queue`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1049) |
| F6 | UC-F6-05 | View the authority log | — | [`F6 · Authority log`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1180) |
| F6 | UC-F6-06 | Use the KB-gap report | BR-F6-07, BR-F6-08 | [`F6 · KB gaps`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1299) |
| F6 | UC-F6-07 | Retire a page | BR-F6-04 | [`F6 · Draft review`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-981) |
| F7 | UC-F7-01 | Confirm or dismiss a proposed incident | BR-F7-01, BR-F7-02, BR-F7-03 | [`F7 · Incident list`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-952), [`F7 · Incident page`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1090) |
| F7 | UC-F7-02 | Declare an incident by hand | BR-F7-02 | [`F7 · Declare incident`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1298) |
| F7 | UC-F7-03 | Broadcast an update | BR-F7-04, BR-F7-05 | [`F7 · Incident page`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1090) (broadcast composer, history, delivery count); chat [`F7 · Incident banner`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1332) |
| F7 | UC-F7-04 | Resolve and close all | BR-F7-06, BR-F7-07 | [`F7 · Resolve dialog`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1324) |
| F7 | UC-F7-05 | Unlink a wrongly matched ticket | BR-F7-08 | [`F7 · Incident page`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1090) |
| F8 | UC-F8-01 | Triage a new alert | BR-F8-01, BR-F8-02, BR-F8-03, BR-F8-04 | [`F8 · Security inbox`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1087), [`F8 · Alert detail`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1265) |
| F8 | UC-F8-02 | Handle a credential pasted into a ticket | BR-F8-05, BR-F8-06 | [`F8 · Alert detail`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1265) |
| F8 | UC-F8-03 | Release a false-positive injection block | BR-F8-06, BR-F8-07 | [`F8 · Alert detail`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1265) |
| F8 | UC-F8-04 | Investigate a session or access alert | BR-F8-08 | [`F8 · Alert detail`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1265) |
| F9 | UC-F9-01 | Turn a branch live | BR-F9-01, BR-F9-02, BR-F9-03, BR-F9-04 | [`F9 · Rollout`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1179), [`F9 · Flag request`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1328) |
| F9 | UC-F9-02 | Turn a branch off now | BR-F9-02 | [`F9 · Rollout`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1179) |
| F9 | UC-F9-03 | Propose a threshold change | BR-F9-05, BR-F9-06 | [`F9 · Threshold change request`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1336) |
| F9 | UC-F9-04 | Approve a threshold change and ship it | BR-F9-05, BR-F9-06, BR-F9-07, BR-F9-08 | [`F9 · Threshold change request`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1336), [`F9 · Threshold history`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1436) |
| F10 | UC-F10-01 | Review the month's SLA compliance | BR-F10-01, BR-F10-02, BR-F10-03, BR-F10-04 | [`F10 · SLA report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1291) |
| F10 | UC-F10-02 | Balance team workload | BR-F10-05 | [`F10 · Team report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1399) |
| F10 | UC-F10-03 | Check reviewers aren't rubber-stamping | BR-F10-06 | [`F10 · Reviewer report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1631) |
| F10 | UC-F10-04 | See KB health and gaps | BR-F10-07 | [`F10 · KB report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1765) |
| F10 | UC-F10-05 | Read requester satisfaction | BR-F10-08 | [`F10 · CSAT report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1916) |
| F10 | UC-F10-06 | Check rollout readiness | BR-F10-09, BR-F10-10 | [`F10 · Rollout readiness`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2028) (also embedded in [`F9 · Rollout`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1179)) |
| F10 | UC-F10-07 | Security and incident numbers | BR-F10-05 | [`F10 · Security report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2164), [`F10 · Incident report`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2311) |
| F11 | UC-F11-01 | Open a page's graph tab: outgoing and incoming edges, score, evidence (symptom → remedy pairs), build id, stale flag | BR-F11-02, BR-F11-04 | see §d |
| F11 | UC-F11-02 | Confirm an edge (`reviewed = true`), hide an edge, or add a missing pointer with a reason | BR-F11-02, BR-F11-03, BR-F11-06 | see §d |
| F11 | UC-F11-03 | Request a rebuild for a page (button, or automatically on publish); see when it last ran | BR-F11-01, BR-F11-05 | see §d |
| F11 | UC-F11-04 | See graph health: pages with ≥ 1 edge, stale edges, hidden/added overrides, expansion contribution | BR-F11-04 | see §d |
| F12 | UC-F12-01 | Approve a runbook proposal; the system checks target rules, runs it, records the outcome on the ticket | BR-F12-01, BR-F12-02, BR-F12-03, BR-F12-04, BR-F12-05, BR-F12-06 | see §d |
| F12 | UC-F12-02 | Resolve an `unknown` outcome: check the target system, mark `succeeded` or `failed` with a note | BR-F12-06 | see §d |
| F12 | UC-F12-03 | Add or change a runbook: code, title, executor, config, required fields, target rule, risk | BR-F12-05, BR-F12-08 | see §d |
| F12 | UC-F12-04 | n8n calls back with the result (REUSED lifecycle callback pattern, one-time token) | BR-F12-07 | see §d |
| F13 | UC-F13-01 | Sign in with the company account | BR-F13-01, BR-F13-02, BR-F13-03, BR-F13-04, BR-F13-05, BR-F13-06 | [`F13 · Sign-in`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2307) (CHANGED both apps' `/login`), [`F13 · Sign-in error`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2328) |
| F13 | UC-F13-02 | First sign-in creates the user (JIT) | BR-F13-02, BR-F13-03 | — |
| F13 | UC-F13-03 | Leaver loses access | BR-F13-04, BR-F13-05, BR-F13-08 | — |
| F13 | UC-F13-04 | Break-glass sign-in | BR-F13-06 | [`F13 · Break-glass sign-in`](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2341) |

## 8.3 Feature → tests

Acceptance scenarios (Gherkin, §j) and the regression tests named in §i.

| Feature | Acceptance scenarios | Regression tests |
|---|---|---|
| PRE-1 | AC-PRE1-01 … AC-PRE1-04 (4) | `test_employee_cannot_decide_review_item`, `test_employee_cannot_read_another_ticket`, `test_every_route_is_gated`, `test_runbook_needs_staff_approver_and_executor` |
| PRE-2 | AC-PRE2-01 | — |
| F1 | AC-F1-01 … AC-F1-12 (12) | `test_business_time_skips_weekend_and_holiday`, `test_dst_free_zone_round_trip_utc`, `test_each_sla_level_fires_once`, `test_hardening`, `test_no_clock_time_in_triage_statuses`, `test_pause_resume_keeps_elapsed`, `test_policy_edit_does_not_change_running_clock`, `test_system_move_succeeds_when_sla_hook_raises` |
| F2 | AC-F2-01 … AC-F2-08 (8) | `test_assignment_never_changes_routing_decision`, `test_auto_route_assigns_team_from_router_category`, `test_concurrent_assignments_balance`, `test_no_eligible_member_leaves_unassigned_and_notifies_lead`, `test_review_reroute_sets_category_and_eval_candidate` |
| F3 | AC-F3-01 … AC-F3-12 (12) | `test_blocked_turn_ends_conversation`, `test_one_rating_per_resolution`, `test_prior_turns_only_from_same_conversation_and_requester`, `test_reopen_after_window_creates_linked_ticket`, `test_reopen_autoreply_creates_eval_candidate`, `test_reply_mask_failed_hidden_and_queued`, `test_reply_masked_before_store`, `test_router_ignores_prior_turns` |
| F4 | AC-F4-01 … AC-F4-10 (10) | `test_dispatch_twice_sends_once`, `test_failed_email_leaves_ticket_unchanged`, `test_mandatory_cell_ignores_preference`, `test_notice_uses_masked_text_only`, `test_rolled_back_event_sends_nothing` |
| F5 | AC-F5-01 … AC-F5-10 (10) | `test_decrypt_has_one_caller`, `test_expired_entry_is_gone`, `test_masking_coverage_still_100`, `test_no_plaintext_when_access_log_insert_fails`, `test_reveal_writes_exactly_one_access_log_row`, `test_revealed_value_absent_from_logs` |
| F6 | AC-F6-01 … AC-F6-08 (8) | `test_bulk_refuses_high_risk`, `test_draft_invisible_to_ai_engine_queries`, `test_edit_revokes_authority_with_log_row`, `test_hash_mismatch_means_not_authorized`, `test_publish_never_grants_authority`, `test_self_review_refused` |
| F7 | AC-F7-01 … AC-F7-10 (10) | `test_broadcast_once_per_requester`, `test_close_all_continues_after_refusal`, `test_confirm_approves_without_eval_candidates`, `test_linked_clock_paused_while_confirmed`, `test_linked_ticket_never_auto_replied`, `test_ticket_count_counts_each_ticket_once`, `test_unrelated_outages_get_separate_incidents` |
| F8 | AC-F8-01 … AC-F8-07 (7) | `test_credential_alert_notifies_requester`, `test_every_security_alert_audit_raises_an_alert`, `test_injection_queue_hidden_from_technicians`, `test_release_goes_to_a_person_not_the_ai`, `test_repeat_alerts_group` |
| F9 | AC-F9-01 … AC-F9-10 (10) | `test_env_shadow_overrides_flags`, `test_no_runbook_flag_exists`, `test_one_person_can_turn_off`, `test_one_person_cannot_turn_on`, `test_route_is_identical_whatever_the_flags`, `test_threshold_cr_rejects_invalid_yaml`, `test_unapproved_thresholds_force_shadow` |
| F10 | AC-F10-01 … AC-F10-10 (10) | `test_automation_rate_split_live_vs_shadow`, `test_facts_build_is_idempotent`, `test_incident_tickets_excluded_from_team_sla`, `test_lead_cannot_read_other_team`, `test_reviewer_flag_needs_min_decisions`, `test_sla_compliance_uses_clocks_not_sla_due_at` |
| F11 | AC-F11-01 … AC-F11-05 (5) | `test_add_override_ranks_first`, `test_hide_override_survives_rebuild`, `test_ingest_marks_edges_stale_not_deleted`, `test_triage_writes_nothing` |
| F12 | AC-F12-01 … AC-F12-06 (6) | `test_high_risk_needs_second_manager`, `test_mock_executor_matches_old_behaviour`, `test_reset_targets_only_the_reporter`, `test_runbook_never_runs_without_approval`, `test_timeout_after_send_is_unknown_not_retried` |
| F13 | AC-F13-01 … AC-F13-10 (10) | `test_backchannel_logout_revokes_all_families`, `test_break_glass_only_manager`, `test_failed_keycloak_read_deactivates_nobody`, `test_token_without_live_family_is_refused`, `test_two_primary_roles_refused` |

## 8.4 Rule → acceptance scenarios

Each Gherkin scenario carries `@BR-…` tags for the rules it proves. A rule with no scenario is listed in 8.5.

| Feature | Rule | Proven by |
|---|---|---|
| PRE-1 | BR-PRE1-01 | AC-PRE1-03, AC-PRE1-04 |
| PRE-1 | BR-PRE1-02 | AC-PRE1-01, AC-PRE1-02 |
| PRE-1 | BR-PRE1-03 | AC-PRE1-03 |
| F1 | BR-F1-01 | AC-F1-01 |
| F1 | BR-F1-02 | AC-F1-01 |
| F1 | BR-F1-03 | AC-F1-01 |
| F1 | BR-F1-04 | AC-F1-02, AC-F1-05 |
| F1 | BR-F1-05 | AC-F1-07 |
| F1 | BR-F1-06 | AC-F1-10 |
| F1 | BR-F1-07 | AC-F1-03 |
| F1 | BR-F1-08 | AC-F1-04 |
| F1 | BR-F1-09 | AC-F1-04 |
| F1 | BR-F1-10 | AC-F1-09 |
| F1 | BR-F1-11 | AC-F1-06 |
| F1 | BR-F1-12 | AC-F1-08 |
| F1 | BR-F1-13 | AC-F1-11 |
| F1 | BR-F1-14 | AC-F1-02 |
| F1 | BR-F1-15 | AC-F1-12 |
| F2 | BR-F2-01 | AC-F2-07 |
| F2 | BR-F2-02 | AC-F2-01, AC-F2-07 |
| F2 | BR-F2-03 | AC-F2-01, AC-F2-02 |
| F2 | BR-F2-04 | AC-F2-05, AC-F2-06 |
| F2 | BR-F2-05 | AC-F2-04 |
| F2 | BR-F2-06 | AC-F2-03 |
| F2 | BR-F2-07 | AC-F2-08 |
| F2 | BR-F2-08 | AC-F2-06 |
| F3 | BR-F3-01 | AC-F3-01, AC-F3-02 |
| F3 | BR-F3-02 | AC-F3-02, AC-F3-03 |
| F3 | BR-F3-03 | AC-F3-04 |
| F3 | BR-F3-04 | AC-F3-05 |
| F3 | BR-F3-05 | AC-F3-12 |
| F3 | BR-F3-06 | AC-F3-07 |
| F3 | BR-F3-07 | AC-F3-06 |
| F3 | BR-F3-08 | AC-F3-08, AC-F3-09 |
| F3 | BR-F3-09 | AC-F3-08 |
| F3 | BR-F3-10 | AC-F3-10 |
| F3 | BR-F3-11 | AC-F3-11 |
| F4 | BR-F4-01 | AC-F4-05 |
| F4 | BR-F4-02 | AC-F4-10 |
| F4 | BR-F4-03 | AC-F4-02, AC-F4-03, AC-F4-06 |
| F4 | BR-F4-04 | AC-F4-01 |
| F4 | BR-F4-05 | AC-F4-04 |
| F4 | BR-F4-06 | AC-F4-07 |
| F4 | BR-F4-07 | AC-F4-08 |
| F4 | BR-F4-08 | AC-F4-09 |
| F5 | BR-F5-01 | AC-F5-01, AC-F5-03 |
| F5 | BR-F5-02 | AC-F5-04 |
| F5 | BR-F5-03 | AC-F5-01, AC-F5-02 |
| F5 | BR-F5-04 | AC-F5-08 |
| F5 | BR-F5-05 | AC-F5-01, AC-F5-06 |
| F5 | BR-F5-06 | AC-F5-09 |
| F5 | BR-F5-07 | AC-F5-07 |
| F5 | BR-F5-08 | AC-F5-10 |
| F6 | BR-F6-01 | AC-F6-01 |
| F6 | BR-F6-02 | AC-F6-02 |
| F6 | BR-F6-03 | AC-F6-03 |
| F6 | BR-F6-04 | AC-F6-03 |
| F6 | BR-F6-05 | AC-F6-04 |
| F6 | BR-F6-06 | AC-F6-05 |
| F6 | BR-F6-07 | AC-F6-06 |
| F6 | BR-F6-08 | AC-F6-06 |
| F6 | BR-F6-09 | AC-F6-08 |
| F7 | BR-F7-01 | AC-F7-01, AC-F7-06 |
| F7 | BR-F7-02 | AC-F7-01 |
| F7 | BR-F7-03 | AC-F7-02 |
| F7 | BR-F7-04 | AC-F7-04 |
| F7 | BR-F7-05 | AC-F7-03, AC-F7-04 |
| F7 | BR-F7-06 | AC-F7-05 |
| F7 | BR-F7-07 | AC-F7-10 |
| F7 | BR-F7-08 | AC-F7-07 |
| F7 | BR-F7-09 | AC-F7-09 |
| F7 | BR-F7-10 | AC-F7-08 |
| F8 | BR-F8-01 | AC-F8-06 |
| F8 | BR-F8-02 | AC-F8-01 |
| F8 | BR-F8-03 | AC-F8-03 |
| F8 | BR-F8-04 | AC-F8-01, AC-F8-05 |
| F8 | BR-F8-05 | AC-F8-01 |
| F8 | BR-F8-06 | AC-F8-04 |
| F8 | BR-F8-07 | AC-F8-02 |
| F8 | BR-F8-08 | AC-F8-07 |
| F9 | BR-F9-01 | AC-F9-01, AC-F9-04, AC-F9-05 |
| F9 | BR-F9-02 | AC-F9-02, AC-F9-03 |
| F9 | BR-F9-03 | AC-F9-06 |
| F9 | BR-F9-04 | AC-F9-08 |
| F9 | BR-F9-05 | AC-F9-09 |
| F9 | BR-F9-06 | AC-F9-09 |
| F9 | BR-F9-07 | AC-F9-05 |
| F9 | BR-F9-08 | AC-F9-10 |
| F9 | BR-F9-09 | AC-F9-01 |
| F9 | BR-F9-10 | AC-F9-07 |
| F10 | BR-F10-01 | AC-F10-01 |
| F10 | BR-F10-02 | AC-F10-01 |
| F10 | BR-F10-03 | AC-F10-01 |
| F10 | BR-F10-04 | AC-F10-07 |
| F10 | BR-F10-05 | AC-F10-03, AC-F10-04, AC-F10-06 |
| F10 | BR-F10-06 | AC-F10-02 |
| F10 | BR-F10-07 | AC-F10-08 |
| F10 | BR-F10-08 | AC-F10-09 |
| F10 | BR-F10-09 | AC-F10-05 |
| F10 | BR-F10-10 | AC-F10-10 |
| F11 | BR-F11-01 | AC-F11-01 |
| F11 | BR-F11-02 | AC-F11-01 |
| F11 | BR-F11-03 | AC-F11-02 |
| F11 | BR-F11-04 | AC-F11-04 |
| F11 | BR-F11-05 | AC-F11-05 |
| F11 | BR-F11-06 | AC-F11-03 |
| F12 | BR-F12-01 | AC-F12-02 |
| F12 | BR-F12-02 | AC-F12-01 |
| F12 | BR-F12-03 | AC-F12-03 |
| F12 | BR-F12-04 | AC-F12-05 |
| F12 | BR-F12-05 | AC-F12-02 |
| F12 | BR-F12-06 | AC-F12-04 |
| F12 | BR-F12-07 | AC-F12-04 |
| F12 | BR-F12-08 | AC-F12-06 |
| F13 | BR-F13-01 | AC-F13-01, AC-F13-06, AC-F13-09 |
| F13 | BR-F13-02 | AC-F13-02, AC-F13-03, AC-F13-04 |
| F13 | BR-F13-03 | AC-F13-02 |
| F13 | BR-F13-04 | AC-F13-01 |
| F13 | BR-F13-05 | AC-F13-05 |
| F13 | BR-F13-06 | AC-F13-07, AC-F13-08 |
| F13 | BR-F13-07 | AC-F13-02 |
| F13 | BR-F13-08 | AC-F13-06, AC-F13-10 |

Cross-cutting rules (§6.0) proven inside feature scenarios: BR-X-07 by AC-F1-06, AC-F2-07, AC-F4-04. The others (BR-X-01…09) are checked by route, model and schema tests named in §7.


## 8.5 Coverage check

- Features traced: 15. Use cases: 66.
- Business rules referenced only where they are defined (no use case, FR or test cites them): none.
- Business rules with no acceptance scenario: none.
- Acceptance scenarios: 123; every Gherkin scenario carries a rule tag, or a `@FR-…` / `@UC-…` tag when it proves a requirement that has no rule.
