"""Reviewer agent: checks the draft against the plan and instructions."""

import json
import sys
from pathlib import Path

import anthropic

# Allow this module to be run directly (`python src/agents/reviewer.py`) as
# well as imported normally — either way, `config` (at the repo root) needs
# to be importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

SYSTEM_PROMPT_TEMPLATE = """You are a strict quality-control rubric checker for cover letters. You are NOT an editor — do not rewrite, fix, or suggest replacement wording. Your only job is to identify problems and report them clearly enough that a separate drafting step can act on them.

You will be given a cover letter draft, the job's company name, role title, and minimum requirements, the candidate's resume, and the full writing instructions the letter was supposed to follow.

Check the draft against these criteria, in order:

1. Fixed sentences: Any sentence or block in the instructions marked as "fixed" (fixed wording, exact template, do not alter, etc.) must preserve the exact surrounding wording as written. Grammatical adaptation of placeholders like [Role Name] is expected and is NOT a violation — e.g. "Software Engineer Intern" vs "Software Engineer Internship," or inserting a natural word like "position" or "role" around the placeholder, are all fine. Only flag this as an issue if wording OUTSIDE the placeholder itself was altered, or if the sentence structure was meaningfully changed beyond adapting the role name. Quote both the expected fixed text and what actually appears in the draft (or note that it's missing entirely).
2. Role title consistency: However the role title is phrased on its first mention in the letter (opening line, any header/date block, etc.), it should be phrased the same way everywhere else it appears — closing, any other mention. Flag it only if the letter is internally inconsistent about how it phrases the role title. Do NOT flag it merely for differing from the literal role title string given below — that's expected phrasing variation, not an error.
3. Company name: The company name must be spelled and capitalized consistently everywhere it appears in the letter, matching the value given below exactly. Flag any inconsistency, typo, or mismatch, quoting the exact discrepancy.
4. Minimum requirements coverage: Most of the listed minimum requirements should be addressed somewhere in the letter, even briefly. Flag any minimum requirement that seems completely unaddressed anywhere in the draft, naming that requirement exactly.
5. Length: The letter should fall in a reasonable range — roughly 14-23 lines or 250-450 words, matching the length of a typical letter in this candidate's letter bank. Flag it if it's clearly too short or too long, and say which.
6. Skill/technology accuracy against resume: Any specific technical skill, tool, programming language, or technology claimed OR IMPLIED in the letter must be genuinely evidenced in the resume provided below. Flag any specific technical skill, tool, language, or technology referenced in the letter that doesn't appear in the resume, being specific about which ones (e.g. "The letter references experience with Lua and C++, which don't appear in the resume").

Additionally, check for one more thing, but report it separately as a note rather than an issue — it should never block the letter:

7. Generic filler: Note any generic filler phrases that could apply to any candidate for any role — e.g. "I am a hardworking team player," "I am passionate about...," "I would be a great fit," or similar boilerplate that doesn't say anything specific about this candidate or this role. Quote the exact phrase. This is worth surfacing so the candidate can manually tighten the prose if they want to, but it must never count as an issue or affect whether the draft passes.

Check ONLY these seven criteria — do not invent additional criteria or flag anything outside this list.

Note on markdown: the draft may contain **bold** markdown around skill-paragraph headers (e.g. **Backend Systems:**), per the instructions' own formatting requirements. This is intentional and expected, not a defect — the draft is plain text that gets converted into a real Word document afterward, where these markers become actual bold text. Do NOT flag markdown bold syntax, visible asterisks around a header, or "formatting not applied" as an issue; it is correct as-is in this draft.

The writing instructions this draft was supposed to follow:

---
{instructions}
---

Respond with ONLY valid JSON, no markdown code fences, no commentary, in exactly this shape:
{{
  "passed": boolean,
  "issues": [string, ...],
  "notes": [string, ...]
}}

"passed" must be true only if you found zero problems across criteria 1-6 — if "issues" is non-empty, "passed" must be false. Criterion 7 (generic filler) findings go in "notes" only, never in "issues," and never affect "passed" — a non-empty "notes" list can still be passed: true. Each issue and note must be specific and actionable, naming the exact problem (e.g. "The fixed closing sentence was reworded from 'X' to 'Y'" or "The minimum requirement 'Bachelor's degree in Computer Science' is not addressed anywhere in the letter"), not a vague category label like "fixed sentence issue." If you find no problems, return empty issues/notes lists and passed: true."""


