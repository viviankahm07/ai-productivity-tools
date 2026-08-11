"""EY.ai / EY Early Careers scraper.

usearlycareers.ey.com is a Radancy-powered single-page app: job results are
loaded client-side and no stable public API endpoint was found during
investigation. Falls back to scanning raw HTML links, which will typically
find few or no candidates.

TODO: if reliable results are needed, revisit with Playwright/headless
rendering to execute the client-side search.
"""

from bs4 import BeautifulSoup

from .base import log_error, log_fallback, make_role, normalize_whitespace, resolve_url, safe_get

COMPANY = "EY"
DIVISION = "EY.ai / Early Careers"
URL = "https://usearlycareers.ey.com/"
MODE = "fallback"


def scrape():
    log_fallback(COMPANY, "Radancy-powered SPA renders jobs client-side; no API found, scanning raw HTML links")

    response = safe_get(URL)
    if response is None:
        log_error(COMPANY, "failed to fetch early careers page")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    roles = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "job" not in href.lower() and "position" not in href.lower():
            continue

        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not title:
            continue

        link = resolve_url(URL, href)
        roles.append(make_role(COMPANY, DIVISION, title, "", link, MODE))

    return roles
