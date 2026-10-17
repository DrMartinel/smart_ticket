# 5. Glossary — new terms only

Existing terms (branch, HITL, hard gate, reason code, shadow mode, trust score,
masking, PII level, quarantine, mass incident, …) are in
[`docs/glossary.md`](../../glossary.md). Lifecycle terms (workflow, status,
transition, rule, action, transfer) are in ADR-0028.

## SLA (F1)

| Term | Meaning |
|---|---|
| **SLA policy** | A rule that gives a ticket its targets. Matches on category and priority. One policy per (category, priority) pair, plus a default |
| **SLA target** | One time limit inside a policy. Two kinds: **response** (first human action after handoff) and **resolution** (ticket reaches a completed system status) |
| **SLA clock** | One running count of business time for one target on one ticket. States: `running`, `paused`, `met`, `breached`, `cancelled` |
| **Business calendar** | Working hours per weekday, a time zone, and a holiday list. Default: Mon–Fri 08:00–17:30, `Asia/Ho_Chi_Minh` [ASSUMPTION] |
| **Holiday calendar** | Dated non-working days, entered each year from the government's announcement. Not computed from the lunar calendar (Tết dates are set by decision each year) |
| **Business time** | Time that counts toward a target: inside working hours, not on a holiday, not while paused |
| **Pause status** | A workflow status whose entry pauses running clocks, e.g. `waiting_on_requester` (NEW status, base `On hold`) |
| **Breach warning** | A notice sent when a clock passes a set share of its target (default 75 %) |
| **Breach escalation** | What happens when a clock passes a level: 100 % notifies the assignee and team lead, 125 % the manager. Priority is never raised automatically (BR-F1-09) |
| **Handoff** | The moment a ticket becomes support's work: its first entry into a status whose base is neither `Intake` (backlog) nor completed — in practice `pending_review`, `auto_routed`, `escalated` or `blocked`, including when a chat requester asks for a ticket. SLA clocks start here, not at submit (BR-F1-01) |
| **Priority** | `P1`–`P4` on the ticket (NEW field). Set by core-api from rules, changed by a person with a reason. Never set from an LLM field (ADR-0001) |

## Teams and assignment (F2)

| Term | Meaning |
|---|---|
| **Team** | A named group of technicians that owns one or more categories |
| **Membership** | A user's place in a team, with role `member` or `lead` |
| **Assignment strategy** | How a team picks the next person: `round_robin` (next in order) or `least_loaded` (fewest open assigned tickets) |
| **Workload** | Count of a person's open tickets, not in a completed or `On hold` system status |
| **Available** | A member who is active, marked available, and not on leave today |
| **Reassignment** | Moving a ticket to another person or team. Needs a reason code and free text |

## Requester experience (F3)

| Term | Meaning |
|---|---|
| **Conversation** | One chat session. Holds several turns. The chat model sees earlier masked turns of the same conversation; nothing carries into a new conversation |
| **Turn** | One requester message and what came back |
| **Reply** | A requester message added to an existing ticket, masked inline like a ticket |
| **Reopen window** | Days after resolution during which the requester may reopen. Default 7 calendar days [ASSUMPTION] |
| **CSAT rating** | 1–5 stars plus optional comment, once per resolution |

## Notifications (F4)

| Term | Meaning |
|---|---|
| **Notification event** | Something worth telling a person, e.g. `ticket.assigned`, `sla.warning`, `incident.broadcast` |
| **Channel** | Where a notice goes: `in_app`, `email`, `webhook` |
| **Notification matrix** | Table of event × recipient × channel, with a default on/off and a mandatory flag |
| **Preference** | A user's own on/off per event and channel, where the matrix allows it |
| **Mandatory notice** | A notice a user cannot turn off (e.g. security alert to `security`, incident broadcast to linked requesters) |
| **Outbox** | The table where notices wait to be sent, written in the same transaction as the event |

## PII reveal (F5)

| Term | Meaning |
|---|---|
| **Reveal** | Decrypting one quarantined value for one person, for one stated reason |
| **Reveal reason** | A reason code plus non-empty free text. Required |
| **Access log** | `pii_access_log` (REUSED table): one row per reveal, written in the same transaction as the decrypt |

## KB governance (F6)

| Term | Meaning |
|---|---|
| **KB draft** | A page not yet live. Retrieval never sees it |
| **KB review** | A second person checks a draft before it goes live |
| **KB gap** | A topic tickets ask about that no page answers, seen through `retrieval_below_floor` refusals |

## Incidents and security (F7, F8)

| Term | Meaning |
|---|---|
| **Broadcast** | One message to every requester linked to an incident |
| **ETA** | Expected fix time an incident manager sets. Shown on every broadcast |
| **Security alert** | A row for a security person to triage: injection, critical PII, refresh-token reuse, unusual reveal volume |
| **Triage state** | `new`, `acknowledged`, `investigating`, `closed_true_positive`, `closed_false_positive` |

## Rollout and identity (F9, F13)

| Term | Meaning |
|---|---|
| **Phase gate** | The measured condition for moving from one rollout phase to the next (README "Rollout phases") |
| **Threshold change request** | A proposed new version of `thresholds.yaml`, approved by someone other than the author |
| **Capability** | An extra right on top of the primary role: `workflow_admin`, `kb_editor`, `incident_manager` |
| **Identity provider (IdP)** | Keycloak. Signs people in. core-api still issues its own session |
| **JIT provisioning** | Creating the core-api user on first successful sign-in |
| **Break-glass account** | A local account kept for when Keycloak is down. At most 2, `manager` role, every use audited |
