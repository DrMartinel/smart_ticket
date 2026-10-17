# Benchmark: F1–F13 against five products

How ServiceNow ITSM, Jira Service Management (JSM), Freshservice, ManageEngine
ServiceDesk Plus (SDP) and Moveworks handle each feature, and what we take.
Patterns are described in our own words; no product text or UI is copied.

**Decisions:** **Adopt** = take the pattern as is. **Adapt** = take it, changed
to fit our ADRs. **Skip** = don't take it, with the reason.

A cell marked *not found* means the sources checked at stage 1 did not
describe it. It does not mean the product lacks it. Each will be rechecked in
the stage that specs the feature.

ITIL 4 practice names follow the 34-practice list ([ITSM.tools summary][itil]).

---

## F1 SLA & business hours

| Product | Pattern |
|---|---|
| ServiceNow | An SLA definition has separate **start, pause, resume, stop, reset and cancel** conditions, checked on every record change. Duration is counted against a **schedule**; with no schedule, it is wall-clock time. Pause can't combine with "relative" durations ([conditions][sn-sla-cond], [duration][sn-sla-dur]) |
| JSM | Each SLA metric has start/pause/stop conditions, e.g. pause while status is "Waiting for customer". **Goals** are ordered rules (by priority via a query); the first match wins. **Calendars** hold working hours, breaks, weekends and holidays ([setting up SLAs][jsm-sla]) |
| Freshservice | A **time × priority matrix** per policy; business or calendar hours; up to **four resolution escalation levels and one response level**, each with when and whom; workspace → global → default precedence ([default SLA policy][fs-sla]) |
| SDP | Separate response and resolution SLAs; **multi-level escalation** that can reassign, change group or raise priority; SLAs picked by priority, impact, urgency, site, VIP; timers **pause while waiting for the requester**; per-site operational hours and holidays ([SLA management][sdp-sla]) |
| Moveworks | Not an SLA engine; it reads the ITSM's ticket state. Sends a weekly status digest of open tickets ([MMTS][mw-mmts]) |

| Decision | What | Why |
|---|---|---|
| Adopt | Response + resolution targets per (category, priority); ordered policy match, first wins, plus a default | Common to all four ITSM tools; simple to test |
| Adopt | Business calendar with time zone, working hours, holiday list | JSM, SDP, Freshservice all do it |
| Adapt | Start/pause/stop as **lifecycle events**, not free conditions. Start at handoff; pause on entering a status flagged `pauses_sla`; stop on entering a completed system status | ADR-0028 already models statuses and actions. Free condition expressions would bring back user-supplied logic ADR-0028 §5 rejected |
| Adapt | Escalation levels: warn at 75 %, breach at 100 % → team lead, 125 % → manager [ASSUMPTION] | Freshservice/SDP pattern, kept short |
| Adapt | Holidays entered per year, not computed | Vietnam sets Tết and bridge days by annual decision; 2027 Tết is 4–10 Feb and National Day 2–5 Sep ([VietNamNet][vn-hol]); Culture Day 24 Nov 2026 was added by a one-off approval |
| Skip | ServiceNow "reset" and "relative" durations | Not needed for an internal desk; extra states to test |

**ITIL 4:** Service level management (primary), Incident management, Service desk.

## F2 Teams, assignment & workload

| Product | Pattern |
|---|---|
| ServiceNow | **Advanced Work Assignment**: routing conditions put work in queues; an assignment rule picks the agent with **most free capacity** or **longest since last assignment**; agents have a **capacity cap** and a **presence** state ([AWA overview][sn-awa]) |
| JSM | Automation "smart assign": **balanced workload** (fewest open issues), **round-robin** over a list, or random ([smart assign][jsm-assign]) |
| Freshservice | Group-level **round robin**; both the group and the agent must opt in; admins toggle agent availability ([auto-assignment][fs-assign]) |
| SDP | **Round robin** (ignores load) or **load balancing** (fewest In-Progress tickets); scoped to group or site; can limit to online technicians and skip those on leave ([technician auto-assign][sdp-assign]) |
| Moveworks | Its Triage model predicts the **assignment group** and writes it only above a confidence threshold ([Triage][mw-triage]) |

