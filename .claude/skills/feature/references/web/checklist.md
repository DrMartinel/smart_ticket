# Web change checklist

Used by `/feature` (self-review) and `/review` (reviewing a diff) when
`services/admin-console/` or `services/chat/` is touched. Both are thin Next.js
clients: core-api decides, the client shows.

## Authority & safety

- [regression] No business logic in the client: nothing decides a branch, a permission, a score, a status move or an SLA figure. The client shows what core-api returns and sends what the person chose.
- [regression] In the admin console, a control is shown or hidden through `can()` in `lib/permissions.ts`, reading `user.permissions`. Never a check on a role name. Hiding is a courtesy; core-api's `require` is the gate.
- [regression] Sessions live in `lib/session.ts`, never in `localStorage` or `sessionStorage` (ADR-0029).
- [regression] Raw PII is never shown except through the reveal route, which core-api logs.

## Contract

- [regression] `lib/types/generated.ts` is never hand-edited. After a core-api schema change, `make types` in `services/core-api` regenerates both apps' copies.
- [convention] API calls go through `lib/api.ts`; a refusal's `code` is shown through the app's existing error mapping, not by matching message text.

## Placement

- [convention] Daily work sits in the Workspace (`components/AppShell.tsx`); figures, authority, rollout, thresholds and settings sit under `/admin/*` (`lib/areas.ts`, ADR-0039). A moved page gets a redirect in `next.config.mjs`.

## Checks

- [regression] `npm run lint` and `npm run build` pass in each app touched.
