# Software Engineering Internship Watcher

A Python automation tool that monitors company career pages for new
U.S.-based software engineering internships and creates a GitHub Issue when
a newly discovered role matches the configured criteria.

Any company can be watched — a software engineering internship at a
consulting firm, a bank, a quant fund, or a tech company is handled by the
exact same pipeline. Nothing about the company matters to the code; only the
posting's title and location do.

## Pipeline

```
company scraper -> normalized role -> SWE internship filter -> dedup -> JSON/Markdown output -> GitHub Issue
```

1. **Scrape** — each module in [`scrapers/`](scrapers/) fetches postings
   from one company's career site (via a public API, server-rendered HTML,
   or an RSS feed) and normalizes them into a common role dict
   (`scrapers/base.py:make_role`).
2. **Filter** — [`filters.py`](filters.py) decides whether a posting looks
   like a U.S.-based software engineering internship.
3. **Dedupe** — [`scrape.py`](scrape.py) tracks previously-seen roles by a
   `company|title|link` identity in [`seen_jobs.json`](seen_jobs.json) so
   the same posting doesn't trigger repeat alerts.
4. **Output** — all currently-matching roles are written to
   [`roles.json`](roles.json) and rendered as a table in
   [`open_roles.md`](open_roles.md).
5. **Alert** — every *newly discovered* role gets a GitHub Issue via
   [`issue_alerts.py`](issue_alerts.py).

## Supported companies

Every scraper module that *exists* in the codebase is registered in the
`SCRAPERS` dict in [`scrapers/__init__.py`](scrapers/__init__.py):

| Key | Company | Mode |
|---|---|---|
| `bcg` | BCG | fallback (HTML scan) |
| `bain` | Bain | html |
| `deloitte` | Deloitte | api (RSS) |
| `ey` | EY | fallback (HTML scan) |
| `kpmg` | KPMG | fallback (HTML scan) |
| `accenture` | Accenture | api |
| `ibm` | IBM | fallback (HTML scan) |
| `two_sigma` | Two Sigma | api (RSS) |

`MODE` just documents how each scraper gets its data — `"api"` (a JSON or
RSS endpoint), `"html"` (a server-rendered page), or `"fallback"` (best-effort
HTML link scanning for a JS-rendered SPA where no stable API was found). It
doesn't affect the pipeline.

Being *registered* here doesn't mean a company actually runs — which of
these keys run on a given invocation is controlled separately by
`ENABLED_COMPANIES`, described next.

## Which companies actually run: `ENABLED_COMPANIES`

The registry above lists every scraper that's *available*; `ENABLED_COMPANIES`
is a comma-separated env var of registry keys that decides which of them run
on a given invocation. This keeps your personal watchlist out of source
control while keeping the set of available scrapers explicit in Python.

```
ENABLED_COMPANIES=accenture,bain,bcg,deloitte,ey,ibm,kpmg,two_sigma
```

- Names are trimmed and lowercased, so `Accenture, BAIN , two_sigma` works.
- Unknown names print a warning and are skipped — they don't crash the run.
- If `ENABLED_COMPANIES` is unset or blank, every registered scraper runs.

**Locally:** copy [`.env.example`](.env.example) to `.env` and edit it:

```bash
cp .env.example .env
# then edit .env to list the companies you want
```