| Decision | What | Why |
|---|---|---|
| Adopt | Two strategies per team: `round_robin`, `least_loaded` | JSM, SDP, Freshservice all offer both |
| Adopt | Availability flag and leave dates; skip unavailable members | SDP, Freshservice, ServiceNow |
| Adapt | Assignment runs **after** the router's decision is carried out: called by core-api when a live `auto_route` is executed, when a reviewer decides a HITL item, or when a chat ticket is released to support. Not a lifecycle action, because pipeline statuses carry none (ADR-0028 §2) | The router chooses the category (ADR-0001, ADR-0017); assignment must never change a branch |
| Adapt | Optional per-person cap (max open tickets); over cap = skipped | ServiceNow capacity, simplified |
| Skip | Predicting the assignee or team with a model | Moveworks/ServiceNow pattern, but our team comes from the router's category. A second model choosing teams would be authority the LLM was never granted |

**ITIL 4:** Service desk, Incident management, Workforce and talent management.

## F3 Requester experience in chat

| Product | Pattern |
|---|---|
| ServiceNow | *Not found* in sources checked (Service Portal / Virtual Agent to recheck in stage 2) |
| JSM | **CSAT**: rating sent when a request is resolved; customer can change it and add a comment; scores show on the issue and in a satisfaction report ([CSAT][jsm-csat]) |
| Freshservice | Satisfaction survey after resolution; by default a survey reply does **not** reopen; reopen-on-feedback is a workflow rule ([reopen on feedback][fs-reopen]) |
| SDP | *Not found* (self-service portal to recheck in stage 2) |
| Moveworks | Chat **ticket status** (open first, then resolved/closed of the last 30 days), alerts on comments and requests for input, **add comment**, **reopen** (resolved → New; closed → new linked ticket), **close**, nudges on stale tickets ([Concierge][mw-concierge]); weekly digest ([MMTS][mw-mmts]) |

| Decision | What | Why |
|---|---|---|
| Adopt | My tickets list: open first, then resolved in the last 30 days | Moveworks pattern fits a chat UI |
| Adopt | Reply, reopen within a window, rating 1–5 + comment, once per resolution | Moveworks + JSM |
| Adapt | Reopen after the window → new ticket linked to the old one | Moveworks does this for closed tickets |
| Adapt | Every reply is masked inline, exactly like a ticket (spec §5) | Our guardrail; vendors don't mask |
| Adapt | A low rating (1–2) does not reopen; it creates an `eval_candidate` and notifies the team lead | Freshservice default; keeps the reopen metric honest (K7) |
| Skip | Requester "close" from chat | Moveworks has it; our resolution belongs to the workflow and a person. Revisit with data |

**ITIL 4:** Service request management, Service desk, Relationship management.

## F4 Notifications

| Product | Pattern |
|---|---|
| ServiceNow | Users turn notifications on/off globally or one by one; channels are email, SMS, push and messaging; per-channel schedules; optional email digest ([preferences][sn-notif]) |
| JSM | Customer notifications are rules; the "request resolved" rule also carries the CSAT prompt ([CSAT][jsm-csat]) |
| Freshservice | Admin toggles per notification and per audience (requester, agent, CC); editable templates with placeholders; translated templates per enabled language ([email notifications][fs-notif]) |
| SDP | Escalation emails use custom templates ([SLA management][sdp-sla]) |
| Moveworks | Delivers updates as chat messages (Slack, Teams) rather than email ([Concierge][mw-concierge], [Employee Communications][mw-comms]) |

| Decision | What | Why |
|---|---|---|
| Adopt | Event × recipient × channel matrix, admin default per cell | Freshservice/ServiceNow |
| Adopt | User preferences per event and channel | ServiceNow |
| Adopt | Templates per language (vi, en) | Freshservice; our users are mixed vi/en |
| Adapt | A **mandatory** flag the user can't override (security alerts, break-glass sign-ins, incident broadcasts, approval requests) | Safety notices must not be opt-out |
| Adapt | Templates read **masked** fields only | ADR-0028 §6 |
| Adapt | Webhook channel only to allow-listed hosts | ADR-0028 §6 already does this |
| Skip | SMS, voice, push | No provider in scope; in-app + email cover the need [ASSUMPTION] |
| Skip | Slack/Teams this phase | Could come through F12 n8n flows |

