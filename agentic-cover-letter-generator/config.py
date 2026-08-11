"""Project configuration.

Loads secrets from .env and centralizes constants shared across the
pipeline (model name, paths, etc.) so nothing is hardcoded per-module.
"""

import os
from pathlib import Path

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
# src/agents/planner.py ("quant_trading", "swe", "markets_and_st").
ROLE_TYPES_PATH = EXAMPLES_DIR / "role_types.json"

# Where src/retrieval.py caches example-letter embeddings so they aren't
# recomputed on every call. Already gitignored (.embeddings_cache/).
EMBEDDINGS_CACHE_PATH = BASE_DIR / ".embeddings_cache" / "cache.pkl"

# Resume (plain text/markdown) used by the generator and reviewer agents to
# keep skill/technology claims honest. See src/orchestrator.py for the
# resume.md-preferred, resume.txt-fallback loading logic.
RESUME_MD_PATH = BASE_DIR / "resume.md"
RESUME_TXT_PATH = BASE_DIR / "resume.txt"
