"""Planner agent: extracts structured fields from the job description."""

import json
import sys
from pathlib import Path

import anthropic

# Allow this module to be run directly (`python src/agents/planner.py`) as
# well as imported normally — either way, `config` (at the repo root) needs
# to be importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

VALID_ROLE_TYPES = {"swe", "swe_finance", "swe_business"}
REQUIRED_FIELDS = {
    "role_type",
    "company",
    "role_title",
    "minimum_requirements",
    "preferred_requirements",
}
LIST_FIELDS = ("minimum_requirements", "preferred_requirements")

SYSTEM_PROMPT_TEMPLATE = """You are a job-posting classifier and field extractor for a cover letter generation pipeline.

Given a job description, classify its role type and extract the fields needed to draft a tailored cover letter.

Role type definitions:
- "swe": general software engineering, backend, full-stack, infra, or AI/ML roles with no notable finance or business/commercial framing.
- "swe_finance": SWE roles at a bank, trading firm, exchange, or other finance-industry company, or roles explicitly framed around markets/trading tech (quant developer, trading systems, financial engineering) — even if the daily work is just writing code.
- "swe_business": SWE roles with a strong business/product/commercial framing — fintech/payments, e-commerce, enterprise SaaS, or any posting that emphasizes customer/business impact alongside the technical work.

Tiebreak for ambiguous postings: default to "swe" unless the posting itself explicitly names markets/trading (-> "swe_finance") or leads with business/customer impact (-> "swe_business").

How to split requirements into minimum_requirements vs preferred_requirements:
- If the posting explicitly separates "required"/"must-have" qualifications from "preferred"/"nice-to-have"/"bonus" qualifications, split them accordingly.
- If the posting lists qualifications as one undifferentiated block with no explicit split, use judgment: put concrete, non-negotiable qualifications (a specific degree, years of experience, required languages/tools explicitly stated as required) in minimum_requirements, and put softer or aspirational items (familiarity with X, exposure to Y, "a plus") in preferred_requirements.
- minimum_requirements should rarely be empty — if genuinely nothing reads as a hard requirement, it's acceptable for preferred_requirements to hold most of the list instead.
- Cap each list at 5 items — pick the most important if there are more.

The cover letter writing instructions this classification will feed into are:

---
{instructions}
---

Respond with ONLY valid JSON, no markdown code fences, no commentary, in exactly this shape:
{{
  "role_type": "swe" | "swe_finance" | "swe_business",
  "company": string,
  "role_title": string,
  "minimum_requirements": [string, ...],
  "preferred_requirements": [string, ...]
}}"""


class PlannerError(Exception):
    """Raised when the Planner's response can't be parsed into the expected shape."""


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


def _parse_planner_response(raw_text: str) -> dict:
    """Parse and validate the model's raw text output into the expected shape."""
    cleaned = _strip_code_fences(raw_text)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise PlannerError(
            f"Failed to parse Planner response as JSON: {exc}\n\n"
            f"Raw response:\n{raw_text}"
        ) from exc

    if not isinstance(result, dict):
        raise PlannerError(
            f"Planner response parsed but was not a JSON object.\n\n"
            f"Raw response:\n{raw_text}"
        )

    missing = REQUIRED_FIELDS - result.keys()
    if missing:
        raise PlannerError(
            f"Planner response is missing expected field(s): {sorted(missing)}\n\n"
            f"Raw response:\n{raw_text}"
        )

    if result["role_type"] not in VALID_ROLE_TYPES:
        raise PlannerError(
            f"Planner returned an unexpected role_type: {result['role_type']!r} "
            f"(expected one of {sorted(VALID_ROLE_TYPES)}).\n\n"
            f"Raw response:\n{raw_text}"
        )

    for field in LIST_FIELDS:
        if not isinstance(result[field], list):
            raise PlannerError(
                f"Planner field {field!r} should be a list, got "
                f"{type(result[field]).__name__}.\n\n"
                f"Raw response:\n{raw_text}"
            )

    return result


def plan(jd_text: str, instructions: str) -> dict:
    """Analyze the job description and produce a structured plan.

    Makes a single Claude API call to classify the role type and extract
    the fields the Generator agent needs, guided by the user's cover
    letter writing instructions.

    Args:
        jd_text: The cleaned job description text (from
            src.ingest.fetch_job_posting).
        instructions: The user's cover letter writing instructions
            (contents of instructions.md).

    Returns:
        A dict shaped like:
            {
                "role_type": "swe" | "swe_finance" | "swe_business",
                "company": str,
                "role_title": str,
                "minimum_requirements": [str, ...],   # up to 5 items
                "preferred_requirements": [str, ...],  # up to 5 items
            }

    Raises:
        PlannerError: If the model's response can't be parsed into the
            expected shape. The raw response is included in the message.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=config.MODEL_NAME,
        max_tokens=1024,
        system=SYSTEM_PROMPT_TEMPLATE.format(instructions=instructions),
        messages=[{"role": "user", "content": jd_text}],
    )

    raw_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )

    return _parse_planner_response(raw_text)


if __name__ == "__main__":
    sample_jd = """
    Software Engineer, Trading Systems - Acme Capital

    Acme Capital is seeking a Software Engineer to join our systematic
    trading desk's engineering team. You will design and build the
    low-latency infrastructure that executes trading strategies across
    equities and futures markets, working closely with quants and traders
    to bring models into production.

    Minimum Qualifications:
    - 3+ years of professional software engineering experience
    - Strong CS fundamentals: data structures, algorithms, concurrency
    - Proficiency in Python and/or C++
    - Bachelor's degree in Computer Science or a related field

    Preferred Qualifications:
    - Experience building low-latency or high-throughput trading systems
    - Familiarity with market data feeds, order management, or exchange connectivity
    - Prior experience in a systematic/HFT trading environment
    - Exposure to cloud infrastructure (AWS/GCP)
    """

    if config.INSTRUCTIONS_PATH.exists():
        instructions_text = config.INSTRUCTIONS_PATH.read_text()
    else:
        instructions_text = "(no instructions.md found — using empty instructions for this test)"

    try:
        result = plan(sample_jd, instructions_text)
    except PlannerError as exc:
        print(f"PlannerError: {exc}")
        sys.exit(1)

    print(json.dumps(result, indent=2))
    print()
    print(f"role_type:  {result['role_type']}")
    print(f"company:    {result['company']}")
    print(f"role_title: {result['role_title']}")
    print()
    print("minimum_requirements:")
    for item in result["minimum_requirements"]:
        print(f"  - {item}")
    print()
    print("preferred_requirements:")
    for item in result["preferred_requirements"]:
        print(f"  - {item}")
