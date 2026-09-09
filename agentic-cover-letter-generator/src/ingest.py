"""Fetch and normalize the job posting text."""

import sys

import requests
from bs4 import BeautifulSoup

# Some job boards block requests' default User-Agent outright.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 10  # seconds
MIN_TEXT_LENGTH = 200  # chars; below this, the fetch probably didn't work

STRIP_TAGS = ["script", "style", "nav", "header", "footer"]

# ATS platforms whose job postings render client-side via JavaScript, so a
# plain requests.get() gets back an (almost) empty shell — confirmed on
# *.wd5.myworkdayjobs.com Workday postings, which get 0 characters of text
# from the fast path. When the fast path comes back under MIN_TEXT_LENGTH,
# _fetch_rendered() below spins up a headless browser (Playwright) instead
# of raising immediately, and waits for this container to appear before
# extracting text. Confirmed against a live SPGI (S&P Global) Workday
# posting — see the CONTAINER_SELECTOR match below.
JOB_POSTING_CONTAINER_SELECTOR = '[data-automation-id="jobPostingDescription"]'
RENDER_TIMEOUT_MS = 20000  # ms; headless browser page navigation timeout
# Separate, shorter timeout for the container-selector wait specifically —
# on a real Workday posting it resolves in a few seconds (confirmed against
# a live SPGI posting), so a non-Workday page that will never show this
# selector doesn't need to wait the full RENDER_TIMEOUT_MS before falling
# back to whole-page text extraction.
CONTAINER_WAIT_TIMEOUT_MS = 8000  # ms


class IngestError(Exception):
    """Raised when a job posting URL can't be fetched or parsed into usable text."""


def _looks_like_url(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://"))


def _collapse_whitespace(text: str) -> str:
    """Strip each line and drop blank lines, collapsing excess whitespace."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _extract_text(html: str) -> str:
    """Strip boilerplate tags and pull out visible, whitespace-normalized text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    raw_text = soup.get_text(separator="\n")
    return _collapse_whitespace(raw_text)


def _fetch_rendered(url: str) -> str:
    """Render `url` in a headless browser and extract the job posting text.

    Fallback for ATS platforms (e.g. Workday's *.wd5.myworkdayjobs.com)
    that render the job description client-side via JavaScript, so a plain
    requests.get() in fetch_job_posting() gets back an (almost) empty
    shell. Waits for JOB_POSTING_CONTAINER_SELECTOR (Workday's job-posting
    container, confirmed against a live SPGI posting) to appear before
    extracting text from it specifically — narrower than the whole page,
    so it skips Workday's nav/header chrome. If that selector never shows
    up (a non-Workday site, a slower load), falls back to the full
    rendered page's visible text instead of giving up outright; the caller
    (fetch_job_posting) still checks the length and raises IngestError if
    it's still too short.

    Playwright is imported here, not at module level, since launching a
    browser is slow and this function is only reached when the fast
    requests-based path already came back short — most postings never pay
    this cost.

    Args:
        url: The job posting URL.

    Returns:
        The extracted, plain-text job description. May still come back
        short/empty — this function doesn't raise on that by itself, only
        on an outright failure to launch/load.

    Raises:
        IngestError: If Playwright/Chromium isn't installed, or the
            headless browser fails to launch or load the page at all.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise IngestError(
            "Playwright is not installed, so the JavaScript-rendering "
            "fallback can't run. Install it with `pip install playwright "
            "&& playwright install chromium`, or paste the job description "
            "text directly instead."
        ) from exc

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
                try:
                    page.wait_for_selector(
                        JOB_POSTING_CONTAINER_SELECTOR, timeout=CONTAINER_WAIT_TIMEOUT_MS
                    )
                    container = page.query_selector(JOB_POSTING_CONTAINER_SELECTOR)
                    text = container.inner_text() if container else ""
                except PlaywrightTimeoutError:
                    # Not a Workday posting (or the container never showed
                    # up in time) — fall back to the fully-rendered page's
                    # visible text rather than giving up here.
                    text = _extract_text(page.content())
            finally:
                browser.close()
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(
            f"Headless-browser rendering of {url} failed: {exc}. Paste the "
            "job description text directly instead."
        ) from exc

    return _collapse_whitespace(text)


def fetch_job_posting(url_or_text: str) -> str:
    """Fetch a job posting and return its plain-text content.

    If `url_or_text` looks like a URL, fetch the page (requests) and strip
    it down to the job description text (BeautifulSoup). Otherwise treat
    the input as already-pasted job description text and return it as-is
    (whitespace-normalized).

    If that fast (requests) path comes back with suspiciously little text —
    usually a sign the page needs JavaScript to render, e.g. Workday's
    *.wd5.myworkdayjobs.com postings — this falls back to rendering the
    page with a headless browser (see _fetch_rendered()) before giving up.
    The headless-browser path is only attempted when the fast path is
    short, since launching a browser is comparatively slow.

    Args:
        url_or_text: A job posting URL, or raw job description text pasted
            directly on the command line.

    Returns:
        The cleaned, plain-text job description.

    Raises:
        IngestError: If a URL fetch fails (bad status, timeout, connection
            error), or the extracted text is still suspiciously short even
            after the headless-browser fallback — usually a sign the site
            blocked the request entirely or removed the posting.
    """
    url_or_text = url_or_text.strip()

    if not _looks_like_url(url_or_text):
        return _collapse_whitespace(url_or_text)

    url = url_or_text
    headers = {"User-Agent": USER_AGENT}

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout as exc:
        raise IngestError(
            f"Timed out after {REQUEST_TIMEOUT}s fetching {url}. The site may "
            "be slow or blocking automated requests — try pasting the job "
            "description text directly instead."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise IngestError(
            f"Could not connect to {url}. Check the URL, or paste the job "
            "description text directly instead."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise IngestError(
            f"Failed to fetch {url}: {exc}. Try pasting the job description "
            "text directly instead."
        ) from exc

    if not response.ok:
        raise IngestError(
            f"Got HTTP {response.status_code} fetching {url}. The posting may "
            "have been removed, or the site is blocking automated requests — "
            "try pasting the job description text directly instead."
        )

    text = _extract_text(response.text)

    if len(text) < MIN_TEXT_LENGTH:
        # The fast path came back short — usually the page needs
        # JavaScript to render (e.g. Workday). Only pay for a
        # headless-browser launch (slow) once we know the fast path wasn't
        # enough, rather than on every fetch.
        text = _fetch_rendered(url)

    if len(text) < MIN_TEXT_LENGTH:
        raise IngestError(
            f"Only extracted {len(text)} characters of text from {url}, even "
            "after rendering it with a headless browser. The posting may "
            "have been removed, or the site is blocking automated access "
            "entirely — paste the job description text directly instead."
        )

    return text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <url_or_text>")
        sys.exit(1)

    try:
        result = fetch_job_posting(sys.argv[1])
    except IngestError as exc:
        print(f"IngestError: {exc}")
        sys.exit(1)

    print(result[:500])
