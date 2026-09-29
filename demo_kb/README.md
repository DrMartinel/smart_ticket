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

## Licensing

AWS documentation text is CC BY-SA 4.0, so each article keeps its source URL
(`kb_articles.source_url`, linked from the KB page in the web app).
