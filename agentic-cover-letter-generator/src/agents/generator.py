"""Generator agent: drafts the cover letter."""

import sys
from datetime import date
from pathlib import Path

import openai

# Allow this module to be run directly (`python src/agents/generator.py`) as
# well as imported normally — either way, `config` (at the repo root) needs
# to be importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

# gpt-5.6-sol is a reasoning model: part of max_completion_tokens is spent on
# internal reasoning before it writes any visible output, and that spend
# isn't capped separately — if reasoning alone consumes the whole budget,
# the response comes back with finish_reason == "length" and an EMPTY
# message.content (observed in practice: reasoning_tokens=2048,
# completion_tokens=2048, i.e. reasoning used 100% of the budget on a
# request whose actual letter output is normally ~300-500 tokens). Budgeting
# generously here — well beyond the ~300-500 tokens the letter itself needs
# — leaves headroom for reasoning without silently truncating the letter.
# A module-level constant (not a magic number inline) so it's a single knob
# to raise further if this recurs.
MAX_COMPLETION_TOKENS = 8192

# Reasoning effort for this call — "low" is enough for a cover-letter draft
# (it's not a hard reasoning task) and leaves far more of
# MAX_COMPLETION_TOKENS available for the actual letter than the model's
# default effort would. One of "none", "minimal", "low", "medium", "high",
# "xhigh" (per the installed openai SDK's ReasoningEffort type) — confirmed
# accepted by the API for gpt-5.6-sol.
REASONING_EFFORT = "low"

