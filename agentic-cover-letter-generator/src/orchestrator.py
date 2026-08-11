"""Wires the pipeline together: ingest -> planner -> retrieval -> generator
-> reviewer -> retry -> docx_writer.
"""

import sys
from pathlib import Path

# Allow this module to be run directly (`python src/orchestrator.py`) as well
# as imported normally — either way, both `config` and the `src` package
# (for the absolute imports below) need to be importable from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config
from src import retrieval
from src.agents.generator import generate
from src.agents.planner import plan
from src.agents.reviewer import review
from src.docx_writer import write_docx
from src.ingest import IngestError, fetch_job_posting


def run_pipeline(job_url_or_text: str) -> str:
    """Run the full cover letter generation pipeline end to end.

    Steps: ingest -> planner -> retrieval -> generator -> reviewer -> (one
    revise-and-retry pass on failure) -> docx_writer.
    Prints a step-by-step progress log throughout, since a full run can
    take 15-30 seconds across several API calls.

    Args:
        job_url_or_text: A job posting URL, or raw job description text.

    Returns:
        Path to the generated .docx file in output/, as a string.

    Raises:
        FileNotFoundError: If instructions.md doesn't exist, or neither
            resume.md nor resume.txt exists.
        IngestError: If the job posting can't be fetched/parsed. Printed
            with a clear message before being re-raised.
        PlannerError, GeneratorError, ReviewerError: Propagated as-is from
            the respective agent if that stage fails.
    """
    if not config.INSTRUCTIONS_PATH.exists():
        raise FileNotFoundError(
            f"{config.INSTRUCTIONS_PATH} not found. Copy instructions.md.example "
            "to instructions.md and fill in your real cover letter template "
            "before running the pipeline."
        )
    instructions = config.INSTRUCTIONS_PATH.read_text()

    if config.RESUME_MD_PATH.exists():
        resume_path = config.RESUME_MD_PATH
    elif config.RESUME_TXT_PATH.exists():
        resume_path = config.RESUME_TXT_PATH
    else:
        raise FileNotFoundError(
            f"Neither {config.RESUME_MD_PATH} nor {config.RESUME_TXT_PATH} "
            "was found. Copy resume.md.example to resume.md and fill in your "
            "real resume before running the pipeline — the generator and "
            "reviewer both use it to keep skill/technology claims honest."
        )
    resume = resume_path.read_text()

    print("Fetching job posting...")
    try:
        jd_text = fetch_job_posting(job_url_or_text)
    except IngestError as exc:
        print(f"Failed to fetch the job posting: {exc}")
        raise

    print("Classifying role...")
    jd_fields = plan(jd_text, instructions)
    print(
        f"  -> {jd_fields['role_type']} role at {jd_fields['company']}: "
        f"{jd_fields['role_title']}"
    )

    print("Retrieving similar example letters...")
    examples = retrieval.retrieve_similar(jd_text, jd_fields["role_type"], k=3)
    print(f"  -> using {len(examples)} example letter(s)")

    print("Generating draft...")
    draft = generate(jd_fields, examples, instructions, resume)

    print("Reviewing...")
    passed, issues, notes = review(draft, jd_fields, instructions, resume)

    if not passed:
        print("Review found issues on the first draft:")
        for issue in issues:
            print(f"  - {issue}")

        print("Regenerating with feedback...")
        draft = generate(jd_fields, examples, instructions, resume, feedback=issues)

        print("Reviewing revised draft...")
        passed, issues, notes = review(draft, jd_fields, instructions, resume)

    if passed:
        print("Draft passed review.")
    else:
        print()
        print(
            "WARNING: the draft still did not pass review after one revision. "
            "Double check it manually before using it. Remaining issues:"
        )
        for issue in issues:
            print(f"  - {issue}")
        print()

    if notes:
        print("Notes (non-blocking):")
        for note in notes:
            print(f"  - {note}")
        print()

    print("Saving to output/...")
    filepath = write_docx(
        draft,
        jd_fields["company"],
        jd_fields["role_title"],
        full_name=config.FULL_NAME,
        location=config.LOCATION,
        phone=config.PHONE,
        email=config.EMAIL,
        linkedin_url=config.LINKEDIN_URL,
        github_url=config.GITHUB_URL,
        portfolio_url=config.PORTFOLIO_URL,
    )
    print(f"Saved to {filepath}")

    return filepath


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <job_url_or_text>")
        sys.exit(1)

    try:
        result_path = run_pipeline(sys.argv[1])
    except IngestError:
        sys.exit(1)

    print(f"\nDone. Cover letter saved to: {result_path}")
