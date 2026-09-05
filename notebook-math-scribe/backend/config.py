"""Environment-based configuration for the backend."""

import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Shared secret the extension must send as the X-API-Key header. If unset
# (e.g. local dev), the /convert endpoint skips the check - see
# routers/convert.py:require_api_key.
API_SHARED_SECRET = os.getenv("API_SHARED_SECRET")