class ReviewerError(Exception):
    """Raised when the Reviewer's API call fails or its response can't be parsed."""


def _strip_code_fences(text: str) -> str:
    """Strip a leading/trailing ```json ... ``` (or bare ```) fence if present.

    Models sometimes wrap JSON in a markdown code fence even when told not
    to; this normalizes that away before json.loads().
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop the opening ``` or ```json line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # drop the trailing ``` line
        text = "\n".join(lines).strip()
    return text


def _build_user_message(draft: str, jd_fields: dict, resume: str) -> str:
    """Assemble the draft + the job fields + resume needed to check it."""
    minimum = jd_fields.get("minimum_requirements", [])
    minimum_block = "\n".join(f"- {item}" for item in minimum) or "(none listed)"

    return f"""Review this cover letter draft against the criteria in your instructions.

Company: {jd_fields.get("company", "")}
Role title: {jd_fields.get("role_title", "")}

Minimum requirements (check that most of these are addressed somewhere in the letter):
{minimum_block}

--- Resume (check skill/technology claims in the draft against this) ---
{resume}
--- End of resume ---

--- Draft ---
{draft}
--- End of draft ---"""


def _parse_reviewer_response(raw_text: str) -> tuple[bool, list[str], list[str]]:
    """Parse and validate the model's raw text output into (passed, issues, notes)."""
    cleaned = _strip_code_fences(raw_text)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ReviewerError(
            f"Failed to parse Reviewer response as JSON: {exc}\n\n"
            f"Raw response:\n{raw_text}"
        ) from exc

    if not isinstance(result, dict):
        raise ReviewerError(
            f"Reviewer response parsed but was not a JSON object.\n\n"
            f"Raw response:\n{raw_text}"
        )

    missing = {"passed", "issues", "notes"} - result.keys()
    if missing:
        raise ReviewerError(
            f"Reviewer response is missing expected field(s): {sorted(missing)}\n\n"
            f"Raw response:\n{raw_text}"
        )

    passed = result["passed"]
    issues = result["issues"]
    notes = result["notes"]

    if not isinstance(passed, bool):
        raise ReviewerError(
            f"Reviewer field 'passed' should be a boolean, got "
            f"{type(passed).__name__}.\n\nRaw response:\n{raw_text}"
        )

    if not isinstance(issues, list) or not all(isinstance(item, str) for item in issues):
        raise ReviewerError(
            f"Reviewer field 'issues' should be a list of strings.\n\n"
            f"Raw response:\n{raw_text}"
        )

    if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
        raise ReviewerError(
            f"Reviewer field 'notes' should be a list of strings.\n\n"
            f"Raw response:\n{raw_text}"
        )

    # Enforce the invariant regardless of what the model claimed: a
    # non-empty issues list can never count as passed, and notes never
    # affect passed either way.
    passed = passed and not issues

    return passed, issues, notes


def review(draft: str, jd_fields: dict, instructions: str, resume: str) -> tuple[bool, list[str], list[str]]:
    """Review a cover letter draft for quality and adherence to instructions.

    Makes a single Claude API call that checks the draft as a strict rubric
    (fixed-sentence fidelity, role-title self-consistency, company-name
    consistency, minimum-requirement coverage, length, skill/technology
    accuracy against the resume) without rewriting anything itself. Generic
    filler phrasing is also flagged, but as a non-blocking note rather than
    an issue.

    Args:
        draft: The cover letter draft text (from
            src.agents.generator.generate).
        jd_fields: Structured job description fields produced by
            src.agents.planner.plan (role_type, company, role_title,
            minimum_requirements, preferred_requirements).
        instructions: The user's cover letter writing instructions
            (contents of instructions.md).
        resume: The candidate's resume text, used to check that any
            skill/technology claims in the draft are genuinely supported.

    Returns:
        A tuple of (passed, issues, notes): `passed` is True if and only
        if `issues` is empty (an empty `notes` list has no bearing on
        `passed`, and vice versa). `issues` is a list of specific,
        blocking problems. `notes` is a list of non-blocking observations
        (currently just generic filler phrasing) worth a manual look but
        never a retry trigger.

    Raises:
        ReviewerError: If the API call fails, or the response can't be
            parsed into the expected shape. The raw response is included
            in the message.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model=config.MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT_TEMPLATE.format(instructions=instructions),
            messages=[
                {"role": "user", "content": _build_user_message(draft, jd_fields, resume)}
            ],
        )
    except anthropic.APIError as exc:
        raise ReviewerError(f"Reviewer API call failed: {exc}") from exc

    raw_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )

    return _parse_reviewer_response(raw_text)


if __name__ == "__main__":
    sample_jd_fields = {
        "role_type": "swe",
        "company": "Nimbus Systems",
        "role_title": "Software Engineer, Backend",
        "minimum_requirements": [
            "Bachelor's degree in Computer Science or related field",
            "2+ years of professional software engineering experience",
            "Proficiency in Python or Go",
            "Experience with Kubernetes and container orchestration",
        ],
        "preferred_requirements": [
            "Experience with distributed systems at scale",
            "Contributions to open-source projects",
        ],
    }

    sample_resume = """Vivian Audrey Kahm
