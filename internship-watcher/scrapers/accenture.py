"""Accenture AI / Technology scraper.

Accenture's public job search runs on Workday, which exposes a public
(no-auth) JSON search API at .../wday/cxs/accenture/AccentureCareers/jobs.
This is used directly instead of scraping the www.accenture.com job search
UI, which is itself a thin client around the same Workday-backed listing.
"""

from .base import log_error, make_role, normalize_whitespace, safe_post

COMPANY = "Accenture"
DIVISION = "AI / Technology"
SITE_BASE_URL = "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"
API_URL = "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"
MODE = "api"

PAGE_SIZE = 20
MAX_PAGES = 5


def scrape():
    roles = []
    offset = 0

    for _ in range(MAX_PAGES):
        response = safe_post(API_URL, json_body={
            "appliedFacets": {},
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": "intern",
        })
        if response is None:
            log_error(COMPANY, "failed to query Workday jobs API")
            break

        try:
            data = response.json()
        except ValueError as e:
            log_error(COMPANY, f"failed to parse Workday API response: {e}")
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for posting in postings:
            title = normalize_whitespace(posting.get("title", ""))
            external_path = posting.get("externalPath", "")
            bullets = posting.get("bulletFields", [])
            location = normalize_whitespace(bullets[1]) if len(bullets) > 1 else ""

            if not title or not external_path:
                continue

            link = f"{SITE_BASE_URL}{external_path}"
            roles.append(make_role(COMPANY, DIVISION, title, location, link, MODE))

        offset += PAGE_SIZE
        if len(postings) < PAGE_SIZE:
            break

    return roles
