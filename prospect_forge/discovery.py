"""Discovery: candidate companies from public sources only.

Two connectors:

* **Seed import** — JSON files in ``data/seeds/`` with company name, domain,
  industry, optional size, and observed signals with evidence sources.
  This is where curated lists (conferences, directories, manual research)
  enter the funnel.
* **News watch** — public news RSS feeds queried with the profile's signal
  keywords. A mention is a *lead*, not a verdict: the human confirms every
  company before it moves down the funnel.

No LinkedIn scraping. No purchased lists. No personal data.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .store import Store

SEED_SCHEMA = "prospect_forge_seed_v1"
NEWS_FEED = "https://news.google.com/rss/search?q={query}"
FETCH_TIMEOUT = 15
USER_AGENT = "ProspectForge/0.1 (public-source research tool)"


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── seed import ───────────────────────────────────────────────────────────


def validate_seed(seed: Any) -> None:
    if not isinstance(seed, dict) or seed.get("schema") != SEED_SCHEMA:
        raise ValueError("seed file must declare prospect_forge_seed_v1")
    if not isinstance(seed.get("profile_id"), str) or not seed["profile_id"].strip():
        raise ValueError("seed.profile_id required")
    companies = seed.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("seed.companies required")
    for index, company in enumerate(companies):
        where = f"seed.companies[{index}]"
        if not isinstance(company, dict):
            raise ValueError(f"{where} must be an object")
        for field in ("name", "domain", "industry"):
            if not isinstance(company.get(field), str) or not company[field].strip():
                raise ValueError(f"{where}.{field} required")
        signals = company.get("signals", [])
        if not isinstance(signals, list):
            raise ValueError(f"{where}.signals must be a list")
        for signal in signals:
            if not isinstance(signal, dict):
                raise ValueError(f"{where}.signals[] must be objects")
            for field in ("id", "evidence"):
                if not isinstance(signal.get(field), str) or not signal[field].strip():
                    raise ValueError(f"{where}.signals[].{field} required")


def import_seed(store: Store, seed_path: str | Path, *, profile_id: str | None = None) -> dict[str, Any]:
    """Import one seed file. Returns {added, existing, signals_attached}."""
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    validate_seed(seed)
    effective_profile = profile_id or seed["profile_id"]
    added, existing, attached = [], [], 0
    for company in seed["companies"]:
        prospect, created = store.upsert_prospect(
            company["name"], company["domain"], company["industry"],
            profile_id=effective_profile,
            size_estimate=company.get("size_estimate"),
            source=f"seed:{Path(seed_path).stem}",
        )
        # Attach signals for existing prospects too: a previous import may
        # have created the record without completing its signal attach.
        # _attach_signal dedupes, so re-importing a seed is always safe.
        if created:
            added.append(prospect["prospect_id"])
        else:
            existing.append(prospect["prospect_id"])
        for signal in company.get("signals", []):
            before = len(prospect.get("signals", []))
            _attach_signal(store, prospect["prospect_id"], effective_profile, signal)
            prospect = next(p for p in store.load_prospects()
                           if p["prospect_id"] == prospect["prospect_id"])
            if len(prospect["signals"]) > before:
                attached += 1
    return {"added": added, "existing": existing, "signals_attached": attached}


def _attach_signal(store: Store, prospect_id: str, profile_id: str,
                   signal: dict[str, Any]) -> dict[str, Any]:
    prospect = next(p for p in store.load_prospects() if p["prospect_id"] == prospect_id)
    if any(s["id"] == signal["id"] and s.get("profile_id") == profile_id
           for s in prospect["signals"]):
        return prospect
    prospect["signals"].append({
        "id": signal["id"],
        "profile_id": profile_id,
        "evidence": signal["evidence"],
        "source_url": signal.get("source_url", ""),
        "observed_utc": signal.get("observed_utc", _now()),
    })
    store.update_prospect(prospect_id, signals=prospect["signals"])
    return prospect


# ── news watch ────────────────────────────────────────────────────────────


def fetch_feed(query: str, *, opener: Any = None) -> str:
    """Fetch a public news RSS feed for the query. Returns raw XML text."""
    url = NEWS_FEED.format(query=urllib.parse.quote(query))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handler = opener if opener is not None else urllib.request.build_opener()
    with handler.open(request, timeout=FETCH_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


_ITEM_RE = re.compile(
    r"<item>(.*?)</item>", re.DOTALL,
)
_TITLE_RE = re.compile(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.DOTALL)
_LINK_RE = re.compile(r"<link>(.*?)</link>", re.DOTALL)


def parse_feed(xml: str) -> list[dict[str, str]]:
    """Parse RSS items to {title, link}. Best-effort, no XML dependencies."""
    items = []
    for match in _ITEM_RE.finditer(xml):
        block = match.group(1)
        title = _TITLE_RE.search(block)
        link = _LINK_RE.search(block)
        if title and link:
            items.append({
                "title": _unescape(title.group(1)).strip(),
                "link": _unescape(link.group(1)).strip(),
            })
    return items


def _unescape(text: str) -> str:
    return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))


def watch_news(store: Store, profile: dict[str, Any], *, query_limit: int = 3,
               fetch: Any = None) -> dict[str, Any]:
    """Run the profile's keyword queries against public news feeds.

    Mentions are recorded as *unconfirmed leads* attached to existing
    prospects (matched by domain in the headline/link), never as new
    prospects — a news mention alone never creates a record, it only
    strengthens one the human already seeded.
    """
    checked, matched = 0, []
    prospects = {p["domain"]: p for p in store.load_prospects()}
    for signal in profile["signals"][:query_limit]:
        query = " OR ".join(f'"{keyword}"' for keyword in signal["keywords"][:4])
        if not query:
            continue
        try:
            xml = fetch(query) if fetch is not None else fetch_feed(query)
        except OSError:
            continue  # offline or blocked: the human runs this on a live machine
        checked += 1
        for item in parse_feed(xml):
            for domain, prospect in prospects.items():
                if domain in item["title"].lower() or domain in item["link"].lower():
                    if not any(s["id"] == signal["id"] and s.get("evidence") == item["title"]
                               for s in prospect["signals"]):
                        _attach_signal(store, prospect["prospect_id"], profile["profile_id"], {
                            "id": signal["id"],
                            "evidence": item["title"],
                            "source_url": item["link"],
                        })
                        matched.append({"prospect_id": prospect["prospect_id"], "title": item["title"]})
    return {"queries_run": checked, "matches": matched}