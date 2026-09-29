"""
`load_demo_kb` loads the demo KB snapshot and applies auto-reply approvals.

Two properties matter more than loading itself:

- The database holds exactly the snapshot the manifest names. A page whose
  hash doesn't match is skipped, not loaded "close enough".
- Auto-reply authority comes only from a named manager, through the
  governance path (ADR-0002), for the exact text that was reviewed. If the
  text changes, the approval must not carry over to it.
"""

import hashlib
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.kb.models import KbArticle, KbAuthorityLog, KbChunk

SSH = '# Resolve SSH errors\n<a name="ssh"></a>\n\nCheck that port 22 is open.\n'
MFA = "# Use MFA\n\nRegister a virtual MFA device.\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_snapshot(root: Path, pages: dict[str, tuple[str, str]], curation: dict) -> None:
    """pages: slug -> (category, markdown)."""
    entries = []
    for slug, (category, text) in pages.items():
        path = f"guides/{slug.replace('.', '/')}.md"
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
        entries.append(
            {
                "slug": slug,
                "path": path,
                "url": f"https://docs.aws.amazon.com/{slug}.html",
                "category": category,
                "title": text.splitlines()[0].removeprefix("# "),
                "sha256": sha(text),
            }
        )
    (root / "manifest.json").write_text(json.dumps({"snapshot_sha256": "s" * 64, "pages": entries}))
    (root / "curation.json").write_text(json.dumps(curation))


CURATION = {
    "category_risk_tier": {"hardware": "medium", "access": "high"},
    "risk_tiers": {"ec2.ssh": "low"},
    "auto_reply": [{"slug": "ec2.ssh", "sha256": sha(SSH), "reason": "reviewed, low risk"}],
}


def load(root: Path, **options) -> None:
    call_command("load_demo_kb", dir=str(root), stdout=StringIO(), stderr=StringIO(), **options)


@pytest.fixture
def snapshot(tmp_path):
    write_snapshot(tmp_path, {"ec2.ssh": ("hardware", SSH), "iam.mfa": ("access", MFA)}, CURATION)
    return tmp_path


@pytest.mark.django_db
def test_pages_are_loaded_with_source_url_risk_tier_and_chunks(snapshot):
    load(snapshot)

    ssh = KbArticle.objects.get(slug="ec2.ssh")
    assert ssh.title == "Resolve SSH errors"
    assert ssh.source_url == "https://docs.aws.amazon.com/ec2.ssh.html"
    assert "<a name=" not in ssh.body
    assert ssh.risk_tier == "low"
    assert KbArticle.objects.get(slug="iam.mfa").risk_tier == "high"  # category default
    assert KbChunk.objects.filter(article=ssh).exists()
    # No approver given: nothing is approved.
    assert not KbArticle.objects.filter(auto_reply_allowed=True).exists()


@pytest.mark.django_db
def test_approvals_go_through_the_governance_path(snapshot, manager_user):
    load(snapshot, approver=manager_user.username)

    ssh = KbArticle.objects.get(slug="ec2.ssh")
    assert ssh.auto_reply_allowed and ssh.approved_by == manager_user
    log = KbAuthorityLog.objects.get(article=ssh, field="auto_reply_allowed")
    assert log.actor == manager_user and log.reason == "reviewed, low risk"
    assert not KbArticle.objects.get(slug="iam.mfa").auto_reply_allowed


@pytest.mark.django_db
def test_reloading_is_idempotent(snapshot, manager_user):
    load(snapshot, approver=manager_user.username)
    chunk_ids = set(KbChunk.objects.values_list("id", flat=True))

    load(snapshot, approver=manager_user.username)

    assert set(KbChunk.objects.values_list("id", flat=True)) == chunk_ids
    assert KbAuthorityLog.objects.count() == 1


@pytest.mark.django_db
def test_changed_text_revokes_an_approval_given_for_the_old_text(snapshot, manager_user):
    """A manager approved the wording they read. If AWS rewrites the page,
    auto-replying from the new text would use authority nobody granted."""
    load(snapshot, approver=manager_user.username)
    new_ssh = SSH + "\nAlso check the network ACL.\n"
    write_snapshot(
        snapshot, {"ec2.ssh": ("hardware", new_ssh), "iam.mfa": ("access", MFA)}, CURATION
    )

    load(snapshot, approver=manager_user.username)

    ssh = KbArticle.objects.get(slug="ec2.ssh")
    assert "network ACL" in ssh.body
    assert not ssh.auto_reply_allowed
    revoke = KbAuthorityLog.objects.filter(article=ssh).latest("changed_at")
    assert revoke.new_value == "False" and "changed since approval" in revoke.reason


