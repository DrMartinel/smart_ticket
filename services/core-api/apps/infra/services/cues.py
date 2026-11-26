"""A ticket's cues (F17 §o, ADR-0048 decision 10): queued on commit at handoff while
`ticket_cues` is live, collected over the reporter's own Keystone projects, linked by a person
as their own read, and read by the ticket page. Cues change nothing about the ticket
(BR-F17-18)."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from functools import partial
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.domain.access import Access
from apps.accounts.domain.catalog import Permission
from apps.accounts.permissions import Caller
from apps.infra.clients.backends import (
    BackendUnavailable,
    alertmanager,
    elasticsearch,
    openstack,
    prometheus,
)
from apps.infra.domain.catalog import Catalog, Surface
from apps.infra.domain.cues import (
    TEMPLATES,
    USAGE,
    Clock,
    CueTemplate,
    Finding,
    Ratios,
    about,
    alerts_finding,
    cpu_query,
    error_counts,
    error_lines,
    failed,
    highest_cpu,
    iops_finding,
    iops_queries,
    iops_ratios,
    log_finding,
    most_errors,
    nearest_quota,
    not_running,
    overview_alerts,
    state_finding,
)
from apps.infra.domain.enrichment import Holdings, linked
from apps.infra.domain.queries import Window
from apps.infra.domain.resources import Network, Server, Volume
from apps.infra.domain.vocabulary import CueRunOutcome, InfraError, ResourceKind, ResourceSource
from apps.infra.models import CueRun, InfraQuery, InfraVia, TicketCue, TicketResource
from apps.infra.services.inventory import Inventory
from apps.infra.services.observability import Observability
from apps.infra.services.recording import QueryLog
from apps.infra.services.scope import InfraScope, member_projects
from apps.lifecycle.models import Transfer
from apps.rollout.domain.vocabulary import FlagBranch
from apps.rollout.services.rollout import rollout
from apps.sla.models import Calendar
from apps.tickets.domain.patterns import PIILevel
from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


class Enrichment:
    """Links a cue run to the resources its ticket is about, found among the projects its
    inventory reaches (BR-F17-14, BR-F17-24, FR-F17-018)."""

    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory

    def holdings(self) -> Holdings:
        """The servers, volumes and networks the inventory reaches, each listing one read."""
        return Holdings(
            self.inventory.servers(None),
            self.inventory.volumes(None),
            self.inventory.networks(None),
        )

    def link(self, run: CueRun, ticket: Ticket, holdings: Holdings) -> list[TicketResource]:
        """Stores the resources the ticket's masked subject and body name, or every server, in
        the order they are taken; a ticket whose masking failed names none."""
        text = (
            None
            if ticket.pii_level == PIILevel.MASK_FAILED.value
            else f"{ticket.subject_masked}\n{ticket.body_masked}"
        )
        found = linked(holdings, text, settings.THRESHOLDS.cues.max_resources)
        return TicketResource.objects.bulk_create(
            TicketResource(
                run=run,
                seq=seq,
                project_id=f.resource.project_id,
                kind=f.resource.kind.value,
                resource_id=f.resource.id,
                name=f.resource.name,
                source=f.source.value,
                token=f.token,
            )
            for seq, f in enumerate(found)
        )


class Collector:
    """Runs one cue run's templates through its reads and stores each cue, in order."""

    def __init__(
        self, run: CueRun, log: QueryLog, inventory: Inventory, observability: Observability
    ) -> None:
        assert run.window_start is not None and run.window_end is not None
        self.run = run
        self.log = log
        self.inventory = inventory
        self.observability = observability
        self.caps = settings.THRESHOLDS.cues
        self.window = Window(run.window_start, run.window_end)
        zone = Calendar.objects.filter(is_default=True).values_list("timezone", flat=True).first()
        self.clock = Clock(ZoneInfo(zone) if zone else UTC)
        self.seq = 0

    def store(
        self,
        template: CueTemplate,
        resource: TicketResource | None,
        finding: Callable[[], Finding],
        query: InfraQuery | None = None,
    ) -> TicketCue:
        """Stores the cue `finding` makes, or the one its failed read leaves, with the first
        query it ran."""
        before = len(self.log.recorded)
        try:
            found = finding()
        except InfraError as e:
            found = failed(template, e)
        query = query or next(iter(self.log.recorded[before:]), None)
        cue = TicketCue.objects.create(
            run=self.run,
            resource=resource,
            seq=self.seq,
            template=template.value,
            status=found.status.value,
            summary=found.summary,
            evidence=found.evidence,
            query=query,
            link=(query.link or None) if query else None,
        )
        self.seq += 1
        return cue

    def about(self, resource: TicketResource) -> None:
        """Runs the templates of `resource`'s kind."""
        for template in TEMPLATES[ResourceKind(resource.kind)]:
            self.store(template, resource, partial(self.finding, template, resource))

    def finding(self, template: CueTemplate, resource: TicketResource) -> Finding:
        step, kind = self.caps.step_seconds, ResourceKind(resource.kind)
        if template in USAGE:
            usage = USAGE[template]
            query = usage.query(resource.resource_id, self.window, step)
            series = self.observability.metrics(query, resource.project_id).series
            return usage.finding(resource.name, series, self.clock)
        if template is CueTemplate.SERVER_STATE:
            return state_finding(self.inventory.server(resource.resource_id), timezone.now())
        if template is CueTemplate.SERVER_ERROR_LOGS:
            search = error_lines(resource.resource_id, self.window, self.caps.log_lines)
            answer = self.observability.logs(search, resource.project_id)
            return log_finding(resource.name, answer.total, answer.lines)
        if template is CueTemplate.VOLUME_IOPS_QUOTA:
            ratios = self.ratios(resource.project_id, resource.resource_id)
            return iops_finding(resource.name, ratios, self.clock)
        alerts = self.inventory.alerts(resource.project_id)
        return alerts_finding(resource.name, about(alerts, kind, resource.resource_id), self.clock)

    def ratios(self, project_id: str | None, volume_id: str | None) -> list[Ratios]:
        """Each volume's IOPS rate over its quota, from two queries divided here."""
        rate, quota = iops_queries(self.window, self.caps.step_seconds, volume_id)
        rates = self.observability.metrics(rate, project_id).series
        quotas = self.observability.metrics(quota, project_id).series
        return iops_ratios(rates, quotas)

    def overview(self, holdings: Holdings, servers_read: InfraQuery | None) -> None:
        """Runs the overview set over every project the reads reach (BR-F17-24)."""
        top, step = self.caps.overview_top, self.caps.step_seconds
        server_ids = {s.name: s.id for s in holdings.servers}
        self.store(
            CueTemplate.OVERVIEW_ALERTS,
            None,
            lambda: overview_alerts(self.inventory.alerts(None), top, self.clock),
        )
        self.store(
            CueTemplate.OVERVIEW_NOT_RUNNING,
            None,
            lambda: not_running(holdings.servers, top, self.clock),
            servers_read,
        )

        def errors() -> Finding:
            answer = self.observability.log_counts(error_counts(self.window, top), None)
            return most_errors(answer.counts, server_ids)

        self.store(CueTemplate.OVERVIEW_ERROR_LOGS, None, errors)
        self.store(
            CueTemplate.OVERVIEW_IOPS_QUOTA,
            None,
            lambda: nearest_quota(self.ratios(None, None), top),
        )
        self.store(
            CueTemplate.OVERVIEW_CPU,
            None,
            lambda: highest_cpu(
                self.observability.metrics(cpu_query(self.window, step), None).series, top
            ),
        )


