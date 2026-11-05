# UX report: case-file renovation

Branch `ux-renovation`. Design direction in [DESIGN_BRIEF.md](DESIGN_BRIEF.md).
Screenshots at 375px and 1440px: [`ux-screenshots/before/`](ux-screenshots/before/) (main) and
[`ux-screenshots/after/`](ux-screenshots/after/) (this branch), same file names.

## 1. Summary

- **One visual system across both apps.** It's called "Case file": warm paper, Forest green (the existing brand colour), IBM Plex Serif titles, Plex Sans body text and Plex Mono for data. Borders are used instead of shadows. The tokens are in `globals.css`, identical in the console and chat.
- **The product's core idea is now visible.** The AI's proposal sits in a dashed ochre block and the routing decision in a solid green block, so reviewers can tell at a glance what the model suggested and what the rules decided.
- **Mobile works.** At 375px the console's fixed 240px sidebar made every page 646px wide. It is now a drawer behind a menu button. Every screenshot at 375px has `scrollWidth == 375`.
- **One header, one loading, empty and error pattern on every screen.** `PageHeader`, `LoadingState`/`Skeleton`, `EmptyState` (it says what to do next) and `ErrorState` (with a retry button) replace about 60 ad-hoc variants.
- **One UI language.** The labels used to be a mix of Vietnamese, English and "Vi · En" pairs. The UI is now English, with the Vietnamese section name as a small secondary label. Content that the user's language setting drives (guides, tours) is unchanged.
- **Feedback for every action.** Toasts confirm actions that used to update silently, and destructive actions (end sessions, withdraw draft, dismiss or unlink an incident) now ask for confirmation.
- **Forms.** Labels are tied to their fields, required fields are marked, errors appear inline, every dialog has a Cancel button, and sign-in fields have `autocomplete`.
- **Accessibility.** A skip link, a visible `:focus-visible` ring, `aria-current` on navigation, `role=status`/`role=alert` on states, 44px touch targets on coarse pointers, colours checked at ≥ 5:1 contrast in light and dark, and `prefers-reduced-motion` respected.
- **No business logic, API, contract, model, auth or route changes.** No dependencies were added.

## 2. Per flow: what was confusing, what I did

| Flow | What was confusing | What I did |
|---|---|---|
| **Shell and navigation** (console) | The fixed sidebar broke every phone layout. Labels were half Vietnamese. There were no icons, and the active item was hard to see. | A drawer below 1024px. Icons, an active bar, mono counts and a warn pill for Needs review. An account block with initials. A skip link. All `data-tour` anchors are kept. |
| **Ticket list** | The empty state was one line of grey text. The table didn't fit on a phone. Search had no affordance. | The header shows the view name and count. Search has an icon. Each view has its own empty state (what will appear and when). There is a stacked card list below `md`, and a retry button on errors. |
| **Ticket record** | The AI's output and the rules' decision looked the same. Status messages appeared in a banner far from the action. | A back link, a title with mono facts, and the `Decision` and `Proposal` blocks. Skeleton loading. Toasts beside the action. The SLA badge reads "At risk · 45m left" instead of a Vietnamese abbreviation. |
| **Board / SLA / Incidents** | The board was drag-only with no hint. Incident forms had no required marks and no Cancel. Dismiss and unlink happened on a single click. | Shared headers and states, a mobile hint, `Labeled` fields with validation, confirmation before destructive steps, and a proposal banner on proposed incidents. |
| **Teams (queue, workload)** | Two pages with no link between them, and taking a ticket gave no feedback. | Queue / Workload tabs. "Take" shows a toast with an Open action. |
| **Knowledge (pages, drafts, graph, gaps)** | Mixed languages, and a reason field with no label. Withdrawing a draft wasn't confirmed. | PageHeader, search, loading and error states, an empty state for "no match". The reason input is labelled and its submit button names the action. Withdraw asks for confirmation. |
| **Security (alerts, access log)** | The alert title was a raw enum. Ending sessions happened on one click. | A readable title, a confirmation dialog for ending sessions, and shared empty states. |
| **Admin settings** (people, teams, SLA, workflows, notifications, webhooks, runbooks, thresholds, rollout) | Twenty pages, each with its own header, error paragraph and "No rows" text. SLA policies and calendars showed nothing while loading. | Generated with one transformer, then corrected by hand: PageHeader with an "Admin / …" eyebrow, `TableStatus` for loading and empty rows, `ErrorState`, and loading/empty states for SLA policies, calendars and workflows. |
| **Dashboard / reports** | Headings used several styles, and the empty reviewer table was a bare paragraph. | Eyebrow headings, skeleton stats, `EmptyState`. |
| **Sign-in** (both apps) | A small card with bilingual button text. On a sign-in error, the error code was the most prominent text. | A two-column layout in the console that explains proposal vs decision. Plain-English button text. Error screens show the meaning first, the Vietnamese line second and the code last. |
| **Chat: ask** | The header's nav text changed its meaning by page ("Hỏi đáp · Chat" on one, "My tickets" on the other). The banner mixed languages. A failed send showed only red text. | Ask and My tickets as tabs, with icons that fit at 375px. A conversation strip with a "New conversation" button. Suggestions are a bordered list with 44px rows. A failed send shows an `ErrorState` with retry. The source is labelled "approved help page". "Did that fix it?" is now an explicit question. |
| **Chat: my tickets and thread** | The loading state was "…". The empty state was "Chưa có · None yet." Errors other than 404 left the page blank. | Skeleton loading, an empty state with an "Ask a question" button, an error state with retry, `StatusChip` and unread pills, a back link, and a thread that distinguishes your replies from the team's. Rating stars are 44px targets. The Reopen and rating panels are in English. |
| **Chat: notifications** | Vietnamese only, no loading state, an error line with no retry. | English, with loading, empty ("You're all caught up") and error states. |

