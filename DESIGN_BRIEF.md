# Design brief: "Case file"

Smart Ticket has two audiences. **Support staff** (technicians, team leads,
managers, security officers) use the console all day to review what the AI
proposed, decide, and keep an audit trail. **Employees** use the IT Help chat
for a minute at a time, to get an answer or hand a problem to a person.

The product's central idea is that *the AI proposes and people (and
deterministic rules) decide*. The visual direction makes that idea visible:
the console reads like a well-kept case file, where every proposal, decision
and change is a dated entry, and where it is always obvious which parts a
model wrote and which parts a person or a rule decided.

## Personality

**Calm, accountable, precise, plain-spoken.**

Staff work under SLA pressure and must be able to defend each decision later,
so the interface stays quiet and legible, puts facts (IDs, times, scores) in a
consistent place, and says plainly what happened. Employees want reassurance
that a real answer, or a real person, is coming; calm and plain fits them too.

## Typography

| Role | Face | Why |
|---|---|---|
| Display (page titles, chat headings) | **IBM Plex Serif** 500/600 | Gives titles the voice of a record or case file without becoming editorial; shares Plex Sans's skeleton, so the pair reads as one family. |
| Body / UI | **IBM Plex Sans** 400/500/600 | Already the app's face, a technical sans with full **Vietnamese** coverage (staff and requesters are Vietnamese; the `vietnamese` subset is now loaded, so diacritics no longer fall back). |
| Data | **IBM Plex Mono** 400/500 | Ticket IDs, counts, scores, durations and timestamps, always with tabular figures, so columns of numbers line up. |

Type scale (rem at 16px root), used through Tailwind tokens:

| Token | Size / line | Use |
|---|---|---|
| `text-2xs` | 11 / 16 | Eyebrows, table headers (uppercase, +0.06em tracking) |
| `text-xs` | 12 / 16 | Meta lines, hints |
| `text-sm` | 14 / 20 | Console body, controls |
| `text-base` | 16 / 24 | Chat body, long reading text |
| `text-lg` | 18 / 26 | Section titles in chat |
| `text-title` | 26 / 32 (serif) | Page titles (22px on phones) |
| `text-display` | 32 / 38 (serif) | The chat's opening question only |

## Color

One brand color, one accent, warm-tinted neutrals, four semantics. Light and
dark both follow the operating system (`prefers-color-scheme`); the app has no
manual switch, so none was added.

| Token | Light | Dark | Use |
|---|---|---|---|
| `primary` (Forest) | `#1f5c4a` | `#7cc3a5` | The existing brand green: primary actions, current page, links, human decisions |
| `accent` (Ochre) | `#8a5d12` | `#e2b866` | Only for **AI proposals**: the proposal rule and tag |
| `background` (paper) | `#f6f5f1` | `#161513` | Page |
| `card` | `#ffffff` | `#1e1d1a` | Raised surfaces: panels, tables, inputs |
| `muted` | `#efede6` | `#262420` | Quiet fills, hover |
| `muted-foreground` | `#625d53` | `#a8a397` | Secondary text (≥ 4.5:1 on both paper and card) |
| `border` / `border-strong` | `#dcd8cc` / `#c4bfb1` | `#34312b` / `#4a463e` | Hairlines / control outlines |
| `ok` | `#2f6b45` | `#8cc9a2` | Success, met, approved |
| `warn` | `#85520b` | `#e0b16a` | At risk, needs attention |
| `danger` | `#a3271c` | `#f08b80` | Errors, breaches, destructive actions |
| `info` | `#2d4f78` | `#9bb8dc` | Neutral information, routed |

Each semantic also has a `-soft` fill for badges and banners; every
text-on-soft pair meets WCAG AA.

## Shape and depth

- **Radius:** 6px on every control and surface (`--radius`). Pills only for status dots and counts.
- **Borders, not shadows.** Surfaces are separated by 1px warm hairlines.
  Shadows are reserved for things that float above the page: menus, dialogs,
  the mobile navigation drawer and toasts.
- **Density:** compact in the console (36px controls, 14px body, 10–12px
  cell padding); airy in the chat (16px body, generous spacing). On touch
  screens every button, input and nav item grows to at least 44px.

## Layout

- **Console:** a 240px sidebar at ≥1024px; below that a top bar with a menu
  button that opens the same navigation as a drawer. Content has a 16px
  gutter on phones, 24px on tablets and 32px on desktop.
- **Max widths:** lists and tables 1200px, record pages (a ticket, an
  incident) 1280px with a 320px side column at ≥1280px, forms 720px.
- **Separating sections:** a page is a header, then panels. A panel is a
  bordered surface with a small uppercase heading; panels are never nested
  inside other panels. Inside a panel, groups are separated by hairlines.
- **Chat:** a single 720px reading column, header and composer pinned.

## Signature details

1. **The ledger header.** Every page opens the same way: a mono uppercase
   eyebrow with where you are (`WORKSPACE / TICKETS`), with the Vietnamese
   name of the section beside it where the domain has one, a serif title, one plain
   sentence on what the page is for, actions on the right, and a hairline
   rule under it all.
2. **Proposed vs decided.** Anything a model wrote (a drafted answer, a
   proposed category, a detector's incident) sits in a *proposal block*: a
   dashed ochre left rule and a small `AI PROPOSAL` mono tag. Decisions made
   by a person or a rule use a solid rule in Forest. Dashed means "not yet
   decided" everywhere, including empty states.
3. **Mono facts.** IDs, counts, scores, durations and times are set in Plex
   Mono with tabular figures, and ticket IDs appear as quiet mono tags, so the
   facts on any screen are easy to scan and copy.

Empty states use one style: a line icon from Lucide (the icon set already
installed) inside a dashed square, a one-line title, one sentence saying what
to do next, and an action when there is one.

## Motion

Only to show cause and effect, 150–250ms, ease-out:

- 150ms color and background changes on hover and focus.
- 200ms fade and slide for dialogs, the navigation drawer and toasts.
- A slow shimmer on loading skeletons.
- Everything above is disabled under `prefers-reduced-motion`.

No decorative animation.

## What we deliberately avoid

Gradients, glassmorphism, emoji as icons, a drop shadow on every card,
centered hero layouts on app screens, and mixing two languages inside one
button or nav label.
