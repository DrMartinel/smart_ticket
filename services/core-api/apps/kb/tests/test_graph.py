"""The entity graph as a KB feature (F11, ADR-0037): edits keep edges until the rebuild, editors'
corrections outlive it, and nothing about an edge reaches a decision."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.audit.models import AuditLog
from apps.incidents.utils.incidents import incidents
from apps.kb.models import (
    AssociationSource,
    KbArticle,
    KbArticleAssociation,
    KbAssociationOverride,
    KbGraphRebuildRequest,
    OverrideAction,
    RebuildReason,
    RebuildState,
)
from apps.kb.utils.graph import cited_by_expansion, kb_graph
from apps.kb.utils.indexing import indexer
from apps.tickets.models import AiRun, IncidentVerdict, RoutingDecision, Ticket
from apps.tickets.tasks import process_ticket
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import Branch
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import (
    AIRunResponse,
    ClassificationSignals,
    EngineSignals,
    GenerationSignals,
    RetrievalSignals,
    TicketCategory,
)
from apps.tickets.tests.test_router import auto_reply_proposal

pytestmark = pytest.mark.django_db

VPN = "client-vpn-user.windows-troubleshooting"
COMMON = "client-vpn-user.common-troubleshooting"
WORKSPACES = "workspaces-user.client_troubleshooting"
OTHERS = ["client-vpn-user.connect", "client-vpn-user.macos-troubleshooting"]


def person(username: str, role: UserRole, *, editor: bool = False) -> User:
    user = User.objects.create_user(username=username, password="x", role=role.value)
    if editor:
        UserCapability.objects.create(
            user=user, capability=Capability.KB_EDITOR.value, source="local"
        )
    return user


def page(slug: str, body: str = "text") -> KbArticle:
    return KbArticle.objects.create(slug=slug, title=slug, body=body, category="network")


def edge(source: KbArticle, target: KbArticle, score: float = 1.0) -> KbArticleAssociation:
    return KbArticleAssociation.objects.create(
        source_article=source,
        target_article=target,
        source=AssociationSource.ENTITY_GRAPH,
        score=score,
        evidence=[f"symptom on {source.slug} -> remedy on {target.slug}"],
        build_id="entity_graph:v1:pairs-abc:2026-10-07",
    )


@pytest.fixture
def team() -> dict[str, User]:
    return {
        "mai": person("mai.bn", UserRole.TECHNICIAN, editor=True),
        "huy": person("huy.pq", UserRole.MANAGER),
        "tech": person("tuan.nv", UserRole.TECHNICIAN),
        "lan": person("lan.nt", UserRole.EMPLOYEE),
    }


@pytest.fixture
def clients(team, api_as) -> dict:
    return {name: api_as(user) for name, user in team.items()}


@pytest.fixture
def vpn() -> KbArticle:
    """The seed page in F11 §g with four outgoing edges."""
    seed = page(VPN)
    edge(seed, page(COMMON), 3)
    edge(seed, page(WORKSPACES), 1)
    for slug in OTHERS:
        edge(seed, page(slug), 1)
    return seed


class TestIngest:
    def test_ingest_marks_edges_stale_not_deleted(self, vpn):
        """AC-F11-01, first half (BR-F11-01): an edit keeps the page's edges, both ways, as stale,
        and files one pending rebuild request."""
        incoming = edge(KbArticle.objects.get(slug=COMMON), vpn)
        unrelated = edge(KbArticle.objects.get(slug=COMMON), KbArticle.objects.get(slug=WORKSPACES))

        vpn.body = "Edited text."
        vpn.save(update_fields=["body"])
        indexer.ingest(vpn)
        indexer.ingest(vpn)

        out = KbArticleAssociation.objects.filter(source_article=vpn)
        assert out.count() == 4
        assert all(e.stale for e in out)
        incoming.refresh_from_db()
        unrelated.refresh_from_db()
        assert (incoming.stale, unrelated.stale) == (True, False)
        pending = KbGraphRebuildRequest.objects.filter(article=vpn, state=RebuildState.PENDING)
        assert [(r.reason, r.requested_by) for r in pending] == [("publish", None)]
        assert AuditLog.objects.filter(event="kb_graph_rebuild_requested").count() == 1

    def test_a_snapshot_reload_files_no_rebuild_request(self):
        """The demo snapshot's graph comes from its committed pairs (`--rescore-only`), so a
        3,542-page load must not queue 3,542 extractions."""
        fields = dict(category="network", risk_tier="medium", title="VPN")
        url = "https://docs.aws.amazon.com/vpn/client-vpn-user/windows-troubleshooting.html"
        KbArticle.objects.upsert_from_source(slug=VPN, body="one", source_url=url, **fields)
        KbArticle.objects.upsert_from_source(slug=VPN, body="two", source_url=url, **fields)

        assert not KbGraphRebuildRequest.objects.exists()

    def test_a_failed_ingest_leaves_edges_fresh_and_files_nothing(self, vpn, monkeypatch):
        def down(text):
            raise RuntimeError("embedder down")

        monkeypatch.setattr(ai_engine, "embed", down)

        with pytest.raises(RuntimeError):
            indexer.ingest(vpn)

        assert not KbArticleAssociation.objects.filter(stale=True).exists()
        assert not KbGraphRebuildRequest.objects.exists()


class TestPageGraph:
    def test_editor_sees_edges_overrides_and_requests(self, clients, team, vpn):
        """UC-F11-01 (FR-F11-004)."""
        incoming = page("vpc.client-vpn")
        edge(incoming, vpn, 2)
        kb_graph.add_override(
            VPN, WORKSPACES, OverrideAction.HIDE, "Không liên quan VPN", team["mai"]
        )
        kb_graph.add_override(
            VPN, "vpc.client-vpn", OverrideAction.ADD, "trang quản trị", team["mai"]
        )
        kb_graph.request_rebuild(vpn, RebuildReason.MANUAL, team["mai"])

        body = clients["mai"].get(f"/api/kb/{VPN}/graph").json()

        assert [e["slug"] for e in body["outgoing"]] == [COMMON, *sorted(OTHERS + [WORKSPACES])] + [
            "vpc.client-vpn"
        ]
        first = body["outgoing"][0]
        assert (first["score"], first["stale"], first["reviewed"], first["override"]) == (
            3.0,
            False,
            False,
            None,
        )
        assert first["evidence"] and first["build_id"].startswith("entity_graph:")
        hidden = next(e for e in body["outgoing"] if e["slug"] == WORKSPACES)
        assert hidden["override"]["action"] == "hide"
        assert hidden["override"]["created_by"] == "mai.bn"
        added = body["outgoing"][-1]
        assert (added["score"], added["override"]["action"]) == (None, "add")
        assert [e["slug"] for e in body["incoming"]] == ["vpc.client-vpn"]
        assert body["pending_request"]["reason"] == "manual"
        assert body["last_build"] is None

    def test_last_build_is_the_latest_finished_request(self, clients, vpn):
        older = KbGraphRebuildRequest.objects.create(article=vpn, reason="publish", state="done")
        newer = KbGraphRebuildRequest.objects.create(article=vpn, reason="manual", state="failed")
        now = timezone.now()
        KbGraphRebuildRequest.objects.filter(id=older.id).update(
            done_at=now - timedelta(hours=1), build_id="b1"
        )
        KbGraphRebuildRequest.objects.filter(id=newer.id).update(done_at=now)

        body = clients["huy"].get(f"/api/kb/{VPN}/graph").json()

        assert body["last_build"]["state"] == "failed"
        assert body["pending_request"] is None

    @pytest.mark.parametrize("who", ["tech", "lan"])
    def test_only_kb_editors_and_managers_read_the_graph(self, clients, vpn, who):
        assert clients[who].get(f"/api/kb/{VPN}/graph").status_code == 403

    def test_an_unknown_page_is_404(self, clients):
        response = clients["mai"].get("/api/kb/no-such-page/graph")
        assert (response.status_code, response.json()["code"]) == (404, "article_not_found")


class TestCorrections:
    def test_confirm_marks_the_edge_reviewed_and_audits(self, clients, team, vpn):
        """UC-F11-02 (FR-F11-008)."""
        response = clients["mai"].post(f"/api/kb/{VPN}/graph/edges/{COMMON}/confirm")

        assert response.status_code == 200
        assert response.json()["reviewed"] is True
        assert KbArticleAssociation.objects.get(
            source_article=vpn, target_article__slug=COMMON
        ).reviewed
        row = AuditLog.objects.get(event="kb_graph_edge_confirmed")
        assert (row.actor_id, row.payload["target"]) == (team["mai"].id, COMMON)

    def test_confirming_a_pointer_that_was_never_built_is_404(self, clients, vpn):
        page("vpc.client-vpn")
        response = clients["mai"].post(f"/api/kb/{VPN}/graph/edges/vpc.client-vpn/confirm")
        assert (response.status_code, response.json()["code"]) == (404, "edge_not_found")

    def test_hide_then_remove_with_reasons(self, clients, team, vpn):
        hide = clients["mai"].post(
            f"/api/kb/{VPN}/graph/overrides",
            {"target": WORKSPACES, "action": "hide", "reason": "Không liên quan VPN"},
            content_type="application/json",
        )
        assert hide.status_code == 201
        assert hide.json()["action"] == "hide"

        again = clients["mai"].post(
            f"/api/kb/{VPN}/graph/overrides",
            {"target": WORKSPACES, "action": "add", "reason": "đổi ý"},
            content_type="application/json",
        )
        assert (again.status_code, again.json()["code"]) == (409, "override_exists")

        removed = clients["mai"].delete(
            f"/api/kb/{VPN}/graph/overrides/{WORKSPACES}",
            {"reason": "đã sửa trang"},
            content_type="application/json",
        )
        assert removed.status_code == 204
        assert not KbAssociationOverride.objects.exists()
        events = list(
            AuditLog.objects.filter(event__startswith="kb_graph_override")
            .order_by("occurred_at")
            .values_list("event", "payload__reason")
        )
        assert events == [
            ("kb_graph_override_added", "Không liên quan VPN"),
            ("kb_graph_override_removed", "đã sửa trang"),
        ]

    def test_a_page_cannot_point_at_itself(self, clients, vpn):
        response = clients["mai"].post(
            f"/api/kb/{VPN}/graph/overrides",
            {"target": VPN, "action": "add", "reason": "x"},
            content_type="application/json",
        )
        assert (response.status_code, response.json()["code"]) == (422, "self_edge")
        assert not KbAssociationOverride.objects.exists()

    def test_an_override_needs_a_reason(self, clients, vpn):
        response = clients["mai"].post(
            f"/api/kb/{VPN}/graph/overrides",
            {"target": COMMON, "action": "hide", "reason": " "},
            content_type="application/json",
        )
        assert response.status_code == 422
        assert not KbAssociationOverride.objects.exists()

    def test_removing_a_missing_override_is_404(self, clients, vpn):
        response = clients["mai"].delete(
            f"/api/kb/{VPN}/graph/overrides/{COMMON}",
            {"reason": "x"},
            content_type="application/json",
        )
        assert (response.status_code, response.json()["code"]) == (404, "override_not_found")

    @pytest.mark.parametrize("who", ["huy", "tech"])
    def test_corrections_are_kb_editors_only(self, clients, vpn, who):
        """§h: confirm and overrides are kb_editor's; a manager reads and rebuilds."""
        confirm = clients[who].post(f"/api/kb/{VPN}/graph/edges/{COMMON}/confirm")
        hide = clients[who].post(
            f"/api/kb/{VPN}/graph/overrides",
            {"target": COMMON, "action": "hide", "reason": "x"},
            content_type="application/json",
        )
        assert (confirm.status_code, hide.status_code) == (403, 403)


