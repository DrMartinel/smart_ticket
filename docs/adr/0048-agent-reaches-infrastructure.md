# ADR-0048: The agent reads infrastructure and proposes infra changes through core-api

**Status:** Accepted (2026-11-24); amendment (decisions 10 and 11) Accepted
(2026-11-26)
**Date:** 2026-11-24
**Builds on:** ADR-0046 (the agent acts as the user, through tiered routes),
ADR-0045 (roles are permission sets with scope), ADR-0012 (one route to each
outside system), ADR-0006 and ADR-0038 (runbooks go through a person)
**Touches:** a new `apps/infra` in core-api, `apps/accounts/utils/catalog.py`
(four permissions), `apps/agent/utils/actions.py` (action targets),
`thresholds.yaml` (`infra:`, `agent:`), ai-engine `agent/tools/` (an `infra`
tool module, the client's retry rule), `graph/agent_state.py`
(`AgentLimits`), compose (an `infra` profile and `cloud-sim`). The amendment
adds: `apps/infra` (customers, cues, `infra_queries`), `tickets` (customer),
the pipeline (the customer lookup), the lifecycle engine (queueing cues),
`apps/sla/services/clocks.py` (the tier floor), `apps/rollout` (the
`ticket_cues` flag), `thresholds.yaml` (`cues:`, `sla.tier_floor`)
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

## Amendment (2026-11-26): cue reads for a ticket, and customers — Accepted

**Spec:** [06-F17-infra.md §o](../requirements/phase-2/06-F17-infra.md#o-amendment-2026-11-26-ticket-cues-and-customers--accepted)

### Context

The owner is adopting module 1 ("AI triage and cues") of an outside Cloud
Support System Plan. Two of its parts reach the cloud without a person asking:

1. **Cues.** When a ticket is handed to support, core-api reads the reporter's
   resources that the ticket names (state, metrics, logs, alerts) and shows
   them on the ticket page. Decision 2 says every read is a person's, or their
   agent's. Decision 9 records who ran each query. A cue has no one to name.
2. **Customers.** A ticket needs its reporter's customer company and that
   company's tier, so F1 can raise its starting priority. "A customer company
   table in core-api" is one of this ADR's rejected alternatives, because a
   copy of membership drifts.

The owner has decided that the model proposes neither priority nor team, and
that the agent never starts by itself (ADR-0046 §3). Neither part may change
either decision.

### Decision

10. **A cue read is a system read, scoped to the reporter's own projects and
    tied to a ticket.**
    - It runs only at handoff (F1 BR-F1-01), after the routing decision has been
      carried out and committed, and only while the F9 flag `ticket_cues` is on.
    - Its scope is the projects Keystone lists the **reporter** as a member of.
      It never uses every project, even when the reporter is staff. A Keystone
      failure links nothing. Decision 2's "never widens" holds unchanged.
    - It finds resources among those projects only, in a fixed order: the ones
      the reporter picked in the chat, then names and IDs in the ticket's
      **masked** subject and body, then volumes attached to those servers.
      When it finds none, it runs a fixed overview of the reporter's projects
      (firing alerts, stopped servers, the most errors, the highest load), and
      says that the ticket named no resource.
    - A pick is recorded by core-api when the person presses a choice the
      agent offered. The model can offer only resources its tools returned
      in that turn, with the person's own token (ADR-0046 decision 17),
      and no agent tool can record a pick.
    - Its queries are fixed templates in core-api code, compiled by the same
      structured query builder and caps as decision 4. No model writes,
      chooses or summarises them, and no agent runs.
    - Results are masked as in decision 5. A source that was down is stated as
      in decision 6, never read as healthy.
    - Each query writes an `infra_queries` row with `via = cue`, no actor, and
      the ticket that caused it. A database CHECK allows a row with no actor
      only for `via = cue`, and requires such a row to name its ticket.
    - Cues are shown only to staff holding `infra:read` who reach the ticket.
      No route puts them in a prompt (agent tier `none`). They never change the
      decision, priority, team, assignee, status or clocks.
    - A resource a technician links on the ticket page is read as that
      technician (decision 9, `via = human`), not as a cue.
11. **A customer is a Keystone domain with a tier. Membership stays in
    Keystone.**
    - `infra_customers` holds only what Keystone lacks: a display name and a
      tier (`standard`, `business`, `enterprise`), keyed by Keystone domain
      ID. A manager creates rows and changes tiers, with a reason, audited.
    - A ticket's customer is read from Keystone when the pipeline starts: the
      domain of the reporter's Keystone user, found by their Keycloak subject
      as in decision 2. It is stamped on the ticket. No `users` column copies
      it.
    - A failed lookup leaves the ticket with no customer and says so on the
      ticket page. It never guesses and never blocks the pipeline.
    - The router never reads the customer. Only F1's tier floor does, and that
      floor can only raise a rule's priority, never lower it.

### How the earlier decisions still hold

- **Decision 1.** core-api is still the only client of every backend. Cues
  are core-api code, and ai-engine gains nothing.
- **Decision 2.** Every read *by a person or their agent* is still scoped as
  before. Cue reads are a new, narrower kind: always the reporter's own
  projects, even when staff hold `infra:read`.
- **Decision 9.** Every read still writes one `infra_queries` row. A cue row
  names its ticket in place of a person.
- **Rejected alternative "a customer company table".** That was rejected as a
  copy of *membership*. `infra_customers` holds no membership, only a tier
  Keystone has no place for.
- **ADR-0046.** No agent runs and no token is used. "An agent that starts on
  its own" stays out (F16 §m, F17 §a).
- **ADR-0001 and BR-F1-02.** Priority comes from rules. The tier floor is a
  rule over data a manager set, never a `proposed_*` field.

### Consequences

- core-api reads customers' logs and metrics with no person asking. A query
  can run for a ticket no one ever opens. The reads are capped, scoped to the
  reporter, recorded, and behind a flag that starts off.
- A cue read's scope rests on enrichment code matching against the right
  projects. A mutation-checked test pins it, as decision 3's filter test does.
- A ticket that names nothing still costs the overview's five queries over
  every project the reporter belongs to, each capped as decision 4's are.
- Each ticket now costs one Keystone call when the pipeline starts, as long as
  any customer row exists. A Keystone outage adds up to the connect timeout to
  each ticket and leaves tickets with no customer.
- Decision 11 assumes the cloud's federation mapping puts each customer's
  users in their company's domain, as `cloud-sim` does. If a real cloud puts
  every federated user in one domain, the lookup must go by the domain of the
  reporter's projects instead. That is a code change in the lookup, not a new
  decision.
- A customer whose domain has no row gets no tier, so a new company starts at
  the rule's priority until a manager adds it.

### Alternatives considered

- **Cues run by the agent on every ticket.** This needs a service identity
  with its own token, which ADR-0046 rules out, and the owner chose not to
  have automatic investigations.
- **A model guessing the resource from the ticket** ("the database" →
  `db-01`), checked against the reporter's resources. It needs a model call,
  a change on both sides of the ai-engine wire and an eval, and a wrong guess
  shows confident cues about the wrong server. The agent asking the person,
  with choices from their own resources, gets the same answer from the person
  who knows.
- **A model summary per cue.** This adds a model call on infra results, their
  masking, an eval, and prose a technician might take as fact. Code-written
  summaries come first; revisit with the investigation agent.
- **Cues behind the F15 agent flags.** These would stay off until F15's evals
  run (TODO 23), though cues involve no agent.
- **`users.customer`, set by a manager.** Simpler to read, but it is the copy
  of membership this ADR rejected.
- **A floor of the highest tier when Keystone is down.** During an outage
  every ticket would become P2, and the ticket reaches a person either way.
