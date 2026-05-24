"""
Browser Tool
============
Fetch URLs, extract readable text, and provide basic content summarization.
Uses urllib + requests for fetching, and simple heuristics for extraction.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse, urljoin

from . import BaseTool

logger = logging.getLogger(__name__)

# Lazy imports to avoid hard dependency at module level
_requests = None


def _get_requests():
    """Lazy-import requests library."""
    global _requests
    if _requests is None:
        try:
            import requests as _r
            _requests = _r
        except ImportError:
            raise ImportError(
                "The 'requests' library is required. Install with: pip install requests"
            )
    return _requests


# Simple HTML tag stripper
_TAG_RE = re.compile(r"<[^>]+>")
_MULTILINE_WS = re.compile(r"\n[ \t]*\n")
_MULTI_SPACE = re.compile(r"[ \t]+")
_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _MULTILINE_WS.sub("\n\n", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def _extract_links(html_text: str, base_url: str) -> List[Dict[str, str]]:
    """Extract <a href> links from raw HTML."""
    links = []
    seen = set()
    for match in _LINK_RE.finditer(html_text):
        href = match.group(1)
        abs_url = urljoin(base_url, href)
        if abs_url not in seen and abs_url.startswith("http"):
            seen.add(abs_url)
            links.append({"url": abs_url, "text": href})
    return links[:50]  # cap


def _simple_summarize(text: str, max_sentences: int = 5) -> str:
    """Extractive summary: pick the first N non-empty sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary_parts: List[str] = []
    for s in sentences:
        s = s.strip()
        if len(s) > 20:
            summary_parts.append(s)
        if len(summary_parts) >= max_sentences:
            break
    return " ".join(summary_parts) if summary_parts else text[:500]


class BrowserTool(BaseTool):
    """Fetch a URL and extract readable text content."""

    name = "browser"
    description = (
        "Fetch a web page by URL and extract its text content. "
        "Can optionally extract links and provide a simple summary."
    )
    parameters = {
        "url": {
            "type": "string",
            "description": "The URL to fetch.",
            "required": True,
        },
        "extract_links": {
            "type": "boolean",
            "description": "If true, also extract hyperlinks from the page (default: false).",
            "required": False,
        },
        "summarize": {
            "type": "boolean",
            "description": "If true, provide a short extractive summary (default: false).",
            "required": False,
        },
        "max_length": {
            "type": "integer",
            "description": "Max characters to return from extracted text (default: 50000).",
            "required": False,
        },
        "timeout": {
            "type": "integer",
            "description": "Request timeout in seconds (default: 30).",
            "required": False,
        },
        "headers": {
            "type": "object",
            "description": "Custom HTTP headers as key-value pairs.",
            "required": False,
        },
    }

    def execute(
        self,
        url: str,
        extract_links: bool = False,
        summarize: bool = False,
        max_length: int = 50_000,
        timeout: int = 30,
        headers: Dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Fetch and process a URL.

        Returns:
            Dict with success, output (text content), url, status_code,
            and optionally links and summary.
        """
        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {
                "success": False,
                "output": f"Invalid URL scheme: {parsed.scheme}. Only http/https supported.",
                "error": "invalid_url",
            }

        requests = _get_requests()

        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; HermesOpenManus/1.0; "
                "+https://github.com/nousresearch)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        if headers:
            default_headers.update(headers)

        try:
            logger.info("Fetching URL: %s", url)
            resp = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "output": f"Request timed out after {timeout}s: {url}",
                "error": "timeout",
            }
        except requests.exceptions.ConnectionError as exc:
            return {
                "success": False,
                "output": f"Connection error: {exc}",
                "error": "connection_error",
            }
        except requests.exceptions.HTTPError as exc:
            return {
                "success": False,
                "output": f"HTTP error: {exc}",
                "status_code": getattr(exc.response, "status_code", None),
                "error": "http_error",
            }
        except requests.exceptions.RequestException as exc:
            return {
                "success": False,
                "output": f"Request failed: {exc}",
                "error": "request_error",
            }

        content_type = resp.headers.get("Content-Type", "")
        raw_html = resp.text
        text = _strip_html(raw_html)

        # Truncate
        if len(text) > max_length:
            text = text[:max_length] + f"\n... [truncated at {max_length} chars]"

        result: Dict[str, Any] = {
            "success": True,
            "output": text,
            "url": resp.url,
            "final_url": resp.url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "content_length": len(raw_html),
        }

        if extract_links:
            result["links"] = _extract_links(raw_html, resp.url)

        if summarize:
            result["summary"] = _simple_summarize(text)

        return result
