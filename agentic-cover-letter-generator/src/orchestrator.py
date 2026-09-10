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
from src import knowledge_base as kb
from src import page_fit, retrieval
from src.agents.generator import generate
from src.agents.planner import plan
from src.agents.reviewer import review
from src.docx_writer import write_docx
from src.ingest import IngestError, fetch_job_posting


def run_pipeline(job_url_or_text: str) -> str:
    """Run the full cover letter generation pipeline end to end.

    Steps: ingest -> planner -> retrieval (example letters + knowledge-base
    sections) -> generator -> reviewer -> (one revise-and-retry pass on
    failure) -> docx_writer -> page-fit check -> (up to three escalating
    tightening passes: trim generic filler, tighten rendering
    spacing/margins, lightly trim in-sentence wording — each re-checked,
    stopping as soon as it fits).
    Prints a step-by-step progress log throughout, since a full run can
    take 15-30 seconds across several API calls.

    Args:
        job_url_or_text: A job posting URL, or raw job description text.

    Returns:
        Path to the generated .docx file in output/, as a string.

    Raises:
        FileNotFoundError: If instructions.md doesn't exist, or if no resume
            can be resolved for the classified role_type — neither a
            role-specific resume_<role_type>.md/.txt (see
            config.resolve_resume_path()) nor the generic
            resume.md/resume.txt fallback exists.
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

    # Resume resolution happens after classification (not before) because it
    # needs jd_fields["role_type"] to pick the right role-specific resume.
    role_type = jd_fields["role_type"]
    print("Loading resume...")
    resume_path = config.resolve_resume_path(role_type)
    if resume_path is None:
        if config.RESUME_MD_PATH.exists():
            resume_path = config.RESUME_MD_PATH
        elif config.RESUME_TXT_PATH.exists():
            resume_path = config.RESUME_TXT_PATH

        if resume_path is None:
            role_md_name = config.RESUME_PATHS_BY_ROLE_TYPE[role_type][0].name
            raise FileNotFoundError(
                f"{role_md_name} not found (and no generic "
                f"{config.RESUME_MD_PATH.name} fallback either) — copy "
                f"resume.md.example to {role_md_name} and fill in your real "
                f"background for {role_type} roles."
            )
        print(
            f"  WARNING: no role-specific resume found for '{role_type}' — "
            f"falling back to generic {resume_path.name} instead."
        )
    else:
        print(f"  -> using {resume_path.name}")
    resume = resume_path.read_text()

    print("Retrieving similar example letters...")
    examples = retrieval.retrieve_similar(jd_text, jd_fields["role_type"], k=3)
    print(f"  -> using {len(examples)} example letter(s)")

    print("Loading knowledge base...")
    if config.KNOWLEDGE_BASE_PATH.exists():
        knowledge_base_text = kb.retrieve_relevant_sections(jd_text)
        # Each retrieved section renders as its own "--- Heading ---" block
        # header line (see kb.retrieve_relevant_sections) — counting those
        # is simpler than re-deriving the count from kb's internals here.
        section_count = sum(
            1 for line in knowledge_base_text.splitlines() if line.startswith("--- ")
        )
        print(f"  -> using {section_count} relevant section(s) from {config.KNOWLEDGE_BASE_PATH.name}")
    else:
        knowledge_base_text = ""
        print(f"  -> {config.KNOWLEDGE_BASE_PATH.name} not found, skipping (optional)")

    print("Generating draft...")
    draft = generate(jd_fields, examples, instructions, resume, knowledge_base_text)

    print("Reviewing...")
    passed, issues, notes = review(draft, jd_fields, instructions, resume, knowledge_base_text, examples)

    if not passed:
        print("Review found issues on the first draft:")
        for issue in issues:
            print(f"  - {issue}")

        print("Regenerating with feedback...")
        draft = generate(jd_fields, examples, instructions, resume, knowledge_base_text, feedback=issues)

        print("Reviewing revised draft...")
        passed, issues, notes = review(draft, jd_fields, instructions, resume, knowledge_base_text, examples)

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

    def _fix_content_if_failed(draft, passed, issues, notes):
        """Run one normal content-fix pass if a length-trim regeneration broke review.

        Trimming wording to save space can accidentally rephrase into a new,
        unverified specific claim (observed in practice: cutting "clear
        documentation, and effective communication" produced "reusable
        design patterns" instead — trading one unsupported claim for
        another). Rather than silently ship whatever the trim pass
        produced, run it through the normal issues-feedback fix path once
        before moving on, same as the pipeline's own first-draft handling.
        """
        if passed:
            return draft, passed, issues, notes
        print("      Content issues found after the trim — attempting one fix pass...")
        draft = generate(jd_fields, examples, instructions, resume, knowledge_base_text, feedback=issues)
        passed, issues, notes = review(draft, jd_fields, instructions, resume, knowledge_base_text, examples)
        if not passed:
            print("      WARNING: still did not pass review after the fix pass. Remaining issues:")
            for issue in issues:
                print(f"        - {issue}")
        return draft, passed, issues, notes

    def _render(compact: bool = False) -> str:
        return write_docx(
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
            compact=compact,
        )

    print("Saving to output/...")
    filepath = _render()

    print("Checking page fit...")
    fits, pages = page_fit.check_page_fit(filepath)
    print(f"  -> estimated {pages:.2f} page(s)" + ("" if fits else " (over one page)"))

    compact = False
    if not fits:
        print()
        print(
            "Letter runs over one page. Tightening it — content first, then "
            "spacing, then wording, stopping as soon as it fits:"
        )

        # (a) Trim generic filler first, if review flagged any non-blocking
        # filler notes on this draft — safe to cut/tighten since it never
        # touches the fixed opening paragraph or the bullets' substance.
        if notes:
            print("  (a) Trimming generic filler phrasing flagged in review notes...")
            length_feedback = [
                "Tighten or cut this generic filler phrasing (do not touch "
                "the fixed opening paragraph, and do not shorten the three "
                "skill bullets or drop their technical specifics). Do not "
                "introduce any new specific technical claim, skill, or work "
                "detail while rewording — only cut/tighten, don't "
                "substitute in a new claim: " + note
                for note in notes
            ]
            draft = generate(
                jd_fields, examples, instructions, resume, knowledge_base_text,
                length_feedback=length_feedback,
            )
            passed, issues, notes = review(draft, jd_fields, instructions, resume, knowledge_base_text, examples)
            draft, passed, issues, notes = _fix_content_if_failed(draft, passed, issues, notes)
            filepath = _render(compact)
            fits, pages = page_fit.check_page_fit(filepath)
            print(f"      -> estimated {pages:.2f} page(s) after trimming filler")
        else:
            print("  (a) No generic-filler notes to trim — skipping to spacing.")

        # (b) Tighten paragraph/line spacing and margins in the rendering
        # step — a pure formatting change, doesn't touch the draft text.
        if not fits:
            print("  (b) Tightening paragraph spacing and margins...")
            compact = True
            filepath = _render(compact)
            fits, pages = page_fit.check_page_fit(filepath)
            print(f"      -> estimated {pages:.2f} page(s) after tightening spacing")

        # (c) Last resort: lightly trim wording within sentences (bullets/
        # closing), never whole sentences, never technical specifics.
        if not fits:
            print("  (c) Lightly trimming in-sentence wording as a last resort...")
            length_feedback = [
                "The letter is still a little over one page after trimming "
                "filler and tightening spacing. Lightly tighten wording "
                "WITHIN sentences in the three skill bullets and/or closing "
                "paragraph(s) — trim wordy phrasing or redundant clauses "
                "only. Do not delete whole sentences, do not remove "
                "technical specifics or a bullet's closing company-bridge "
                "sentence, and do not touch the fixed opening paragraph. Do "
                "not introduce any new specific technical claim, skill, or "
                "work detail while rewording — only cut/tighten existing "
                "wording, don't substitute in a new claim."
            ]
            draft = generate(
                jd_fields, examples, instructions, resume, knowledge_base_text,
                length_feedback=length_feedback,
            )
            passed, issues, notes = review(draft, jd_fields, instructions, resume, knowledge_base_text, examples)
            draft, passed, issues, notes = _fix_content_if_failed(draft, passed, issues, notes)
            filepath = _render(compact)
            fits, pages = page_fit.check_page_fit(filepath)
            print(f"      -> estimated {pages:.2f} page(s) after trimming wording")

        if fits:
            print("  -> now fits on one page.")
        else:
            print(
                f"  WARNING: still estimated at {pages:.2f} pages after all "
                "tightening steps. Double check it manually — it may run "
                "slightly onto a second page."
            )
        print()

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
