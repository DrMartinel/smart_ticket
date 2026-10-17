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
| Version | **0.4 — Stage 4 draft** (adds F11, F12, §7 cross-cutting, §8 traceability, proposed ADRs 0037–0038) |
| Status | Draft, awaiting stage 4 review |
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
| — | Figma mockups | 5 | Not started |
| 9 | [Risks, assumptions, open questions, proposed ADRs](09-risks-open-questions.md) | 6 | Updated at stage 4 |
| 10 | Release plan | 6 | Not started |

Existing vocabulary is in [`docs/glossary.md`](../../glossary.md). §5 adds only new terms.
