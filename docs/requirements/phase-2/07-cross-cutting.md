# 7. Cross-cutting requirements

Rules here apply to every phase 2 feature. Feature files reference them;
where a feature file and this section disagree, raise it as a CR (§0.4).

## 7.1 RBAC matrix for new actions

Key: **✔** allowed · **own** only their own records · **team** only teams
they lead (or belong to, for "take") · **R** read only · **—** refused (403
or 404). A capability adds rights on top of the primary role (proposed
ADR-0031). Every row is enforced in core-api (BR-X-02).

Columns: **Emp** employee · **Tech** technician · **Lead** team lead
(membership role) · **Mgr** manager · **Sec** security · **WfA**
`workflow_admin` · **KBE** `kb_editor` · **IM** `incident_manager`.

| Feature | Action | Emp | Tech | Lead | Mgr | Sec | WfA | KBE | IM |
|---|---|---|---|---|---|---|---|---|---|
| PRE-1 | Read a ticket | own | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| PRE-1 | Review queue: claim, decide (except `injection`, `pii_verify`) | — | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| F8 | Review queues `injection`, `pii_verify` | — | — | — | — | ✔ | — | — | — |
| F1 | Change a ticket's priority | — | assignee | team | ✔ | — | — | — | — |
| F1 | Draft SLA policy, edit calendars and holidays | — | — | — | ✔ | — | ✔ | — | — |
| F1 | Approve SLA policy (≠ author) | — | — | — | ✔ | — | — | — | — |
| F1 | Rebuild a ticket's clocks | — | — | — | ✔ | — | — | — | — |
| F2 | Take an unassigned ticket | — | team | team | ✔ | — | — | — | — |
| F2 | Reassign within the team | — | assignee | team | ✔ | security category | — | — | — |
| F2 | Reassign out of the team | — | — | team | ✔ | — | — | — | — |
| F2 | Edit own availability, own leave | — | own | own | own | own | own | own | own |
| F2 | Edit members' leave | — | — | team | ✔ | — | — | — | — |
| F2 | Create or edit teams | — | — | — | ✔ | — | ✔ | — | — |
| F3 | My tickets, reply, reopen, rate | own | own | own | own | own | own | own | own |
| F3 | Public comment / internal note | — | ✔ | ✔ | ✔ | ✔ | — | — | ✔ |
| F4 | Read own notifications, set own preferences | own | own | own | own | own | own | own | own |
| F4 | Edit notification matrix, templates, webhooks | — | — | — | R | — | ✔ | — | — |
| F4 | Retry failed deliveries | — | — | — | ✔ | — | ✔ | — | — |
| F5 | Reveal a non-critical value | — | claim holder / assignee | claim holder / assignee | — | ✔ | — | — | — |
| F5 | Reveal a critical value (password, token, key) | — | — | — | — | ✔ | — | — | — |
| F5 | Read / export the PII access log | — | — | — | — | ✔ | — | — | — |
| F6 | Create, edit, submit a KB draft | — | — | — | ✔ | — | — | ✔ | — |
| F6 | Review a KB draft (≠ author) | — | — | — | ✔ | — | — | ✔ | — |
| F6 | Grant auto-reply authority, set final risk tier | — | — | — | ✔ | — | — | — | — |
| F6 | Read the authority log | — | — | — | ✔ | ✔ | — | R | — |
| F6 | KB-gap report: read, dismiss | — | — | — | ✔ | — | — | ✔ | — |
| F7 | Confirm, dismiss, declare, broadcast, resolve an incident | — | — | — | — | — | — | — | ✔ |
| F7 | Unlink a ticket | — | assignee | assignee | — | — | — | — | ✔ |
| F7 | Read incidents | — | R | R | R | R | R | R | ✔ |
| F8 | Security inbox: read, ack, close, release ticket | — | — | — | — | ✔ | — | — | — |
| F8 | Security summary counts | — | — | — | R | ✔ | — | — | — |
| F9 | Request a flag on; approve (≠ requester) | — | — | — | ✔ | — | — | — | — |
| F9 | Turn a flag off | — | — | — | ✔ | ✔ | — | — | — |
| F9 | Submit a threshold change request | — | ✔ | — | ✔ | — | ✔ | — | — |
| F9 | Approve a threshold change request (≠ author) | — | ✔ (2nd reviewer) | — | ✔ | — | — | — | — |
| F10 | SLA, team, CSAT reports | — | own row | team | ✔ | — | — | — | — |
| F10 | Reviewer report | — | own row | own row | ✔ | — | — | — | — |
| F10 | KB report | — | — | — | ✔ | — | — | ✔ | — |
| F10 | Security report | — | — | — | — | ✔ | — | — | — |
| F10 | Incident report | — | — | — | ✔ | — | — | — | ✔ |
| F11 | Page graph: confirm, hide, add, rebuild | — | — | — | ✔ | — | — | ✔ | — |
| F12 | Approve and execute a runbook | — | ✔ | ✔ | ✔ | — | — | — | — |
| F12 | Second approval of a high-risk runbook (≠ first) | — | — | — | ✔ | — | — | — | — |
| F12 | Draft runbook catalog / approve it | — | — | — | approve | — | draft | — | — |
| F13 | Change roles, capabilities, teams of `oidc` users | — | — | — | — | — | — | — | — |