class TestRebuildRequests:
    def test_a_second_manual_rebuild_while_pending_is_409(self, clients, team, vpn):
        """UC-F11-03."""
        first = clients["huy"].post(f"/api/kb/{VPN}/graph/rebuild")
        assert first.status_code == 201
        assert (first.json()["reason"], first.json()["state"]) == ("manual", "pending")

        second = clients["mai"].post(f"/api/kb/{VPN}/graph/rebuild")
        assert (second.status_code, second.json()["code"]) == (409, "already_pending")
        row = AuditLog.objects.get(event="kb_graph_rebuild_requested")
        assert row.actor_id == team["huy"].id

    def test_a_publish_while_a_manual_request_is_pending_adds_none(self, team, vpn):
        kb_graph.request_rebuild(vpn, RebuildReason.MANUAL, team["mai"])
        indexer.ingest(vpn)

        assert KbGraphRebuildRequest.objects.filter(article=vpn).count() == 1

    def test_after_a_build_a_new_request_may_be_filed(self, clients, vpn):
        KbGraphRebuildRequest.objects.create(article=vpn, reason="manual", state="done")
        assert clients["mai"].post(f"/api/kb/{VPN}/graph/rebuild").status_code == 201


class TestHealth:
    def test_cited_by_expansion_reads_jevs_top_passage(self):
        chunks = [
            {"kb_slug": COMMON, "rerank_score": 0.2, "origin": "fused"},
            {"kb_slug": VPN, "rerank_score": 0.7, "origin": "expansion"},
        ]
        assert cited_by_expansion(chunks)
        assert not cited_by_expansion([{"kb_slug": VPN, "rerank_score": 0.7}])
        assert not cited_by_expansion([])

    def test_kb_report_carries_graph_health(self, clients, team, vpn):
        """UC-F11-04 (FR-F11-007)."""
        kb_graph.mark_stale(vpn)
        kb_graph.add_override(
            VPN, WORKSPACES, OverrideAction.HIDE, "Không liên quan VPN", team["mai"]
        )
        kb_graph.request_rebuild(vpn, RebuildReason.MANUAL, team["mai"])

        graph = clients["huy"].get("/api/reports/kb").json()["graph"]

        assert (graph["pages"], graph["pages_with_edges"], graph["edges"]) == (5, 1, 4)
        assert (graph["stale_edges"], graph["hidden"], graph["added"]) == (4, 1, 0)
        assert (graph["pending_requests"], graph["failed_requests"]) == (1, 0)
        assert graph["auto_replies"] == 0 and graph["expansion_share"] is None

    def test_the_expansion_share_counts_only_runs_that_report_origins(self, team, vpn):
        """A run from before F11 has no `origin`; counting it as fused would understate the
        share."""
        reporter = team["lan"]
        for i, chunks in enumerate(
            [
                [{"kb_slug": VPN, "rerank_score": 0.9}],
                [{"kb_slug": VPN, "rerank_score": 0.9, "origin": "expansion"}],
                [{"kb_slug": VPN, "rerank_score": 0.9, "origin": "fused"}],
            ]
        ):
            ticket = Ticket.objects.create(
                public_id=f"TKT-H-{i}", reporter=reporter, subject_masked="s", body_masked="b"
            )
            run = AiRun.objects.create(
                ticket=ticket,
                idempotency_key=f"h-{i}",
                prompt_version="t",
                model="t",
                graph_version="t",
                trust_signals={},
                retrieved_chunks=chunks,
            )
            RoutingDecision.objects.create(
                ticket=ticket,
                ai_run=run,
                branch=Branch.AUTO_REPLY.value,
                reason_code="ok",
                thresholds_used={},
            )

        health = kb_graph.health(timezone.now() - timedelta(days=1))

        assert (health.auto_replies, health.auto_replies_from_expansion) == (2, 1)
        assert health.expansion_share == 0.5


