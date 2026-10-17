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
| Version | **0.1 — Stage 1 draft** (baseline, scope, benchmark, personas) |
| Status | Draft, awaiting stage 1 review |
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
| 2 | [Scope, dependencies, build order](02-scope.md) | 1 | Draft — **feature list awaits your confirmation** |
| 3 | [Baseline summary](03-baseline.md) | 1 | Draft |
| 4 | [Personas and roles](04-personas.md) | 1 | Draft |
| 5 | [Glossary (new terms only)](05-glossary.md) | 1 | Draft |
| — | [Benchmark: F1–F13 against five products](benchmark.md) | 1 | Draft |
| 6 | Per-feature specs: F1–F5 | 2 | Not started |
| 6 | Per-feature specs: F6–F10 | 3 | Not started |
| 6 | Per-feature specs: F11–F13 | 4 | Not started |
| 7 | Cross-cutting: RBAC, notifications, audit, NFRs | 4 | Not started |
| 8 | Traceability | 4 | Not started |
| — | Figma mockups | 5 | Not started |
| 9 | [Risks, assumptions, open questions, proposed ADRs](09-risks-open-questions.md) | 6 | **Seeded** with stage 1 findings |
| 10 | Release plan | 6 | Not started |

Existing vocabulary is in [`docs/glossary.md`](../../glossary.md). §5 adds only new terms.
