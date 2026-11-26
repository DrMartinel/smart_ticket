# cloud-sim

A simulated OpenStack cloud for F17 ([spec](../../docs/requirements/phase-2/06-F17-infra.md),
[ADR-0048](../../docs/adr/0048-agent-reaches-infrastructure.md)). Dev and test only.

```bash
docker compose --profile infra up -d     # with ELASTIC_PASSWORD … CLOUD_SIM_* in .env
```

| Port (host) | What |
|---|---|
| 8090 | cloud-sim: Keystone `/identity/v3`, Nova `/compute/v2.1`, Cinder `/volume/v3` (the project in the path optional, as since API 3.67), Neutron `/network/v2.0`, `/metrics`, `/sim/*` |
| 9091 | Prometheus (scrapes `/metrics`, evaluates `infra/observability/rules.yml`) |
| 9092 | prom-label-proxy, the only way core-api queries Prometheus |
| 9094 | Alertmanager |
| 9201 | Elasticsearch (`elastic` / `ELASTIC_PASSWORD`) |
| 8201 | APM Server, receiving cloud-sim's OTLP logs and traces |
| 5602 | Kibana |

## Inventory

The seed is [`seed.json`](src/cloud_sim/seed.json): two customer companies
(Sao Mai Logistics with `saomai-prod` and `saomai-staging`, Hoa Binh Retail
with `hbr-web`), their servers, volumes, networks and security groups. `lan.nt`
is a member of both Sao Mai projects; her Keystone user carries her Keycloak
subject, pinned in `infra/keycloak/smart-ticket-realm.json`.

Only the service account (`OPENSTACK_SERVICE_USER`) signs in, with a
system-scoped password token. Every metric series, log line and span carries
its project: the `project` label on metrics and alerts; on logs and traces
the `openstack.project_id` resource attribute, which the APM Server stores as
`labels.openstack_project_id`. Logs land in `logs-apm.app.<service>-default`,
traces in `traces-apm-default`.

## Faults

```bash
curl -X POST localhost:8090/sim/faults -H 'Content-Type: application/json' \
  -d '{"kind": "volume_degraded", "target_id": "<volume id>"}'
curl localhost:8090/sim/faults
curl -X DELETE localhost:8090/sim/faults/<fault id>
curl -X POST localhost:8090/sim/reset
```

| Kind | Target | Shows as |
|---|---|---|
| `volume_degraded` | volume | read and write latency ×25, slow-query logs, slow traces |
| `iops_throttled` | volume | IOPS at quota, latency ×8 |
| `disk_full` | server | disk at 99.5 %, "No space left on device" errors |
| `server_hung` | server | ACTIVE but down; no logs; callers time out. Only a hard reboot or stop and start clears it |
| `crash_loop` | server | Nova ERROR, segfault logs |
| `cpu_saturation` | server | CPU at 97 %, load-average warnings |
| `packet_loss` | network | dropped packets (`params.ratio`, default 0.08), upstream timeouts |
| `log_injection` | server | a log line telling an assistant to act (`params.text`) |
| `api_slow` | the API | every OpenStack call waits `params.delay_sec` |
| `api_unavailable` | the API | every OpenStack call answers 503 |
