# Figma mockups — frame index

**File:** [Smart Ticket — Phase 2 mockups](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL) (Figma, Starter team; editable layers, no images).
Stage 5 of the pack. Every `Screens` reference in §6 links to the frame below.

## Pages

| Page | What is on it |
|---|---|
| [00 Design system](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=0-1) | Color variables (admin console and chat tokens from both `globals.css`, badge tones from `lib/badges.ts`), space/radius variables, 8 text styles, 2 effect styles; components `Badge` (8 tones), `Button` (Primary, Secondary, Danger, Chat), `Admin/NavLink`, `Admin/NavBar` (Current / Phase 2), `Chat/Header` (Current / Phase 2), `Field`, `Spec note`; the [Badge mapping](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=5-17) for branch, risk tier, priority, category, SLA, PII level, ticket status, requester status |
| [01 Screens](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=1-2) | One section per feature, plus two sections for existing pages changed by several features. Under each frame a yellow **Spec note**: NEW/CHANGED, use cases, rules, what to look at |
| [02 Flows](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=1-3) | One flow per feature: numbered steps with actor and screen; each screen name links to its frame |

## How to read a frame

- Mock "now" is **Mon 26 Oct 2026 09:30 (+07)** unless the frame says otherwise; data follows §6.0.5 (people, tickets `TKT-2026-000412/415/418`, KB pages from `demo_kb`, masked placeholders like `[EMAIL_1]`, `[PHONE_VN_1]`, `[CCCD_1]`).
- Admin frames are 1280 wide (content 1152, as `max-w-6xl`); chat frames are 1024 wide with a 736 column (`max-w-3xl`). Dialogs are drawn alone, 560 wide.
- Status, SLA, priority, category, PII level, risk tier and branch always use the `Badge` component with text; color is never the only cue (WCAG 2.2 AA, §7).
- Font: the apps use the system UI stack; the mockups use Inter as its stand-in.

## Frames

