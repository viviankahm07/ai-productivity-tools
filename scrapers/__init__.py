"""Company scraper registry.

Each scraper module exposes:
  - COMPANY, DIVISION: display metadata
  - MODE: "api", "html", or "fallback"
  - scrape() -> list[dict]: normalized, unfiltered role candidates

Companies are peers here regardless of industry — the pipeline (scrape ->
normalize -> filter -> dedupe -> output) doesn't care whether a role comes
from a consulting firm, a bank, or a tech company. Adding another employer
is just:
  1. creating its scraper module (see scrapers/base.py for shared helpers)
  2. registering it below under a short lowercase key

This dict lists every scraper module that *exists* in the codebase — it
stays hard-coded in Python so what's available is explicit and easy to read.
Which of these actually run on a given invocation is a separate, runtime
decision controlled by the ENABLED_COMPANIES environment variable (see
scrape.py:get_enabled_scrapers and README.md), so the watchlist itself never
needs to be committed to source control.
"""

from . import accenture, bain, bcg, deloitte, ey, ibm, kpmg, twosigma

SCRAPERS = {
    "accenture": accenture,
    "bain": bain,
    "bcg": bcg,
    "deloitte": deloitte,
    "ey": ey,
    "ibm": ibm,
    "kpmg": kpmg,
    "two_sigma": twosigma,
}
