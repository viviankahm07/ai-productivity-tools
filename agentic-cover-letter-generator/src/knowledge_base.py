"""Load and retrieve relevant sections from knowledge_base.md.

knowledge_base.md is a single, unified background document — detailed
narrative write-ups of internships, projects, and extracurriculars, much
richer than a role-specific resume has room for. Unlike the resumes, it's
not split by role_type; the whole file is always in play, every run.

It's real HTML under a `.md` extension (authored with <h2>/<h3>/<h4>
section headers), so this module parses it back into plain-text sections
along those header boundaries rather than treating it as flat markdown.

Why retrieval instead of dumping the whole file into every prompt: at
~8,000 words / ~19 sections, the full file is larger than the resume and
all three retrieved example letters put together, and any single job only
draws on a handful of those sections (three skill bullets' worth). Sending
the whole thing into every Generator/Reviewer call would roughly double
each prompt's size with mostly irrelevant material. So this reuses the
same sentence-transformers approach src/retrieval.py already uses for past
letters — chunked at the file's own section boundaries — to pull only the
sections most relevant to the current job description. Every section is
still embedded and considered every run (nothing is filtered out by
role_type or file naming, per the "no role-type filtering" requirement) —
what's selective is which of those sections' *text* makes it into the
prompt, not which sections get considered for retrieval.
"""

import html as html_module
import pickle
import re
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

_MODEL_NAME = "all-MiniLM-L6-v2"  # same model src/retrieval.py uses