The last row is intentional: those come from Keycloak only (BR-F13-07).
Grants and revocations in Keycloak are themselves audited there and on sync.

## 7.2 Notification matrix

Source of truth: the catalog in [F4 §f](06-F4-notifications.md#f-functional-requirements).
This copy is generated from it; mandatory cells can't be turned off by users
or admins (BR-F4-03).

| Event | Feature | Recipients → channels | Mandatory |
|---|---|---|---|
| `ticket.received` | F3 | requester → in_app, email | — |
| `ticket.assigned` | F2 | assignee → in_app, email | — |
| `ticket.reassigned` | F2 | new assignee → in_app, email; previous assignee → in_app; team lead → in_app | — |
| `ticket.unassigned` | F2 | team lead → in_app, email | — |
| `ticket.public_comment` | F3 | requester → in_app, email | — |
| `ticket.requester_replied` | F3 | assignee → in_app, email | — |
| `ticket.status_changed` | F3 | requester → in_app (only into `waiting_on_requester`, `resolved`) | — |
| `ticket.resolved` | F3 | requester → in_app, email (carries the CSAT link) | — |
| `ticket.reopened` | F3 | assignee, team lead → in_app | — |
| `ticket.rated_low` | F3 | team lead → in_app, email | — |
| `sla.warning` | F1 | assignee → in_app, email; team lead → in_app | — |
| `sla.breached` | F1 | assignee, team lead → in_app, email | — |
| `sla.breached_escalated` | F1 | manager → in_app, email | — |
| `sla.holidays_missing` | F1 | workflow_admins → in_app, email | — |
| `assignment.failed` | F2 | team lead of the fallback team → in_app | — |
| `approval.requested` | lifecycle | approver → in_app, email | in_app |
| `identity.break_glass_used` | F13 | security → in_app, email | both |
| `incident.broadcast` | F7 | linked requesters → in_app, email | both |
| `incident.proposed` | F7 | incident managers → in_app, email | both |
| `incident.sla_breached` | F7 | manager → in_app, email | — |
| `security.credential_exposed` | F8 | requester → in_app, email | both |
| `security.ack_overdue` | F8 | security → in_app, email | both |
| `kb.review_requested` | F6 | kb editors, managers → in_app | — |
| `kb.authority_needed` | F6 | managers → in_app, email | — |
| `kb.gaps_ready` | F6 | kb editors → in_app, email | — |
| `rollout.flag_requested` | F9 | managers → in_app, email | — |
| `rollout.flag_changed` | F9 | managers, security → in_app, email | in_app |
| `rollout.gate_unmet` | F9 | managers → in_app, email | — |
| `thresholds.cr_pending` | F9 | managers → in_app | — |
| `thresholds.unapproved` | F9 | managers, security → in_app, email | both |
| `report.weekly` | F10 | managers → email | — |

Defaults a `workflow_admin` may change: every non-mandatory cell. Language:
the recipient's `accounts_user.language` (vi default).

## 7.3 Audit events added

All written through `AuditLog.objects.record` in the same transaction as the
change (BR-X-03). `audit_log` stays append-only.

| Feature | Events |
|---|---|
| PRE-1 | `access_denied` |
| F1 | `sla_started`, `sla_paused`, `sla_resumed`, `sla_met`, `sla_breached`, `sla_escalated`, `sla_retargeted`, `sla_override`, `sla_update_failed`, `sla_policy_fallback`, `sla_policy_activated`, `sla_calendar_changed`, `ticket_priority_changed` |
| F2 | `ticket_assigned`, `ticket_reassigned`, `assignment_failed`, `team_changed`, `membership_changed`, `availability_changed`, `leave_changed` |
| F3 | `conversation_started`, `conversation_ended`, `ticket_comment_added`, `requester_replied`, `ticket_reopen_linked`, `ticket_rated`, `ticket_auto_closed` (`ticket_reopened` REUSED) |
| F4 | `notif_matrix_changed`, `notif_template_changed`, `notif_webhook_changed`, `notif_delivery_retried` |
| F5 | `pii_revealed`, `pii_reveal_failed`, `pii_access_log_exported` (`pii_access_log` rows are separate and also append-only) |
| F6 | `kb_draft_created`, `kb_draft_submitted`, `kb_draft_reviewed`, `kb_published`, `kb_retired`, `kb_authority_revoked`, `kb_gap_dismissed`, `kb_snapshot_loaded` |
| F7 | `incident_proposed`, `incident_confirmed`, `incident_dismissed`, `incident_declared`, `incident_broadcast`, `incident_resolved`, `incident_closed`, `incident_ticket_linked`, `incident_ticket_unlinked` |
| F8 | `security_alert_acknowledged`, `security_alert_closed`, `security_alert_reopened`, `security_ticket_released` (`security_alert` REUSED, now also creates an inbox alert) |
| F9 | `rollout_flag_requested`, `rollout_flag_approved`, `rollout_flag_on`, `rollout_flag_off`, `threshold_cr_submitted`, `threshold_cr_approved`, `threshold_cr_rejected`, `thresholds_loaded`, `thresholds_unapproved` |
| F10 | `report_exported` |
| F11 | `kb_graph_edge_confirmed`, `kb_graph_override_added`, `kb_graph_override_removed`, `kb_graph_rebuild_requested` |
| F12 | `runbook_approved`, `runbook_executed`, `runbook_failed`, `runbook_unknown`, `runbook_resolved`, `runbook_catalog_changed` |
| F13 | `auth_login` (CHANGED: `method`), `identity_provisioned`, `identity_linked`, `identity_rights_changed`, `identity_deactivated`, `auth_backchannel_logout`, `identity_sync_failed` |

**Payload rule:** IDs, codes, before/after values, and masked text only.
Never a revealed value, a password, a token, or a raw reply.

## 7.4 Non-functional requirements

### Capacity — the load every number below is measured at

| Item | Value | Source |
|---|---|---|
| Tickets | 800/day sustained; 40 in 15 min during a mass incident | Spec §0 (200–800/day); F7 |
| Staff users online | 50 concurrent | [ASSUMPTION] |
| Employees (requesters) | 3,000 accounts, 300 concurrent chat sessions | [ASSUMPTION] |
| Notifications | 15,000 messages/day, 1,000 in 5 min during a broadcast | F4, F7 |
| KB pages | 3,542 (demo) to 10,000 | `demo_kb/`; spec §0 warns above 5,000 |

### Performance

| ID | Requirement |
|---|---|
| NFR-P-01 | New read endpoints (lists, reports for today) p95 ≤ 300 ms; p99 ≤ 800 ms, measured at core-api, excluding network |
| NFR-P-02 | New write endpoints p95 ≤ 500 ms, except those that mask text inline (replies, comments), which add today's masking time (regex + NER call, connect 3 s / read 120 s budget unchanged) |
| NFR-P-03 | Extra time added to a lifecycle status change by F1's hook and F4's emit: p95 ≤ 20 ms |
| NFR-P-04 | Report endpoints over past months (facts table) p95 ≤ 1.5 s for one year of data |
| NFR-P-05 | Ticket submit and the triage pipeline: no regression beyond +5 % p95 against the last `ops_metrics` baseline |
| NFR-P-06 | Assignment lock wait (BR-F2-08) p99 ≤ 200 ms at 40 tickets in 15 min |

### SLA timer accuracy

| ID | Requirement |
|---|---|
| NFR-S-01 | `due_at` and `warn_at` are exact to the second for the calendar and holidays in force when computed |
| NFR-S-02 | A warning, breach or escalation is recorded ≤ 120 s after its time (sweep every 60 s) |
| NFR-S-03 | Business-time code passes a property test of 10,000 random (start, minutes, pauses, holidays) cases against a simple minute-by-minute reference |
| NFR-S-04 | All stored times UTC; display in `Asia/Ho_Chi_Minh` (no DST); a calendar with another zone is computed in that zone |

### Availability and degradation

| ID | Requirement |
|---|---|
| NFR-A-01 | core-api availability ≥ 99.5 % per month during business hours (08:00–17:30 +07, Mon–Fri) [ASSUMPTION] |
| NFR-A-02 | Keycloak down: live sessions keep working to their ADR-0029 limits; new sign-ins show `idp_unavailable` |
| NFR-A-03 | SMTP down: in-app notices unaffected; email retried, then listed as failed; no ticket affected |
| NFR-A-04 | Celery down: tickets are still accepted and masked inline (today's behaviour); SLA sweeps, notification sends and reports catch up on restart without double-sending (idempotency keys) |
| NFR-A-05 | Every new failure resolves toward a person (BR-X-07); none silently drops a ticket, a notice, or a log row |

### Security and privacy

| ID | Requirement |
|---|---|
| NFR-SEC-01 | New endpoints meet OWASP ASVS 4.0 Level 2 for authentication, access control, input validation and logging [ASSUMPTION: the org's baseline] |
| NFR-SEC-02 | Every endpoint gated in core-api; CI test fails on an ungated route (PRE-1) |
| NFR-SEC-03 | TLS 1.2+ between browser, core-api, Keycloak, SMTP relay and n8n; webhook bodies signed (HMAC-SHA256) |
| NFR-SEC-04 | Secrets (OIDC client secret, Keycloak admin secret, webhook secrets, SMTP password) come from environment / secret store only; webhook secrets stored encrypted at rest |
| NFR-SEC-05 | `audit_log` and `pii_access_log` are append-only at the database (`REVOKE UPDATE, DELETE`) |
| NFR-SEC-06 | No raw PII in logs, notices, reports, exports or webhook bodies; a log-capture test runs over every feature's happy path |
| NFR-SEC-07 | Rate limits: reveal 20/user/hour (F5); `POST /api/auth/oidc/exchange` 10/IP/min; reply/comment 30/user/min [ASSUMPTION] |
| NFR-PRIV-01 | Processing of personal data follows Vietnam's Law on Personal Data Protection No. 91/2025/QH15 and Decree 356/2025/ND-CP (both in force since 2026-01-01; Decree 13/2023 is superseded). The DPO confirms the lawful basis for the quarantine, the access log and notification content before F5 and F13 go live |
| NFR-PRIV-02 | Retention: raw PII 72 h (unchanged); in-app notices 90 days; chat conversations keep ids and timestamps only (turn text lives on tickets, as today); PII access log, audit log, security alerts kept per the org's records policy, default 5 years [ASSUMPTION] |

### Internationalisation

| ID | Requirement |
|---|---|
| NFR-I-01 | Every new user-facing string exists in vi and en; vi is the default; the user's `language` decides |
| NFR-I-02 | Dates and times shown in `Asia/Ho_Chi_Minh`: vi `dd/MM/yyyy HH:mm`, en `d MMM yyyy, HH:mm` |
| NFR-I-03 | Search and filters on names and subjects ignore Vietnamese diacritics (same folding as `LexicalShortlister`, `đ`/`Đ` included) |
| NFR-I-04 | Notification templates and broadcast bodies keep Vietnamese text exactly as written (UTF-8 end to end, email `charset=utf-8`) |

### Accessibility — WCAG 2.2 AA

| ID | Requirement |
|---|---|
| NFR-ACC-01 | Text contrast ≥ 4.5:1, large text and UI parts ≥ 3:1, in light and dark themes |
| NFR-ACC-02 | SLA, priority, PII level, risk tier and status never shown by colour alone: each badge has text (e.g. "Quá hạn 2 giờ") |
| NFR-ACC-03 | All actions reachable by keyboard; visible focus not hidden by sticky headers (2.4.11) |
| NFR-ACC-04 | Pointer targets ≥ 24 × 24 CSS px (2.5.8); drag-only interactions have a click alternative (2.5.7) |
| NFR-ACC-05 | New notices, SLA state changes and chat replies are announced through `aria-live="polite"`; security alerts and breaches `assertive` for the people who receive them |
| NFR-ACC-06 | Countdowns don't update the accessible name more than once a minute |
| NFR-ACC-07 | Sign-in through Keycloak doesn't require a cognitive test beyond what the company IdP requires (3.3.8) |
| NFR-ACC-08 | Each new screen passes axe-core with 0 serious or critical issues in CI |

### Operability

| ID | Requirement |
|---|---|
| NFR-O-01 | Every new Celery task logs `trace_id` and is idempotent (stated per task in each feature's §h) |
| NFR-O-02 | Migrations are additive first; backfills run in batches of ≤ 1,000 rows, resumable |
| NFR-O-03 | Every new setting appears in the settings code (type only), `.env.example` (value and why) and the service's `environment:` in `docker-compose.yml` (CLAUDE.md "Commands") |
| NFR-O-04 | Every new tunable lives in `thresholds.yaml`; F9's change-request flow applies to them |
