#!/usr/bin/env python3
"""
Build a frozen snapshot of AWS documentation for the knowledge base.

Every page of each AWS guide listed in sources.json. The guide's
sitemap.xml gives the complete page list; each page is fetched as Markdown
by swapping `.html` for `.md` on docs.aws.amazon.com.

manifest.json records every page's URL, category and content hash, plus a
`snapshot_sha256` over all of them, so an eval run can name the exact KB it
ran against. Commit manifest.json; the Markdown files are git-ignored.

Usage (stdlib only):
    python3 demo_kb/fetch.py                     # fetch what is missing
    python3 demo_kb/fetch.py --only iam lambda   # just these guides
    python3 demo_kb/fetch.py --limit 3           # smoke test: 3 pages per guide
    python3 demo_kb/fetch.py --refresh           # re-fetch pages already on disk
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
SOURCES_PATH = ROOT / "sources.json"
MANIFEST_PATH = ROOT / "manifest.json"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Page:
    slug: str  # the KB article's id; see slug_for
    path: str  # relative to demo_kb/
    url: str
    guide: str  # the guide's key in sources.json
    category: str
    title: str
    sha256: str
    fetched_at: str


class Fetcher:
    """Single-threaded, rate-limited HTTP with retry on throttling."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.delay = cfg["request_delay_seconds"]
        self.timeout = cfg["request_timeout_seconds"]
        self.max_retries = cfg["max_retries"]
        self.backoff = cfg["retry_backoff_seconds"]
        self.user_agent = cfg["user_agent"]
        self._last = 0.0

    def request(
        self, url: str, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[bytes, str]:
        """Return (body, content type). Raises on a non-retryable failure."""
        all_headers = {"User-Agent": self.user_agent, **(headers or {})}
        for attempt in range(self.max_retries + 1):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, data=body, headers=all_headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read(), resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE_STATUS or attempt == self.max_retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.max_retries:
                    raise
            time.sleep(self.backoff * 2**attempt)
        raise AssertionError("unreachable")


def slug_for(path: str) -> str:
    """`guides/iam/id_users.md` -> `iam.id_users`. Slugs appear in core-api
    URL paths (`/api/kb/{slug}/...`), so they never contain "/"."""
    return path.removeprefix("guides/").removesuffix(".md").replace("/", ".")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def title_of(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Snapshot:
    """The manifest being built, seeded from the previous run so re-runs resume."""

    def __init__(self, refresh: bool) -> None:
        self.refresh = refresh
        self.pages: dict[str, Page] = {}
        self.errors: list[dict[str, str]] = []
        if MANIFEST_PATH.exists():
            for p in json.loads(MANIFEST_PATH.read_text())["pages"]:
                self.pages[p["path"]] = Page(
                    slug=slug_for(p["path"]),
                    path=p["path"],
                    url=p["url"],
                    # Manifests written before `guide` existed call it `origin`.
                    guide=p.get("guide", p.get("origin", "")),
                    category=p["category"],
                    title=p["title"],
                    sha256=p["sha256"],
                    fetched_at=p["fetched_at"],
                )

    def have(self, path: str) -> bool:
        return not self.refresh and path in self.pages and (ROOT / path).exists()

    def add(self, page: Page, markdown: str) -> None:
        target = ROOT / page.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown)
        self.pages[page.path] = page

    def error(self, url: str, reason: str) -> None:
        self.errors.append({"url": url, "reason": reason})
        print(f"  ! {url}: {reason}", file=sys.stderr)

    def save(self) -> None:
        pages = sorted(self.pages.values(), key=lambda p: p.path)
        # Hash content, not fetch times: two runs that fetched identical
        # pages are the same snapshot.
        digest = sha256("".join(f"{p.path}\t{p.sha256}\n" for p in pages))
        MANIFEST_PATH.write_text(
            json.dumps(
                {
                    "snapshot_sha256": digest,
                    "generated_at": now(),
                    "page_count": len(pages),
                    "pages": [asdict(p) for p in pages],
                    "errors": self.errors,
                },
                ensure_ascii=False,
                indent=1,
            )
            + "\n"
        )
        print(f"\nmanifest: {len(pages)} pages, {len(self.errors)} errors, snapshot {digest[:12]}")


def fetch_guide(fetcher: Fetcher, snap: Snapshot, guide: dict[str, str], limit: int | None) -> None:
    base, key = guide["base_url"], guide["key"]
    xml, _ = fetcher.request(base + "sitemap.xml")
    locs = [el.text or "" for el in ET.fromstring(xml).iterfind("sm:url/sm:loc", SITEMAP_NS)]
    html_pages = [u for u in locs if u.startswith(base) and u.endswith(".html")]
    if limit is not None:
        html_pages = html_pages[:limit]
    print(f"[{key}] {len(html_pages)} pages")

    for i, html_url in enumerate(html_pages, 1):
        rel = html_url[len(base) : -len(".html")]
        path = f"guides/{key}/{rel}.md"
        if snap.have(path):
            continue
        md_url = html_url[: -len(".html")] + ".md"
        try:
            raw, ctype = fetcher.request(md_url)
        except (urllib.error.URLError, TimeoutError) as e:
            snap.error(md_url, str(e))
            continue
        if not ctype.startswith("text/markdown"):
            snap.error(md_url, f"unexpected content type {ctype!r}")
            continue
        markdown = raw.decode("utf-8")
        page = Page(
            slug=slug_for(path),
            path=path,
            url=html_url,
            guide=key,
            category=guide["category"],
            title=title_of(markdown),
            sha256=sha256(markdown),
            fetched_at=now(),
        )
        snap.add(page, markdown)
        if i % 50 == 0:
            print(f"  {i}/{len(html_pages)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--only", nargs="+", metavar="KEY", help="guide keys to fetch")
    parser.add_argument("--limit", type=int, help="max pages per guide (smoke test)")
    parser.add_argument("--refresh", action="store_true", help="re-fetch pages on disk")
    args = parser.parse_args()

    sources = json.loads(SOURCES_PATH.read_text())
    fetcher = Fetcher(sources["fetch"])
    snap = Snapshot(refresh=args.refresh)

    guides = sources["guides"]
    if args.only:
        unknown = set(args.only) - {g["key"] for g in guides}
        if unknown:
            parser.error(f"unknown guide keys: {', '.join(sorted(unknown))}")
        guides = [g for g in guides if g["key"] in args.only]

    # Save whatever was fetched even on Ctrl-C, so the next run resumes.
    try:
        for guide in guides:
            try:
                fetch_guide(fetcher, snap, guide, args.limit)
            except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
                snap.error(guide["base_url"] + "sitemap.xml", str(e))
    finally:
        snap.save()


if __name__ == "__main__":
    main()