**ITIL 4:** Service desk, Relationship management, Incident management.

## F5 PII quarantine reveal

| Product | Pattern |
|---|---|
| ServiceNow | Sensitive Data Handler masked card numbers, SSNs and emails in chat by regex and stopped agents sending them; being replaced by a Data Privacy app ([Sensitive Data Handler][sn-sdh]) |
| JSM | Atlassian Guard scans issue fields for credentials, card and ID numbers and **alerts admins**; it doesn't mask ([Guard detection][guard]) |
| Freshservice | A marketplace masker replaces card/SSN digits with X, keeping the last four; no stated way back ([masker][fs-mask]) |
| SDP | PII fields can be marked and encrypted at rest; a **PII access log** records module, action and time, exportable ([GDPR features][sdp-gdpr]) |
| Moveworks | *Not found* |

| Decision | What | Why |
|---|---|---|
| Adopt | Access log for every read, exportable | SDP |
| Adapt | Mandatory reason code + text; same transaction as decrypt; one value per reveal | Spec §3.1 is stricter than any vendor: "every raw-PII read is a log line" |
| Adapt | Who may reveal: `security`, or the technician who holds the claim on that ticket's `pii_verify` item | `TODO.md` item 1 |
| Skip | Irreversible masking only | Spec §0 chose an encrypted quarantine with TTL |
| Skip | Showing revealed values inside notifications or exports | A reveal is for one person on one screen |

**ITIL 4:** Information security management.

## F6 KB authoring & governance

| Product | Pattern |
|---|---|
| ServiceNow | Two publish paths, **instant** or **approval**; two retire paths; states Draft → In review → (Scheduled) → Published → Retired; rejection returns to Draft ([knowledge workflows][sn-kb]) |
| JSM | Article reports on views and helpful votes ([KB reports][jsm-kb]) |
| Freshservice | Approvers per folder; author sends for approval and can't edit while waiting; approvers return with "edits required" or approve ([KB approvals][fs-kb]) |
| SDP | *Not found* |
| Moveworks | Finds **knowledge gaps** by clustering last month's tickets and drafts an article per cluster for a person to review; separates "new topic" from "update an existing page" ([recommendations][mw-gaps]) |

| Decision | What | Why |
|---|---|---|
| Adopt | Draft → In review → Published → Retired; reject → Draft | ServiceNow, Freshservice |
| Adopt | Author can't approve own draft | Freshservice; ADR-0002 separation |
| Adapt | **Two separate approvals**: publish (content) and auto-reply authority (ADR-0002). Publishing never grants authority | Our auto-reply authority lives on the row |
| Adapt | KB-gap report from `retrieval_below_floor` refusals, clustered by embedding; gap vs. update split | Moveworks idea, our signal (`refusal_rate`, spec §11.1) |
| Skip | LLM-drafted articles in this phase | A model writing the pages it later quotes is a loop the eval set can't catch. Revisit as a proposed ADR |
| Skip | Bulk approval of high-risk pages | ADR-0027 |

**ITIL 4:** Knowledge management, Continual improvement.

## F7 Mass-incident management

| Product | Pattern |
|---|---|
| ServiceNow | Anyone **proposes** a major-incident candidate (or a rule flags one); the major incident manager **promotes** it; it becomes the parent of the candidate; **communication plans** create communication tasks ([major incident][sn-mim]) |
| JSM | Incidents can be marked major; stakeholders and status updates are separate features (articles listed, not read at stage 1) ([incidents][jsm-inc]) |
| Freshservice | Promote or create a major incident; link child tickets; email stakeholders from a collaborate panel; publish to a status page; resolving opens a post-incident report ([major incident][fs-mim]) |
| SDP | Announcements: company-wide or technicians only, optional portal display and email, start/end time ([announcements][sdp-ann]) |
| Moveworks | Targeted broadcast messages in chat, scheduling, delivery and click analytics ([Employee Communications][mw-comms]) |

