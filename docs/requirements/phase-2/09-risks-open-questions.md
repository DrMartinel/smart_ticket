# 9. Risks, assumptions, open questions, proposed ADRs

**State: updated at stage 5.** Completed in stage 6. Each stage adds its rows.

OQ-01…OQ-27 defaults were accepted by the product owner on 2026-10-17 and are
now decisions; they stay listed so the trace is visible.

## 9.1 Open questions

Each has an owner and a proposed default. If nobody answers by the stage that
needs it, the default is used and stays tagged [ASSUMPTION].

| ID | Question | Owner | Proposed default | Needed by | State |
|---|---|---|---|---|---|
| OQ-01 | Is F13 (Keycloak) a Must? | Product owner | **Yes, Must**, wave 1 | Stage 2 | Decided 2026-10-17 |
| OQ-02 | Are PRE-1 (role enforcement) and PRE-2 (accept ADR-0028, ADR-0029) accepted as prerequisites? | Tech lead | **Yes**, wave 0 | Stage 2 | Decided 2026-10-17 |
| OQ-03 | What directory sits behind Keycloak: on-prem Active Directory, Entra ID, or Keycloak's own users? | Head of IT Operations | On-prem AD through Keycloak LDAP federation | F13 | Decided 2026-10-17 |
| OQ-04 | One business calendar or one per site? | IT Service Desk Manager | One: Mon–Fri 08:00–17:30, lunch counted as working, `Asia/Ho_Chi_Minh`; Saturday off | F1 | Decided 2026-10-17 |
| OQ-05 | SLA targets per priority | IT Service Desk Manager | P1: respond 15 min / resolve 4 h, **24×7**. P2: 30 min / 8 business h. P3: 4 business h / 3 business days. P4: 1 business day / 5 business days | F1 | Decided 2026-10-17 |
| OQ-06 | Who sets ticket priority? | IT Service Desk Manager | core-api rules: category default (security → P2, others → P3); linked to a mass incident → P1; a technician changes it with a reason. Requesters can't set it. Never from an LLM field | F1 | Decided 2026-10-17 |
| OQ-07 | When does a chat ticket's SLA start? | IT Service Desk Manager | When the requester asks for a ticket (`requester_asked_for_ticket`), not at the first message | F1, F3 | Decided 2026-10-17 |
| OQ-08 | "Chat memory across turns": does the chat model see earlier turns, or does only the screen show them? | Product owner | The model sees the **masked** earlier turns of the same conversation (last 6 turns); a conversation ends after 30 min idle; nothing carries into a new one. Needs a wire change and an ADR | F3 | Decided 2026-10-17 |
| OQ-09 | Reopen window | IT Service Desk Manager | 7 calendar days after resolution; after that, a new linked ticket | F3 | Decided 2026-10-17 |
| OQ-10 | Email relay and sender | Head of IT Operations | Company SMTP relay over TLS; sender `helpdesk@<company domain>` | F4 | Decided 2026-10-17 |
| OQ-11 | Break-glass accounts | Information Security Officer | 2 local accounts, role `manager`, password in the company vault, every sign-in alerts `security` | F13 | Decided 2026-10-17 |
| OQ-12 | Who may reveal PII? | Information Security Officer | `security`; or the technician who holds the claim on a pending review item of the ticket, or is its assignee. Critical labels: `security` only. Managers: no. (Refined at stage 2: `pii_verify` holds only blocked credential tickets) | F5 | Decided 2026-10-17 |
| OQ-13 | Holidays that apply only to public employees (e.g. Culture Day 24 Nov 2026) | HR | The holiday calendar is whatever HR enters each year | F1 | Decided 2026-10-17 |
| OQ-14 | How long are in-app notifications kept? | Data Protection Officer | 90 days, then deleted; the audit log keeps the event | F4 | Decided 2026-10-17 |
| OQ-15 | Should a requester be told when someone reveals their PII? | Data Protection Officer | No notice; the access log is exportable on request | F5 | Decided 2026-10-17 |
| OQ-16 | Does the requester see the assignee's name, or only the team? | IT Service Desk Manager | Team only | F3 | Decided 2026-10-17 |
| OQ-17 | Should `on_hold` (waiting on a vendor) pause the SLA? | IT Service Desk Manager | No; only `waiting_on_requester` pauses | F1 | Decided 2026-10-17 |
| OQ-18 | Do teams need their own calendars (e.g. a 24×7 network on-call)? | Head of IT Operations | One default calendar; the field exists if needed | F1, F2 | Decided 2026-10-17 |
| OQ-19 | Migrate today's `open` incidents as `confirmed`? | IT Service Desk Manager | Yes | F7 | Decided 2026-10-17 |
| OQ-20 | Are there at least two people with the `manager` role to approve a rollout flag (F9)? | Head of IT Operations | Yes: the Service Desk Manager and the Head of IT Operations both hold `manager` | F9 | Decided 2026-10-17 |
| OQ-21 | Gate for `requester_questions`: clarify agreement ≥ 0.80 over 14 days | IT Service Desk Manager | Accept as a starting gate; re-choose on shadow data | F9 | Decided 2026-10-17 |
| OQ-22 | Ask for a rating on tickets closed by an incident's close-all? | IT Service Desk Manager | No | F7, F3 | Decided 2026-10-17 |
| OQ-23 | Backfill security alerts from the last 30 days of audit rows? | Information Security Officer | Yes, 30 days | F8 | Decided 2026-10-17 |
| OQ-24 | Mirror tickets into an external ITSM (ServiceNow, Jira)? | Head of IT Operations | Not this phase; if needed later, an n8n flow on F4 webhook events | F12 | Decided 2026-10-17 |
| OQ-25 | Use a separate Keycloak client for runbook actions, apart from the F13 sync client? | Information Security Officer | Yes: `smart-ticket-runbooks`, only `manage-users` on the realm, no impersonation | F12 | Decided 2026-10-17 |
| OQ-26 | Records retention for audit log, PII access log, security alerts | Data Protection Officer | 5 years, then archived | §7 NFR-PRIV-02 | Decided 2026-10-17 |
| OQ-27 | Capacity planning numbers (3,000 employees, 50 staff online) | Head of IT Operations | As in §7.4 | §7 | Decided 2026-10-17 |

