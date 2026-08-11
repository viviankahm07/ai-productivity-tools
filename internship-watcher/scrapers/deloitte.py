"""Deloitte AI & Data / Engineering / Product / Technology scraper.

apply.deloitte.com exposes an RSS feed for its job search results
(SearchJobs/feed/), which mirrors the same job-family filters used by the
site's search UI. This is a stable structured feed, so it's used as the API
source instead of scraping the SPA's rendered HTML.
"""

from xml.etree import ElementTree as ET

from .base import log_error, make_role, normalize_whitespace, safe_get

COMPANY = "Deloitte"
DIVISION = "AI & Data / Engineering / Product / Technology"
FEED_URL = (
    "https://apply.deloitte.com/en_US/careers/SearchJobs/feed/"
    "?3_5_3=477%2C478%2C480&jobSort=relevancy&jobRecordsPerPage=200"
)
MODE = "api"


def scrape():
    response = safe_get(FEED_URL)
    if response is None:
        log_error(COMPANY, "failed to fetch SearchJobs RSS feed")
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

        roles.append(make_role(COMPANY, DIVISION, title, "", link, MODE))

    return roles