| Decision | What | Why |
|---|---|---|
| Adopt | Detector **proposes**, incident manager **confirms** | ServiceNow; matches "LLM proposes, code decides" in spirit |
| Adopt | Broadcast to all linked requesters with ETA; delivery count | Moveworks, Freshservice |
| Adapt | Close-all on resolve moves linked tickets through the lifecycle with one reason, per-ticket audit | No vendor source found for close-all; we need it per ticket so the audit stays per ticket |
| Skip | Public status page | Internal only |

**ITIL 4:** Incident management, Problem management, Service desk.

## F8 Security inbox

| Product | Pattern |
|---|---|
| ServiceNow | Security Incident Response: incidents from events, alert rules, or the catalog; access limited to security roles, even admins blocked by default ([SIR][sn-sir]) |
| JSM | Guard alerts admins on sensitive content, naming the content and who wrote it ([Guard detection][guard]) |
| Freshservice | *Not found* |
| SDP | *Not found* |
| Moveworks | *Not found* |

| Decision | What | Why |
|---|---|---|
| Adopt | Alerts visible to `security` only | ServiceNow SIR access separation |
| Adopt | Alert names the ticket, the reason code, and who submitted | Guard pattern |
| Adapt | Sources: `block` decisions, `security_alert` audit events (router, refresh-token reuse ADR-0029), reveal volume (F5) | Our signals already exist |
| Skip | Full SOC tooling (threat intel, NIST lookups) | Out of scope for a helpdesk |

**ITIL 4:** Information security management, Monitoring and event management.

## F9 Rollout & threshold control

| Product | Pattern |
|---|---|
| Moveworks | Triage writes a field only above a confidence threshold; each field has an enable switch, off = **dry-run**; tracks coverage and precision; threshold changes go through their success team ([Triage][mw-triage], [setup][mw-triage-setup]) |
| ServiceNow, JSM, Freshservice, SDP | *Not found* for AI rollout gating; change approval is their Change enablement practice |

| Decision | What | Why |
|---|---|---|
| Adopt | Per-branch enable switch with dry-run = shadow | Moveworks; same idea as our shadow mode (spec §8.2) |
| Adopt | Show coverage and precision per branch at each gate | Moveworks |
| Adapt | Threshold changes as reviewed versions of `thresholds.yaml`, author ≠ approver | Hard rule 2 and rule 9 (CLAUDE.md); the snapshot in `routing_decisions.thresholds_used` must keep working |

**ITIL 4:** Change enablement, Deployment management, Release management.

## F10 Reporting

| Product | Pattern |
|---|---|
| ServiceNow | SLA dashboard: % resolved in time, % responded in time, open-and-overdue counts, broken down by group, priority, category ([SLA dashboard][sn-sla-dash]) |
| Freshservice | Group performance: resolved %, first-contact resolution, response and resolution SLA %, CSAT % ([group performance][fs-group]) |
| JSM | Satisfaction report; KB article reports ([CSAT][jsm-csat], [KB reports][jsm-kb]) |
| SDP | Breached tickets flagged in list views ([SLA management][sdp-sla]) |
| Moveworks | Coverage and precision of Triage ([Triage][mw-triage]) |

| Decision | What | Why |
|---|---|---|
| Adopt | SLA % (response, resolution), open-overdue, by team/priority/category | ServiceNow |
| Adopt | Team: resolved %, SLA %, CSAT | Freshservice |
| Adapt | Reviewer fatigue stays first-class (`approve_rate_per_reviewer`, `median_time_spent`) | Spec §11.1; vendors don't report rubber-stamping |
| Skip | `automation_rate` as a target | Spec §14 warning on ADR-0006 |

**ITIL 4:** Measurement and reporting, Service level management, Continual improvement.

## F11 Graph-based retrieval

| Product | Pattern |
|---|---|
| LightRAG (research) | LLM extracts entities and relations into a graph; **low-level** retrieval for specific entities, **high-level** for themes; incremental updates ([paper][lightrag]) |
| ServiceNow, JSM, Freshservice, SDP, Moveworks | *Not found* at stage 1 |

