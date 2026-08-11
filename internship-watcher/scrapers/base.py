"""Shared utilities for company scrapers."""

import json
import re
from datetime import date
from urllib.parse import urljoin

import requests

USER_AGENT = "Mozilla/5.0 (compatible; swe-internship-watcher/2.0; +https://github.com/)"
DEFAULT_TIMEOUT = 20


def _headers(extra=None):
    headers = {"User-Agent": USER_AGENT}
    if extra:
        headers.update(extra)
    return headers


def safe_get(url, params=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """GET a URL, returning the Response or None if the request failed."""
    try:
        response = requests.get(url, params=params, headers=_headers(headers), timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"  [error] GET {url} failed: {e}")
        return None


def safe_post(url, json_body=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """POST JSON to a URL, returning the Response or None if the request failed."""
    try:
        response = requests.post(url, json=json_body, headers=_headers(headers), timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"  [error] POST {url} failed: {e}")
        return None


def resolve_url(base_url, href):
    """Resolve a possibly-relative href against a base URL."""
    if not href:
        return ""
    return urljoin(base_url, href)


def normalize_whitespace(text):
    """Collapse whitespace/newlines into single spaces and strip."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_json_from_script(html, script_id):
    """Parse JSON out of a <script id="script_id">...</script> block, e.g.
    __NEXT_DATA__ or other embedded state blobs. Returns None if not found
    or not valid JSON.
    """
    pattern = rf'<script[^>]*id=["\']{re.escape(script_id)}["\'][^>]*>(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None


def today_str():
    return str(date.today())


def make_role(company, division, title, location, link, source):
    """Build a normalized role dict in the shared schema."""
    return {
        "company": company,
        "division": division,
        "title": normalize_whitespace(title),
        "location": normalize_whitespace(location) or "US / Unknown",
        "link": link,
        "date_found": today_str(),
        "source": source,
    }


def log_stats(company, mode, raw_count, matched_count):
    print(f"[{company}] mode={mode} raw_candidates={raw_count} matched_after_filters={matched_count}")


def log_fallback(company, reason):
    print(f"[{company}] FALLBACK MODE: {reason}")


def log_error(company, message):
    print(f"[{company}] ERROR: {message}")
