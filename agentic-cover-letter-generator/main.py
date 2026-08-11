"""CLI entrypoint.

Usage:
    python main.py <job_url>
"""

import argparse

from src.orchestrator import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a cover letter draft from a job posting."
    )
    parser.add_argument(
        "job_url",
        help="URL of the job posting (or raw job description text).",
    )
    args = parser.parse_args()

    output_path = run_pipeline(args.job_url)
    print(f"Draft written to {output_path}")


if __name__ == "__main__":
    main()
