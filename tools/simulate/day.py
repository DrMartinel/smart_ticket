"""One working day at the simulated company, acted out through the same API calls the two frontends make."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .cast import (
    AFTERNOON_CHAT,
    DEFAULT_REPLY,
    DEPARTMENTS,
    EMPLOYEES,
    EVERYONE,
    FORM_TICKETS,
    HEADS,
    MORNING_CHAT,
    OUTAGE,
    REPLIES,
    STAFF,
    TEAM_STAFFING,
    Persona,
    Request,
)
from .client import ApiError
from .idp import Directory, DirectoryAccount
from .world import Finding, Raised, World

TECHNICIANS = ["duc.tm", "mai.bn", "tu.dv", "long.nh", "vy.tt"]
SECURITY_QUEUES = {"security", "security_review", "blocked", "mask_failed"}
EXPECTED_CATEGORY = {
    "printer": "hardware",
    "laptop": "hardware",
    "offboard-access": "access",
    "new-starter": "access",
    "ses-bounce": "software",
    "lambda-perm": "software",
    "security-hub": "security",
    "mfa-lockout": "access",
    "pasted-password": "access",
}
LOW_RATINGS = {"printer": 2}
KB_DRAFT_SLUG = "client-vpn-drops-every-few-minutes"
WAITING_FOR_YOU = ("Chờ bạn phản hồi", "Waiting for you")
TRIAGE_DONE = ("pending_review", "auto_routed", "escalated", "reopened")
RESOLUTION_NOTE = "Reset the account settings and confirmed with the requester that it works."


def csv_rows(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join([",".join(header), *(",".join(r) for r in rows)])


class Day:
    """The day's scenes, in the order a real office would live them."""

    def __init__(
        self, world: World, requests: dict[str, list[Request]], directory: Directory | None
    ) -> None:
        self.w = world
        self.requests = requests
        self.directory = directory

    # ── before the day: IT and HR set people up ──

    def it_creates_accounts(self) -> None:
        """IT creates company sign-in accounts for this week's new hires."""
        if self.directory is None:
            self.w.tell("IT: no directory admin credentials, new hires must already have accounts")
            return
        for p in STAFF + EMPLOYEES:
            created = self.directory.ensure(
                DirectoryAccount(p.username, p.first_name, p.last_name, "change-me")
            )
            if created:
                self.w.tell(f"IT creates a company account for {p.username}")

    def hr_imports_the_org(self) -> None:
        """The IT manager loads HR's export: departments first, then people, each checked before applying."""
        huy = self.w.as_("huy.pq")
        departments = csv_rows(
            ["code", "name", "parent_code", "head", "cost_centre"],
            [[code, name, parent, "", cc] for code, name, parent, cc in DEPARTMENTS],
        )
        people = csv_rows(
            [
                "username",
                "email",
                "first_name",
                "last_name",
                "department_code",
                "line_manager",
                "job_title",
                "location",
                "phone",
                "employee_id",
            ],
            [
                [
                    p.username,
                    f"{p.username}@congty.vn",
                    p.first_name,
                    p.last_name,
                    p.department,
                    "",
                    p.job_title,
                    "Hanoi",
                    "",
                    "",
                ]
                for p in STAFF + EMPLOYEES
            ],
        )
        for kind, text in (("departments", departments), ("people", people)):
            check = self.w.attempt(
                "huy.pq",
                f"check {kind} import",
                lambda k=kind, t=text: huy.post(
                    f"/api/org/import/{k}?dry_run=true", {"csv": t, "reason": "Quarterly HR export"}
                ),
            )
            if check is None:
                continue
            failed = [r for r in check.get("rows", []) if r.get("error")]
            self.w.tell(
                f"huy.pq checks the {kind} import: {len(check.get('rows', []))} rows, {len(failed)} with errors"
            )
            if failed:
                self.w.tell(f"  first error: {failed[0]}")
                continue
            self.w.pause()
            self.w.attempt(
                "huy.pq",
                f"apply {kind} import",
                lambda k=kind, t=text: huy.post(
                    f"/api/org/import/{k}?dry_run=false",
                    {"csv": t, "reason": "Quarterly HR export"},
                ),
            )
            self.w.tell(f"huy.pq applies the {kind} import")

    def everyone_signs_in(self) -> None:
        """Each person opens their app for the first time today; new hires link to their invited record."""
        for p in STAFF + EMPLOYEES:
            self.w.attempt(p.username, "sign in", lambda u=p.username: self.w.as_(u))

    def manager_sets_up_new_staff(self) -> None:
        """The IT manager gives new IT hires their base role, and team leads put them in teams."""
        huy = self.w.as_("huy.pq")
        for p in STAFF:
            if not p.new_hire:
                continue
            self.w.attempt(
                "huy.pq",
                "set base role",
                lambda p=p: huy.put(
                    f"/api/accounts/people/{p.username}/base-role",
                    {"role": p.base_role, "reason": f"Joined IT as {p.job_title}"},
                ),
            )
            self.w.tell(f"huy.pq makes {p.username} a {p.base_role}")
            for team, role in p.teams:
                self.w.attempt(
                    "huy.pq",
                    "add to team",
                    lambda t=team, r=role, u=p.username: huy.post(
                        f"/api/teams/{t}/members", {"username": u, "role": r}
                    ),
                )
                self.w.tell(f"huy.pq adds {p.username} to {team} as {role}")
        tu = self.w.as_("tu.dv")
        for team, username, role in TEAM_STAFFING:
            self.w.attempt(
                "tu.dv",
                "staff a team",
                lambda t=team, u=username, r=role: tu.post(
                    f"/api/teams/{t}/members", {"username": u, "role": r}
                ),
            )
            self.w.tell(f"tu.dv (workflow admin) adds {username} to {team} as {role}")
        for code, head in HEADS.items():
            self.w.attempt(
                "huy.pq",
                "set department head",
                lambda c=code, h=head: huy.patch(
                    f"/api/org/departments/{c}", {"head": h, "reason": "Per HR org chart"}
                ),
            )
            self.w.tell(f"huy.pq sets {head} as head of {code}")

    # ── requesters ──

    def ask_in_chat(self, requests: list[Request]) -> None:
        """Employees ask their question in chat and wait for the answer, as the chat page polls."""
        for r in requests:
            s = self.w.as_(r.who)
            turn = self.w.attempt(
                r.who, "ask in chat", lambda r=r, s=s: s.post("/api/chat/ask", {"message": r.text})
            )
            if turn:
                self.w.raised[r.key] = Raised(
                    r.key, r.who, "chat", turn["public_id"], str(turn.get("conversation_id") or "")
                )
                self.w.tell(f"{r.who} asks in chat ({r.key}) → {turn['public_id']}")
            self.w.pause()
        for r in requests:
            self.follow_chat(r)

    def follow_chat(self, r: Request) -> None:
        raised = self.w.raised.get(r.key)
        if raised is None:
            return
        s = self.w.as_(r.who)
        turn = self.chat_settled(s, raised)
        if turn is None:
            self.w.tell(f"  {r.who}: still thinking after the wait ({raised.public_id})")
            return
        raised.state = turn["state"]
        self.w.tell(f"  {r.who} sees '{turn['state']}' for {r.key}")
        if turn["state"] == "answered" and r.follow_up:
            self.w.pause()
            follow = self.w.attempt(
                r.who,
                "follow-up in chat",
                lambda: s.post(
                    "/api/chat/ask",
                    {"message": r.follow_up, "conversation_id": raised.conversation_id or None},
                ),
            )
            if follow:
                key = f"{r.key}+follow-up"
                self.w.raised[key] = Raised(
                    key, r.who, "chat", follow["public_id"], raised.conversation_id
                )
                self.w.tell(
                    f"  {r.who} follows up in the same conversation → {follow['public_id']}"
                )
                settled = self.chat_settled(s, self.w.raised[key])
                if settled:
                    self.w.raised[key].state = settled["state"]
                    self.w.tell(f"  {r.who} sees '{settled['state']}' for the follow-up")
        elif turn["state"] == "clarify" and turn.get("clarification"):
            options = turn["clarification"]["options"]
            answer = options[0] if options else "The first one"
            self.w.pause()
            self.w.attempt(
                r.who,
                "answer clarification",
                lambda: s.post(f"/api/chat/tickets/{raised.public_id}/clarify", {"answer": answer}),
            )
            self.w.tell(f"  {r.who} answers the clarifying question: {answer[:60]}")
            settled = self.chat_settled(s, raised)
            if settled:
                raised.state = settled["state"]
                self.w.tell(f"  {r.who} now sees '{settled['state']}'")
        if raised.state == "suggest_ticket":
            self.w.pause()
            self.w.attempt(
                r.who,
                "ask for a ticket",
                lambda: s.post(f"/api/chat/tickets/{raised.public_id}/create-ticket"),
            )
            self.w.tell(f"  {r.who} asks for a person to look at it")

    def chat_settled(self, s: Any, raised: Raised) -> dict[str, Any] | None:
        latest: dict[str, Any] = {}

        def settled() -> bool:
            latest.update(s.get(f"/api/chat/tickets/{raised.public_id}"))
            return latest.get("state") != "thinking"

        return latest if self.w.wait_until(settled, timeout=240) else None

    def submit_forms(self, requests: list[Request]) -> None:
        """Employees fill in the ticket form in the chat app."""
        for r in requests:
            s = self.w.as_(r.who)
            ticket = self.w.attempt(
                r.who,
                "submit a ticket",
                lambda r=r, s=s: s.post(
                    "/api/tickets/submit", {"subject": r.subject, "body": r.text}
                ),
            )
            if ticket:
                pid = ticket["ticket_public_id"]
                self.w.raised[r.key] = Raised(r.key, r.who, "form", pid)
                self.w.tell(f"{r.who} submits '{r.subject}' → {pid}")
            self.w.pause(0.5 if "outage" in r.tags else 1.0)

    def wait_for_triage(self, keys: list[str]) -> None:
        """Waits until the pipeline has decided every listed ticket, read as a staff member's ticket page."""
        huy = self.w.as_("huy.pq")
        pending = [k for k in keys if k in self.w.raised]

        def decided() -> bool:
            for key in list(pending):
                detail = huy.get(f"/api/tickets/{self.w.raised[key].public_id}/detail")
                if detail.get("routing"):
                    latest = max(detail["routing"], key=lambda d: d.get("decided_at") or "")
                    self.w.raised[key].branch = latest["branch"]
                    self.w.raised[key].reason = latest["reason_code"]
                    pending.remove(key)
            return not pending

        if not self.w.wait_until(decided, timeout=600, every=6):
            self.w.tell(f"  triage still pending for {pending}")
        for key in keys:
            if key in self.w.raised and self.w.raised[key].branch:
                r = self.w.raised[key]
                self.w.tell(f"  triage: {key} → {r.branch} ({r.reason})")

    def requesters_check_in(self) -> None:
        """Each requester opens 'My tickets': replies where IT is waiting on them, rates what was resolved."""
        for p in EMPLOYEES:
            mine = [r for r in self.w.raised.values() if r.who == p.username]
            if not mine:
                continue
            s = self.w.as_(p.username)
            listing = self.w.attempt(
                p.username, "open my tickets", lambda s=s: s.get("/api/requester/tickets")
            )
            if not listing:
                continue
            for row in listing["open"] + listing["recent"]:
                raised = next((r for r in mine if r.public_id == row["public_id"]), None)
                if raised is None:
                    continue
                detail = self.w.attempt(
                    p.username,
                    "read a ticket",
                    lambda s=s, row=row: s.get(f"/api/requester/tickets/{row['public_id']}"),
                )
                if not detail:
                    continue
                self.w.pause(0.5)
                if detail.get("can_reply") and row.get("status_label") in WAITING_FOR_YOU:
                    body = REPLIES.get(raised.key.split("+")[0], DEFAULT_REPLY)
                    self.w.attempt(
                        p.username,
                        "reply to IT",
                        lambda s=s, row=row, body=body: s.post(
                            f"/api/requester/tickets/{row['public_id']}/replies", {"body": body}
                        ),
                    )
                    raised.replied += 1
                    self.w.tell(f"{p.username} replies on {row['public_id']} ({raised.key})")
                if detail.get("can_rate") and not raised.rated:
                    score = LOW_RATINGS.get(raised.key, self.w.rng.choice([4, 5, 5]))
                    comment = (
                        "Still jamming after the visit."
                        if score <= 2
                        else "Thanks, quick and clear."
                    )
                    self.w.attempt(
                        p.username,
                        "rate a ticket",
                        lambda s=s, row=row, score=score, comment=comment: s.put(
                            f"/api/requester/tickets/{row['public_id']}/rating",
                            {"score": score, "comment": comment},
                        ),
                    )
                    raised.rated = True
                    self.w.tell(f"{p.username} rates {row['public_id']} {score}/5")
                    if score <= 2 and row.get("can_reopen_until") and not raised.reopened:
                        self.w.attempt(
                            p.username,
                            "reopen",
                            lambda s=s, row=row: s.post(
                                f"/api/requester/tickets/{row['public_id']}/reopen",
                                {"reason": "The printer jammed again this afternoon."},
                            ),
                        )
                        raised.reopened = True
                        self.w.tell(f"{p.username} reopens {row['public_id']}")

    def head_reads_department(self) -> None:
        """The engineering head looks at what their department has open with IT."""
        s = self.w.as_("khanh.lv")
        rows = self.w.attempt(
            "khanh.lv",
            "read department tickets",
            lambda: s.get("/api/requester/department-tickets"),
        )
        if rows is not None:
            count = (
                len(rows)
                if isinstance(rows, list)
                else len(rows.get("items", rows.get("open", [])))
            )
            self.w.tell(f"khanh.lv (head of ENG) reads the department's tickets: {count}")

    # ── staff ──

    def reviewers_work_the_queue(self, rounds: int = 1) -> None:
        """Technicians claim items from the review queue, read the proposal, and decide."""
        for _ in range(rounds):
            for tech in TECHNICIANS:
                s = self.w.as_(tech)
                queue = self.w.attempt(
                    tech, "open review queue", lambda s=s: s.get("/api/review/queue")
                )
                if not queue:
                    continue
                for item in [
                    i
                    for i in queue
                    if i["queue"] not in SECURITY_QUEUES and i["state"] == "pending"
                ][:3]:
                    self.review_one(tech, s, item)

    def review_one(self, tech: str, s: Any, item: dict[str, Any]) -> None:
        claimed = self.w.attempt(
            tech, "claim review item", lambda: s.post(f"/api/review/items/{item['id']}/claim")
        )
        if not claimed:
            return
        ticket_id = item["ticket_public_id"]
        detail = (
            self.w.attempt(tech, "read ticket", lambda: s.get(f"/api/tickets/{ticket_id}/detail"))
            or {}
        )
        self.w.pause()
        key = next((r.key for r in self.w.raised.values() if r.public_id == ticket_id), "")
        if item["queue"] == "runbook_approval":
            self.w.attempt(
                tech, "read runbook", lambda: s.get(f"/api/itsm/review-items/{item['id']}/runbook")
            )
            body = {
                "action_taken": "reject",
                "override_reason": "Handling this one by hand.",
                "time_spent_sec": 140,
            }
        else:
            body = self.decision_for(key, item, detail)
        decided = self.w.attempt(
            tech,
            "decide review item",
            lambda: s.post(f"/api/review/items/{item['id']}/decide", body),
        )
        if decided:
            self.w.tell(
                f"{tech} decides {ticket_id} ({key or item['queue']}): {body['action_taken']}"
            )

    def decision_for(
        self, key: str, item: dict[str, Any], detail: dict[str, Any]
    ) -> dict[str, Any]:
        """What a careful reviewer does with the proposal in front of them."""
        ai = detail.get("ai") or {}
        expected = EXPECTED_CATEGORY.get(key.split("+")[0])
        spent = self.w.rng.randint(45, 300)
        if expected and ai.get("category") and ai["category"] != expected:
            return {
                "action_taken": "reroute",
                "category_verdict": "wrong",
                "corrected_category": expected,
                "kb_verdict": "not_applicable",
                "override_reason": f"This is a {expected} request.",
                "time_spent_sec": spent,
            }
        if ai.get("answer_draft") and ai.get("kb_slug"):
            roll = self.w.rng.random()
            if roll < 0.7:
                return {
                    "action_taken": "approve",
                    "kb_verdict": "correct",
                    "category_verdict": "correct",
                    "time_spent_sec": spent,
                }
            return {
                "action_taken": "edit_and_send",
                "kb_verdict": "partial",
                "category_verdict": "correct",
                "override_reason": "Added the step for our own account setup.",
                "time_spent_sec": spent + 120,
            }
        if item["queue"] == "clarification":
            return {
                "action_taken": "reroute",
                "kb_verdict": "not_applicable",
                "category_verdict": "correct",
                "override_reason": "Requester did not answer; sending to the team.",
                "time_spent_sec": spent,
            }
        return {
            "action_taken": "reroute",
            "kb_verdict": "not_applicable",
            "category_verdict": "correct" if ai.get("category") else None,
            "override_reason": "No help page fits; the team should handle it.",
            "time_spent_sec": spent,
        }

    def teams_work_their_tickets(self) -> None:
        """Each technician takes tickets from their team's queue and moves them along."""
        for tech in TECHNICIANS:
            s = self.w.as_(tech)
            me = s.me
            for membership in me.get("teams", []):
                team = membership["team"]
                page = self.w.attempt(
                    tech,
                    "open team queue",
                    lambda s=s, team=team: s.get(f"/api/teams/{team}/queue", unassigned=True),
                )
                rows = page.get("items", []) if isinstance(page, dict) else (page or [])
                for row in rows[:2]:
                    self.take_and_work(tech, s, row)
            self.progress_my_tickets(tech, s)

    def take_and_work(self, tech: str, s: Any, row: dict[str, Any]) -> None:
        pid = row["public_id"]
        taken = self.w.attempt(
            tech,
            "take ticket",
            lambda: s.post(f"/api/tickets/{pid}/take", {"expected_version": row["version"]}),
        )
        if not taken:
            return
        self.w.tell(f"{tech} takes {pid} ({self.key_of(pid)})")
        self.w.pause()
        self.move(tech, s, pid, "in_progress")
        key = self.key_of(pid).split("+")[0]
        if key in REPLIES:
            self.comment(
                tech,
                s,
                pid,
                "Hi, could you give me a little more detail so I can sort this out?",
                wait=True,
            )
        else:
            self.comment(
                tech,
                s,
                pid,
                "Internal: checked the account settings, applying the fix now.",
                visibility="internal",
            )

    def progress_my_tickets(self, tech: str, s: Any) -> None:
        """Works the tickets assigned to the technician: picks up new ones, asks for detail where
        needed, and resolves those that need nothing more from the requester."""
        page = self.w.attempt(tech, "open my tickets", lambda: s.get("/api/tickets", view="mine"))
        for row in (page or {}).get("items", []):
            pid, status = row["public_id"], row["status"]["key"]
            if row["status"].get("is_completed") or status in ("blocked", "waiting_on_vendor"):
                continue
            raised = next((r for r in self.w.raised.values() if r.public_id == pid), None)
            key = raised.key.split("+")[0] if raised else ""
            if status in TRIAGE_DONE:
                if not self.move(tech, s, pid, "assigned"):
                    continue
                status = "assigned"
            if status != "in_progress" and status != "waiting_on_requester":
                if not self.move(tech, s, pid, "in_progress"):
                    continue
                self.w.pause(0.5)
                if key in REPLIES and raised is not None and not raised.replied:
                    self.comment(
                        tech,
                        s,
                        pid,
                        "Hi, could you give me a little more detail so I can sort this out?",
                        wait=True,
                    )
                    continue
            if status == "waiting_on_requester":
                continue
            self.comment(
                tech, s, pid, "This is fixed on our side now. Let us know if it comes back."
            )
            self.move(tech, s, pid, "resolved")

    def move(self, who: str, s: Any, pid: str, to: str) -> bool:
        options = (
            self.w.attempt(
                who, "list moves", lambda: s.get(f"/api/lifecycle/tickets/{pid}/transitions")
            )
            or []
        )
        target = next((o for o in options if o["status"]["key"] == to), None)
        if target is None:
            self.w.tell(f"  {who}: no move to {to} from {pid}'s status")
            return False
        body = {"status_id": target["status"]["id"]}
        try:
            version = s.get(f"/api/lifecycle/tickets/{pid}")["version"]
            moved = s.post(
                f"/api/lifecycle/tickets/{pid}/move", {**body, "expected_version": version}
            )
            self.w.count(f"move to {to}")
        except ApiError as e:
            missing = self.required_fields(e)
            if not missing:
                moved = None
                self.w.refused(who, f"move to {to}", e)
            else:
                self.w.findings.append(
                    Finding(
                        who,
                        f"move to {to}",
                        f"needs {', '.join(missing.values())}, which the console's ticket page cannot fill; "
                        "filled through PUT /api/lifecycle/tickets/{id}/fields",
                    )
                )
                self.w.attempt(
                    who,
                    "fill ticket fields",
                    lambda: s.put(
                        f"/api/lifecycle/tickets/{pid}/fields",
                        {"values": dict.fromkeys(missing, RESOLUTION_NOTE)},
                    ),
                )
                moved = self.w.attempt(
                    who,
                    f"move to {to}",
                    lambda: s.post(
                        f"/api/lifecycle/tickets/{pid}/move",
                        {
                            **body,
                            "expected_version": s.get(f"/api/lifecycle/tickets/{pid}")["version"],
                        },
                    ),
                )
        if moved:
            self.w.tell(f"  {who} moves {pid} to {to}")
        return bool(moved)

    @staticmethod
    def required_fields(e: ApiError) -> dict[str, str]:
        """The fields a refused move named as required, by id."""
        if e.code != "rule_violation" or not isinstance(e.body, dict):
            return {}
        return {
            d["field_id"]: d["field_name"]
            for d in e.body.get("details") or []
            if d.get("rule") == "required" and d.get("field_id")
        }

    def comment(
        self,
        who: str,
        s: Any,
        pid: str,
        body: str,
        *,
        visibility: str = "public",
        wait: bool = False,
    ) -> None:
        version = (s.get(f"/api/tickets/{pid}/detail") or {}).get("version")
        done = self.w.attempt(
            who,
            "comment",
            lambda: s.post(
                f"/api/tickets/{pid}/comments",
                {
                    "body": body,
                    "visibility": visibility,
                    "move_to_waiting": wait,
                    "expected_version": version,
                },
            ),
        )
        if done:
            self.w.tell(
                f"  {who} comments on {pid} ({visibility}{', now waiting on requester' if wait else ''})"
            )

    def key_of(self, pid: str) -> str:
        return next((r.key for r in self.w.raised.values() if r.public_id == pid), "?")

    def security_triages_alerts(self) -> None:
        """The security analyst works the open alerts: acknowledge, look, act, close."""
        s = self.w.as_("anh.lh")
        alerts = (
            self.w.attempt(
                "anh.lh", "open alerts", lambda: s.get("/api/security/alerts", state="open")
            )
            or []
        )
        rows = alerts.get("items", alerts) if isinstance(alerts, dict) else alerts
        self.w.tell(f"anh.lh opens the security alerts: {len(rows)} open")
        for alert in rows[:6]:
            aid = alert["id"]
            if alert["state"] == "new":
                self.w.attempt(
                    "anh.lh", "acknowledge alert", lambda: s.post(f"/api/security/alerts/{aid}/ack")
                )
            detail = (
                self.w.attempt("anh.lh", "read alert", lambda: s.get(f"/api/security/alerts/{aid}"))
                or {}
            )
            self.w.pause()
            ticket = alert.get("ticket") or {}
            key = self.key_of(ticket.get("public_id", ""))
            if key == "pasted-password":
                self.reveal_and_contain(s, aid, ticket["public_id"])
                resolution, note = (
                    "true_positive",
                    "Password pasted in a ticket; requester told to change it, sessions ended.",
                )
            elif key == "injection" or "injection" in alert["kind"]:
                resolution, note = (
                    "true_positive",
                    "Prompt injection attempt; no model acted on it. Talked to the requester.",
                )
            else:
                resolution, note = "false_positive", "Reviewed; nothing sensitive here."
            self.w.attempt(
                "anh.lh",
                "add alert note",
                lambda note=note: s.post(f"/api/security/alerts/{aid}/notes", {"note": note}),
            )
            self.w.attempt(
                "anh.lh",
                "close alert",
                lambda r=resolution, n=note: s.post(
                    f"/api/security/alerts/{aid}/close", {"resolution": r, "note": n}
                ),
            )
            self.w.tell(
                f"anh.lh closes the {alert['kind']} alert on {ticket.get('public_id', '-')} as {resolution}"
            )
            if detail.get("can_release") and resolution == "false_positive":
                self.w.attempt(
                    "anh.lh",
                    "release ticket",
                    lambda: s.post(
                        f"/api/security/alerts/{aid}/release-ticket",
                        {"reason": "False positive, back to the service desk."},
                    ),
                )
                self.w.tell(f"  anh.lh releases {ticket.get('public_id')} to the service desk")

    def reveal_and_contain(self, s: Any, alert_id: str, pid: str) -> None:
        detail = (
            self.w.attempt("anh.lh", "read ticket", lambda: s.get(f"/api/tickets/{pid}/detail"))
            or {}
        )
        for ph in detail.get("pii_placeholders", [])[:1]:
            self.w.attempt(
                "anh.lh",
                "reveal PII",
                lambda ph=ph: s.post(
                    f"/api/tickets/{pid}/quarantine/reveal",
                    {
                        "placeholder": ph["placeholder"],
                        "reason_code": "security_investigation",
                        "reason": "Confirming a password was pasted in clear text.",
                    },
                ),
            )
            self.w.tell(
                f"  anh.lh reveals {ph['placeholder']} on {pid} for the investigation (logged)"
            )
        self.w.attempt(
            "anh.lh",
            "notify requester",
            lambda: s.post(
                f"/api/security/alerts/{alert_id}/notify-requester",
                {"reason": "Please change your password now."},
            ),
        )
        self.w.attempt(
            "anh.lh",
            "end sessions",
            lambda: s.post(
                f"/api/security/alerts/{alert_id}/end-sessions",
                {"reason": "Credential exposed in a ticket."},
            ),
        )
        self.w.tell("  anh.lh tells the requester to change the password and ends their sessions")

    def incident_manager_handles_outage(self) -> None:
        """The incident manager confirms the VPN outage the detector raised, or declares it, and updates everyone."""
        s = self.w.as_("duc.tm")
        rows = self.w.attempt("duc.tm", "open incidents", lambda: s.get("/api/incidents")) or []
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        suspected = [
            i for i in rows if i["status"] not in ("confirmed", "resolved", "closed", "dismissed")
        ]
        outage_ids = [self.w.raised[r.key].public_id for r in OUTAGE if r.key in self.w.raised]
        if suspected:
            incident = suspected[0]
            self.w.tell(
                f"duc.tm sees the detector's incident {incident['public_id']} with {incident['ticket_count']} tickets"
            )
            self.w.attempt(
                "duc.tm",
                "confirm incident",
                lambda: s.post(
                    f"/api/incidents/{incident['public_id']}/confirm",
                    {
                        "title": "Client VPN disconnects every few minutes",
                        "category": "network",
                        "service": "Client VPN",
                    },
                ),
            )
            pid = incident["public_id"]
            linked = {
                link["ticket"] for link in (s.get(f"/api/incidents/{pid}") or {}).get("links", [])
            }
            missing = [t for t in outage_ids if t not in linked]
            if missing:
                self.w.attempt(
                    "duc.tm",
                    "link tickets",
                    lambda: s.post(f"/api/incidents/{pid}/links", {"ticket_ids": missing}),
                )
                self.w.tell(f"  duc.tm links {len(missing)} more tickets the detector missed")
        else:
            created = self.w.attempt(
                "duc.tm",
                "declare incident",
                lambda: s.post(
                    "/api/incidents",
                    {
                        "title": "Client VPN disconnects every few minutes",
                        "category": "network",
                        "service": "Client VPN",
                        "ticket_ids": outage_ids,
                    },
                ),
            )
            if not created:
                return
            pid = created["public_id"]
            self.w.tell(
                f"duc.tm declares incident {pid} over {len(outage_ids)} tickets (the detector raised none)"
            )
        self.w.attempt(
            "duc.tm",
            "broadcast",
            lambda: s.post(
                f"/api/incidents/{pid}/broadcasts",
                {
                    "stage": "investigating",
                    "body_vi": "Chúng tôi đang kiểm tra sự cố Client VPN bị ngắt kết nối.",
                    "body_en": "We are looking into Client VPN disconnecting every few minutes.",
                    "eta_unknown": True,
                },
            ),
        )
        self.w.tell("  duc.tm sends an 'investigating' update to everyone affected")
        self.w.raised["_incident"] = Raised("_incident", "duc.tm", "incident", pid)

    def incident_manager_resolves(self) -> None:
        incident = self.w.raised.get("_incident")
        if incident is None:
            return
        s = self.w.as_("duc.tm")
        self.w.attempt(
            "duc.tm",
            "broadcast",
            lambda: s.post(
                f"/api/incidents/{incident.public_id}/broadcasts",
                {
                    "stage": "monitoring",
                    "body_vi": "Đã thay chứng chỉ máy chủ VPN, đang theo dõi.",
                    "body_en": "The VPN endpoint's server certificate was renewed; we are monitoring.",
                    "eta_unknown": True,
                },
            ),
        )
        self.w.pause()
        result = self.w.attempt(
            "duc.tm",
            "resolve incident",
            lambda: s.post(
                f"/api/incidents/{incident.public_id}/resolve",
                {
                    "resolution_note": "Expired server certificate on the Client VPN endpoint; renewed and verified.",
                    "close_all": True,
                },
            ),
        )
        closed = (result or {}).get("closed", [])
        failed = (result or {}).get("failed", [])
        self.w.tell(
            f"duc.tm resolves {incident.public_id}: close-all closed {len(closed)}, "
            f"refused {len(failed)} {sorted({f.get('code') for f in failed})}"
        )

    def kb_editor_writes_a_page(self) -> None:
        """The KB editor drafts a page for the outage; one manager asks for changes, another approves."""
        mai, huy, quang = self.w.as_("mai.bn"), self.w.as_("huy.pq"), self.w.as_("quang.nv")
        gaps = self.w.attempt("mai.bn", "read KB gaps", lambda: mai.get("/api/kb/gaps"))
        if gaps is not None:
            self.w.tell(
                f"mai.bn reads the KB gap report: {len(gaps) if isinstance(gaps, list) else len(gaps.get('items', []))} clusters"
            )
        found = self.w.attempt(
            "mai.bn", "search the KB", lambda: mai.get("/api/kb", q=KB_DRAFT_SLUG)
        )
        exists = any(a.get("slug") == KB_DRAFT_SLUG for a in (found or {}).get("items", []))
        draft = self.w.attempt(
            "mai.bn",
            "create KB draft",
            lambda: mai.post(
                "/api/kb/drafts",
                {
                    "kind": "edit" if exists else "create",
                    "slug": KB_DRAFT_SLUG,
                    "title": "Client VPN drops every few minutes",
                    "body": "If the AWS Client VPN disconnects every few minutes:\n\n1. Quit the AWS VPN Client.\n"
                    "2. Download the current configuration file from the self-service portal.\n"
                    "3. Import it again and reconnect.\n\nIf it still drops, open a ticket and attach the client log."
                    + (
                        "\n\nOn a laptop, turn off the Wi-Fi power saving setting too."
                        if exists
                        else ""
                    ),
                    "category": "network",
                    "proposed_risk_tier": "low",
                    "change_note": "From today's VPN incident.",
                },
            ),
        )
        if not draft:
            return
        did = draft["id"]
        self.w.tell(
            f"mai.bn drafts {'an edit of' if exists else 'a new page,'} '{KB_DRAFT_SLUG}', and submits it for review"
        )
        self.w.attempt("mai.bn", "submit draft", lambda: mai.post(f"/api/kb/drafts/{did}/submit"))
        self.w.pause()
        self.w.attempt(
            "huy.pq",
            "review draft",
            lambda: huy.post(
                f"/api/kb/drafts/{did}/review",
                {"decision": "request_changes", "comment": "Say where the self-service portal is."},
            ),
        )
        self.w.tell("  huy.pq asks for changes")
        current = (
            self.w.attempt("mai.bn", "read draft", lambda: mai.get(f"/api/kb/drafts/{did}")) or {}
        )
        body = (current.get("body") or "").replace(
            "self-service portal",
            "self-service portal (https://self-service.clientvpn.amazonaws.com)",
        )
        self.w.attempt(
            "mai.bn",
            "edit draft",
            lambda: mai.patch(
                f"/api/kb/drafts/{did}", {"body": body, "change_note": "Portal address added."}
            ),
        )
        self.w.attempt("mai.bn", "resubmit draft", lambda: mai.post(f"/api/kb/drafts/{did}/submit"))
        self.w.attempt(
            "quang.nv",
            "review draft",
            lambda: quang.post(
                f"/api/kb/drafts/{did}/review", {"decision": "approve", "comment": "Clear. Thanks."}
            ),
        )
        self.w.tell("  mai.bn edits and resubmits; quang.nv approves")

    def managers_oversee(self) -> None:
        """The managers read the dashboard and reports, check workload, and rebalance a ticket."""
        huy, quang = self.w.as_("huy.pq"), self.w.as_("quang.nv")
        for path in (
            "/api/metrics/dashboard",
            "/api/reports/sla",
            "/api/reports/reviewers",
            "/api/reports/csat",
            "/api/rollout",
            "/api/security/summary",
        ):
            self.w.attempt("quang.nv", f"read {path}", lambda p=path: quang.get(p))
        self.w.tell("quang.nv reads the dashboard, SLA, reviewer and CSAT reports")
        for team in ("network", "access", "software", "hardware"):
            self.w.attempt(
                "huy.pq", "read workload", lambda t=team: huy.get(f"/api/teams/{t}/workload")
            )
        page = (
            self.w.attempt(
                "huy.pq", "list open tickets", lambda: huy.get("/api/tickets", view="open")
            )
            or {}
        )
        busy = [r for r in page.get("items", []) if r.get("assignee") == "duc.tm"]
        for row in busy:
            team = row.get("assigned_team")
            mates = (
                self.w.attempt(
                    "huy.pq", "read workload", lambda t=team: huy.get(f"/api/teams/{t}/workload")
                )
                if team
                else None
            ) or []
            free = sorted(
                (
                    m
                    for m in mates
                    if m["user"] != "duc.tm" and m["available"] and not m["on_leave"]
                ),
                key=lambda m: m["open"],
            )
            if not free:
                continue
            to = free[0]["user"]
            moved = self.w.attempt(
                "huy.pq",
                "reassign",
                lambda: huy.post(
                    f"/api/tickets/{row['public_id']}/reassign",
                    {
                        "to_user": to,
                        "reason_code": "workload",
                        "note": "Duc is on the VPN incident.",
                        "expected_version": row["version"],
                    },
                ),
            )
            if moved:
                self.w.tell(f"huy.pq moves {row['public_id']} from duc.tm to {to} (workload)")
            break

    def access_review(self) -> None:
        """The IT manager opens an access review of KB editors; the reviewers answer from their inbox."""
        huy = self.w.as_("huy.pq")
        campaign = self.w.attempt(
            "huy.pq",
            "open access review",
            lambda: huy.post(
                "/api/access/reviews",
                {
                    "name": "KB editors, November",
                    "fallback_reviewer": "quang.nv",
                    "on_no_answer": "flag",
                    "role": "urn:smart-ticket:role:system:kb-editor",
                },
            ),
        )
        if not campaign:
            return
        self.w.tell(f"huy.pq opens the access review '{campaign.get('name')}'")
        for reviewer in ("quang.nv", "huy.pq"):
            s = self.w.as_(reviewer)
            inbox = (
                self.w.attempt(
                    reviewer, "open review inbox", lambda s=s: s.get("/api/access/reviews/inbox")
                )
                or []
            )
            items = inbox.get("items", inbox) if isinstance(inbox, dict) else inbox
            for it in items:
                self.w.attempt(
                    reviewer,
                    "answer access review",
                    lambda s=s, it=it: s.post(
                        f"/api/access/reviews/items/{it['id']}/decide",
                        {"decision": "keep", "note": "Still edits help pages."},
                    ),
                )
                self.w.tell(
                    f"  {reviewer} keeps {it.get('user', it.get('grantee', '?'))}'s KB editor access"
                )

    def technician_books_leave(self) -> None:
        s = self.w.as_("vy.tt")
        start = dt.date.today() + dt.timedelta(days=3)
        self.w.attempt(
            "vy.tt",
            "book leave",
            lambda: s.post(
                "/api/me/leaves",
                {
                    "starts_on": start.isoformat(),
                    "ends_on": (start + dt.timedelta(days=1)).isoformat(),
                    "note": "Family event",
                },
            ),
        )
        self.w.tell("vy.tt books two days of leave next week")

    def everyone_reads_notifications(self) -> None:
        for (username, client), s in list(self.w.sessions.items()):
            unread = self.w.attempt(
                username,
                "read notifications",
                lambda s=s: s.get("/api/notifications", unread="true"),
            )
            if unread:
                items = unread.get("items", unread) if isinstance(unread, dict) else unread
                if items:
                    self.w.attempt(
                        username, "mark all read", lambda s=s: s.post("/api/notifications/read-all")
                    )

    # ── the day ──

    def run(self) -> None:
        w, req = self.w, self.requests
        w.tell("── 07:30 IT and HR set up the week's changes ──")
        self.it_creates_accounts()
        self.hr_imports_the_org()
        self.everyone_signs_in()
        self.manager_sets_up_new_staff()
        w.tell("── 09:00 morning questions in chat ──")
        self.ask_in_chat(req["morning"])
        w.tell("── 09:20 the ticket form, and a VPN outage ──")
        self.submit_forms(req["forms"])
        self.submit_forms(req["outage"])
        self.wait_for_triage([r.key for r in req["morning"] + req["forms"] + req["outage"]])
        w.tell("── 10:00 security, the incident, the review queue ──")
        self.security_triages_alerts()
        self.incident_manager_handles_outage()
        self.reviewers_work_the_queue()
        self.teams_work_their_tickets()
        w.tell("── 11:30 requesters check their tickets ──")
        self.requesters_check_in()
        self.head_reads_department()
        w.tell("── 13:30 afternoon ──")
        self.ask_in_chat(req["afternoon"])
        self.wait_for_triage([r.key for r in req["afternoon"]])
        self.reviewers_work_the_queue()
        self.teams_work_their_tickets()
        self.kb_editor_writes_a_page()
        self.incident_manager_resolves()
        self.requesters_check_in()
        self.teams_work_their_tickets()
        self.requesters_check_in()
        w.tell("── 16:30 oversight and housekeeping ──")
        self.managers_oversee()
        self.access_review()
        self.technician_books_leave()
        self.everyone_reads_notifications()
        w.sign_everyone_out()
        w.tell("── 17:30 everyone signs out ──")


def requests_for(scale: str) -> dict[str, list[Request]]:
    """The day's requests: a smoke run takes a few of each kind."""
    if scale == "smoke":
        return {
            "morning": MORNING_CHAT[:3],
            "forms": FORM_TICKETS[3:5],
            "outage": OUTAGE[:3],
            "afternoon": AFTERNOON_CHAT[:1],
        }
    return {
        "morning": MORNING_CHAT,
        "forms": FORM_TICKETS,
        "outage": OUTAGE,
        "afternoon": AFTERNOON_CHAT,
    }


__all__ = ["Day", "requests_for", "Persona", "EVERYONE", "ApiError"]
