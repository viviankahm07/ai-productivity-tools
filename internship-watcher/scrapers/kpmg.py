"""KPMG Lighthouse scraper.

kpmg.com/jp/en/about/alh/careers-alh.html is a static program-overview page,
not a job search tool, and KPMG does not expose a public Lighthouse-specific
job search API. Falls back to scanning raw HTML links for anything
careers-related; realistically this will find few or no direct role
postings, since the page mostly links out to KPMG's general careers site.

TODO: if a real Lighthouse job listing page/API is found, switch to that.
"""

from bs4 import BeautifulSoup

from .base import log_error, log_fallback, make_role, normalize_whitespace, resolve_url, safe_get

COMPANY = "KPMG"
DIVISION = "Lighthouse"
URL = "https://kpmg.com/jp/en/about/alh/careers-alh.html"
MODE = "fallback"


def scrape():
    log_fallback(COMPANY, "static program page with no job search API; scanning raw HTML links")

    response = safe_get(URL)
    if response is None:
        log_error(COMPANY, "failed to fetch Lighthouse careers page")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    roles = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "career" not in href.lower() and "job" not in href.lower():
            continue

        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not title:
            continue

        link = resolve_url(URL, href)
        roles.append(make_role(COMPANY, DIVISION, title, "", link, MODE))

    return roles