# How many of the file's sections to pull into a single Generator/Reviewer
# call. ~19 sections at ~150-400 words each; 6 gives enough material for
# three substantive bullets plus headroom, without approaching the size of
# the full document. Tune up if letters start feeling short on specifics
# the knowledge base actually has, down if prompts are running too large.
DEFAULT_K = 6

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SECTION_TAG_RE = re.compile(r"<h[234]>(.*?)</h[234]>", re.IGNORECASE | re.DOTALL)
_SPLIT_RE = re.compile(r"(<h[234]>.*?</h[234]>)", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")

_model = None


def _get_model():
    """Load (once per process) and return the shared SentenceTransformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _strip_html(fragment: str) -> str:
    """Strip tags and decode entities, collapsing whitespace to single spaces/lines."""
    text = _TAG_RE.sub(" ", fragment)
    text = html_module.unescape(text)
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_sections(html_text: str) -> list[tuple[str, str]]:
    """Split knowledge_base.md's HTML into (heading, plain_text) sections.

    Splits on <h2>/<h3>/<h4> boundaries (this file's actual structure —
    see knowledge_base.md.example). HTML comments are stripped first —
    without this, a comment that happens to mention "<h2>" etc. as prose
    (e.g. explaining the file format to whoever edits it) has no matching
    closing tag nearby, and the section-splitting regex greedily spans
    from that stray opening tag all the way to the next real closing tag,
    swallowing everything in between into one garbled heading (caught via
    knowledge_base.md.example, which explains this exact convention in a
    leading comment). Text before the first heading (a title/intro) is
    dropped; a heading with no body text before the next heading is
    skipped. Nested <h4>s under an <h3> each become their own section
    (e.g. "AI Productivity Suite" and its "Internship Watcher"
    sub-section split into two retrievable chunks) rather than one large
    one — finer-grained retrieval, and each is still coherent on its own.

    Returns:
        (heading_text, section_plain_text) pairs, in document order.
    """
    html_text = _COMMENT_RE.sub("", html_text)
    parts = _SPLIT_RE.split(html_text)
    sections = []
    # parts alternates: [pre-heading text, heading, body, heading, body, ...]
    for i in range(1, len(parts), 2):
        heading_match = _SECTION_TAG_RE.match(parts[i])
        heading = _strip_html(heading_match.group(1)) if heading_match else ""
        body = _strip_html(parts[i + 1]) if i + 1 < len(parts) else ""
        if heading and body:
            sections.append((heading, body))
    return sections


def _load_cache() -> dict:
    if not config.KNOWLEDGE_BASE_CACHE_PATH.exists():
        return {"model_name": _MODEL_NAME, "mtime": None, "entries": []}
    with open(config.KNOWLEDGE_BASE_CACHE_PATH, "rb") as f:
        return pickle.load(f)


def _save_cache(cache: dict) -> None:
    config.KNOWLEDGE_BASE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.KNOWLEDGE_BASE_CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)


def _load_and_embed_sections() -> list[dict]:
    """Return cached (heading, text, embedding) entries, re-embedding if the file changed.

    Cached and invalidated by knowledge_base.md's mtime as a whole (not
    per-section, unlike src/retrieval.py's per-file cache) since it's a
    single file — any edit re-parses and re-embeds every section, which is
    cheap enough (~19 short texts) not to need finer-grained diffing.
    """
    mtime = config.KNOWLEDGE_BASE_PATH.stat().st_mtime
    cache = _load_cache()

    if cache.get("mtime") == mtime and cache.get("entries"):
        return cache["entries"]

    html_text = config.KNOWLEDGE_BASE_PATH.read_text(errors="replace")
    sections = parse_sections(html_text)

    entries = []
    if sections:
        model = _get_model()
        texts = [f"{heading}\n{body}" for heading, body in sections]
        vectors = model.encode(texts)
        for (heading, body), vector in zip(sections, vectors):
            entries.append({"heading": heading, "text": body, "embedding": np.asarray(vector)})

    cache = {"model_name": _MODEL_NAME, "mtime": mtime, "entries": entries}
    _save_cache(cache)
    return entries


def retrieve_relevant_sections(jd_text: str, k: int = DEFAULT_K) -> str:
    """Retrieve the k knowledge-base sections most relevant to `jd_text`.

    Returns an empty string (not an error) if knowledge_base.md doesn't
    exist — it's an optional, purely additive source; src/orchestrator.py
    treats its absence the same way it treats zero retrieved examples.

    Args:
        jd_text: The job description text to match sections against.
        k: Number of sections to return, most relevant first.

    Returns:
        The selected sections as clearly-labeled, numbered blocks (each
        prefixed by its original heading), ready to drop into a prompt.
        Empty string if the file is missing or has no parseable sections.
    """
    if not config.KNOWLEDGE_BASE_PATH.exists():
        return ""

    entries = _load_and_embed_sections()
    if not entries:
        return ""

    model = _get_model()
    jd_vector = np.asarray(model.encode([jd_text])[0])
    jd_norm = np.linalg.norm(jd_vector)

    scored = []
    for entry in entries:
        vector = entry["embedding"]
        denom = jd_norm * np.linalg.norm(vector)
        similarity = float(np.dot(jd_vector, vector) / denom) if denom else 0.0
        scored.append((similarity, entry["heading"], entry["text"]))
    scored.sort(key=lambda item: item[0], reverse=True)

    blocks = [f"--- {heading} ---\n{text}" for _similarity, heading, text in scored[:k]]
    return "\n\n".join(blocks)


if __name__ == "__main__":
    sample_jd = """
    Software Engineering Intern - Backend, Summer 2027

    Join our backend team building infrastructure that integrates with
    third-party APIs, coordinates asynchronous workflows, and stores data
    at scale using AWS services.

    Minimum Qualifications:
    - Pursuing a Bachelor's in CS or a related field
    - Experience with Python and REST APIs
    - Familiarity with cloud infrastructure (AWS or similar)
    """

    if not config.KNOWLEDGE_BASE_PATH.exists():
        print(f"{config.KNOWLEDGE_BASE_PATH} not found — nothing to retrieve.")
        sys.exit(0)

    entries = _load_and_embed_sections()
    print(f"{len(entries)} section(s) parsed from {config.KNOWLEDGE_BASE_PATH.name}:")
    for entry in entries:
        print(f"  - {entry['heading']} ({len(entry['text'].split())} words)")

    print(f"\nTop {DEFAULT_K} sections for the sample JD:\n")
    print(retrieve_relevant_sections(sample_jd, k=DEFAULT_K))
