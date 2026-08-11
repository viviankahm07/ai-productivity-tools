"""Two Sigma Product and Strategy scraper.

careers.twosigma.com runs on the same recruiting platform as Deloitte's
apply.deloitte.com and also exposes an RSS feed for open roles
(OpenRoles/feed/). Job detail URLs embed a location slug (e.g.
".../JobDetail/New-York-City-United-States-..."), which is used as a
best-effort location signal since the feed itself has no location field.
"""

from xml.etree import ElementTree as ET

from .base import log_error, make_role, normalize_whitespace, safe_get

COMPANY = "Two Sigma"
DIVISION = "Product and Strategy"
FEED_URL = "https://careers.twosigma.com/careers/OpenRoles/feed/?jobRecordsPerPage=200"
MODE = "api"

COUNTRY_MARKERS = [
    ("united-kingdom", "United Kingdom"),
    ("united-states", "United States"),
    ("hong-kong", "Hong Kong"),
]


def _guess_location(link):
    link_lower = link.lower()
    for marker, label in COUNTRY_MARKERS:
        if marker in link_lower:
            return label
    return ""


def scrape():
    response = safe_get(FEED_URL)
    if response is None:
        log_error(COMPANY, "failed to fetch OpenRoles RSS feed")
        return []

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        log_error(COMPANY, f"failed to parse RSS feed: {e}")
        return []

    roles = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")

        title = normalize_whitespace(title_el.text) if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""

        if not title or not link:
            continue

        location = _guess_location(link)
        roles.append(make_role(COMPANY, DIVISION, title, location, link, MODE))

    return roles