| Decision | What | Why |
|---|---|---|
| Adapt | Keep the problem-to-fix pointer graph (ADR-0018 `entity_graph`, ADR-0025); add a KB-side review of edges | Already shipped and measured; a LightRAG shared-entity graph measured worse (0.817 vs 0.900 recall@3, `TODO.md` item 12) |
| Skip | LightRAG's answer generation | Our generation must quote a retrieved chunk verbatim (spec §6.4) |

**ITIL 4:** Knowledge management.

## F12 ITSM / IAM integration, n8n

| Product | Pattern |
|---|---|
| Moveworks | Sits on top of an existing ITSM (ServiceNow, ManageEngine, SysAid…) and syncs tickets ([integrations][mw-me]) |
| Others | Are the ITSM; integration is out of their own scope |

| Decision | What | Why |
|---|---|---|
| Adapt | One connector interface; `itsm_mock` becomes its test double | Moveworks pattern, reversed: we are the triage layer |
| Adopt | n8n via the existing `trigger_n8n` action with callback | ADR-0028 already built it |
| Adapt | IAM actions (unlock, reset) only as runbooks through HITL | ADR-0006 |

**ITIL 4:** Service configuration management, Infrastructure and platform management.

## F13 Identity via Keycloak

| Product | Pattern |
|---|---|
| ServiceNow | Multi-provider SSO over OIDC or SAML, up to 10 IdPs; **auto-provisioning** into groups at sign-in; local login kept as a fallback ([multi-provider SSO][sn-sso]) |
| Keycloak | Federates LDAP/AD users; brokers other OIDC/SAML IdPs; realm and client roles; groups carry role mappings; **mappers** put roles and groups into tokens; brute-force lockout; login and admin events ([server admin guide][kc]) |
| JSM, Freshservice, SDP | SSO through their own admin products; *not detailed at stage 1* |

| Decision | What | Why |
|---|---|---|
| Adopt | OIDC authorization code + PKCE; Keycloak federates AD | Standard; Keycloak does the directory work |
| Adopt | JIT provisioning; roles, capabilities and groups from token claims | ServiceNow auto-provisioning; Keycloak mappers |
| Adopt | Brute-force lockout in Keycloak | Closes ADR-0029's "not done: lockout" |
| Adapt | Keycloak signs in; **core-api keeps issuing its own session** (ADR-0029) | Keeps one-query immediate revocation via `SessionAuth` |
| Adapt | Local login only for ≤ 2 break-glass accounts | ServiceNow fallback, narrowed |

**ITIL 4:** Information security management, Service desk.

---

## Sources

