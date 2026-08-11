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


def fetch_job_posting(url_or_text: str) -> str:
    """Fetch a job posting and return its plain-text content.

    If `url_or_text` looks like a URL, fetch the page (requests) and strip
    it down to the job description text (BeautifulSoup). Otherwise treat
    the input as already-pasted job description text and return it as-is
    (whitespace-normalized).

    Args:
        url_or_text: A job posting URL, or raw job description text pasted
            directly on the command line.

    Returns:
        The cleaned, plain-text job description.

    Raises:
        IngestError: If a URL fetch fails (bad status, timeout, connection
            error) or the extracted text is suspiciously short — usually a
            sign the page needs JavaScript to render or blocked the
            request.
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
        raise IngestError(
            f"Only extracted {len(text)} characters of text from {url}, which "
            "usually means the page needs JavaScript to render or blocked the "
            "request. Paste the job description text directly instead."
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
