# ADR-0013: Lexical retrieval uses pg_search BM25, and `bm25_keyword_hit` means agreement

**Status:** Proposed
**Date:** 2026-09-29
**Departs from:** spec §6.3 (`ts_rank_cd` over a `tsvector` column) and spec §4.4 (`bm25_keyword_hit` left undefined beyond `bool`)

## Context

The lexical half of hybrid retrieval was silently dead. `bm25_search` built
its query with `plainto_tsquery('simple', ...)`, which ANDs every word of the
ticket, so a chunk matched only if it contained all of them. Across the 60
English `kb_covered` golden tickets it returned **0 hits for every one**.
Hybrid retrieval was vector-only, the error-code boost never fired, and
`bm25_keyword_hit` (`len(bm25_hits) > 0`) was always `False`. Nothing
reported any of it.

Switching the query to OR does not fix it. `ts_rank_cd` is Postgres's
cover-density ranking, not BM25: it has no inverse document frequency, so
"the" and "GuardDuty" weigh the same. Once any word can match, common words
decide the ranking. A throwaway probe on the same 60 tickets (lexical
channel only, top 20 chunks, article-level):

| Ranker | Right article #1 | In top 3 | In top 20 | MRR |
|---|---|---|---|---|
| `plainto_tsquery` + `ts_rank_cd` (as shipped) | 0.00 | 0.00 | 0.00 | 0.000 |
| OR `to_tsquery` + `ts_rank_cd` | 0.05 | 0.17 | 0.45 | 0.132 |
| pg_search BM25, `unicode_words` | 0.50 | 0.67 | 0.83 | 0.596 |
| pg_search BM25, `unicode_words('stemmer=english')` | **0.58** | **0.68** | 0.83 | **0.647** |

The golden set is synthetic and these numbers come from the set CI gates on,
so they show a direction, not a tuned result.

Separately, `bm25_keyword_hit` has no definition that survives a working
lexical channel. "Any hit" becomes almost always true with OR matching, so the
feature collapses into the intercept. "Top BM25 score above X" has the flaw
ADR-0005 describes for RRF: BM25 magnitudes depend on query length and on which
words the query contains, so a score means nothing across tickets.

## Decision

**1. Lexical retrieval uses ParadeDB `pg_search`**, a real BM25 index inside
Postgres, pinned to an exact version and package checksum (0.25.10 at the time
of writing). The index uses the `unicode_words` tokenizer with the English
stemmer on `content` and `section_title`, and queries use match-disjunction
(`|||`), so any ticket word can match and IDF decides which ones matter.

**2. `bm25_keyword_hit` means agreement between the two retrieval channels:**
the article the cross-encoder ranks first also appears among BM25's top `k`
articles (duplicate chunks of one article collapse to its best position).

**3. ai-engine reports the rank, core-api makes the comparison.** ai-engine
sends the raw rank of the reranker's top article in BM25's article-level
list (`int`, or `None` if absent). core-api derives the boolean feature as
`rank is not None and rank <= k`, with `k` in `thresholds.yaml` under
`retrieval:` (initially **3**, equal to `rerank_top_n`).

**4. The `tsvector` column, its trigger and its GIN index are dropped** in
the same change. After the switch nothing reads them.

RRF fusion and the cross-encoder are unchanged. ADR-0005 still holds: no
threshold compares against a fused score, and none compares against a BM25
score either. The agreement signal compares **ranks**, which mean the same
thing on every ticket.

## Rationale

The lexical channel's job next to dense vectors is the rare token: an error
code, a service name, a finding type. IDF is exactly what ranks those above
filler words, and real BM25 gives it without us owning the maths. Doing it in
Postgres keeps retrieval in SQL, behind ai-engine's `SELECT`-only role, with
no second index to keep in sync with `kb_chunks`. An in-process BM25 in
ai-engine would be rebuilt on every restart and could drift from the KB.

Agreement is the only definition of the flag that carries information. The
two channels are independent, so when both put the same page on top, that
corroborates the answer the model will quote. It also fails where trust should
fall. On g028 the vector path and reranker chose `iam.troubleshoot_saml`, while
BM25 ranked the correct article first. Under this definition the flag is false
on that wrong answer.

Sending the rank rather than the flag keeps `k` a tunable in
`thresholds.yaml` (hard rule 2) and in the service that makes decisions (the
organizing principle). It also leaves calibration a real variable to fit:
with ≥500 shadow pairs, `k` can be chosen from data instead of set by hand.

## Alternatives considered

- **`ts_rank_cd` with OR and the `english` config.** Its stopword list removes
  "the" but not corpus-common words like "AWS", "instance" or "error". Measured
  above without the stopword list, and it is far behind.
- **An IDF table built from `ts_stat` at KB load.** Approximate BM25 in SQL we
  would write and maintain, rebuilt on every KB change. It does the extension's
  job, only worse.
- **In-memory BM25 in ai-engine** (e.g. `rank_bm25`). It is real BM25, but it
  is a second copy of the KB, rebuilt on every restart, and can drift from it.
- **Keeping `tsv` for one release as a fallback.** Nothing would read it, and a
  fallback nobody exercises only looks like one.

## Consequences

- **The DB image is no longer stock.** `infra/` gains a Dockerfile `FROM
  pgvector/pgvector:pg17` that installs the pinned `.deb` (after `apt-get
  update`, which `libopenblas0` needs). `pg_search` must be in
  `shared_preload_libraries`, a server start setting, not a migration.
  `CREATE EXTENSION pg_search` requires `vector` to exist first. CI's Postgres
  service must use the same image.
- **License.** `pg_search` is AGPL-3.0. Acceptable for this project today, but
  review it before any distribution or commercial deployment.
- **Upgrades are deliberate.** Upstream releases often (four patch releases in
  two weeks around this decision). Bump the version and checksum together, and
  re-run the retrieval suite.
- **Wire schema change, both services in one PR** (ADR-0010). A new rank field
  in core-api `infrastructure/dtos.py` and ai-engine `schemas.py`,
  defaulted so old rows deserialize. The existing `bm25_keyword_hit` field
  stays for old rows, and the TypeScript types are regenerated. The rank is
  computed after reranking, so the BM25 article ranking has to travel in
  `TriageState` from the retrieve step to where signals are emitted.
- **The trust score shifts.** `bm25_keyword_hit` goes from always 0 to
  sometimes 1 under a hand-set weight of 0.5, which moves scores relative to
  the placeholder `t_auto`/`t_route`. Harmless in shadow mode. Record it in
  `evals/HISTORY.md` with the first run after the change.
- **Error codes are a separate concern.** The exact error-code boost
  (`ERROR_CODE_BOOST`, currently a constant in `bm25.py`) moves to
  configuration (hard rule 2). Whether an exact error-code match becomes its
  own trust feature is left open; it is not folded into this flag.
- **English only.** The stemmer is an English decision tied to the AWS demo
  KB. The tokenizer keeps Vietnamese diacritics, so unaccented input ("mat
  khau") does not match accented text ("mật khẩu"). A Vietnamese corpus needs
  its own tokenizer choice and diacritic folding, and a new decision.
- **To verify at implementation:** that ai-engine's `SELECT`-only role can run
  `|||` / `pdb.score()` queries without extra grants beyond `USAGE` on the
  `pdb` schema. That role is how the read-only boundary (ADR-0004) is enforced,
  so it must not be widened to make this work.
- **Code review checklist item:** any PR touching `bm25.py` must keep
  thresholds off BM25 scores. Only ranks cross into decisions.