[itil]: https://itsm.tools/34-itil-4-management-practices/
[sn-sla-cond]: https://www.servicenow.com/docs/r/Mr7qUatbFXax1_h~z60rmA/G_mVso6Vk9nk4W7RfIKwkw
[sn-sla-dur]: https://www.servicenow.com/docs/r/it-service-management/service-level-management/c_SLADuration.html
[jsm-sla]: https://confluence.atlassian.com/servicemanagementserver0420/setting-up-slas-1095771691.html
[fs-sla]: https://support.freshservice.com/support/solutions/articles/156457-defining-your-default-sla-policy
[sdp-sla]: https://www.manageengine.com/products/service-desk/automation/sla-management.html
[mw-mmts]: https://docs.moveworks.com/platform/moveworks-classic/concierge/monday-morning-ticket-status
[vn-hol]: https://vietnamnet.vn/en/holiday-schedules-for-vn-culture-day-lunar-new-year-national-day-approved-2561288.html
[sn-awa]: https://www.servicenow.com/docs/r/conversational-interfaces/advanced-work-assignment/awa-overview.html
[jsm-assign]: https://confluence.atlassian.com/automation074/smart-assign-jira-issues-load-balancing-round-robin-and-more-1141481228.html
[fs-assign]: https://support.freshservice.com/support/solutions/articles/157134
[sdp-assign]: https://help.servicedeskplus.com/configurations/user-management/tech_auto_assign.html
[mw-triage]: https://docs.moveworks.com/service-management/triage
[mw-triage-setup]: https://docs.moveworks.com/service-management/triage/moveworks-setup-triage
[jsm-csat]: https://confluence.atlassian.com/servicemanagementserver/collecting-customer-satisfaction-csat-feedback-939926566.html
[fs-reopen]: https://support.freshservice.com/support/solutions/articles/50000000430-how-to-reopen-the-ticket-when-a-customer-feedback-is-received-
[mw-concierge]: https://docs.moveworks.com/service-management/concierge-assistant
[sn-notif]: https://www.servicenow.com/docs/r/zurich/platform-administration/advanced-notification-prefrences.html
[fs-notif]: https://support.freshservice.com/support/solutions/articles/156454-manage-email-notifications
[mw-comms]: https://docs.moveworks.com/ai-assistant/capabilities/employee-communications
[sn-sdh]: https://www.servicenow.com/docs/r/BfFhnVBqpVWNfzvxxnpNzw/4kpZKUxHLwexd14wxZj60w
[guard]: https://support.atlassian.com/security-and-access-policies/docs/what-sensitive-data-is-detected/
[fs-mask]: https://support.freshservice.com/support/solutions/articles/50000010727-freshservice-integration-with-credit-card-and-social-security-number-masker
[sdp-gdpr]: https://www.manageengine.com/products/service-desk/gdpr-service-desk-software.html
[sn-kb]: https://www.servicenow.com/docs/bundle/yokohama-servicenow-platform/page/product/knowledge-management/reference/r_KnowledgeWorkflows.html
[jsm-kb]: https://support.atlassian.com/jira-service-desk-cloud/docs/how-are-my-knowledge-base-articles-performing
[fs-kb]: https://support.freshservice.com/support/solutions/articles/50000001889-approvals-in-knowledge-base
[mw-gaps]: https://docs.moveworks.com/service-management/knowledge-studio/ai-powered-recommendations
[sn-mim]: https://www.servicenow.com/docs/r/it-service-management/incident-management/major-incident-management.html
[jsm-inc]: https://support.atlassian.com/jira-service-management-cloud/docs/manage-your-incidents/
[fs-mim]: https://support.freshservice.com/support/solutions/articles/50000006363-managing-a-major-incident
[sdp-ann]: https://help.servicedeskplus.com/problems/make_an_announcement.html
[sn-sir]: https://www.servicenow.com/docs/r/security-management/security-incident-response/what-is-sir.html
[sn-sla-dash]: https://www.servicenow.com/docs/r/QykF2iRSIs6VXztArCSo3w/Yeuf0nu1K2JS39UJK4~MZw
[fs-group]: https://msp.support.freshservice.com/support/solutions/articles/50000011307-agent-group-performance
[lightrag]: https://arxiv.org/html/2410.05779v3
[mw-me]: https://docs.moveworks.com/service-management/concierge-assistant/concierge-integrations/concierge-integration-manageengine
[sn-sso]: https://www.servicenow.com/docs/r/platform-security/authentication/c_MultipleProviderSingleSignOn.html
[kc]: https://www.keycloak.org/docs/26.7.3/server_admin/