## 9.2 Assumptions made at stage 1

| ID | Assumption | Where used |
|---|---|---|
| A-01 | The org is Vietnam-based, staff in one time zone | §5, F1 |
| A-02 | 3–5 technicians work the queue (spec §0) | F2 sizing |
| A-03 | KPI targets K1, K2, K4, K6, K11 are ITSM-typical, not measured | §1.3 |
| A-04 | No SMS, voice or push provider is in scope | F4 |
| A-05 | The org has a Data Protection Officer | §0.2 |
| A-06 | Reveal reasons are masked by the regex tier only, so reveals work when ai-engine is down | F5 BR-F5-04 |
| A-07 | *(Decided by OQ-17 on 2026-10-17)* Vendor waits (`on_hold`) keep counting SLA time | F1 BR-F1-07 |
| A-08 | No backfill of SLA clocks or priority for tickets created before F1 | F1 §g |
| A-09 | A reopened ticket resumes its old resolution clock; response is not restarted | F1 BR-F1-13 |
| A-10 | `security` may assign only within the `security` category | F2 BR-F2-04 |
| A-11 | Gap clustering bars (`kb_gaps.cluster_similarity` 0.80, `update_similarity` 0.65) are guesses on bge-m3 cosine | F6 |
| A-12 | Linked incident tickets are excluded from team SLA % | F10 BR-F10-04 |
| A-13 | No automatic flag turn-off when a gate becomes unmet; managers are notified | F9 |
| A-14 | Availability target 99.5 % in business hours; OWASP ASVS L2 as the security baseline | §7.4 |
| A-15 | Capacity: 3,000 employees, 300 concurrent chat sessions, 50 staff online, 15,000 notices/day | §7.4 |
| A-16 | The SLA badge shows the response clock until it is met, then the resolution clock | F1, [mockups](mockups.md) |
| A-17 | Admin console navigation: top-level Reports, Incidents, Security, Settings, each shown by role; Queue gains tabs Review queue, Team queue, My tickets, SLA at risk | F1, F2, F7–F10, [mockups](mockups.md) |
| A-18 | The fallback team migrated from category `other` is named "Service Desk" | F2 §g |
| A-19 | Requester-facing labels show Vietnamese first, English second; staff UI stays English with Vietnamese data | F3, F13 |
| A-20 | Dashboard keeps today's Ops tiles and adds a Service row | F10 |
| A-21 | Mockups use Inter in place of the apps' system UI font stack | [mockups](mockups.md) |

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
| R-08 | F3's prompt bumps (`hyde_draft.v3`, `propose.v10`) move an eval gate | Medium | High | Run the full eval before merge; single-turn cases must not regress; no floor lowered (rule 9) |
| R-09 | The SLA hook adds work inside every status change | Low | Medium | One indexed write; savepoint; p95 status-move latency in §7 NFRs |
| R-10 | Engine change `lifecycle.automatic_move` widens who can move tickets | Low | Medium | Governed exactly like a person's move; never targets pipeline statuses; tested |
| R-11 | Incident detector defects found in code reading (every incident keyed to `other`; trigger ticket counted twice) already affect shadow data on escalations | High | Medium | F7 fixes both; pin each with a test first; note in `status.md` |
| R-12 | Revoking authority on every page edit (F6) can drop auto-reply coverage suddenly | Medium | Medium | Authority queue with the diff makes re-grant quick; F10 shows coverage per week |
| R-13 | A production deploy without an approved thresholds change request boots shadow-forced (F9) | Medium | Medium | Baseline `CR-2026-000` created by migration; deploy checklist item; the alert names the cause |
| R-14 | Two managers needed for every flag-on can stall rollout | Low | Low | Requests expire in 72 h with a notice; turning off never waits |
| R-15 | A Keycloak admin credential that can reset passwords and add groups is a high-value secret | Medium | High | Separate client (OQ-25), least roles, allow-listed groups only, secret in the vault, every call audited in both systems |
| R-16 | Editor overrides of the entity graph could quietly lower retrieval recall | Low | Medium | Retrieval suite runs with production overrides weekly; F10 KB report shows expansion's share |