| Frame | Feature | Kind |
|---|---|---|
| [F1 · Breach list](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-685) | [F1](06-F1-sla.md) | NEW |
| [F1 · Business calendars](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-283) | [F1](06-F1-sla.md) | NEW |
| [F1 · Holidays](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-435) | [F1](06-F1-sla.md) | NEW |
| [F1 · Priority dialog](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-677) | [F1](06-F1-sla.md) | NEW |
| [F1 · SLA badge](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-604) | [F1](06-F1-sla.md) | NEW |
| [F1 · SLA policies](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=8-57) | [F1](06-F1-sla.md) | NEW |
| [F2 · My availability](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-603) | [F2](06-F2-teams-assignment.md) | NEW |
| [F2 · Reassign dialog](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-442) | [F2](06-F2-teams-assignment.md) | NEW |
| [F2 · Team queue](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-237) | [F2](06-F2-teams-assignment.md) | NEW |
| [F2 · Team workload](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-450) | [F2](06-F2-teams-assignment.md) | NEW |
| [F2 · Teams](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=9-646) | [F2](06-F2-teams-assignment.md) | NEW |
| [F3 · Answer card / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-500) | [F3](06-F3-requester-chat.md) | CHANGED · after |
| [F3 · Answer card / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-488) | [F3](06-F3-requester-chat.md) | CHANGED · before |
| [F3 · Chat conversation / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-426) | [F3](06-F3-requester-chat.md) | CHANGED · after |
| [F3 · Chat conversation / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-383) | [F3](06-F3-requester-chat.md) | CHANGED · before |
| [F3 · Comment box](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-665) | [F3](06-F3-requester-chat.md) | NEW |
| [F3 · My tickets](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-517) | [F3](06-F3-requester-chat.md) | NEW |
| [F3 · Rating](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-623) | [F3](06-F3-requester-chat.md) | NEW |
| [F3 · Ticket thread](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=10-580) | [F3](06-F3-requester-chat.md) | NEW |
| [F4 · Delivery log](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-890) | [F4](06-F4-notifications.md) | NEW |
| [F4 · My notification settings](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-564) | [F4](06-F4-notifications.md) | NEW |
| [F4 · Notification bell](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-480) | [F4](06-F4-notifications.md) | CHANGED (NavBar, chat header) |
| [F4 · Notification matrix](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-710) | [F4](06-F4-notifications.md) | NEW |
| [F4 · Notification panel](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-531) | [F4](06-F4-notifications.md) | NEW |
| [F4 · Webhook subscriptions](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=11-1047) | [F4](06-F4-notifications.md) | NEW |
| [F5 · Access log](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=12-734) | [F5](06-F5-pii-reveal.md) | NEW |
| [F5 · Reveal dialog](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=12-677) | [F5](06-F5-pii-reveal.md) | NEW |
| [F6 · Authority log](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1180) | [F6](06-F6-kb-governance.md) | NEW |
| [F6 · Authority queue](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1049) | [F6](06-F6-kb-governance.md) | NEW |
| [F6 · Draft review](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-981) | [F6](06-F6-kb-governance.md) | NEW |
| [F6 · KB drafts](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-828) | [F6](06-F6-kb-governance.md) | NEW |
| [F6 · KB editor](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-737) | [F6](06-F6-kb-governance.md) | NEW |
| [F6 · KB gaps](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=13-1299) | [F6](06-F6-kb-governance.md) | NEW |
| [F7 · Declare incident](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1298) | [F7](06-F7-mass-incident.md) | NEW |
| [F7 · Incident banner](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1332) | [F7](06-F7-mass-incident.md) | NEW |
| [F7 · Incident list](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-952) | [F7](06-F7-mass-incident.md) | NEW |
| [F7 · Incident page](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1090) | [F7](06-F7-mass-incident.md) | NEW |
| [F7 · Resolve dialog](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=14-1324) | [F7](06-F7-mass-incident.md) | NEW |
| [F8 · Alert detail](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1265) | [F8](06-F8-security-inbox.md) | NEW |
| [F8 · Security inbox](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=15-1087) | [F8](06-F8-security-inbox.md) | NEW |
| [F9 · Flag request](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1328) | [F9](06-F9-rollout-control.md) | NEW |
| [F9 · Rollout](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1179) | [F9](06-F9-rollout-control.md) | NEW |
| [F9 · Threshold change request](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1336) | [F9](06-F9-rollout-control.md) | NEW |
| [F9 · Threshold history](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=16-1436) | [F9](06-F9-rollout-control.md) | NEW |
| [F10 · CSAT report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1916) | [F10](06-F10-reporting.md) | NEW |
| [F10 · Dashboard / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=19-2015) | [F10](06-F10-reporting.md) | CHANGED · after |
| [F10 · Dashboard / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=19-1930) | [F10](06-F10-reporting.md) | CHANGED · before |
| [F10 · Incident report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2311) | [F10](06-F10-reporting.md) | NEW |
| [F10 · KB report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1765) | [F10](06-F10-reporting.md) | NEW |
| [F10 · Reviewer report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1631) | [F10](06-F10-reporting.md) | NEW |
| [F10 · Rollout readiness](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2028) | [F10](06-F10-reporting.md) | NEW |
| [F10 · SLA report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1291) | [F10](06-F10-reporting.md) | NEW |
| [F10 · Security report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-2164) | [F10](06-F10-reporting.md) | NEW |
| [F10 · Team report](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1399) | [F10](06-F10-reporting.md) | NEW |
| [F11 · Graph health](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=17-1912) | [F11](06-F11-graph-retrieval.md) | NEW (card inside F10 · KB report) |
| [F11 · Page graph](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-1874) | [F11](06-F11-graph-retrieval.md) | CHANGED (tab on KB editor) |
| [F12 · Runbook approval / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2041) | [F12](06-F12-itsm-iam-integration.md) | CHANGED · after |
| [F12 · Runbook approval / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2006) | [F12](06-F12-itsm-iam-integration.md) | CHANGED · before |
| [F12 · Runbook catalog](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2142) | [F12](06-F12-itsm-iam-integration.md) | NEW |
| [F13 · Break-glass sign-in](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2341) | [F13](06-F13-identity.md) | NEW |
| [F13 · Sign-in / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2307) | [F13](06-F13-identity.md) | CHANGED · after |
| [F13 · Sign-in / after (chat)](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2317) | [F13](06-F13-identity.md) | CHANGED · after |
| [F13 · Sign-in / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2290) | [F13](06-F13-identity.md) | CHANGED · before |
| [F13 · Sign-in error](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=20-2328) | [F13](06-F13-identity.md) | NEW |
| [Knowledge Base / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=19-1816) | F6, F11 | CHANGED · after |
| [Knowledge Base / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=19-1740) | F6, F11 | CHANGED · before |
| [Queue / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=18-1663) | F1, F2, F7, F8 | CHANGED · after |
| [Queue / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=18-1593) | F1, F2, F7, F8 | CHANGED · before |
| [Review item / after](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=18-1866) | F1, F2, F3, F5 | CHANGED · after |
| [Review item / before](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=18-1767) | F1, F2, F3, F5 | CHANGED · before |

## Flows

[F1](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-60) · [F2](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-135) · [F3](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-194) · [F4](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-253) · [F5](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-312) · [F6](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-355) · [F7](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-414) · [F8](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-473) · [F9](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-516) · [F10](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-567) · [F11](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-626) · [F12](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-669) · [F13](https://www.figma.com/design/KXpnlC78p9pHYRuZZuQxIL?node-id=21-712)

## Decisions made while drawing

Recorded as assumptions A-16…A-21 in [§9](09-risks-open-questions.md#92-assumptions).

| Decision | Where |
|---|---|
| The SLA badge shows the response clock until it is met, then the resolution clock; tooltip shows both | `F1 · SLA badge` |
| Admin console top nav gains Reports, Incidents, Security, Settings (each shown by role, §7 RBAC). Settings holds SLA policies, calendars, holidays, teams, notifications, webhooks, runbooks, rollout, thresholds. Queue gains tabs Review queue, Team queue, My tickets, SLA at risk | `Admin/NavBar` Phase 2, `Queue / after` |
| The migrated fallback team for category `other` is shown as "Service Desk" | `F2 · Teams` |
| The chat header gains My tickets and the bell; requester-facing labels are Vietnamese first, English second | `Chat/Header` Phase 2, `F3 · My tickets` |
| Dashboard keeps today's Ops tiles; adds a Service row (SLA, at-risk, incidents, security counts, unassigned) | `F10 · Dashboard / after` |
| One combined before/after pair for an existing page changed by several features | `Queue / …`, `Review item / …`, `Knowledge Base / …` |