| Ref | Source |
|---|---|
| itil | [ITIL 4 management practices — ITSM.tools](https://itsm.tools/34-itil-4-management-practices/) |
| sn-sla-cond · sn-sla-dur · sn-awa · sn-notif · sn-sdh · sn-kb · sn-mim · sn-sir · sn-sla-dash · sn-sso | [ServiceNow docs: SLA conditions](https://www.servicenow.com/docs/r/Mr7qUatbFXax1_h~z60rmA/G_mVso6Vk9nk4W7RfIKwkw) · [SLA duration](https://www.servicenow.com/docs/r/it-service-management/service-level-management/c_SLADuration.html) · [Advanced Work Assignment](https://www.servicenow.com/docs/r/conversational-interfaces/advanced-work-assignment/awa-overview.html) · [Notification preferences](https://www.servicenow.com/docs/r/zurich/platform-administration/advanced-notification-prefrences.html) · [Sensitive Data Handler](https://www.servicenow.com/docs/r/BfFhnVBqpVWNfzvxxnpNzw/4kpZKUxHLwexd14wxZj60w) · [Knowledge workflows](https://www.servicenow.com/docs/bundle/yokohama-servicenow-platform/page/product/knowledge-management/reference/r_KnowledgeWorkflows.html) · [Major incident management](https://www.servicenow.com/docs/r/it-service-management/incident-management/major-incident-management.html) · [Security Incident Response](https://www.servicenow.com/docs/r/security-management/security-incident-response/what-is-sir.html) · [Incident SLA dashboard](https://www.servicenow.com/docs/r/QykF2iRSIs6VXztArCSo3w/Yeuf0nu1K2JS39UJK4~MZw) · [Multi-provider SSO](https://www.servicenow.com/docs/r/platform-security/authentication/c_MultipleProviderSingleSignOn.html) |
| jsm-sla · jsm-assign · jsm-csat · jsm-kb · jsm-inc · guard | [JSM: Setting up SLAs](https://confluence.atlassian.com/servicemanagementserver0420/setting-up-slas-1095771691.html) · [Smart assign](https://confluence.atlassian.com/automation074/smart-assign-jira-issues-load-balancing-round-robin-and-more-1141481228.html) · [CSAT](https://confluence.atlassian.com/servicemanagementserver/collecting-customer-satisfaction-csat-feedback-939926566.html) · [KB reports](https://support.atlassian.com/jira-service-desk-cloud/docs/how-are-my-knowledge-base-articles-performing) · [Incidents](https://support.atlassian.com/jira-service-management-cloud/docs/manage-your-incidents/) · [Atlassian Guard detection](https://support.atlassian.com/security-and-access-policies/docs/what-sensitive-data-is-detected/) |
| fs-* | [Freshservice: Default SLA policy](https://support.freshservice.com/support/solutions/articles/156457-defining-your-default-sla-policy) · [Auto-assignment](https://support.freshservice.com/support/solutions/articles/157134) · [Reopen on feedback](https://support.freshservice.com/support/solutions/articles/50000000430-how-to-reopen-the-ticket-when-a-customer-feedback-is-received-) · [Email notifications](https://support.freshservice.com/support/solutions/articles/156454-manage-email-notifications) · [Card/SSN masker](https://support.freshservice.com/support/solutions/articles/50000010727-freshservice-integration-with-credit-card-and-social-security-number-masker) · [KB approvals](https://support.freshservice.com/support/solutions/articles/50000001889-approvals-in-knowledge-base) · [Major incident](https://support.freshservice.com/support/solutions/articles/50000006363-managing-a-major-incident) · [Group performance](https://msp.support.freshservice.com/support/solutions/articles/50000011307-agent-group-performance) |
| sdp-* | [SDP: SLA management](https://www.manageengine.com/products/service-desk/automation/sla-management.html) · [Technician auto-assign](https://help.servicedeskplus.com/configurations/user-management/tech_auto_assign.html) · [GDPR features](https://www.manageengine.com/products/service-desk/gdpr-service-desk-software.html) · [Announcements](https://help.servicedeskplus.com/problems/make_an_announcement.html) |
| mw-* | [Moveworks: Monday Morning Ticket Status](https://docs.moveworks.com/platform/moveworks-classic/concierge/monday-morning-ticket-status) · [Triage](https://docs.moveworks.com/service-management/triage) · [Triage setup](https://docs.moveworks.com/service-management/triage/moveworks-setup-triage) · [Concierge](https://docs.moveworks.com/service-management/concierge-assistant) · [Employee Communications](https://docs.moveworks.com/ai-assistant/capabilities/employee-communications) · [Knowledge recommendations](https://docs.moveworks.com/service-management/knowledge-studio/ai-powered-recommendations) · [ManageEngine integration](https://docs.moveworks.com/service-management/concierge-assistant/concierge-integrations/concierge-integration-manageengine) |
| vn-hol | [VietNamNet: holiday schedules approved](https://vietnamnet.vn/en/holiday-schedules-for-vn-culture-day-lunar-new-year-national-day-approved-2561288.html) |
| lightrag | [LightRAG paper (arXiv 2410.05779)](https://arxiv.org/html/2410.05779v3) |
| kc | [Keycloak Server Administration Guide](https://www.keycloak.org/docs/26.7.3/server_admin/) |
