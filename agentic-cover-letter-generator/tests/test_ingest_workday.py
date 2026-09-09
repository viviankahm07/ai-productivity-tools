"""Integration-style check for src/ingest.py's Workday (JS-rendered) fallback.

Hits the real network — this repo has no pytest/CI setup, so this is a
manual verification script, matching the __main__-smoke-test convention
used elsewhere in this codebase (see src/agents/planner.py,
src/retrieval.py, etc.) rather than a pytest suite. Run directly:

    python3 tests/test_ingest_workday.py

Confirms two things against a live Workday posting:
  1. The fast (plain requests) path alone still can't extract usable text
     from it — this is the bug being fixed, and confirms this test is
     actually exercising the headless-browser fallback, not just
     re-confirming requests already worked.
  2. fetch_job_posting() (fast path + headless-browser fallback) DOES
     return non-empty, sufficiently long text for the same URL.
"""

import sys
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ingest import (
    MIN_TEXT_LENGTH,
    REQUEST_TIMEOUT,
    USER_AGENT,
    IngestError,
    _extract_text,
    fetch_job_posting,
)

# A live SPGI (S&P Global / Kensho) Workday posting, confirmed working as of
# 2026-09-09. Workday postings get taken down once filled — if this URL
# 404s or the posting is gone, swap in any other *.wd5.myworkdayjobs.com
# posting and re-run; the point is exercising the Workday ATS rendering
# pattern, not this specific job.
WORKDAY_URL = (
    "https://spgi.wd5.myworkdayjobs.com/en-US/SPGI_Careers/job/Cambridge-MA/"
    "Software-Engineer---Summer-Intern-2027_331717-2"
)


def check_fast_path_alone_is_insufficient() -> None:
    """Confirm the plain requests fetch alone still can't extract this posting.

    Not testing a bug we want — confirming the *setup*. If this assertion
    ever fails (the fast path starts working on its own), Workday likely
    changed how this page is served server-side, and this URL no longer
    exercises the fallback this test is meant to check.
    """
    response = requests.get(
        WORKDAY_URL, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
    )
    text = _extract_text(response.text)
    print(f"  fast path alone: {len(text)} chars (expected: under {MIN_TEXT_LENGTH})")
    assert len(text) < MIN_TEXT_LENGTH, (
        "Fast path alone already returned enough text on its own — this "
        "test no longer exercises the headless-browser fallback for this URL."
    )


def check_fetch_job_posting_succeeds() -> None:
    """Confirm fetch_job_posting() (fast path + fallback) returns real text."""
    text = fetch_job_posting(WORKDAY_URL)
    print(f"  fetch_job_posting(): {len(text)} chars")
    assert len(text) >= MIN_TEXT_LENGTH, "fetch_job_posting() returned suspiciously short text"
    assert "Kensho" in text or "S&P Global" in text, (
        "Extracted text doesn't look like the expected job posting content"
    )


if __name__ == "__main__":
    print(f"Testing Workday fallback against:\n  {WORKDAY_URL}\n")

    print("1. Confirming the fast (requests-only) path alone is insufficient...")
    try:
        check_fast_path_alone_is_insufficient()
    except AssertionError as exc:
        print(f"   WARNING (not fatal): {exc}")

    print("2. Confirming fetch_job_posting() succeeds via the headless-browser fallback...")
    try:
        check_fetch_job_posting_succeeds()
    except IngestError as exc:
        print(f"FAILED: fetch_job_posting() raised IngestError: {exc}")
        sys.exit(1)
    except AssertionError as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)

    print("\nPASSED: Workday JS-rendered fallback returns usable job posting text.")