`scrape.py` loads `.env` automatically via `python-dotenv` at startup.
`.env` is gitignored — never commit it (it's your personal watchlist).

**In GitHub Actions:** `.env` doesn't exist in CI, so set `ENABLED_COMPANIES`
as a **repository variable** instead:

1. Repo → **Settings** → **Secrets and variables** → **Actions** → **Variables** tab
2. **New repository variable**
3. Name: `ENABLED_COMPANIES`, Value: e.g. `accenture,bain,bcg,deloitte,ey,ibm,kpmg,two_sigma`

The workflow ([`.github/workflows/daily-check.yml`](.github/workflows/daily-check.yml))
exposes it to `scrape.py` as `ENABLED_COMPANIES: ${{ vars.ENABLED_COMPANIES }}`.
Nobody's actual watchlist is hard-coded in the workflow YAML; if the
repository variable is never set, the workflow just runs every registered
scraper.

## How filtering works

`filters.py:matches_role(title, location)` looks at the combined
title + location text and requires **all** of the following:

- **Internship signal** — e.g. `intern`, `internship`, `co-op`, `new grad`,
  `campus`, `student`.
- **SWE signal** — e.g. `software engineer`, `software engineering`,
  `software developer`, `backend engineer`, `frontend engineer`,
  `full stack engineer`, `platform engineer`, `infrastructure engineer`.
- **U.S. location signal** — `United States`, `US` / `U.S.`, `Remote - US`,
  a known U.S. city (`New York`, `Seattle`, `San Francisco`, ...), or a
  `", <state abbreviation>"` pattern like `, NY` / `, WA` / `, CA`.
- **No exclusion terms** — seniority levels (`senior`, `staff`, `principal`,
  `manager`, `director`, `lead`) and unrelated job families
  (`product management`, `investment banking`, `marketing`, `accounting`,
  `hr`, `legal`) are rejected.

Keyword matching uses word-boundary-safe regex, so short/ambiguous keywords
(`us`, `hr`) don't false-positive inside unrelated words (`business`,
`chair`). See [`tests/test_filters.py`](tests/test_filters.py) for concrete
match/no-match examples.

## GitHub Issue alerts

Every newly discovered matching role creates a GitHub Issue
(`issue_alerts.py`) labeled **`new-role`**, with:

- company
- job title
- location
- a direct link to the job posting
- the date it was found

## GitHub Actions

[`.github/workflows/daily-check.yml`](.github/workflows/daily-check.yml)
runs the watcher daily (`0 13 * * *` UTC) and on demand:

1. installs dependencies
2. runs `python scrape.py`, which scrapes the companies enabled via
   `ENABLED_COMPANIES` (see above), filters, dedupes, and files GitHub
   Issues for new roles
3. commits the updated `roles.json`, `seen_jobs.json`, and `open_roles.md`
   back to the repository

**To run it manually:** open the repo on GitHub → **Actions** tab → **Daily
Role Check** → **Run workflow** (uses the `workflow_dispatch` trigger).

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: control which companies run, see above
python scrape.py
```

Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` env vars if you want local runs
to also create GitHub Issues; without them, issue creation is skipped and
everything else still runs.

## Tests

```bash
python -m unittest discover -s tests
```

## Adding a Company

Adding another employer is primarily two steps:

1. Create a module in [`scrapers/`](scrapers/) implementing the existing
   scraper contract:
   - `COMPANY`, `DIVISION` — display metadata
   - `MODE` — `"api"`, `"html"`, or `"fallback"`
   - `scrape() -> list[dict]` — return normalized role dicts, typically via
     `scrapers.base.make_role(...)`
2. Register it under a short lowercase key in the `SCRAPERS` dict in
   [`scrapers/__init__.py`](scrapers/__init__.py), e.g. `"roblox": roblox`.

That's it — the new key is immediately available. It won't actually run
until you add it to your `ENABLED_COMPANIES` list (locally in `.env`, or as
the `ENABLED_COMPANIES` repository variable in GitHub Actions).

Career sites expose job data in different ways — a public JSON API
(preferred, see `accenture.py`), an RSS feed (see `deloitte.py`,
`twosigma.py`), server-rendered HTML (see `bain.py`), or a JS-rendered SPA
with no stable API (see the `"fallback"` scrapers, which scan raw HTML links
as a best effort). Heavily JS-rendered sites may require Playwright or
another headless-browser tool to get real results — that's not wired up
today, so those scrapers are noted as low-yield until someone adds it.

No profiles, categories, or configuration files are needed — every company
is a peer, and the SWE internship filter is what decides whether any given
posting is relevant.
