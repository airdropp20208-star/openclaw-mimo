"""
Search Tool
===========
Web search via DuckDuckGo, returning top results.
Self-contained — no BaseTool dependency.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports
_ddgs = None  # will be set to DDGS class or False (unavailable) on first use


def _get_ddgs():  # type: ignore[no-untyped-def]
    """Lazy-import duckduckgo-search."""
    global _ddgs
    if _ddgs is None:
        try:
            from duckduckgo_search import DDGS

            _ddgs = DDGS
        except ImportError:
            _ddgs = False  # sentinel: not available
    if _ddgs is False:
        raise ImportError(
            "duckduckgo-search not installed. Install with: pip install duckduckgo-search"
        )
    return _ddgs


def _search_via_ddgs(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search using the duckduckgo-search library."""
    DDGS = _get_ddgs()
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", r.get("link", "")),
            "snippet": r.get("body", ""),
        }
        for r in results
    ]


def _search_via_fallback(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Fallback: scrape DuckDuckGo HTML (limited, best-effort)."""
    import requests as _requests

    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; HermesOpenManus/1.0; "
            "+https://github.com/nousresearch)"
        ),
    }

    resp = _requests.post(url, data={"q": query}, headers=headers, timeout=15)
    resp.raise_for_status()

    results: list[dict[str, Any]] = []
    blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td)',
        resp.text,
        re.DOTALL,
    )

    for href, title, snippet in blocks[:max_results]:
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        snippet_clean = re.sub(r"<[^>]+>", "", snippet).strip()
        if "uddg=" in href:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            actual_url = parsed.get("uddg", [href])[0]
        else:
            actual_url = href
        results.append({
            "title": title_clean,
            "url": actual_url,
            "snippet": snippet_clean,
        })

    return results


def execute(
    query: str,
    max_results: int = 10,
    region: str = "wt-wt",
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a web search.

    Args:
        query: Search query.
        max_results: Max results (capped at 30).
        region: Region code.

    Returns:
        Dict with success, output (formatted results), and raw results list.
    """
    max_results = min(max(1, max_results), 30)

    if not query.strip():
        return {
            "success": False,
            "output": "Search query cannot be empty.",
            "error": "empty_query",
        }

    results: list[dict[str, Any]] = []

    # Try duckduckgo-search library first
    try:
        logger.info("Searching DuckDuckGo: %s (max=%d)", query, max_results)
        results = _search_via_ddgs(query, max_results)
    except Exception as exc:
        logger.warning("DDGS library failed (%s), trying fallback...", exc)

    # Fallback to HTML scraping
    if not results:
        try:
            results = _search_via_fallback(query, max_results)
        except Exception as exc:
            logger.error("Fallback search also failed: %s", exc)
            return {
                "success": False,
                "output": f"Search failed: {exc}",
                "error": "search_failed",
            }

    # Format output
    if not results:
        return {
            "success": True,
            "output": f"No results found for: {query}",
            "results": [],
            "count": 0,
        }

    formatted_lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        formatted_lines.append(f"{i}. {r['title']}")
        formatted_lines.append(f"   URL: {r['url']}")
        if r.get("snippet"):
            formatted_lines.append(f"   {r['snippet']}")
        formatted_lines.append("")

    return {
        "success": True,
        "output": "\n".join(formatted_lines).strip(),
        "results": results,
        "count": len(results),
        "query": query,
    }