## 9.4 Proposed ADRs

| ADR | Title | Feature | Relaxes a guardrail? | Draft |
|---|---|---|---|---|
| 0030 | SLA clocks count business time, driven by lifecycle events | F1 | No | [written](proposed-adrs/0030-sla-clocks-on-lifecycle-events.md) |
| 0031 | Capabilities and team scope alongside the primary role | F2, F6, F7, F9, F13 | No (adds rights, each audited) | [written](proposed-adrs/0031-capabilities-and-team-scope.md) |
| 0032 | Keycloak signs people in; core-api keeps the session | F13 | No; builds on ADR-0029 | [written](proposed-adrs/0032-keycloak-signs-in-core-api-keeps-the-session.md) |
| 0033 | Notifications go through an outbox written in the event's transaction | F4 | No | [written](proposed-adrs/0033-notifications-through-an-outbox.md) |
| 0034 | A chat conversation gives the model its earlier masked turns | F3 | **Yes**: today each ticket is analysed alone. Must say why cross-turn context is safe | [written](proposed-adrs/0034-conversation-context-for-the-model.md) |
| 0035 | Reviewed thresholds and per-branch rollout switches | F9 | No; adds keys that can only make the system more conservative | [written](proposed-adrs/0035-reviewed-thresholds-and-per-branch-rollout.md) |
| 0036 | KB drafts live outside `kb_articles`; a text change revokes authority | F6 | No; tightens ADR-0002 | [written](proposed-adrs/0036-kb-drafts-outside-kb-articles.md) |
| 0037 | The entity graph survives edits, rebuilds on a schedule, and takes editor overrides | F11 | Slightly: ai-engine gets SELECT on one table and limited UPDATE on another | [written](proposed-adrs/0037-entity-graph-as-a-kb-feature.md) |
| 0038 | Real runbook executors stay behind ADR-0006, with target rules | F12 | No; adds checks to ADR-0006 | [written](proposed-adrs/0038-runbook-executors-behind-adr-0006.md) |