class Cues:
    """Queues, collects, links and reads a ticket's cue runs."""

    # ── at handoff (BR-F17-13) ──

    def on_status_entered(self, ticket: Ticket, transfer: Transfer) -> None:
        """Queues the ticket's cues on commit when `transfer` hands it off and `ticket_cues` is
        live."""
        try:
            with transaction.atomic():
                due = Transfer.objects.is_handoff(transfer) and rollout.is_live(
                    FlagBranch.TICKET_CUES
                )
        except Exception:  # noqa: BLE001 — cues never undo the move they follow
            logger.exception("infra: queueing cues for %s failed", ticket.public_id)
            return
        if not due:
            return
        from apps.infra import tasks

        ticket_id, transfer_id = str(ticket.id), str(transfer.id)
        transaction.on_commit(lambda: tasks.ticket_cues.delay(ticket_id, transfer_id), robust=True)

    def collect(self, ticket_id: uuid.UUID, transfer_id: uuid.UUID) -> None:
        """Runs the handoff's cues once, while `ticket_cues` is live; leaves a run that already
        exists as it is."""
        if not rollout.is_live(FlagBranch.TICKET_CUES):
            return
        run, created = CueRun.objects.get_or_create(
            transfer_id=transfer_id, defaults={"ticket_id": ticket_id}
        )
        if created:
            self.finish(run, lambda: self.handoff_outcome(run))

    def handoff_outcome(self, run: CueRun) -> CueRunOutcome:
        """Links the resources the ticket names among its reporter's Keystone projects and runs
        their templates, or runs the overview set when it links none."""
        ticket = Ticket.objects.select_related("reporter").get(pk=run.ticket_id)
        log, cloud = QueryLog.of_cues(ticket), openstack()
        started = time.monotonic()
        try:
            projects = member_projects(ticket.reporter, cloud)
        except BackendUnavailable as e:
            logger.warning("infra: cue scope for %s unavailable: %s", ticket.public_id, e)
            log.scope_unavailable(started)
            return CueRunOutcome.SCOPE_UNAVAILABLE
        if not projects:
            return CueRunOutcome.NO_CLOUD_USER
        self.open_window(run, ticket)
        scope = InfraScope(everything=False, project_ids=projects)
        inventory = Inventory(log, scope, cloud, alertmanager())
        observability = Observability(
            log, scope, Catalog(Surface.CUSTOMER), cloud, prometheus(), elasticsearch()
        )
        enrichment = Enrichment(inventory)
        before = len(log.recorded)
        holdings = enrichment.holdings()
        resources = enrichment.link(run, ticket, holdings)
        collector = Collector(run, log, inventory, observability)
        if not resources:
            collector.overview(holdings, log.recorded[before])
            return CueRunOutcome.OVERVIEW
        for resource in resources:
            collector.about(resource)
        return CueRunOutcome.DONE

    # ── a person links a resource (BR-F17-25) ──

    def link(self, ticket: Ticket, caller: Caller, kind: ResourceKind, resource_id: str) -> CueRun:
        """Queues a run of one resource's templates, started by `caller` and read as theirs;
        refuses a resource the cloud doesn't have with `infra_not_found`."""
        inventory = Inventory(
            QueryLog.of(caller, ticket), InfraScope.all(), openstack(), alertmanager()
        )
        reads: dict[ResourceKind, Callable[[str], Server | Volume | Network]] = {
            ResourceKind.SERVER: inventory.server,
            ResourceKind.VOLUME: inventory.volume,
            ResourceKind.NETWORK: inventory.network,
        }
        resource = reads[kind](resource_id)
        with transaction.atomic():
            run = CueRun.objects.create(ticket=ticket, started_by=caller.user)
            TicketResource.objects.create(
                run=run,
                seq=0,
                project_id=resource.project_id,
                kind=kind.value,
                resource_id=resource.id,
                name=resource.name,
                source=ResourceSource.LINKED.value,
            )
            from apps.infra import tasks

            run_id = str(run.id)
            transaction.on_commit(lambda: tasks.linked_cues.delay(run_id), robust=True)
        return run

    def collect_linked(self, run_id: uuid.UUID) -> None:
        """Runs a person's run once; leaves one past `running`, or with cues, as it is."""
        run = (
            CueRun.objects.select_related("ticket", "started_by")
            .filter(pk=run_id, outcome=CueRunOutcome.RUNNING.value, started_by__isnull=False)
            .first()
        )
        if run is not None and not run.cues.exists():
            self.finish(run, lambda: self.linked_outcome(run))

    def linked_outcome(self, run: CueRun) -> CueRunOutcome:
        """Runs the linked resource's templates as the person who linked it, across every
        project as their `infra:read` reaches."""
        person = run.started_by
        assert person is not None
        if not Access.of(person).holds(Permission.INFRA_READ):
            logger.warning("infra: %s no longer holds infra:read; run %s", person, run.id)
            return CueRunOutcome.FAILED
        self.open_window(run, run.ticket)
        log, cloud = QueryLog(person, InfraVia.HUMAN, ticket=run.ticket), openstack()
        scope = InfraScope.all()
        collector = Collector(
            run,
            log,
            Inventory(log, scope, cloud, alertmanager()),
            Observability(log, scope, Catalog(Surface.STAFF), cloud, prometheus(), elasticsearch()),
        )
        for resource in run.resources.all():
            collector.about(resource)
        return CueRunOutcome.DONE

    # ── how a run runs ──

    def open_window(self, run: CueRun, ticket: Ticket) -> None:
        """Sets the run's window: from `cues.lookback_minutes` before the ticket was opened
        until now."""
        run.window_start = ticket.created_at - timedelta(
            minutes=settings.THRESHOLDS.cues.lookback_minutes
        )
        run.window_end = timezone.now()
        run.save(update_fields=["window_start", "window_end"])

    def finish(self, run: CueRun, work: Callable[[], CueRunOutcome]) -> None:
        """Runs `work` and records the outcome it gives, or `failed` when it raises."""
        try:
            outcome = work()
        except Exception:  # noqa: BLE001 — a run that raised is failed, never left running
            logger.exception("infra: cue run %s failed", run.id)
            outcome = CueRunOutcome.FAILED
        run.outcome, run.finished_at = outcome.value, timezone.now()
        run.save(update_fields=["outcome", "finished_at"])

    # ── the ticket page ──

    def of(self, ticket: Ticket) -> list[CueRun]:
        """The runs the Cues panel shows (§o.3)."""
        return list(CueRun.objects.shown_for(ticket.id))


cues = Cues()
