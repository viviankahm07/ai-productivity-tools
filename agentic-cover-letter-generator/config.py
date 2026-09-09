"""Project configuration.

Loads secrets from .env and centralizes constants shared across the
pipeline (model name, paths, etc.) so nothing is hardcoded per-module.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Default to Claude Opus 5 unless you have a reason to change it.
MODEL_NAME = "claude-opus-5"

# Cover letter header / contact info — see src/docx_writer.py.
FULL_NAME = os.environ.get("FULL_NAME")
LOCATION = os.environ.get("LOCATION")
PHONE = os.environ.get("PHONE")
EMAIL = os.environ.get("EMAIL")
LINKEDIN_URL = os.environ.get("LINKEDIN_URL")
GITHUB_URL = os.environ.get("GITHUB_URL")
PORTFOLIO_URL = os.environ.get("PORTFOLIO_URL")

BASE_DIR = Path(__file__).resolve().parent
INSTRUCTIONS_PATH = BASE_DIR / "instructions.md"
EXAMPLES_DIR = BASE_DIR / "examples"
OUTPUT_DIR = BASE_DIR / "output"

# Filename -> role_type manifest used by src/retrieval.py to boost examples
# matching the current job's role_type. Keys must match VALID_ROLE_TYPES in
# src/agents/planner.py ("swe", "swe_finance", "swe_business").
ROLE_TYPES_PATH = EXAMPLES_DIR / "role_types.json"

# Where src/retrieval.py caches example-letter embeddings so they aren't
# recomputed on every call. Already gitignored (.embeddings_cache/).
EMBEDDINGS_CACHE_PATH = BASE_DIR / ".embeddings_cache" / "cache.pkl"

# Role-specific resumes (plain text/markdown) used by the generator and
# reviewer agents to keep skill/technology claims honest — one per
# src.agents.planner.VALID_ROLE_TYPES value, so each letter is fact-checked
# against the resume version tailored to that role type. Each entry is
# (md_path, txt_path); .md is preferred, .txt is the fallback, same
# convention as the old singular resume.md/resume.txt.
#
# Hardcoded here (not imported from src.agents.planner.VALID_ROLE_TYPES) to
# avoid a circular import — planner.py imports config. Keep this set in
# sync with VALID_ROLE_TYPES by hand if it ever changes.
RESUME_PATHS_BY_ROLE_TYPE = {
    "swe": (BASE_DIR / "resume_swe.md", BASE_DIR / "resume_swe.txt"),
    "swe_finance": (
        BASE_DIR / "resume_swe_finance.md",
        BASE_DIR / "resume_swe_finance.txt",
    ),
    "swe_business": (
        BASE_DIR / "resume_swe_business.md",
        BASE_DIR / "resume_swe_business.txt",
    ),
}


def resolve_resume_path(role_type: str) -> Optional[Path]:
    """Return the resume path to use for `role_type`, or None if none exists.

    Checks RESUME_PATHS_BY_ROLE_TYPE[role_type] only — .md first, then
    .txt. Does NOT fall back to the generic RESUME_MD_PATH/RESUME_TXT_PATH
    below; that fallback (with its accompanying warning) is
    src/orchestrator.py's responsibility, in run_pipeline().

    Args:
        role_type: One of src.agents.planner.VALID_ROLE_TYPES.

    Returns:
        The first existing path (md then txt) for this role_type, or None
        if role_type is unrecognized or neither file exists yet.
    """
    md_path, txt_path = RESUME_PATHS_BY_ROLE_TYPE.get(role_type, (None, None))
    if md_path is None:
        return None
    if md_path.exists():
        return md_path
    if txt_path.exists():
        return txt_path
    return None


# Generic resume — last-resort fallback used by src/orchestrator.py when the
# role-specific resume above doesn't exist yet for the classified role_type.
# Kept around (rather than removed) so a single resume.md still works if
# someone hasn't split their resume into role-specific versions yet.
RESUME_MD_PATH = BASE_DIR / "resume.md"
RESUME_TXT_PATH = BASE_DIR / "resume.txt"
