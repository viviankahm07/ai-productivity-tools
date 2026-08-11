"""Filter for U.S.-based software engineering internship postings.

A role matches when its title/location together contain an internship
signal, a software-engineering signal, and a U.S. location signal, and none
of the exclusion terms (seniority levels or unrelated job families).
"""

import re

INTERNSHIP_KEYWORDS = [
    "intern", "internship", "co-op", "coop",
    "new grad", "new graduate", "early career", "early careers",
    "campus", "student", "university",
]

SWE_KEYWORDS = [
    "software engineer", "software engineering", "software developer",
    "backend engineer", "backend developer",
    "frontend engineer", "frontend developer",
    "full stack engineer", "full-stack engineer",
    "platform engineer", "infrastructure engineer",
]

EXCLUDE_KEYWORDS = [
    # Seniority levels that indicate a non-intern role.
    "senior", "staff", "principal", "manager", "director", "lead", "associate",
    "mba", "phd", "contractor", "contract", "permanent", "full-time", "full time",
    # Job families that aren't software engineering, even when they run
    # their own "internship" programs.
    "product management", "investment banking", "marketing", "accounting", "hr", "legal",
]

US_KEYWORDS = [
    "united states", "usa", "u.s.", "us",
    "remote - us", "remote, us", "remote - united states", "remote (us)",
    "new york", "boston", "chicago", "atlanta", "dallas",
    "austin", "seattle", "san francisco", "san jose", "los angeles",
    "washington", "philadelphia", "houston", "denver",
    "miami", "minneapolis", "raleigh", "pittsburgh", "portland",
]

# Two-letter USPS state/territory codes. Matched only against the original
# (non-lowercased) text, immediately after a comma, so ambiguous codes like
# "OR" or "IN" don't false-positive inside ordinary lowercase words.
US_STATE_ABBREVIATIONS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

_STATE_ABBR_PATTERN = re.compile(r",\s*(?:" + "|".join(US_STATE_ABBREVIATIONS) + r")\b")


def _contains_keyword(text: str, keyword: str) -> bool:
    # Word-boundary match on alnum edges, since plain substring matching lets
    # short/ambiguous keywords (e.g. "us", "hr") false-positive inside
    # unrelated words ("business", "chair").
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _has_us_state_abbreviation(raw_text: str) -> bool:
    # e.g. "New York, NY" or "Cambridge, MA" — covers cities not in the
    # US_KEYWORDS city list without having to hand-maintain it.
    return _STATE_ABBR_PATTERN.search(raw_text) is not None


def matches_role(title: str, location: str = "") -> bool:
    raw_text = f"{title} {location}"
    text = raw_text.lower()

    is_internship = any(_contains_keyword(text, keyword) for keyword in INTERNSHIP_KEYWORDS)
    is_swe = any(_contains_keyword(text, keyword) for keyword in SWE_KEYWORDS)
    is_us = (
        any(_contains_keyword(text, keyword) for keyword in US_KEYWORDS)
        or _has_us_state_abbreviation(raw_text)
    )
    has_exclude = any(_contains_keyword(text, keyword) for keyword in EXCLUDE_KEYWORDS)

    return is_internship and is_swe and is_us and not has_exclude
