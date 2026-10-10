"""
`load_associations` (ADR-0018): ai-engine's offline `entity_graph.jsonl`
into `kb_article_associations`. The file is keyed by slug and may be older
than the database, so a slug it names can be gone; those lines are skipped
and counted, never guessed at. Inactive articles load: the read hides them.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation

pytestmark = pytest.mark.django_db


def _article(slug: str, *, active: bool = True) -> KbArticle:
    return KbArticle.objects.create(
        slug=slug, title=slug, body="x", category="access", is_active=active
    )


def _line(source: str, target: str, score: float = 6.38) -> dict:
    return {
        "source_slug": source,
        "target_slug": target,
        "score": score,
        "evidence": ["SES Sandbox"],
        "build_id": "entity_graph:kb_entity_graph.v1:pairs-abc:2026-10-10",
    }


def _load(tmp_path: Path, lines: list[dict]) -> str:
    path = tmp_path / "entity_graph.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    out = StringIO()
    call_command("load_associations", str(path), source="entity_graph", stdout=out)
    return out.getvalue()


def _pairs(source: str = AssociationSource.ENTITY_GRAPH) -> set[tuple[str, str]]:
    return set(
        KbArticleAssociation.objects.filter(source=source).values_list(
            "source_article__slug", "target_article__slug"
        )
    )


def test_unknown_slugs_and_self_pairs_are_skipped_and_counted_and_inactive_targets_load(tmp_path):
    _article("verify")
    _article("prod", active=False)

    out = _load(
        tmp_path,
        [
            _line("verify", "prod"),
            _line("prod", "verify"),
            _line("verify", "deleted"),
            _line("verify", "verify"),
        ],
    )

    assert _pairs() == {("verify", "prod"), ("prod", "verify")}
    assert "unknown_slug=1" in out and "self_pair=1" in out


def test_a_load_replaces_its_source_and_leaves_the_others(tmp_path):
    verify, prod, smtp = _article("verify"), _article("prod"), _article("smtp")
    KbArticleAssociation.objects.create(
        source_article=verify,
        target_article=smtp,
        source=AssociationSource.AUTHORED_LINK,
        score=1.0,
        build_id="t",
    )
    _load(tmp_path, [_line("verify", "smtp")])

    _load(tmp_path, [_line("verify", "prod")])

    assert _pairs() == {("verify", "prod")}
    assert _pairs(AssociationSource.AUTHORED_LINK) == {("verify", "smtp")}
    assert prod.associations_in.get().evidence == ["SES Sandbox"]


def test_reloading_the_same_file_gives_the_same_rows(tmp_path):
    _article("verify"), _article("prod")
    lines = [_line("verify", "prod"), _line("prod", "verify")]

    _load(tmp_path, lines)
    first = sorted(
        KbArticleAssociation.objects.values_list("source_article", "target_article", "score")
    )
    _load(tmp_path, lines)

    assert (
        sorted(
            KbArticleAssociation.objects.values_list("source_article", "target_article", "score")
        )
        == first
    )


def test_a_malformed_line_loads_nothing(tmp_path):
    """A broken file is not a few bad edges: keep the rows that were there."""
    _article("verify"), _article("prod")
    _load(tmp_path, [_line("verify", "prod")])
    path = tmp_path / "entity_graph.jsonl"
    path.write_text(json.dumps(_line("prod", "verify")) + "\n{not json\n")

    with pytest.raises(CommandError, match="entity_graph.jsonl:2"):
        call_command("load_associations", str(path), source="entity_graph", stdout=StringIO())

    assert _pairs() == {("verify", "prod")}


def test_load_demo_kb_loads_a_committed_entity_graph(tmp_path):
    from apps.kb.tests.test_load_demo_kb import CURATION, MFA, SSH, load, write_snapshot

    write_snapshot(tmp_path, {"ec2.ssh": ("hardware", SSH), "iam.mfa": ("access", MFA)}, CURATION)
    (tmp_path / "associations").mkdir()
    (tmp_path / "associations" / "entity_graph.jsonl").write_text(
        json.dumps(_line("ec2.ssh", "iam.mfa")) + "\n"
    )

    load(tmp_path)

    assert _pairs() == {("ec2.ssh", "iam.mfa")}
