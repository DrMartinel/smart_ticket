# ADR-0048: The agent reads infrastructure and proposes infra changes through core-api

**Status:** Accepted (2026-11-24)
**Date:** 2026-11-24
**Builds on:** ADR-0046 (the agent acts as the user, through tiered routes),
ADR-0045 (roles are permission sets with scope), ADR-0012 (one route to each
outside system), ADR-0006 and ADR-0038 (runbooks go through a person)
**Touches:** a new `apps/infra` in core-api, `apps/accounts/utils/catalog.py`
(four permissions), `apps/agent/utils/actions.py` (action targets),
`thresholds.yaml` (`infra:`, `agent:`), ai-engine `agent/tools/` (an `infra`
tool module, the client's retry rule), `graph/agent_state.py`
(`AgentLimits`), compose (an `infra` profile and `cloud-sim`)
**Supersedes:** nothing. Every decision of ADR-0046 stands.
**Spec:** [06-F17-infra.md](../requirements/phase-2/06-F17-infra.md)

## Context

The tickets this system handles are about a cloud: servers that won't boot,
volumes that are slow, networks that drop packets. Today a technician
answers them by leaving the console for Kibana, Prometheus, Alertmanager and
the cloud's own console, and a customer can only open a ticket and wait.

The owner wants the agent to dig into that infrastructure: read metrics,
logs, traces and alerts, read the state of servers, volumes and networks,
and change some of it. That raises four problems ADR-0046 did not have to
answer:

1. **The agent would query systems outside the stack.** If ai-engine called
   Elasticsearch or Prometheus itself, it would hold credentials and
   authority of its own, which ADR-0046 §2 forbids.
2. **One cloud has many customers.** A customer asking through the chat
   must never read another company's servers or logs, however the question
   is phrased.
3. **A model that writes queries can hurt the backends** (a 30-day range at
   a 1-second step, a match-everything selector) and can read more than it
   should.
4. **Infra changes are not ticket changes.** A reboot or a detached volume
   affects a running system at once, and some of them lose data.

## Decision

1. **Every infra read and change is a core-api route.** core-api's new
   `apps/infra` is the only client of Elasticsearch (logs, and OpenTelemetry
   traces through Elastic APM), Prometheus, Alertmanager and the cloud's
   API (OpenStack: Keystone, Nova, Cinder, Neutron). ai-engine gets no URL,
   key or setting for any of them; a test fails if it does. The agent's
   infra tools are routes like any other, at a tier (ADR-0046 §2, §5).
2. **The agent sees what its person sees.** Staff who hold
   `infra:read` reach every cloud project. A customer who holds
   `infra:read:own` reaches only the projects their Keystone user is a
   member of, read from Keystone on every request. A membership lookup that
   fails refuses the call; it never widens to "all projects".
3. **Scope is added by core-api, never by the model.** The model names a
   resource or writes a query; core-api resolves the caller's projects and
   adds the project filter to every compiled query.
   - **Prometheus** is enforced twice: core-api adds the matcher, and every
     query goes through `prom-label-proxy`, which adds it again.
   - **Elasticsearch** (logs and traces) is enforced once, by core-api's
     structured query builder. There is no paid licence for document-level
     security, and one index per project does not scale to many projects.
     The agent therefore gets **no raw Elasticsearch DSL**, only the
     structured query, and a mutation-checked test pins the filter.
4. **Queries are flexible but bounded.** The agent may write:
   - a **structured query** (JSON: metric or dataset, filters on allowlisted
     labels or fields, aggregation, grouping, range, step, size), which
     core-api compiles to PromQL or Elasticsearch DSL;
   - **raw PromQL**, which core-api parses with Prometheus's own
     `/api/v1/parse_query` and checks before running: allowlisted functions,
     no match-everything matcher, range, step and series caps.
   Every cap is in `thresholds.yaml` `infra:`. A query over a cap is a coded
   422 the model can read and narrow.
5. **Infra results are untrusted and masked.** Log messages, span
   attributes and alert annotations are wrapped as untrusted text (ADR-0046
   §10) and masked inline before they leave core-api, like a ticket. Text
   whose masking fails, or that holds critical PII, is withheld; the
   numbers around it are still returned. A result that trips the injection
   screen makes the rest of the turn read-only, as in F15.
6. **A backend that is down is said, by code.** When one backend is
   unreachable, the route answers a coded 424 (a 4xx, so the agent's client
   records the step instead of handing off) and the turn goes on with the
   others, but the reply carries a code-built warning naming the missing
   source ("Elasticsearch was unreachable; this answer has no logs"). The
   model's prose cannot drop or soften it. Missing data is never read as
   "no problem".
7. **Infra changes are tiered by what they risk.**
   - `confirm`: soft reboot, start, stop, attach a volume. The person
     confirms the card (ADR-0046 §8).
   - `human_only`: hard reboot (its own route), detach a volume, add or
     remove a security group rule. The agent leaves a draft; a person applies it on the
     resource's page.
   - Not built: any delete, and Alertmanager silences. Adding one needs a
     new ADR.
   A staff change names an open ticket the person covers, and writes an
   internal comment on it (spec OQ-F17-02). A customer may soft reboot, start or stop
   their own servers (`infra:operate:own`); everything else they ask for
   goes through a ticket.
8. **A change is never resent.** A cloud call whose answer is lost is an
   unknown outcome and hands off (ADR-0046 §12). The client decides retry
   behaviour by the route's tier, not its HTTP method, so a structured query
   sent as `POST` is still a read.
9. **Infra reads are recorded, not audited.** Each query writes one
   `infra_queries` row: who, via human or agent, the compiled query, the
   backend, rows withheld and a link to it in Kibana or Grafana. Receipts
   show that query, so a person can check any claim. Changes write
   `audit_log` rows as every change does (BR-X-03).

## How the earlier decisions still hold

- **ADR-0046.** Every infra tool is one call to a core-api route, as the
  signed-in person, at a declared tier. ai-engine's database role and
  settings gain nothing. An agent token never reaches a project its person
  can't.
- **ADR-0045.** The four new permissions are URNs in `catalog.py`. Staff
  scope is global; a customer's comes from Keystone, which this ADR treats
  as the source of truth for project membership. No access reaches a prompt.
- **ADR-0006 and ADR-0038.** No runbook is involved. Infra actions are their
  own routes, and none of them is reachable from the triage pipeline or the
  router.
- **ADR-0012.** core-api is the only client of each outside system, as
  ai-engine is the only client of vLLM.

## Consequences

- Elasticsearch scope rests on one layer of code. A bug in the structured
  query builder would leak logs across companies. The test that pins the
  filter is the guard, and raw DSL stays out until there is a second layer.
- Customers get real access to their own infrastructure through the chat,
  which is new for a helpdesk. Their logs may name internal components;
  that is their own project's data.
- Keystone is read on every customer request, so Keystone being down stops
  customer infra reads (refused, never widened).
- Debugging turns are long. The console gets its own step, read and token
  caps, and reads count separately from writes.
- The agent gains write tools while `agent.v1` has never run against a
  model (TODO 23). The owner chose to build F17 first; the spec records it.

## Alternatives considered

- **ai-engine queries the backends directly.** Simpler wiring, but ai-engine
  would hold credentials and decide scope itself. Rejected by ADR-0046 §2.
- **Fixed query templates only.** Safest, but too rigid for debugging;
  the owner asked for as much flexibility as can be made safe.
- **Raw Elasticsearch DSL, validated.** DSL has scripts, runtime fields and
  arbitrary index patterns; no validator would be trusted alone. Rejected
  while there is no backend check.
- **OpenSearch for logs**, whose free security plugin enforces document
  scope. Rejected by the owner (2026-11-24): Elasticsearch stays, scope
  enforced in core-api.
- **Team ownership of projects.** Rejected by the owner: staff reach every
  project.
- **A customer company table in core-api.** A second copy of the cloud's
  membership that can drift; Keystone is the source instead.
