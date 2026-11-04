# ADR-0044: thresholds.yaml changes by pull request; no approval check

**Status:** Accepted (2026-11-04), the owner's decision. **Relaxes a guardrail.**
**Date:** 2026-11-04
**Supersedes:** ADR-0035 §1 (the third key, "loaded thresholds are approved"), §4 and §5; ADR-0043 §4; BR-F9-05, BR-F9-06, BR-F9-07, BR-F9-08, FR-F9-008, FR-F9-010, AC-F9-05, AC-F9-09, AC-F9-10
**Builds on:** ADR-0035, ADR-0043; CLAUDE.md hard rule 2

## Context

After ADR-0043 a threshold change was a change request the manager who
wrote it approved, then the same text shipped by PR under the request's id.
At boot core-api hashed the loaded file; a file matching no approved
request kept every branch in shadow and raised a security alert. CI failed
a change to the file that kept its old `version`.

With one approver, the change request only repeated what the pull request
already records: who changed which number, and when. The dev database and
the file drifted apart (the file reached CR-2026-004 with only
CR-2026-000 and 001 in the table), and local dev and CI ran with the check
off. The owner finds it redundant.

## Decision

1. **A branch is live when `SHADOW_MODE` is false and its flag is on.**
   Two keys; the thresholds file is not one of them.
2. **`thresholds.yaml` changes by pull request**, reviewed like code. Its
   `version` names the file in every decision's `thresholds_used` and
   `rollout_snapshot`; give a changed file a new one.
3. **Removed:** threshold change requests (`threshold_change_requests`,
   dropped by `rollout.0004`), the boot hash check, the
   `thresholds_unapproved` security alert and notification
   (`notifications.0006`), the `THRESHOLDS_REQUIRE_APPROVAL` setting, and
   CI's `thresholds-version` job.
4. **Kept:** the file is still parsed into `Thresholds` at boot, so a
   malformed file still stops core-api. Admin → Thresholds shows the
   loaded file, its version and SHA-256, read-only
   (`GET /api/thresholds/current`).

## Consequences

- **A file edited on a production host acts live** on any branch whose flag
  is on; before, it degraded to shadow. Deploys are the control now.
- Nothing checks that `version` changes with the file. A decision's
  `thresholds_used` still holds the full numbers, so replay is unaffected,
  but two different files can share a version string.
- Calibration is unchanged: trust coefficients and `t_auto` / `t_route` are
  hand-set placeholders, and the reason P3/P4 wait.
- The rows of earlier change requests are gone from the database; the
  versions they named stay in old decisions' snapshots.
