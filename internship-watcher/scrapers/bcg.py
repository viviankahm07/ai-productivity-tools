"""BCG / BCG X / BCG Platinion scraper.

careers.bcg.com is a Phenom People single-page app: job search results are
rendered client-side and no stable public JSON API endpoint was found during
investigation (guessed Phenom "apply/v2" and "widgets/data" endpoints both
redirected rather than returning data). Falls back to scanning raw HTML
links, which will typically find few or no candidates.

TODO: if reliable results are needed, revisit with Playwright/headless
rendering to execute the client-side search.
"""

from bs4 import BeautifulSoup

from .base import log_error, log_fallback, make_role, normalize_whitespace, resolve_url, safe_get

COMPANY = "BCG"
DIVISION = "BCG / BCG X / Platinion"
URL = "https://careers.bcg.com/global/en/search-results"
MODE = "fallback"


def scrape():
    log_fallback(COMPANY, "Phenom People SPA renders jobs client-side; no API found, scanning raw HTML links")

    response = safe_get(URL)
    if response is None:
        log_error(COMPANY, "failed to fetch search-results page")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    roles = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/job/" not in href.lower():
            continue

        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not title:
            continue

        link = resolve_url(URL, href)
        roles.append(make_role(COMPANY, DIVISION, title, "", link, MODE))

    return roles
