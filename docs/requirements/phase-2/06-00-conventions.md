# 6.0 Conventions for every feature spec

Read this once. Each feature file (§6 F1, F2, …) follows it and doesn't repeat it.

## 6.0.1 IDs

| Kind | Pattern | Example |
|---|---|---|
| Use case | `UC-<feature>-NN` | `UC-F1-03` |
| Business rule | `BR-<feature>-NN` | `BR-F5-02` |
| Functional requirement | `FR-<feature>-NNN` | `FR-F2-014` |
| Acceptance scenario | `AC-<feature>-NN` | `AC-F13-07` |
| Cross-feature rule | `BR-X-NN` | `BR-X-03` |

IDs never get reused. A removed item keeps its ID with the note *withdrawn*.

## 6.0.2 Cross-feature rules

These hold for every feature in this pack. Each feature's §i lists which ones
it leans on.

| ID | Rule | Rationale | Enforced where |
|---|---|---|---|
| BR-X-01 | Business configuration (SLA policies, calendars, holidays, teams, notification matrix) is **data**, edited through the API and audited. System tunables (warning percent, sweep interval, windows, limits) live in `thresholds.yaml`. Endpoints, secrets and timeouts live in `.env.example` | ADR-0028 already splits it this way: workflows are data, `lifecycle.max_chain_depth` is a threshold. Hard rule 2 (CLAUDE.md) stays true | Code review; `test_settings_match_env_example` pattern for new settings |
| BR-X-02 | Every new endpoint uses `SessionAuth` **and** a role or capability check in core-api. The browser check is never the only check | §3.4 item 1 | PRE-1 route test |
| BR-X-03 | Every action that decides or changes something writes one `audit_log` row through `AuditLog.objects.record`, in the same transaction as the change | Spec §3.5; `audit_log` is append-only | Per-feature tests |
| BR-X-04 | New tables inherit `apps.core.models.BaseModel` (UUID key, ADR-0011) and are named with their app's prefix (`sla_`, `team_`, `notif_`, `chat_`) | ADR-0011; `TODO.md` item 7's direction | `test_every_model_has_a_uuid_primary_key` |
| BR-X-05 | No feature reads a `proposed_*` field to decide anything. Category comes from the router or a person's review decision | ADR-0001 | Code review; tests in each feature |
| BR-X-06 | Text a person types that is stored or sent (requester replies, reveal reasons, reassignment notes, rating comments) is masked with `mask_reply` before it is stored, like a clarification answer | Spec §5; ADR-0023 | Per-feature tests |
| BR-X-07 | A failure in a phase 2 feature never changes a routing decision and never blocks the pipeline. It is logged with its own code and shown to a person | ADR-0028 §2; "degrade toward humans" | Per-feature failure tests |
| BR-X-08 | Refusals use the lifecycle's error shape: `{"code": "...", "message": "...", "details": ...}` with a specific HTTP status, from a `StrEnum` per app | One shape for the frontends; `apps/lifecycle/utils/errors.py` already does this | Exception handler in `config/urls.py` |
| BR-X-09 | All stored times are UTC (`USE_TZ = True`). Business-time math converts to the calendar's zone and back | `config/settings/base.py` | F1 tests |

## 6.0.3 How each feature file is laid out

a. Problem & goal; benchmark notes ([benchmark.md](benchmark.md) has the sources)
b. Process flow (Mermaid), showing where it joins today's flow
c. State changes
d. Use cases (template below)
e. Business rules
f. Functional requirements
g. Data changes, with 2–3 realistic records
h. API changes, Celery tasks, webhook events
i. Impact on existing behavior and regression tests
j. Acceptance criteria (Gherkin)

**Use-case template**

| Field | Content |
|---|---|
| ID · Name | |
| Actor | |
| Trigger | |
| Preconditions | |
| Main flow | numbered steps |
| Alternate | `Na.` branches off step N |
| Exception | `Nx.` failures at step N |
| Postconditions | |
| Rules | BR ids |
| Screens | Figma frame names (links added in stage 5) |
| MoSCoW | |

## 6.0.4 Screens

Figma frames are named `<feature> · <screen>`, e.g. `F1 · SLA policies`. The
file and links come in stage 5. A screen marked **CHANGED** will have a
before and an after frame (`… / before`, `… / after`).

Existing admin-console pages: `queue`, `review/[id]`, `dashboard`, `kb`,
`login`. Existing chat page: one page with `Welcome`, `TurnView`, `Composer`
(`services/chat/components/`).

## 6.0.5 Mock data used across the pack

| Kind | Values |
|---|---|
| People | Nguyễn Thị Lan (`lan.nt`, employee, Finance); Trần Minh Đức (`duc.tm`, technician, Network lead); Võ Thu Hà (`ha.vt`, technician, Access lead); Bùi Ngọc Mai (`mai.bn`, technician, Access); Phạm Quốc Huy (`huy.pq`, manager); Lê Hoàng Anh (`anh.lh`, security); Đặng Văn Tú (`tu.dv`, technician + `workflow_admin`) |
| Tickets | `TKT-2026-000412` "Không vào được AWS access portal, báo sai mật khẩu" (access); `TKT-2026-000415` "VPN client báo lỗi TLS handshake failed khi kết nối từ nhà" (network); `TKT-2026-000418` "Laptop không nhận màn hình thứ hai sau update Windows" (hardware) |
| KB pages (demo_kb) | `identity-center.resetpassword-accessportal`, `client-vpn-user.windows-troubleshooting`, `workspaces-user.client_troubleshooting` |
| Masked text | `[EMAIL_1]`, `[PHONE_VN_1]`, `[EMPLOYEE_CODE_1]`, `[CCCD_1]` (labels from `apps/tickets/utils/patterns.py`) |