SYSTEM_PROMPT_TEMPLATE = """You are a cover letter writer. Draft a complete cover letter following the instructions below exactly.

## Fixed vs. flexible content

- Any sentence or block in the instructions marked as "fixed" (fixed wording, exact template, do not alter, etc.) must appear in your output EXACTLY as written — character for character. Do not reword, paraphrase, or substitute synonyms in fixed content, even if it seems repetitive or could read better another way.
- Any section described as flexible, tailored, or to be written based on the candidate's background/experience should be written fresh, specific to this role and company. Do not reuse generic boilerplate for these sections.

## Output format

Return ONLY the finished letter text, ready to hand off as-is. Do not include a preamble, a note to the user, or any code fences.

One explicit exception to "no markdown": each bullet's lead-in header uses literal double-asterisk markdown — `**Header text:**` — exactly as instructions.md specifies. This is required, not optional. Do NOT substitute Unicode "styled"/stylized bold or italic lookalike characters (e.g. writing "𝗣𝘆𝘁𝗵𝗼𝗻" instead of "Python") to fake a bold appearance — those are not real bold formatting, will not render as bold in the final document, and show up as garbled-looking plain text instead. Use plain ASCII text everywhere except the literal `**...**` markers themselves.

Do NOT type a manual bullet character ("•", "-", "*", etc.) at the start of a bullet line — the rendering step adds a real bulleted-list marker automatically. Each bullet line should start directly with its `**Bolded header:**`.

Separate every logical block — date, role name, salutation, opening paragraph, each of the three bullets, each closing paragraph, and the sign-off — with a blank line in your raw output. Do not run multiple blocks together on consecutive lines with no blank line between them; the rendering step depends on blank-line separation to apply correct paragraph spacing, bullet formatting, and bold headers. (One exception: no blank line between "Sincerely," and the name on the next line — those two stay adjacent.)

Write in clean, direct prose — no em dashes (—) or other overly stylistic punctuation.

Do NOT write the name-and-contact-info header block yourself, even if the instructions describe one (e.g. a centered name and a contact line with phone/email/LinkedIn/GitHub/portfolio). That block is generated separately and inserted programmatically after your output — a real document can give it hyperlinks and font sizing that plain text can't, so if you also write it, it will appear twice in the final letter. Start your output at whatever comes right after that header — typically the date and role-name lines — and continue through the salutation, body, and closing exactly as the instructions describe.

## Using the job's requirement lists

You will be given two lists of requirements extracted from the job posting: minimum_requirements and preferred_requirements.

- Address most minimum_requirements implicitly, through the natural narrative of the letter — not as a checklist. Do NOT add standalone sentences that explicitly restate logistical requirements (e.g. willingness to work onsite, specific days/location, degree program/major) unless instructions.md specifically calls for that information to be stated. If a requirement is already evident from context (e.g. the candidate's field of study, standard availability), it does not need its own explicit sentence. Only spend words explicitly addressing requirements that meaningfully differentiate this candidate's actual fit for the role.
- preferred_requirements should be used more selectively: pick only the ones that genuinely connect to real experience in the candidate's background, rather than forcing all of them in. It's fine to leave some preferred_requirements unaddressed if they don't fit naturally.
- Do NOT present minimum and preferred requirements differently in tone, and never call out which is which (e.g. never write something like "I also meet your preferred requirement of..."). The letter should read as one natural, unified narrative — not a checklist being worked through point by point.

## Length

The letter must fit on one printed page under the formatting instructions.md specifies. With three full 5-6 sentence bullets (per instructions.md's bullet-length requirement), that's roughly 500-650 words total — meaningfully longer than a short, compressed letter, but still one page. The hard ceiling is one page, not a specific word count — the word count above is just what one page comfortably holds under this formatting.

If the draft is running long: tighten paragraph spacing and/or use a single-paragraph closing instead of two before shortening anything else. Do NOT shorten the three skill bullets or drop their technical specifics to save space — that's the last thing to cut, not the first. If explicitly addressing every minimum requirement would still push the letter past one page after that, prioritize the 2-3 minimum requirements that most meaningfully differentiate this candidate's fit, address those, and leave the rest implicit (per the guidance above) or unaddressed.

## Reference examples

You will be given past cover letters as examples. These are for tone, structure, and phrasing-style reference ONLY — do not copy their specific content, employers, or claims. Only use experience that is actually true for this candidate, per the instructions below and the candidate's real background.

## Resume — technical accuracy

You will also be given the candidate's resume. Any specific technical skill, tool, programming language, framework, or technology you mention in the letter must be evidenced in the resume — do not invent, exaggerate, or infer technical experience the candidate doesn't actually have. In particular, do NOT pull specific languages, frameworks, engines, or other named technologies out of the job posting and into the letter unless the resume shows the candidate has real experience with them — a technology being in the job posting is not evidence the candidate knows it. It's fine, and often better, to express genuine interest in the company's mission, product, or engineering culture broadly, without naming specific technologies the candidate hasn't actually used.

The resume's ONLY purpose here is fact-checking — confirming that a skill or technology you were already going to mention is real. It is not a content source: do not scan it for additional accomplishments, projects, or details to pad the letter with, and do not restate resume bullet points just because they're available in context. The letter's level of detail and overall length should match the example letters' style below, not the resume's level of detail — a resume is dense by design; a cover letter is not, and having the resume available is not a reason to make this letter longer or more detailed than the examples.

## Instructions for this candidate

---
{instructions}
---

Follow these instructions exactly. Now write the letter for the role described in the next message."""


class GeneratorError(Exception):
    """Raised when the Generator's API call fails or returns no usable content."""


def _strip_code_fences(text: str) -> str:
    """Strip a leading/trailing ```...``` fence if present.

    Models sometimes wrap plain-text output in a markdown code fence even
    when told not to.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop the opening ``` or ```language line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # drop the trailing ``` line
        text = "\n".join(lines).strip()
    return text


def _format_examples(examples: list[str]) -> str:
    """Render past example letters as clearly-labeled, numbered blocks."""
    if not examples:
        return "(no past example letters provided)"
    blocks = [f"--- Example {i} ---\n{example.strip()}" for i, example in enumerate(examples, start=1)]
    return "\n\n".join(blocks)


def _build_user_message(
    jd_fields: dict,
    examples: list[str],
    resume: str,
    feedback: list[str] | None = None,
    length_feedback: list[str] | None = None,
) -> str:
    """Assemble the job-specific content (fields, requirements, resume, examples)."""
    minimum = jd_fields.get("minimum_requirements", [])
    preferred = jd_fields.get("preferred_requirements", [])

    minimum_block = "\n".join(f"- {item}" for item in minimum) or "(none listed)"
    preferred_block = "\n".join(f"- {item}" for item in preferred) or "(none listed)"
    today = date.today().strftime("%B %d, %Y")

    message = f"""Write a cover letter for this role.

