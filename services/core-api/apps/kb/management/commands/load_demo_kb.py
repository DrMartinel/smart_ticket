"""
Load the demo knowledge base (repo-root `demo_kb/`) into `kb_articles`.

Reads two tracked files:

- `manifest.json`, written by `demo_kb/fetch.py`: every page's slug, path,
  source URL, proposed category and SHA-256.
- `curation.json`, written by people: risk tiers, and which articles are
  approved for auto-reply.

Every page is checked against the SHA-256 in the manifest before it is
loaded, so the KB in the database is exactly the snapshot the manifest
names. Reloading is idempotent: unchanged articles are not re-embedded.

Auto-reply approval goes through `KbArticle.set_auto_reply_allowed` with a
named manager and a reason, like any approval (ADR-0002). Each approval in
`curation.json` is pinned to the SHA-256 of the text that was reviewed. If
a later snapshot changes that text, the approval is not applied, and an
existing one is revoked: a person approved the old wording, not the new.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.accounts.models import User
from apps.kb.models import KbArticle
from apps.kb.utils import clean_markdown
from apps.tickets.utils.router import RiskTier
from infrastructure.dtos import TicketCategory

SLUG_MAX_LENGTH = KbArticle._meta.get_field("slug").max_length


class ManifestPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str = Field(min_length=1, max_length=SLUG_MAX_LENGTH, pattern=r"^[^/]+$")
    path: str
    url: str
    category: TicketCategory
    title: str
    sha256: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    snapshot_sha256: str
    pages: list[ManifestPage]


class Approval(BaseModel):
    slug: str
    sha256: str
    reason: str = Field(min_length=1)


class Curation(BaseModel):
    category_risk_tier: dict[TicketCategory, RiskTier]
    risk_tiers: dict[str, RiskTier] = {}
    auto_reply: list[Approval] = []


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Command(BaseCommand):
    help = "Load the demo KB snapshot (demo_kb/) into the knowledge base."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dir", default=settings.DEMO_KB_DIR, help="demo KB directory")
        parser.add_argument(
            "--approver",
            help="username of the manager who applies curation.json's auto-reply "
            "approvals; without it, no approvals are applied",
        )
        parser.add_argument("--limit", type=int, help="load only the first N pages (smoke test)")

    def handle(self, *args: Any, **options: Any) -> None:
        root = Path(options["dir"])
        manifest = self._read(root / "manifest.json", Manifest)
        curation = self._read(root / "curation.json", Curation)
        approver = self._approver(options["approver"], curation)

        # Refuse before loading anything: approving anything above `low`
        # risk contradicts spec §14 P4, and fixing it later means a manager
        # revoking what a script granted.
        for approval in curation.auto_reply:
            tier = curation.risk_tiers.get(approval.slug)
            if tier != RiskTier.LOW:
                raise CommandError(
                    f"curation.json approves {approval.slug} for auto-reply, but its risk tier "
                    f"is {tier or 'unset'}; only risk_tiers[slug] = 'low' may be approved"
                )

        pages = manifest.pages[: options["limit"]]
        uncovered = {p.category for p in pages} - set(curation.category_risk_tier)
        if uncovered:
            raise CommandError(
                "curation.json category_risk_tier has no default for: "
                + ", ".join(sorted(uncovered))
            )
        counts = {"created_or_updated": 0, "unchanged": 0, "missing": 0, "hash_mismatch": 0}
        for i, page in enumerate(pages, 1):
            file = root / page.path
            if not file.exists():
                counts["missing"] += 1
                continue
            # Bytes, not read_text: text mode turns "\r\n" into "\n", so a
            # page with Windows line endings would fail its own hash.
            raw = file.read_bytes().decode("utf-8")
            if sha256(raw) != page.sha256:
                counts["hash_mismatch"] += 1
                self.stderr.write(f"  hash mismatch, skipped: {page.path}")
                continue
            _, changed = KbArticle.objects.upsert_from_source(
                slug=page.slug,
                title=page.title or page.slug,
                body=clean_markdown(raw),
                category=page.category.value,
                risk_tier=curation.risk_tiers.get(
                    page.slug, curation.category_risk_tier[page.category]
                ).value,
                source_url=page.url,
            )
            counts["created_or_updated" if changed else "unchanged"] += 1
            if i % 100 == 0:
                self.stdout.write(f"  {i}/{len(pages)}")

        if approver is not None:
            loaded = {p.slug: p.sha256 for p in pages}
            self._apply_approvals(curation.auto_reply, loaded, approver)

        self.stdout.write(
            self.style.SUCCESS(
                f"demo KB snapshot {manifest.snapshot_sha256[:12]}: "
                + ", ".join(f"{k}={v}" for k, v in counts.items())
            )
        )
        if counts["missing"] or counts["hash_mismatch"]:
            self.stdout.write(
                self.style.WARNING(
                    "The loaded KB is not the full snapshot: run demo_kb/fetch.py for missing "
                    "pages; a hash mismatch means a file was edited or re-fetched after "
                    "the manifest was written."
                )
            )

    def _read[T: BaseModel](self, path: Path, schema: type[T]) -> T:
        if not path.exists():
            raise CommandError(f"{path} not found (set --dir or DEMO_KB_DIR)")
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise CommandError(f"{path} is invalid:\n{e}") from e

    def _approver(self, username: str | None, curation: Curation) -> User | None:
        if username is None:
            if curation.auto_reply:
                self.stdout.write(
                    self.style.WARNING(
                        f"no --approver: skipping {len(curation.auto_reply)} auto-reply "
                        "approvals in curation.json"
                    )
                )
            return None
        user = User.objects.filter(username=username).first()
        # Checked here as well as in set_auto_reply_allowed, so a wrong
        # username fails before thousands of pages are embedded.
        if user is None or not user.is_manager:
            raise CommandError(f"--approver {username!r} must be an existing manager-role user")
        return user

    def _apply_approvals(
        self, approvals: list[Approval], loaded: dict[str, str], approver: User
    ) -> None:
        for approval in approvals:
            current = loaded.get(approval.slug)
            article = KbArticle.objects.filter(slug=approval.slug).first()
            if current is None or article is None:
                self.stderr.write(f"  approval for {approval.slug} skipped: not loaded")
                continue
            if current != approval.sha256:
                self.stderr.write(
                    f"  approval for {approval.slug} not applied: content changed since "
                    f"review ({approval.sha256[:12]} -> {current[:12]})"
                )
                if article.auto_reply_allowed:
                    article.set_auto_reply_allowed(
                        allowed=False,
                        actor=approver,
                        reason=f"Demo KB: source text changed since approval "
                        f"({approval.sha256[:12]} -> {current[:12]}); needs re-review",
                    )
                continue
            if not article.auto_reply_allowed:
                article.set_auto_reply_allowed(allowed=True, actor=approver, reason=approval.reason)
                self.stdout.write(f"  auto_reply_allowed=True: {approval.slug}")
