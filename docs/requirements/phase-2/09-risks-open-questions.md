# 9. Risks, assumptions, open questions, proposed ADRs

**State: seeded at stage 1.** Completed in stage 6. Each stage adds its rows.

## 9.1 Open questions

Each has an owner and a proposed default. If nobody answers by the stage that
needs it, the default is used and stays tagged [ASSUMPTION].

| ID | Question | Owner | Proposed default | Needed by |
|---|---|---|---|---|
| OQ-01 | Is F13 (Keycloak) a Must? | Product owner | **Yes, Must**, wave 1 | Stage 2 |
| OQ-02 | Are PRE-1 (role enforcement) and PRE-2 (accept ADR-0028, ADR-0029) accepted as prerequisites? | Tech lead | **Yes**, wave 0 | Stage 2 |
| OQ-03 | What directory sits behind Keycloak: on-prem Active Directory, Entra ID, or Keycloak's own users? | Head of IT Operations | On-prem AD through Keycloak LDAP federation | F13 (stage 4) |
| OQ-04 | One business calendar or one per site? | IT Service Desk Manager | One: Mon–Fri 08:00–17:30, lunch counted as working, `Asia/Ho_Chi_Minh`; Saturday off | F1 |
| OQ-05 | SLA targets per priority | IT Service Desk Manager | P1: respond 15 min / resolve 4 h, **24×7**. P2: 30 min / 8 business h. P3: 4 business h / 3 business days. P4: 1 business day / 5 business days | F1 |
| OQ-06 | Who sets ticket priority? | IT Service Desk Manager | core-api rules: category default (security → P2, others → P3); linked to a mass incident → P1; a technician changes it with a reason. Requesters can't set it. Never from an LLM field | F1 |
| OQ-07 | When does a chat ticket's SLA start? | IT Service Desk Manager | When the requester asks for a ticket (`requester_asked_for_ticket`), not at the first message | F1, F3 |
| OQ-08 | "Chat memory across turns": does the chat model see earlier turns, or does only the screen show them? | Product owner | The model sees the **masked** earlier turns of the same conversation (last 6 turns); a conversation ends after 30 min idle; nothing carries into a new one. Needs a wire change and an ADR | F3 |
| OQ-09 | Reopen window | IT Service Desk Manager | 7 calendar days after resolution; after that, a new linked ticket | F3 |
| OQ-10 | Email relay and sender | Head of IT Operations | Company SMTP relay over TLS; sender `helpdesk@<company domain>` | F4 |
| OQ-11 | Break-glass accounts | Information Security Officer | 2 local accounts, role `manager`, password in the company vault, every sign-in alerts `security` | F13 |
| OQ-12 | Who may reveal PII? | Information Security Officer | `security`; or the technician holding the claim on that ticket's `pii_verify` item. Managers: no | F5 |
| OQ-13 | Holidays that apply only to public employees (e.g. Culture Day 24 Nov 2026) | HR | The holiday calendar is whatever HR enters each year | F1 |
| OQ-14 | How long are in-app notifications kept? | Data Protection Officer | 90 days, then deleted; the audit log keeps the event | F4 |

## 9.2 Assumptions made at stage 1

| ID | Assumption | Where used |
|---|---|---|
| A-01 | The org is Vietnam-based, staff in one time zone | §5, F1 |
| A-02 | 3–5 technicians work the queue (spec §0) | F2 sizing |
| A-03 | KPI targets K1, K2, K4, K6, K11 are ITSM-typical, not measured | §1.3 |
| A-04 | No SMS, voice or push provider is in scope | F4 |
| A-05 | The org has a Data Protection Officer | §0.2 |

## 9.3 Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | Any signed-in employee can read any ticket, decide review items, create KB pages and execute runbooks today (§3.4 item 1). New features add more endpoints on the same pattern | High (it's the current state) | High | PRE-1 first; a test that fails if any non-auth route lacks a role gate |
| R-02 | F1, F2, F4, F13 build on ADR-0028 and ADR-0029, both Proposed. Rejecting either later reworks four features | Medium | High | PRE-2 |
| R-03 | 13 features + 2 prerequisites is a large phase for one team | High | Medium | MoSCoW holds; waves 4–5 can move to phase 3 without breaking waves 0–3 |
| R-04 | Notification volume causes people to ignore notices (alert fatigue, like approval fatigue in spec §11.1) | Medium | Medium | Matrix defaults off for low-value events; digest option; F10 reports read rates |
| R-05 | Chat memory carries one turn's content into another ticket's analysis | Medium | High | Only masked turns; same conversation only; same requester only; ADR required |
| R-06 | Keycloak down = nobody can start a new sign-in | Low | High | Existing core-api sessions keep working until their own limits (ADR-0029); break-glass accounts |
| R-07 | README and CLAUDE.md describe one `services/web` app; the code has two | Certain | Low | Patch both in the PRE-1 PR |

## 9.4 Proposed ADRs (to be written in the stage that specs the feature)

| ADR | Title | Feature | Relaxes a guardrail? |
|---|---|---|---|
| 0030 | SLA clocks count business time, driven by lifecycle events | F1 | No |
| 0031 | Capabilities and team scope alongside the primary role | F2, F6, F7, F9, F13 | No (adds rights, each audited) |
| 0032 | Keycloak signs people in; core-api keeps the session | F13 | No; builds on ADR-0029 |
| 0033 | Notifications go through an outbox written in the event's transaction | F4 | No |
| 0034 | A chat conversation gives the model its earlier masked turns | F3 | **Yes**: today each ticket is analysed alone. Must say why cross-turn context is safe |
| 0035 | Threshold and shadow-mode changes are reviewed, versioned configuration (`thresholds.yaml` stays the source; `SHADOW_MODE` is an env var today) | F9 | No; makes hard rule 2 auditable |
| 0036 | KB drafts are invisible to retrieval | F6 | No; ai-engine reads, never writes |