Today's date: {today}
Use this exact date wherever the instructions call for the letter's date — do not guess, invent, or reuse a different date.

Company: {jd_fields.get("company", "")}
Role: {jd_fields.get("role_title", "")}
Role type: {jd_fields.get("role_type", "")}

Minimum requirements (address every one of these, even briefly):
{minimum_block}

Preferred requirements (use selectively, only where they fit naturally):
{preferred_block}

--- Resume (only name specific technical skills/tools/technologies that are evidenced here) ---
{resume}
--- End of resume ---

Past example letters — for tone and structure reference only, do not copy their specific content:

{_format_examples(examples)}"""

    if feedback:
        feedback_block = "\n".join(f"- {item}" for item in feedback)
        message += f"""

This is a revision of a previous draft that failed review. Fix these specific issues:
{feedback_block}"""

    if length_feedback:
        length_block = "\n".join(f"- {item}" for item in length_feedback)
        message += f"""

This is a revision of a previous draft that rendered a little over one printed page. Apply ONLY the length-reduction edit(s) below — do not touch the fixed opening paragraph, do not rewrite anything else, and unless an item below explicitly says otherwise, do not shorten the three skill bullets or drop their technical specifics or company-bridge sentences:
{length_block}"""

    return message


def generate(
    jd_fields: dict,
    examples: list[str],
    instructions: str,
    resume: str,
    feedback: list[str] | None = None,
    length_feedback: list[str] | None = None,
) -> str:
    """Draft a cover letter from the planned fields and retrieved examples.

    Makes a single OpenAI API call to write a first-draft cover letter,
    combining the structured job description fields, similar past letters
    as style/content reference, and the user's writing instructions. The
    resume is used to keep technical claims honest — see the "Resume —
    technical accuracy" section of SYSTEM_PROMPT_TEMPLATE.

    Args:
        jd_fields: Structured job description fields produced by
            src.agents.planner.plan (role_type, company, role_title,
            minimum_requirements, preferred_requirements).
        examples: Text of similar past cover letters, most similar first
            (from src.retrieval.retrieve_similar).
        instructions: The user's cover letter writing instructions
            (contents of instructions.md).
        resume: The candidate's resume text. Any specific technical skill,
            tool, language, or technology named in the letter must be
            evidenced here — technologies pulled from the job posting
            alone are not a valid basis for a claim.
        feedback: Optional list of specific issues from a prior
            src.agents.reviewer.review pass. When provided, appended to the
            prompt as a "Fix these specific issues:" section so this call
            revises the draft instead of writing one from scratch.
        length_feedback: Optional list of specific length-reduction edits
            from src.orchestrator's page-fit loop (src/page_fit.py), used
            when a rendered draft came out a little over one printed page.
            Distinct from `feedback` (rubric issues) — this is scoped
            narrowly to page-fit edits only (trim generic filler, or, as a
            last resort, lightly tighten wording within a sentence) and
            explicitly forbids touching the fixed opening paragraph or
            cutting bullet substance unless a specific item says otherwise.

    Returns:
        The drafted cover letter body text, with any markdown code fences
        and leading/trailing whitespace stripped.

    Raises:
        GeneratorError: If the API call fails, or the response contains no
            usable text content — including the case where a reasoning
            model (gpt-5.6-sol) burns its entire MAX_COMPLETION_TOKENS
            budget on internal reasoning before writing any visible
            output (finish_reason == "length" with empty content), which
            raises a more specific, actionable message than a generic
            empty-content error.
    """
    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            reasoning_effort=REASONING_EFFORT,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_TEMPLATE.format(instructions=instructions),
                },
                {
                    "role": "user",
                    "content": _build_user_message(
                        jd_fields, examples, resume, feedback, length_feedback
                    ),
                },
            ],
        )
    except openai.APIError as exc:
        raise GeneratorError(f"Generator API call failed: {exc}") from exc

    choice = response.choices[0]
    raw_text = choice.message.content or ""

    letter = _strip_code_fences(raw_text).strip()

    if not letter:
        if choice.finish_reason == "length":
            reasoning_tokens = getattr(
                getattr(response.usage, "completion_tokens_details", None),
                "reasoning_tokens",
                None,
            )
            raise GeneratorError(
                "Model exhausted its token budget on reasoning before "
                "generating any visible output "
                f"(finish_reason='length', reasoning_tokens={reasoning_tokens}, "
                f"completion_tokens={getattr(response.usage, 'completion_tokens', None)}, "
                f"budget={MAX_COMPLETION_TOKENS}) — try raising "
                "MAX_COMPLETION_TOKENS in src/agents/generator.py, or "
                "lowering REASONING_EFFORT further (e.g. to 'minimal' or "
                "'none')."
            )
        raise GeneratorError(
            "Generator returned empty content — nothing usable to write. "
            f"Raw response: {response!r}"
        )

    return letter


if __name__ == "__main__":
    # Includes an onsite/location requirement (last item) so this run also
    # confirms the Generator no longer writes a standalone sentence
    # restating logistics like "I am able to work onsite in Austin 4 days
    # a week" — that should now be left implicit or unaddressed rather
    # than called out explicitly, since instructions.md doesn't ask for it.
    sample_jd_fields = {
        "role_type": "swe",
        "company": "Nimbus Systems",
        "role_title": "Software Engineer, Backend",
        "minimum_requirements": [
            "Bachelor's degree in Computer Science or related field",
            "2+ years of professional software engineering experience",
            "Proficiency in Python or Go",
            "Experience designing and building RESTful APIs",
            "Must be able to work onsite in Austin, TX at least 4 days per week",
        ],
        "preferred_requirements": [
            "Experience with distributed systems at scale",
            "Familiarity with Kubernetes and container orchestration",
            "Contributions to open-source projects",
            "Exposure to event-driven architectures (e.g. Kafka)",
        ],
    }

    sample_example_1 = """Dear Recruiter,

