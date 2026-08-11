import json
import os
from pathlib import Path

from dotenv import load_dotenv

from filters import matches_role
from render_table import render_open_roles
from issue_alerts import create_issue_for_role
from scrapers import SCRAPERS
from scrapers.base import log_error, log_stats

# No-op if .env doesn't exist (e.g. in GitHub Actions, where ENABLED_COMPANIES
# is instead supplied as a real environment variable — see README.md).
load_dotenv()

SEEN_FILE = Path("seen_jobs.json")
ROLES_FILE = Path("roles.json")


def load_seen():
    if not SEEN_FILE.exists():
        return set()
    return set(json.loads(SEEN_FILE.read_text()))


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def make_role_id(company, title, link):
    return f"{company}|{title}|{link}"


def get_enabled_scrapers():
    """Resolve which registered scrapers should run this invocation from the
    ENABLED_COMPANIES env var: a comma-separated list of SCRAPERS keys (e.g.
    "accenture,bain,two_sigma"), trimmed and lowercased.

    If ENABLED_COMPANIES is unset or blank, every registered scraper runs
    (keeps local/no-config usage working). Unknown names are warned about
    and skipped rather than crashing the whole run.
    """
    raw = os.getenv("ENABLED_COMPANIES", "").strip()
    if not raw:
        print("[config] ENABLED_COMPANIES not set; running all registered scrapers.")
        return list(SCRAPERS.items())

    requested = [name.strip().lower() for name in raw.split(",") if name.strip()]

    enabled = []
    for name in requested:
        scraper = SCRAPERS.get(name)
        if scraper is None:
            print(
                f"[config] WARNING: ENABLED_COMPANIES has unknown company '{name}' — skipping. "
                f"Known companies: {', '.join(sorted(SCRAPERS))}"
            )
            continue
        enabled.append((name, scraper))

    if not enabled:
        print("[config] WARNING: ENABLED_COMPANIES matched no known companies; nothing will run.")

    return enabled


def main():
    seen = load_seen()

    all_roles = []
    new_roles = []

    for key, scraper in get_enabled_scrapers():
        name = getattr(scraper, "COMPANY", key)
        print(f"\nChecking {name}...")

        try:
            raw_roles = scraper.scrape()
        except Exception as e:
            log_error(name, f"unhandled exception during scrape: {e}")
            raw_roles = []

        matched = [role for role in raw_roles if matches_role(role["title"], role["location"])]
        log_stats(name, getattr(scraper, "MODE", "unknown"), len(raw_roles), len(matched))

        for role in matched:
            role_id = make_role_id(role["company"], role["title"], role["link"])
            all_roles.append(role)

            if role_id not in seen:
                new_roles.append(role)
                seen.add(role_id)

    ROLES_FILE.write_text(json.dumps(all_roles, indent=2))
    render_open_roles(all_roles)
    save_seen(seen)

    for role in new_roles:
        create_issue_for_role(role)

    print(f"\nFound {len(all_roles)} matching roles across all companies.")
    print(f"New roles: {len(new_roles)}")


if __name__ == "__main__":
    main()
