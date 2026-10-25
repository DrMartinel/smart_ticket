# ADR-0033: Notifications are written in the event's transaction and sent after commit

**Status:** Proposed (phase 2 pack, stage 2). Moved to [`docs/adr/0033-notifications-through-an-outbox.md`](../../../adr/0033-notifications-through-an-outbox.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0028 §6 (masked text, host allow-list)
**Feature:** F4 ([spec](../06-F4-notifications.md))

## Context

Features need to tell people things. Sending inside a request couples a
ticket change to an SMTP server; sending from a task queued before commit
can announce something that then rolls back.

## Decision

1. `Notifier.emit()` inserts one `notif_messages` row per recipient and
   channel **in the caller's transaction**. In-app rows are delivered on
   insert.
2. Email and webhook rows are sent by a Celery task queued `on_commit`, with
   retries and a sweep for stuck rows. A unique key per
   (event, recipient, channel) makes re-emits and retries safe.
3. **A failed send never changes a ticket.** Failures are listed for a person.
4. Templates read masked fields only; webhooks go to allow-listed hosts,
   signed, with a fixed body.
5. The event catalog and mandatory cells are code; matrix defaults and user
   preferences are data.

## Consequences

- No event without its notice, and no notice for an event that rolled back.
- In-app delivery is as fast as the client's poll (15 s); no websocket server
  is added (the stack has none, ADR-0028 "Not adopted").
