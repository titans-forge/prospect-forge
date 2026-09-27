"""Research enrichment: fetch a prospect's public pages for signal evidence.

The research step fetches the company's own public website (home page, and
common subpages if they exist) and scans it for the profile's signal
keywords. Every match becomes a signal with a quoted snippet, a source URL,
and an observed date — the evidence a human reads before sending outreach.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Any

FETCH_TIMEOUT = 15
USER_AGENT = "ProspectForge/0.1 (public-source research tool)"
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
MAX_SNIPPET = 280


def fetch_page(url: str, *, opener: Any = None) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handler = opener if opener is not None else urllib.request.build_opener()
    with handler.open(request, timeout=FETCH_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def page_text(html: str) -> str:
    text = TAG_RE.sub(" ", html)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _snippet(text: str, position: int) -> str:
    start = max(0, position - MAX_SNIPPET // 2)
    end = min(len(text), start + MAX_SNIPPET)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def scan_page(text: str, signal: dict[str, Any]) -> str | None:
    """Return the first evidence snippet for a signal's keywords, or None."""
    for keyword in signal["keywords"]:
        match = re.search(re.escape(keyword), text, re.IGNORECASE)
        if match:
            return _snippet(text, match.start())
    return None


def research_prospect(prospect: dict[str, Any], profile: dict[str, Any],
                      *, fetch: Any = None) -> list[dict[str, Any]]:
    """Scan the prospect's public home page for the profile's signals.

    Returns the list of signals found (already shaped for the store); the
    caller attaches them. Network failures are silently skipped — research
    runs on a live machine and a company with an unreachable site simply
    yields no new evidence this round.
    """
    fetch = fetch or fetch_page
    url = f"https://{prospect['domain']}"
    try:
        html = fetch(url)
    except (OSError, ValueError):
        return []
    text = page_text(html)
    found = []
    for signal in profile["signals"]:
        # Skip signals the prospect already has evidence for.
        if any(s["id"] == signal["id"] for s in prospect.get("signals", [])):
            continue
        snippet = scan_page(text, signal)
        if snippet:
            found.append({
                "id": signal["id"],
                "profile_id": profile["profile_id"],
                "evidence": snippet,
                "source_url": url,
                "observed_utc": None,  # set by the caller on attach
            })
    return found