## 3. New shared components and tokens

**Tokens** are in `services/admin-console/app/globals.css`, mirrored in `services/chat/app/globals.css`:
- New colours: `--proposal` / `--proposal-soft` (ochre; marks an AI proposal) and a darker `--muted-foreground` for AA contrast.
- New theme scales: `--font-display` (Plex Serif), `--text-2xs` / `--text-title` / `--text-display`, `--shadow-float` (floating layers only), `--ease-out`.
- Utilities: `eyebrow` (mono label), `num` (mono tabular figures), `skeleton` (shimmer), `scrollbar-none`.
- Base rules: the focus ring, 44px controls on coarse pointers, reduced motion.

**Components** are in `components/ui/` in both apps unless noted:

| Component | File | Use |
|---|---|---|
| `PageHeader`, `Page` | `page-header.tsx` | Eyebrow, Vietnamese secondary label, serif title, description, meta, actions, back link; `Page` sets the width (list, record or form) |
| `LoadingState`, `Skeleton`, `EmptyState`, `ErrorState`, `TableStatus` | `states.tsx` | The single loading, empty and error pattern |
| `Panel`, `Proposal`, `Decision`, `Facts` | `panel.tsx` | Sections of a record page; proposal vs decision blocks |
| `Toaster`, `useToast` | `toast.tsx` | Action feedback (success, error, info, optional action) |
| `ConfirmDialog` | `confirm.tsx` (console) | Confirmation before destructive actions |
| `Labeled` | `components/Modal.tsx` (console) | Label, required mark, hint and inline error |
| `StatusChip` | `services/chat/components/StatusChip.tsx` | A requester's ticket status |
| Restyled primitives | `button`, `card`, `input`, `select`, `textarea`, `table`, `dialog` | Flat, bordered, consistent focus styles |
| Shell | `components/AppShell.tsx` (console), `components/AppHeader.tsx` (chat) | Navigation |

## 4. Assumptions

- **English is the working UI language.** Vietnamese is kept as a secondary label, in content the user's language setting drives (guides, tours), in the fields that hold Vietnamese text, and as the second line of sign-in errors. I chose English because the demo KB, golden set and most existing labels are English.
- **Dark mode follows the system setting only.** It works the same way as before; I added no toggle.
- **Detail screens were checked with mock data.** The local database has no tickets, incidents or drafts, and creating one would run the AI pipeline and hosted models. `ux-screenshots/*/console-mockdata-*` and `chat-mockdata-*` use Playwright GET mocks shaped like the real responses.
- **Tours were left as they are.** On phones, tour steps that point into the console drawer may highlight a hidden element. The selectors are unchanged, except the chat bell's, which follows its new English `aria-label`.
- **The brand mark is a plain "S" square.** No logo asset exists.

## 5. Needs backend / out of scope

- **A demo-data seed command.** There's no way to create tickets, incidents or drafts without running the live pipeline, so populated screens can only be checked with mocks.
- **Machine-readable validation errors.** Several incident and declaration errors arrive as a code plus English text, which the UI maps to its own copy. A field-level error shape from core-api would let forms highlight the exact field.
- **Keyboard moves on the board.** Drag-and-drop is the only way to move a card on the board. Keyboard users have to use the ticket page's "Move to" buttons. A proper fix needs an accessible move action on the board, which goes beyond styling.
- **ESLint isn't configured** in either app (`next lint` asks to set it up). The gates I ran are `tsc --noEmit` and `next build`.

## 6. Known remaining issues

- Wide admin tables (deliveries, notifications matrix, access log) scroll horizontally inside their card on phones, but the page itself doesn't overflow.
- The workflow canvas is usable at 375px but cramped; it's meant for desktop.
- I translated Vietnamese-only strings by hand; a few rare error strings may still be Vietnamese.
- Without data, the before/after screenshots of the ticket, incident and draft detail pages exist only in the mock set.

## Verification

- `npx tsc --noEmit`: clean in both apps.
- `next build`: passes in both apps.
- 90 screenshots before and 96 after (the after set adds the mocked chat screens and three screens that only had data on the branch), covering every route discovered at 375 and 1440 for the manager, security and requester roles. No horizontal overflow at 375px.
- I signed in through local Keycloak as each role and clicked through the list, record, board, knowledge, admin and chat pages against the branch's prod builds (console :3002, chat :3003, core-api :8010).
