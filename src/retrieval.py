"""Embed and retrieve past cover letters similar to the current job.

Uses sentence-transformers to embed examples from examples/ and rank them
against the current job description, boosted by a role_type manifest.
"""

import json
import pickle
import sys
from pathlib import Path

import numpy as np
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

# Allow this module to be run directly (`python src/retrieval.py`) as well
# as imported normally — either way, `config` (at the repo root) needs to
# be importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

_MODEL_NAME = "all-MiniLM-L6-v2"

# examples/README.md originally documented a .txt-only convention, but every
# example letter actually on disk is a .docx export — so both are read here,
# reusing the same read-with-.docx-fallback pattern src/orchestrator.py uses
# for the same reason.
_EXAMPLE_EXTENSIONS = {".txt", ".docx"}

# Flat similarity bonus added when an example's examples/role_types.json
# entry matches the requested role_type. Additive (not multiplicative) so
# it's a predictable nudge rather than a score multiplier, against
# sentence-transformers cosine similarities (typically ~0.1-0.8 for related
# text, per all-MiniLM-L6-v2's usual range).
_ROLE_TYPE_BOOST = 0.15

_model = None  # lazy singleton shared by embed_examples() and retrieve_similar()


def _get_model():
    """Load (once per process) and return the shared SentenceTransformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _read_letter_text(path: Path) -> str:
    """Read a past-letter file's text content (.txt or .docx).

    Small, deliberate duplicate of src/orchestrator.py's helper of the same
    name — orchestrator.py imports this module, so importing the other way
    would create a cycle. Some ".docx" files turn out to be plain text saved
    with the wrong extension; python-docx rejects those as an invalid Word
    package, so fall back to reading as plain text whenever that happens.
    """
    if path.suffix.lower() == ".docx":
        try:
            document = Document(str(path))
            return "\n".join(p.text for p in document.paragraphs if p.text.strip())
        except PackageNotFoundError:
            return path.read_text(errors="replace")
    return path.read_text(errors="replace")


def _load_role_types() -> dict[str, str]:
    """Load the filename -> role_type manifest (examples/role_types.json).

    Returns an empty dict (no boosting applied) if the manifest is missing.
    """
    if not config.ROLE_TYPES_PATH.exists():
        return {}
    return json.loads(config.ROLE_TYPES_PATH.read_text())


def _load_cache() -> dict:
    if not config.EMBEDDINGS_CACHE_PATH.exists():
        return {"model_name": _MODEL_NAME, "entries": {}}
    with open(config.EMBEDDINGS_CACHE_PATH, "rb") as f:
        return pickle.load(f)


def _save_cache(cache: dict) -> None:
    config.EMBEDDINGS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.EMBEDDINGS_CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)


def embed_examples(examples_dir: str = "examples") -> None:
    """Embed every example letter in `examples_dir` and cache the results.

    Reads every .txt/.docx file in `examples_dir`, (re-)embeds only the
    ones that are new or have changed since the last cache (by comparing
    file modification times against the cached mtime — no content hashing,
    per the "keep this simple" brief), and writes filenames + raw text +
    embeddings to a local cache file (see config.EMBEDDINGS_CACHE_PATH) so
    unchanged letters aren't re-embedded on every call. Cache entries for
    files no longer present in `examples_dir` are dropped.

    Args:
        examples_dir: Directory containing past cover letter files (.txt
            or .docx). Defaults to "examples" (relative to cwd) for
            standalone/manual use; src.retrieval.retrieve_similar() always
            passes config.EXAMPLES_DIR explicitly instead, so it works
            regardless of the caller's working directory.

    Returns:
        None. Results are written to the cache file as a side effect.
    """
    examples_path = Path(examples_dir)
    cache = _load_cache()
    entries = cache.get("entries", {})

    candidates = (
        sorted(
            p
            for p in examples_path.iterdir()
            if p.is_file() and p.suffix.lower() in _EXAMPLE_EXTENSIONS
        )
        if examples_path.exists()
        else []
    )

    # Drop entries for files that were removed since the last cache.
    current_names = {p.name for p in candidates}
    for stale_name in set(entries) - current_names:
        del entries[stale_name]

    to_embed = []  # list of (filename, mtime, text)
    for path in candidates:
        mtime = path.stat().st_mtime
        cached_entry = entries.get(path.name)
        if cached_entry is not None and cached_entry["mtime"] >= mtime:
            continue  # unchanged since it was last cached
        try:
            text = _read_letter_text(path)
        except Exception as exc:
            print(f"  (skipping {path.name}: {exc})")
            continue
        if text.strip():
            to_embed.append((path.name, mtime, text))

    if to_embed:
        model = _get_model()
        vectors = model.encode([text for _, _, text in to_embed])
        for (name, mtime, text), vector in zip(to_embed, vectors):
            entries[name] = {"mtime": mtime, "text": text, "embedding": np.asarray(vector)}

    cache["model_name"] = _MODEL_NAME
    cache["entries"] = entries
    _save_cache(cache)


def _rank_examples(jd_text: str, role_type: str) -> list[tuple[str, float, str]]:
    """Rank all cached examples against `jd_text`, boosted by `role_type`.

    Shared by retrieve_similar() (which only needs the text) and this
    module's __main__ test block (which also wants to show filenames and
    scores). Ensures a cache exists first — see retrieve_similar()'s
    docstring for when embed_examples() is (and isn't) called.

    Returns:
        (filename, boosted_similarity, text) tuples, most similar first.
    """
    if not config.EMBEDDINGS_CACHE_PATH.exists():
        embed_examples(str(config.EXAMPLES_DIR))

    cache = _load_cache()
    entries = cache.get("entries", {})
    if not entries:
        return []

    role_types = _load_role_types() if role_type else {}

    model = _get_model()
    jd_vector = np.asarray(model.encode([jd_text])[0])
    jd_norm = np.linalg.norm(jd_vector)

    scored = []
    for name, entry in entries.items():
        vector = entry["embedding"]
        denom = jd_norm * np.linalg.norm(vector)
        similarity = float(np.dot(jd_vector, vector) / denom) if denom else 0.0
        if role_type and role_types.get(name) == role_type:
            similarity += _ROLE_TYPE_BOOST
        scored.append((name, similarity, entry["text"]))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def retrieve_similar(jd_text: str, role_type: str, k: int = 3) -> list[str]:
    """Retrieve the k most similar past cover letters for a job description.

    Loads the cached example embeddings — calling embed_examples() first
    to build the cache if none exists yet — embeds `jd_text` with the same
    model, ranks candidates by cosine similarity, and adds a flat
    similarity boost to examples whose examples/role_types.json entry
    matches `role_type`. Note: an *existing* cache is used as-is (not
    re-scanned for new/changed files on every call) — re-run
    embed_examples() manually after adding new example letters.

    Args:
        jd_text: The job description text to match against.
        role_type: Role type to boost matching examples by — must match a
            value in examples/role_types.json to have any effect (e.g.
            "quant_trading", "swe", "markets_and_st", per
            src.agents.planner.VALID_ROLE_TYPES). Pass an empty string to
            disable boosting entirely.
        k: Number of similar examples to return.

    Returns:
        The text content of the top-k most similar example letters,
        ordered most similar first. Returns fewer than k (or an empty
        list) if fewer examples are cached — never errors on a short list.
    """
    ranked = _rank_examples(jd_text, role_type)
    return [text for _, _, text in ranked[:k]]


if __name__ == "__main__":
    sample_jd = """
    Quantitative Trading Intern - Summer 2027

    We're looking for a Quantitative Trading Intern to join our systematic
    trading desk. You'll help design, backtest, and monitor short-horizon
    trading strategies across futures and equities, working closely with
    traders and researchers.

    Minimum Qualifications:
    - Pursuing a Bachelor's or Master's in CS, Math, Statistics, or a
      related quantitative field
    - Strong Python skills; comfort with numpy/pandas
    - Solid grounding in probability and statistics

    Preferred Qualifications:
    - Prior trading, market-making, or quant research experience
    - Familiarity with time-series analysis
    """
    sample_role_type = "quant_trading"

    ranked = _rank_examples(sample_jd, sample_role_type)
    k = 3

    print(f"role_type: {sample_role_type!r}, k={k}")
    print(f"{len(ranked)} example(s) cached\n")
    print("Ranked candidates (top selections marked):")
    for i, (name, score, _text) in enumerate(ranked):
        marker = "*" if i < k else " "
        print(f"  {marker} {score:+.4f}  {name}")

    print(f"\nTop {k} selected by retrieve_similar():")
    selected = retrieve_similar(sample_jd, sample_role_type, k=k)
    for i, text in enumerate(selected, start=1):
        preview = " ".join(text.split())[:80]
        print(f"  {i}. {preview}...")
