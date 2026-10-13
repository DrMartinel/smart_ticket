# demo_kb — the demo knowledge base

The knowledge base the demo runs on: a frozen snapshot of AWS documentation
for an internal cloud-platform help desk. `fetch.py` builds the snapshot,
and core-api's `manage.py load_demo_kb` loads it into `kb_articles`.

| Path | Tracked | What |
|---|---|---|
| `sources.json` | yes | Guides to fetch, each with its ticket category; crawl politeness settings |
| `fetch.py` | yes | The fetcher (Python stdlib only) |
| `manifest.json` | yes | Every page's slug, URL, category, title and SHA-256, plus `snapshot_sha256` for the whole set |
| `curation.json` | yes | People's decisions: risk tier per category and per article, and which articles are approved for auto-reply |
| `guides/<key>/*.md` | no | Every page of each guide, from its `sitemap.xml`, fetched as Markdown |
| `associations/entity_graph_pairs.jsonl` | yes | (symptom, remedy, where) pairs extracted per page by ai-engine's offline build (ADR-0018) |
| `associations/entity_graph_resolutions.jsonl` | yes | How each page the pairs name resolved to a KB page: exact, embedding, ambiguous or unresolved |
| `associations/entity_graph.jsonl` | yes | Page-to-page pointer edges built from the pairs, loaded by core-api |

## Use it

```bash
python3 demo_kb/fetch.py                # fetch whatever is missing (resumable; ~30 min from empty)
python3 demo_kb/fetch.py --help         # --only, --limit, --refresh

cd services/core-api
make load-demo-kb ARGS="--approver manager1"   # or: docker compose exec core-api python manage.py load_demo_kb --approver manager1
```

Without `--approver`, articles are loaded and no approvals are applied.
Reloading is cheap: an article whose text didn't change is not re-embedded.

## Slugs and categories

A page's slug is its guide key plus file name (`iam.id_credentials_mfa`).
Slugs appear in core-api URL paths, so they never contain `/`. The category
comes from the page's guide in `sources.json`: a mapping proposed per guide,
not a judgement per page.

## Why a snapshot, not a live lookup

The pipeline never looks anything up in live AWS documentation. That
would send ticket text off-network, and evals would depend on content that
changes under them.

`load_demo_kb` checks every page against its SHA-256 in `manifest.json` and
skips any that differ, so the database holds exactly the snapshot the
manifest names. Re-fetching changes `manifest.json`, which makes a refresh
a reviewable diff like any other change to the KB.

## Approvals are pinned to the text

Each entry in `curation.json`'s `auto_reply` names the article, the SHA-256
of the text that was reviewed, and the reason. The loader applies it
through `KbArticle.set_auto_reply_allowed`, as a named manager, with a
`kb_authority_log` row (ADR-0002). If a later snapshot changes that page,
the approval is not applied, and an existing one is revoked: the manager
approved the old wording, not the new one. Re-review the page, then update
the pinned hash.

Only articles whose `risk_tiers` entry is `low` can be approved (spec §14
P4). The loader refuses anything else before loading a single page.

## Entity associations

Link expansion can follow the entity graph instead of authored links
(`ASSOCIATION_SOURCE=entity_graph`, ADR-0018): pointers from a page that
names a problem to the page the text says has its fix. It is built offline
by ai-engine, from the host, on DeepSeek (`CLOUD_*`, ADR-0019), after
`uv sync --all-packages --group build`:

```bash
uv run python -m ai_engine.core.associations.build \
    --working-dir <scratch dir> --out demo_kb/associations
uv run python -m ai_engine.core.associations.build --sample 150 \
    --include <slug> ... --working-dir <scratch dir> --out <scratch dir>   # a spike
uv run python -m ai_engine.core.associations.build --rescore-only \
    --out demo_kb/associations   # re-resolve, re-score and write; no model call
```

`<scratch dir>` holds the reply cache: a rebuild sends only new or changed
sections. A full build and `--rescore-only` replace every `entity_graph` row
of `kb_article_associations` in one transaction (ADR-0025); a `--sample`
spike writes files only. `load_demo_kb` loads no entity-graph edge, so
**after a load, run the `--rescore-only` line** (it needs the embedder up,
as the load does) or link expansion on `ASSOCIATION_SOURCE=entity_graph`
finds nothing. A database migrated before 2026-10-13 lacks the write
grant: reset its volume, or run
`GRANT INSERT, DELETE ON kb_article_associations TO ai_engine_ro;`.

**`entity_graph_pairs.jsonl` is the contract between the extractor and
everything after it.** One JSON object per line, one per pair found on a
page; `page` is null when the remedy is on the page itself:

```json
{"article_slug": "guardduty.guardduty_finding-types-ec2", "symptom": "EC2 instance acting as Tor relay", "remedy": "Assume instance compromised and take remediation actions", "page": "Remediating a potentially compromised Amazon EC2 instance"}
```

`entity_graph.jsonl` has one line per edge, keyed by slug; `score` is the
number of distinct pairs pointing that way:

```json
{"source_slug": "guardduty.guardduty_finding-types-ec2", "target_slug": "guardduty.compromised-ec2", "score": 2.0, "evidence": ["EC2 instance acting as Tor relay -> Assume instance compromised and take remediation actions", "…"], "build_id": "entity_graph:kb_entity_graph.v1:pairs-…"}
```

The files are reviewed in a PR like `curation.json`: `evidence` names the
pairs behind each edge, and the resolutions file shows how each named page
was matched, so a bad edge is visible in the diff.

## Licensing

AWS documentation text is CC BY-SA 4.0, so each article keeps its source URL
(`kb_articles.source_url`, linked from the KB page in the web app).