Ithaca, NY | +1 (646) 221-8142 | vak39@cornell.edu

Education
Cornell University — B.S. Computer Science & Operations Research

Experience
Cornell Data Science, Quantitative Subteam — built data pipelines ingesting
and serving large volumes of market data, in Python.
ACM Research — led a technical project from ambiguous problem statement to
written result.

Skills
Python, REST API design, SQL, Git, basic Docker.
(Note: no professional Kubernetes/container-orchestration experience.)"""

    # Deliberately broken in three ways so the checker has something to catch:
    #   1. The opening paragraph is reworded away from instructions.md's
    #      fixed template (should trip criterion 1).
    #   2. "Kubernetes and container orchestration" is never mentioned
    #      anywhere (should trip criterion 4).
    #   3. The draft claims Kubernetes/container-orchestration experience
    #      that isn't backed by the resume above (should trip criterion 6).
    sample_draft = """Vivian Audrey Kahm
Ithaca, NY | +1 (646) 221-8142 | vak39@cornell.edu | LinkedIn | GitHub | Portfolio

August 10, 2026
Software Engineer, Backend

Dear Recruiter,

My name is Vivian Kahm, and I'm excited to apply for the Software Engineer, Backend role at Nimbus Systems. I'm currently a student at Cornell University studying Computer Science, with a passion for solving hard technical problems. I think my skills make me a great match for this position.

    **Backend Engineering & API Design:** Over the past two years, I have built and maintained backend services in Python, designing RESTful API endpoints with clear versioning and error handling. My coursework in Computer Science and Operations Research at Cornell reinforced this with formal grounding in algorithms, data structures, and systems programming.

    **Distributed Systems & Data Infrastructure:** On the quantitative subteam of Cornell Data Science, I helped build data pipelines that ingested and served large volumes of market data, and I have deployed and managed several production Kubernetes clusters to orchestrate these services at scale.

    **Research & Open Source:** Through ACM Research, I worked on a technical project from ambiguous problem statement to written result. I keep my work on GitHub and have contributed to open-source projects that my own tooling depends on.

As for my interest in Nimbus Systems, it is deeply rooted in the firm's ability to build cloud-native backend infrastructure that other engineering teams depend on as a foundation. I am enthusiastic about the possibility of bringing my skills to Nimbus Systems and look forward to discussing how my background and experience would allow me to contribute to the Backend Engineering team.

Sincerely,

Vivian Kahm"""

    if config.INSTRUCTIONS_PATH.exists():
        instructions_text = config.INSTRUCTIONS_PATH.read_text()
    else:
        instructions_text = "(no instructions.md found — using empty instructions for this test)"

    try:
        passed, issues, notes = review(sample_draft, sample_jd_fields, instructions_text, sample_resume)
    except ReviewerError as exc:
        print(f"ReviewerError: {exc}")
        sys.exit(1)

    print(f"passed: {passed}")
    print("issues (blocking):")
    if issues:
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("  (none)")
    print("notes (non-blocking):")
    if notes:
        for note in notes:
            print(f"  - {note}")
    else:
        print("  (none)")
