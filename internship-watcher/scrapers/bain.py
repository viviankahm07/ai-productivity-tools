"""Bain / Bain Vector scraper.

The technology-engineering work-area page is server-rendered and embeds real
job cards directly in the HTML (links like
"/careers/find-a-role/position/?jobid=NNNNNN" with a <h4> title and a list
of location <li> items), so this is a straightforward HTML scrape with no
need for an API.
"""

from bs4 import BeautifulSoup

from .base import log_error, make_role, normalize_whitespace, resolve_url, safe_get

COMPANY = "Bain"
DIVISION = "Bain Vector"
URL = "https://www.bain.com/careers/work-with-us/our-work-areas/technology-engineering/"
MODE = "html"


def scrape():
    response = safe_get(URL)
    if response is None:
        log_error(COMPANY, "failed to fetch technology-engineering page")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    roles = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "jobid=" not in href:
            continue

        heading = a.find("h4")
        if heading is None:
            continue

        title = normalize_whitespace(heading.get_text(" ", strip=True))
        if not title:
            continue

        locations = [normalize_whitespace(li.get_text(" ", strip=True)) for li in a.find_all("li")]
        location = ", ".join(loc for loc in locations if loc)

        link = resolve_url(URL, href)
        roles.append(make_role(COMPANY, DIVISION, title, location, link, MODE))

    return roles
