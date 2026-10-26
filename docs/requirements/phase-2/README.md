# Phase 2 requirements pack — Smart Ticket

New features on top of the system that exists today. This pack says what to
build next. It does not re-document the current code: where a feature touches
existing behavior, it links the file, the spec section (`requirement.md` §) or
the ADR.

Every item is tagged:

| Tag | Meaning |
|---|---|
| **NEW** | Does not exist today |
| **CHANGED** | Exists today and behaves differently after this phase. Shown as *before → after* |
| **REUSED** | Exists today, used as is, referenced only |

---

## 0. Document control

### 0.1 Version

| Field | Value |
|---|---|
| Document | Phase 2 requirements pack |
| Version | **0.6 — Stage 6 draft, complete** (adds §10 release plan, completes §9, tags every acceptance scenario with its rules). Next: 1.0 at sign-off |
| Status | Complete draft, awaiting sign-off by the approvers in §0.2 |
| Date | 2026-10-17 |
| Baseline commit | `main` @ `7ac264b` |
| Owner | Product owner (Hoàng) |
| Spec it extends | `requirement.md` (Architecture Specification v2) |

### 0.2 Approvers

The pack is for a real IT organization. Approvers are named by role here. Names
go in at sign-off.

| Role | Approves | Must sign before |
|---|---|---|
| Product owner | Whole pack, scope, MoSCoW | Every stage |
| IT Service Desk Manager | F1, F2, F3, F7, F10, KPIs | Stage 2 build |
| Information Security Officer | F5, F8, F13, RBAC matrix (§7), every proposed ADR that relaxes a guardrail | Stage 2 build |
| Head of IT Operations | F9 (rollout control), release plan (§10) | P3 switch |
| Tech lead, core-api | Data and API changes (§6g, §6h), proposed ADRs | Each feature's build |
| Data Protection Officer [ASSUMPTION: the org has one] | F5, F13, notification content (F4) | F5 and F13 build |

