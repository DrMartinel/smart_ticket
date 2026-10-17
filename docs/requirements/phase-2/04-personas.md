# 4. Personas and roles

## 4.1 Existing roles (REUSED)

`User.role` is one of four values (`apps/accounts/models.py`). Each user has
exactly one.

| Role | Persona | Today | Phase 2 adds |
|---|---|---|---|
| `employee` | **Nguyễn Thị Lan**, accountant, Finance, Hà Nội office. Writes in Vietnamese, pastes English error text. Uses the chat on her laptop | Asks in the chat or the form; sees one answer per question | My tickets, reply, reopen, rating, notifications (F3, F4) |
| `technician` | **Trần Minh Đức**, network technician. Works the review queue 8:00–17:30 | Claims and decides review items; moves tickets through the lifecycle | Team queue, assignment, SLA timers, reassign with reason (F1, F2) |
| `manager` | **Phạm Quốc Huy**, IT Service Desk Manager | Sole holder of KB auto-reply authority and risk tier (ADR-0002); configures workflows (`apps/lifecycle/views.py`) | Approves SLA policies, threshold changes, phase gates; reports (F1, F9, F10) |
| `security` | **Lê Hoàng Anh**, Information Security Officer | Role exists; no screen of its own | Security inbox, PII reveal review (F5, F8) |

## 4.2 New responsibilities, and how to model them

Your brief names three candidates: team lead, workflow admin, KB editor. The
system adds one more: incident manager. Each is needed, for the reason in the
table.

**Recommendation: don't add them as new values of `User.role`.** One role per
user can't express "a technician who also leads the Access team and edits KB
drafts". Add two things instead (proposed ADR-0031, §9):

1. **Team scope (F2):** `team_lead` is a role *inside a team membership*, not a
   global role. Đức can lead Network and be a plain member of Hardware.
2. **Capabilities:** a short, fixed list of extra rights on top of the primary
   role, granted from Keycloak client roles (F13).

| Responsibility | Modeled as | Persona | Why it's needed | What it may do | What it may **not** do |
|---|---|---|---|---|---|
| Team lead | Membership role `lead` in a team (F2) | **Võ Thu Hà**, lead of the Access team | Workload and reassignment are per team. A manager over all teams is too far away to rebalance one queue every hour | See the team queue and workload; reassign within or out of the team with a reason; receive breach escalations for the team | Change SLA policies; approve KB authority; reveal PII |
| Workflow admin | Capability `workflow_admin` | **Đặng Văn Tú**, ITSM process owner | SLA policies, calendars, holidays, workflows and the notification matrix are process configuration. Today only `manager` can configure the lifecycle, which mixes "configures" with "approves" | Draft and edit SLA policies, business calendars, holidays, workflows, notification matrix; draft threshold change requests (F9) | Approve their own change; approve KB authority; flip shadow mode |
| KB editor | Capability `kb_editor` | **Bùi Ngọc Mai**, senior technician who writes KB pages | Today `POST /api/kb` publishes live with no review (and no role check). Authoring and authority must be separate people (ADR-0002) | Create and edit KB drafts; submit for review; propose a risk tier | Publish without review; set `auto_reply_allowed`; set the final risk tier |
| Incident manager | Capability `incident_manager` | **Trần Minh Đức** during on-call weeks | Broadcasting to hundreds of requesters and closing all linked tickets is a high-blast action. It needs a named person, not any technician | Confirm or declare an incident; set and update ETA; broadcast; resolve and close linked tickets | Bypass a review item; auto-reply to linked tickets |

A requester is still `employee`. No external customer role (Won't).

## 4.3 Worked example: one person, before → after

Đức signs in. Keycloak sends core-api an ID token. core-api maps it to its own
user and session (ADR-0029 stays the session owner).

**Keycloak token claims (input):**

```json
{
  "sub": "8c1e6a0e-3f0d-4c51-9b7a-5f2d0c9a41b7",
  "preferred_username": "duc.tm",
  "email": "duc.tm@congty.vn",
  "name": "Trần Minh Đức",
  "resource_access": {
    "smart-ticket": { "roles": ["technician", "incident_manager"] }
  },
  "groups": ["/it/network/lead", "/it/hardware"]
}
```

**`accounts_user` row, before (today, made by hand):**

| username | role | email |
|---|---|---|
| `tech1` | `technician` | *(empty)* |

**After F13 + F2 (rows core-api writes):**

`accounts_user`

| username | role | email | external_id |
|---|---|---|---|
| `duc.tm` | `technician` | `duc.tm@congty.vn` | `8c1e6a0e-…41b7` |

`accounts_user_capabilities` (NEW)

| user | capability | granted_by |
|---|---|---|
| `duc.tm` | `incident_manager` | `keycloak` |

`team_memberships` (NEW, F2)

| user | team | role |
|---|---|---|
| `duc.tm` | Network | `lead` |
| `duc.tm` | Hardware | `member` |

**What the session can do:** everything `technician` can, plus incident
actions, plus lead actions only inside Network.

## 4.4 General rule

One primary role says *who you are* (employee, technician, manager, security).
Capabilities say *which extra jobs you hold*. Team membership says *where* your
lead rights apply. All three come from Keycloak and are re-read at each sign-in,
so removing a group in the directory removes the right at the next sign-in, and
deactivation ends every session at once (ADR-0029 decision 5).