def _engine_response(origin: str, request_id: str) -> AIRunResponse:
    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="test",
        proposal=auto_reply_proposal(kb_slug=VPN),
        retrieved_chunks=[
            {"kb_slug": VPN, "rerank_score": 0.95, "origin": origin},
            {"kb_slug": COMMON, "rerank_score": 0.02, "origin": "fused"},
        ],
        signals=EngineSignals(
            retrieval=RetrievalSignals(
                rerank_top1=0.95,
                rerank_margin=0.9,
                docs_above_floor=1,
                rerank_confidence=0.95,
                rerank_total=0.97,
            ),
            generation=GenerationSignals(
                quote_match_ratio=1.0,
                quote_source_in_topk=True,
                negation_consistent=True,
                cited_is_rerank_choice=True,
            ),
            classification=ClassificationSignals(
                category_choice=TicketCategory.NETWORK, category_confidence=0.9
            ),
            injection_detected=False,
        ),
    )


def test_where_the_cited_page_came_from_changes_no_decision(team, vpn, monkeypatch):
    """AC-F11-04 (BR-F11-04): identical signals, one cited page from expansion, same score and
    branch."""
    vpn.risk_tier = "low"
    vpn.save(update_fields=["risk_tier"])
    vpn.set_auto_reply_allowed(allowed=True, actor=team["huy"], reason="reviewed")
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    origins = iter(["fused", "expansion"])
    monkeypatch.setattr(
        ai_engine, "analyze", lambda masked, request_id: _engine_response(next(origins), request_id)
    )
    tickets = [
        Ticket.objects.create(
            public_id=f"TKT-F11-{i}",
            reporter=team["lan"],
            subject_masked="VPN không kết nối",
            body_masked="TLS handshake failed",
            pii_level=PIILevel.ROUTINE.value,
        )
        for i in range(2)
    ]

    for ticket in tickets:
        process_ticket.apply(args=(ticket.id,)).get()

    runs = [t.ai_runs.get() for t in tickets]
    decisions = [t.routing_decisions.get() for t in tickets]
    assert [cited_by_expansion(r.retrieved_chunks) for r in runs] == [False, True]
    assert runs[0].trust_score == runs[1].trust_score
    assert [d.branch for d in decisions] == [Branch.AUTO_REPLY.value] * 2