### 0.3 Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-17 | BA (Claude) for the product owner | Stage 1: §0–§5, benchmark, seeded §9 |
| 0.2 | 2026-10-17 | BA (Claude) for the product owner | Stage 2: OQ-01…14 defaults accepted; §6 for PRE-1/PRE-2, F1–F5, F13; proposed ADRs 0030–0034; fixes to benchmark F2/F4, glossary, K8. OQ-17 (no pause on vendor waits) and OQ-18 (one shared calendar) decided |
| 0.3 | 2026-10-17 | BA (Claude) for the product owner | Stage 3: §6 for F6–F10; proposed ADRs 0035, 0036; BR-F1-15; F4 catalog extended; OQ-15, OQ-16 decided; OQ-19…23 added |
| 0.4 | 2026-10-17 | BA (Claude) for the product owner | Stage 4: F11, F12 (lighter spec), §7 RBAC/notification/audit/NFR, §8 generated traceability, proposed ADRs 0037, 0038; OQ-19…23 decided; OQ-24…27 added |
| 0.5 | 2026-10-17 | BA (Claude) for the product owner | Stage 5: Figma mockups ([file](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL)); every `Screens` reference links its frame ([mockups.md](mockups.md)); OQ-24…27 decided; F2 reassignment example fixed (a member can't move a ticket out of the team, so the lead does it) |
| 0.6.8 | 2026-10-26 | Claude for the product owner (wave 4 build) | F8: a true positive approves the block without handing off; `break_glass_in_keycloak` and `reveal_failed` kinds; one audit row per raise; refused calls counted from their own table; end-sessions action; security-queue items refused to non-security; backfill pages nobody. Details in F8 "v0.6.8" |
| 0.6.7 | 2026-10-26 | Claude for the product owner (wave 3 build) | F3: ADR-0034 accepted; held comments reviewed as show or discard; `status_changed` only into the wait; `answer_excerpt_chars`, `low_rating_at_most`; only decided turns are context; one active conversation; reply resumes `in_progress` after a pipeline status; refused auto-close audited once; reopen back to the eligible assignee; chat links via `NOTIFICATION_CHAT_BASE_URL`; multi-turn cases pending review. Details in F3 "v0.6.7" |
| 0.6.6 | 2026-10-26 | Claude for the product owner (wave 2 build) | F1: ADR-0030 accepted; `escalate_at`, `sla_rebuilds`, replacement drafts for active policies; leave zone from calendars (`ASSIGNMENT_TIMEZONE` removed); responses today are manual moves and review decisions; `set_sla` in business hours; badge on staff rows; notices keyed to survive rebuilds. Details in F1 "v0.6.6" |
| 0.6.5 | 2026-10-26 | Claude for the product owner (wave 2 build) | F2: leave zone from `ASSIGNMENT_TIMEZONE` until F1; open count includes on hold; duplicates inherit at handoff; old assign endpoint retired; one reroute label per decision; approval category rule; `move_categories`; extra team endpoints and refusals. Details in F2 "v0.6.5" |
| 0.6.4 | 2026-10-26 | Claude for the product owner (wave 1 build) | F4: webhook secrets under `NOTIFICATION_SECRET_KEY`; assignment events active before F2; `security.alert` wired at F5/F13 sites (not the routing step); emit never raises; language endpoint; deletes and failures listed. Details in F4 "v0.6.4" |
| 0.6.3 | 2026-10-25 | Claude for the product owner (review fixes) | F13: every failed local sign-in is the same 401 (owner's decision); failures counted in a window; break-glass never linked or synced; `exp` required; Keycloak refetch limits; sync robustness. F5: refused reveals audited and counted; unknown labels critical. Details in each feature's v0.6.x section |
| 0.6.2 | 2026-10-17 | Claude for the product owner (wave 0 build) | F5: claim state `claimed` not `pending`; append-only by trigger (AC-F5-09 message); `access_log_failed`; assignee works without F2; reveal on `tickets/[id]` with `pii_placeholders` on the detail. Code wins (§0.4 item 5); details in F5 "v0.6.2" |
| 0.6.1 | 2026-10-17 | Claude for the product owner (wave 0 build) | PRE-1 §h: rows added for `POST /api/tickets/submit`, the staff ticket views, logout-everywhere; lifecycle refusals take the shared error shape. Code wins (§0.4 item 5) |
| 0.6 | 2026-10-17 | BA (Claude) for the product owner | Stage 6: §10 release plan (waves on a calendar, rollout phases P2–P5, cut-overs, rollback); §9 complete (OQ-28 default applied, A-22, A-23, R-17…R-20); every Gherkin scenario tagged `@BR-…`, 25 scenarios added so every rule has one; §8.4 rule → scenario table generated. Product owner asked for all remaining stages on defaults without a stage review |

### 0.4 Change control

1. **Every change is a pull request** to `docs/requirements/phase-2/`. No edits on `main`.
2. **Version numbers:**
   - Patch (0.1 → 0.1.1): wording, typo, a broken link. Owner approves.
   - Minor (0.1 → 0.2): a stage added, a requirement added or changed. Owner plus the approvers of the touched features.
   - Major (0.x → 1.0): sign-off for build. All approvers in §0.2.
3. **After 1.0, a change request (CR)** is needed for any change to a Must
   feature, a KPI target, or the RBAC matrix. A CR row goes in §0.3 with the
   CR id (`CR-001`), the reason, the affected FR/BR ids, and the approvers.
4. **A requirement that would contradict an accepted ADR is not edited in.** It
   becomes a proposed ADR in §9. The feature waits for that ADR.
5. **Code wins over docs.** If this pack and the code disagree on how something
   works today, the code is right and this pack is fixed (patch version).

---

## Contents

| § | File | Stage | State |
|---|---|---|---|
| 0 | This file | 1 | Draft |
| 1 | [Executive summary](01-executive-summary.md) | 1 | Draft |
| 2 | [Scope, dependencies, build order](02-scope.md) | 1 | Draft — feature list confirmed 2026-10-17 |
| 3 | [Baseline summary](03-baseline.md) | 1 | Draft |
| 4 | [Personas and roles](04-personas.md) | 1 | Draft |
| 5 | [Glossary (new terms only)](05-glossary.md) | 1 | Draft |
| — | [Benchmark: F1–F13 against five products](benchmark.md) | 1 | Draft |
| 6.0 | [Conventions, cross-feature rules, mock data](06-00-conventions.md) | 2 | Draft |
| 6 | [PRE-1 role enforcement, PRE-2 ADR acceptance](06-PRE-prerequisites.md) | 2 | Draft |
| 6 | [F1 SLA & business hours](06-F1-sla.md) | 2 | Draft |
| 6 | [F2 Teams, assignment & workload](06-F2-teams-assignment.md) | 2 | Draft |
| 6 | [F3 Requester experience in chat](06-F3-requester-chat.md) | 2 | Draft |
| 6 | [F4 Notifications](06-F4-notifications.md) | 2 | Draft |
| 6 | [F5 PII quarantine reveal](06-F5-pii-reveal.md) | 2 | Draft |
| 6 | [F13 Identity via Keycloak](06-F13-identity.md) | 2 | Draft |
| 6 | [F6 KB authoring & governance](06-F6-kb-governance.md) | 3 | Draft |
| 6 | [F7 Mass-incident management](06-F7-mass-incident.md) | 3 | Draft |
| 6 | [F8 Security inbox](06-F8-security-inbox.md) | 3 | Draft |
| 6 | [F9 Rollout & threshold control](06-F9-rollout-control.md) | 3 | Draft |
| 6 | [F10 Reporting](06-F10-reporting.md) | 3 | Draft |
| 6 | [F11 Graph-based retrieval as a KB feature](06-F11-graph-retrieval.md) | 4 | Draft |
| 6 | [F12 ITSM / IAM integration, n8n](06-F12-itsm-iam-integration.md) | 4 | Draft |
| — | [Proposed ADRs 0030–0038](proposed-adrs/) | 2–4 | Draft |
| 7 | [Cross-cutting: RBAC, notifications, audit, NFRs](07-cross-cutting.md) | 4 | Draft |
| 8 | [Traceability](08-traceability.md) (generated by [`tools/build_traceability.py`](tools/build_traceability.py)) | 4 | Draft |
| — | [Figma mockups: frame index and links](mockups.md) | 5 | Draft |
| 9 | [Risks, assumptions, open questions, proposed ADRs](09-risks-open-questions.md) | 6 | Complete |
| 10 | [Release plan](10-release-plan.md) | 6 | Draft |

Existing vocabulary is in [`docs/glossary.md`](../../glossary.md). §5 adds only new terms.
