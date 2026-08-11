"""IBM Consulting AI / Software / Data scraper.

www.ibm.com/careers/search is a Next.js single-page app; the initial HTML's
__NEXT_DATA__ blob ships with an empty pageProps, and job results are fetched
client-side after hydration. No stable public API endpoint was found during
investigation (several guessed REST paths returned redirects, not job data).
Falls back to scanning raw HTML links, which will typically find few or no
candidates.

TODO: if reliable results are needed, revisit with Playwright/headless
rendering to execute the client-side search.
"""

from bs4 import BeautifulSoup

from .base import log_error, log_fallback, make_role, normalize_whitespace, resolve_url, safe_get

COMPANY = "IBM"
DIVISION = "Consulting AI / Software / Data"
URL = (
    "https://www.ibm.com/careers/search"
    "?field_keyword_08%5B0%5D=Software+Engineering"
    "&field_keyword_08%5B1%5D=Infrastructure+%26+Technology"
    "&field_keyword_08%5B2%5D=Data+%26+Analytics"
)
MODE = "fallback"


def scrape():
    log_fallback(COMPANY, "Next.js SPA renders jobs client-side; no API found, scanning raw HTML links")

    response = safe_get(URL)
    if response is None:
        log_error(COMPANY, "failed to fetch careers search page")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    roles = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/careers/" not in href.lower() or "search" in href.lower():
            continue

        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not title:
            continue

        link = resolve_url(URL, href)
        roles.append(make_role(COMPANY, DIVISION, title, "", link, MODE))

    return roles
