"""What the simulated company shares during a run: signed-in people, the tickets they raised, and what went wrong."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .cast import EVERYONE, PASSWORD, Persona
from .client import ApiError, CallLog, Endpoints, Session


@dataclass
class Raised:
    """A request someone made and the ticket it became."""

    key: str
    who: str
    channel: str
    public_id: str
    conversation_id: str | None = None
    state: str = ""
    branch: str = ""
    reason: str = ""
    rated: bool = False
    replied: int = 0
    reopened: bool = False


@dataclass
class Finding:
    """Something a persona tried that the system refused or broke on."""

    persona: str
    action: str
    detail: str


@dataclass
class World:
    """The run's shared state."""

    ends: Endpoints
    log: CallLog
    rng: random.Random
    think: float
    sessions: dict[tuple[str, str], Session] = field(default_factory=dict)
    raised: dict[str, Raised] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    story: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_(self, username: str, client: str | None = None) -> Session:
        """The persona's session in their frontend, signing them in the first time."""
        persona: Persona = EVERYONE[username]
        key = (username, client or persona.client)
        if key not in self.sessions:
            session = Session(username, PASSWORD, key[1], self.ends, self.log)
            session.sign_in()
            self.sessions[key] = session
            self.tell(f"{username} signs in to the {key[1]} app")
        return self.sessions[key]

    def tell(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.story.append(f"{stamp} {line}")
        print(f"{stamp} {line}", flush=True)

    def count(self, what: str) -> None:
        self.counts[what] = self.counts.get(what, 0) + 1

    def pause(self, scale: float = 1.0) -> None:
        """A person's think time between two actions."""
        if self.think > 0:
            time.sleep(self.rng.uniform(0.3, 1.0) * self.think * scale)

    def attempt(self, persona: str, action: str, fn: Callable[[], Any]) -> Any:
        """Runs one action; a refusal or error becomes a finding instead of stopping the day."""
        try:
            result = fn()
            self.count(action)
            return result
        except ApiError as e:
            self.refused(persona, action, e)
        except Exception as e:  # noqa: BLE001
            self.findings.append(Finding(persona, action, f"{type(e).__name__}: {e}"))
            self.tell(f"  ✗ {persona}: {action} failed ({type(e).__name__}: {str(e)[:160]})")
        return None

    def refused(self, persona: str, action: str, e: ApiError) -> None:
        """Records a refusal as a finding."""
        self.findings.append(Finding(persona, action, f"{e.status} {e.body}"))
        self.tell(f"  ✗ {persona}: {action} refused ({e.status} {str(e.body)[:160]})")

    def wait_until(self, check: Callable[[], bool], timeout: float, every: float = 4.0) -> bool:
        """Polls like someone refreshing the page until `check` holds or `timeout` passes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return True
            time.sleep(every)
        return False

    def sign_everyone_out(self) -> None:
        for (username, _), session in self.sessions.items():
            try:
                session.sign_out()
            except ApiError:
                self.findings.append(Finding(username, "sign out", "refused"))