@pytest.mark.django_db
def test_a_page_whose_hash_does_not_match_the_manifest_is_skipped(snapshot):
    (snapshot / "guides/iam/mfa.md").write_text(MFA + "edited by hand\n")

    load(snapshot)

    assert not KbArticle.objects.filter(slug="iam.mfa").exists()
    assert KbArticle.objects.filter(slug="ec2.ssh").exists()


@pytest.mark.django_db
def test_a_page_with_windows_line_endings_matches_its_hash(tmp_path):
    """Two real AWS pages contain "\r\n". Reading them in text mode
    normalizes the line endings, changes the hash, and would skip valid pages
    as if they had been edited."""
    crlf = "# Send an email\r\n\r\nChoose Send test email.\r\n"
    curation = {**CURATION, "category_risk_tier": {"software": "medium"}, "auto_reply": []}
    write_snapshot(tmp_path, {"ses.send": ("software", crlf)}, curation)
    (tmp_path / "guides/ses/send.md").write_bytes(crlf.encode())

    load(tmp_path)

    assert KbArticle.objects.filter(slug="ses.send").exists()


@pytest.mark.django_db
def test_approving_an_article_that_is_not_low_risk_is_refused(tmp_path, manager_user):
    curation = {**CURATION, "risk_tiers": {}}
    write_snapshot(tmp_path, {"ec2.ssh": ("hardware", SSH)}, curation)

    with pytest.raises(CommandError, match="only risk_tiers"):
        load(tmp_path, approver=manager_user.username)
    assert not KbArticle.objects.exists()


@pytest.mark.django_db
def test_a_category_without_a_default_risk_tier_is_refused_before_anything_loads(tmp_path):
    """Otherwise the load dies partway, with thousands of pages already
    embedded and the rest missing."""
    write_snapshot(tmp_path, {"ses.send": ("software", MFA)}, {**CURATION, "auto_reply": []})

    with pytest.raises(CommandError, match="no default for: software"):
        load(tmp_path)
    assert not KbArticle.objects.exists()


@pytest.mark.django_db
def test_a_non_manager_approver_is_refused_before_anything_loads(snapshot, technician_user):
    with pytest.raises(CommandError, match="manager-role"):
        load(snapshot, approver=technician_user.username)
    assert not KbArticle.objects.exists()


@pytest.mark.django_db
def test_an_article_left_without_chunks_is_re_embedded_on_reload(snapshot):
    """create_and_ingest commits the row before embedding. If embedding
    failed, a reload must retry it, not report the article as unchanged."""
    load(snapshot)
    KbChunk.objects.all().delete()

    load(snapshot)

    assert KbChunk.objects.filter(article__slug="ec2.ssh").exists()


@pytest.mark.django_db
def test_chunks_from_an_older_chunker_are_replaced_on_reload(snapshot):
    """An interrupted first load left client-vpn-admin articles chunked by
    the chunker of that time. The body hadn't changed, so a reload called
    them unchanged and retrieval kept searching the old chunks."""
    load(snapshot)
    stale = KbChunk.objects.get(article__slug="ec2.ssh", chunk_index=0)
    stale.content = "text an older chunker produced"
    stale.save(update_fields=["content"])

    load(snapshot)

    contents = KbChunk.objects.filter(article__slug="ec2.ssh").values_list("content", flat=True)
    assert "text an older chunker produced" not in contents
    assert KbArticle.objects.get(slug="ec2.ssh").chunks_are_current()


@pytest.mark.django_db
def test_a_new_title_re_embeds_an_unchanged_body():
    """The title is part of each chunk's embedding input, so vectors made
    under the old title no longer describe the article."""
    fields = dict(
        slug="ec2.ssh",
        body="Check port 22.",
        category="hardware",
        risk_tier="medium",
        source_url="https://docs.aws.amazon.com/ec2.ssh.html",
    )
    KbArticle.objects.upsert_from_source(title="Resolve SSH errors", **fields)
    before = set(KbChunk.objects.values_list("id", flat=True))

    _, changed = KbArticle.objects.upsert_from_source(title="Fix SSH connection errors", **fields)

    after = set(KbChunk.objects.values_list("id", flat=True))
    assert changed and after and not after & before