My name is Jane Doe, and I am writing to express my interest in the Backend Engineer role at Initech. I am currently working as a software engineer with a strong focus on distributed systems and API design. I believe the following skills make me a strong fit for this role.

Backend Systems: At my current role, I designed and shipped a rate-limiting service that reduced downstream API errors by 40%, working primarily in Python and Go.

Distributed Systems: I led a project migrating a monolithic order-processing service into a set of independently deployable microservices, cutting deploy time from 45 minutes to under 5.

As for my interest in Initech, it is deeply rooted in the company's investment in developer tooling and platform reliability. I am enthusiastic about the possibility of bringing my skills to Initech and look forward to discussing how my background would allow me to contribute to the Platform team.

Sincerely,

Jane Doe"""

    sample_example_2 = """Dear Recruiter,

My name is Jane Doe, and I am writing to express my interest in the Software Engineer position at Globex. I am currently a software engineer with a background in backend systems and API design. I believe the following skills make me a strong fit for this role.

API Design: I built and maintained a public-facing REST API serving over 10,000 requests per minute, focusing on backward compatibility and clear versioning.

Open Source: I am an active contributor to an open-source workflow orchestration tool, where I've shipped several performance improvements to its task scheduler.

As for my interest in Globex, it is deeply rooted in the company's engineering culture and its reputation for shipping reliable infrastructure at scale. I am enthusiastic about the possibility of bringing my skills to Globex and look forward to discussing how my background would allow me to contribute to the Infrastructure team.

Sincerely,

Jane Doe"""

    # Deliberately lacks Kubernetes/container-orchestration experience even
    # though sample_jd_fields lists it as a preferred requirement — the
    # generated letter should NOT claim it, per the resume-accuracy rule.
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
Python, Go, REST API design, SQL, Git, basic Docker.
(No professional Kubernetes/container-orchestration experience.)"""

    if config.INSTRUCTIONS_PATH.exists():
        instructions_text = config.INSTRUCTIONS_PATH.read_text()
    else:
        instructions_text = "(no instructions.md found — using empty instructions for this test)"

    try:
        letter = generate(
            jd_fields=sample_jd_fields,
            examples=[sample_example_1, sample_example_2],
            instructions=instructions_text,
            resume=sample_resume,
        )
    except GeneratorError as exc:
        print(f"GeneratorError: {exc}")
        sys.exit(1)

    print(letter)
