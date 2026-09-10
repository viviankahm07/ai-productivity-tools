# Agentic Cover Letter Generator

An agentic CLI tool that drafts a tailored cover letter from a job posting.
Give it a job URL (or raw job description text) and it fetches the posting,
retrieves your most relevant past letters by embedding similarity, and runs
a **Planner &rarr; Generator &rarr; Reviewer** pipeline of OpenAI API calls to
produce a polished `.docx` draft — fact-checked against your own resume, an
optional richer knowledge base, and your retrieved past letters (any one of
the three is a valid source, so a real detail that didn't make it onto the
resume for space reasons still counts) and your writing instructions, so it
doesn't invent experience you don't have. The final `.docx` is rendered to
match a fixed personal format (bold centered name header, real bulleted
skill sections with bold lead-in headers) and checked against a
one-page-length estimate, tightening automatically if it runs long.

This is plain Python orchestration — each stage is a separate `messages.create`
call chained together in `src/orchestrator.py`, not a Claude Code / Agent SDK
workflow.

## Architecture

1. **Ingest** (`src/ingest.py`) — fetch and clean the job posting text from a
   URL, or accept raw pasted text directly.
2. **Retrieval** (`src/retrieval.py`) — embed your past letters in
   `examples/` with `sentence-transformers`, cache the embeddings, and pull
   the ones most similar to the current job description (boosted by a
   `role_types.json` role-type match).
3. **Knowledge base retrieval** (`src/knowledge_base.py`, optional) — if
   `knowledge_base.md` exists, parse it into sections (see below) and
   retrieve the ones most relevant to the current job description, the
   same way `src/retrieval.py` retrieves past letters. Skipped gracefully
   (empty string, no error) if the file doesn't exist.
4. **Planner** (`src/agents/planner.py`) — extract structured fields (company,
   role title, role type, key requirements) from the job description.
5. **Generator** (`src/agents/generator.py`) — draft the letter using the
   plan, the retrieved past letters, your resume, the retrieved knowledge-
   base sections, and `instructions.md`.
6. **Reviewer** (`src/agents/reviewer.py`) — check the draft against the plan,
   instructions, and a fixed rubric (fixed-sentence fidelity, role/company
   consistency, minimum-requirement coverage, length, and factual accuracy).
   The factual-accuracy check treats your resume, the same retrieved
   knowledge-base sections, and the same retrieved past letters passed to
   the Generator as equally valid sources — a claim is only flagged if
   it's unsupported by *all three* — since a resume is dense by design and
   can't list every detail your past letters or knowledge base cover.
   Flags trigger one revise-and-retry pass through the Generator.
7. **docx writer** (`src/docx_writer.py`) — render the final letter as a
   `.docx` in `output/`, matching a fixed personal format: bold centered
   name header, real Word bulleted-list formatting for each skill section
   (not a typed "•"), and bold lead-in headers — decoding both literal
   `**markdown**` and any stray Unicode "styled" lookalike characters a
   model might substitute, so formatting renders correctly either way.
8. **Page-fit check** (`src/page_fit.py`) — estimate whether the rendered
   `.docx` fits on one printed page (word-wrapping simulated against real
   font metrics, not just a word count). If it runs long, `orchestrator.py`
   tightens it in order — trim generic filler phrasing, tighten rendering
   spacing/margins, then lightly trim in-sentence wording as a last
   resort — re-checking after each step and stopping as soon as it fits,
   without shortening the three skill bullets' substance unless every
   earlier step already failed.

Wired together end to end in `src/orchestrator.py`.

## Setup

```bash
git clone <this-repo-url>
cd agentic-cover-letter-generator

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

The `playwright install chromium` step downloads a headless browser used
as a fallback in `src/ingest.py` when a job posting renders its content
client-side via JavaScript (e.g. Workday's `*.wd5.myworkdayjobs.com`
postings) — the fast `requests`-based fetch is tried first and used as-is
whenever it already returns enough text, so this only kicks in for sites
that need it.

Then set up your personal, gitignored config and content files from their
`.example` templates:

```bash
# API key + contact info used in the letter header
cp .env.example .env
# then edit .env and add your OPENAI_API_KEY and contact details

# your resumes — used by the Generator/Reviewer to keep claims honest.
# One per role_type (src/agents/planner.VALID_ROLE_TYPES: swe,
# swe_finance, swe_business) so each letter is fact-checked against the
# resume version tailored to that audience — the underlying background is
# the same, but what you foreground differs. E.g. resume_swe_finance.md
# can surface quant/markets-adjacent coursework and projects that
# resume_swe.md might leave out to keep the general-SWE version focused.
cp resume.md.example resume_swe.md
cp resume.md.example resume_swe_finance.md
cp resume.md.example resume_swe_business.md
# then edit each with your real education/experience/projects, framed for
# that role type

# your fixed writing template and tone rules
cp instructions.md.example instructions.md
# then edit instructions.md with your real instructions

# a past cover letter to seed retrieval (repeat for each one you have)
cp examples/sample_letter.txt.example examples/your_company.txt
# then edit it, and add a matching entry to examples/role_types.json,
# e.g. {"your_company.txt": "swe"} — see examples/README.md for the format

# optional: a single, unified, richer background document — not split by
# role_type, unlike the resumes above. src/knowledge_base.py retrieves
# the sections most relevant to each job and passes them to the
# Generator/Reviewer as an equally-trusted, deeper source alongside your
# resume. Skipped gracefully if you don't create this file.
cp knowledge_base.md.example knowledge_base.md
# then edit it with your real background — keep the <h2>/<h3>/<h4>
# section-header structure, since that's what defines the retrievable
# chunks (see the comment at the top of the file)
```

The pipeline classifies each job posting's `role_type` before picking a
resume, so if `resume_<role_type>.md` (or `.txt`) is missing for the type it
just classified, it falls back to a generic `resume.md`/`resume.txt` (if you
have one) with a printed warning, rather than failing immediately — this is
intentional, so a partially-split resume setup still works. It only raises
`FileNotFoundError` if neither the role-specific file nor the generic
fallback exists.

## Usage

```bash
python3 src/orchestrator.py "<job_url>"
```

`<job_url>` can be a URL to a job posting, or raw job description text. The
generated draft is written to `output/`. (`python main.py "<job_url>"` is
equivalent and gives friendlier `--help` output.)

## Notes

- `knowledge_base.md` is parsed as real HTML despite the `.md` extension
  (kept consistent with the resume/instructions naming convention) —
  `src/knowledge_base.py` splits it into retrievable sections at its
  `<h2>`/`<h3>`/`<h4>` boundaries. At roughly 8,000 words for the reference
  document this was built against — larger than the resume and all
  retrieved example letters combined — sending the whole file into every
  Generator/Reviewer call would meaningfully bloat every prompt with
  mostly irrelevant material, since any single letter only draws on a
  handful of sections. So this reuses `src/retrieval.py`'s
  sentence-transformers approach to retrieve only the most relevant
  sections per job (`kb.DEFAULT_K = 6`), rather than embedding the file in
  full on every call.
- The model is set in `config.MODEL_NAME` (currently `gpt-5.6-sol`). It's a
  reasoning model, so part of its output token budget goes to internal
  reasoning before it writes any visible text — if you swap in a different
  reasoning model and start seeing `GeneratorError`s about an empty
  response, raise `MAX_COMPLETION_TOKENS` and/or lower `REASONING_EFFORT`
  in `src/agents/generator.py`.
- `src/page_fit.py`'s page-count estimate is exactly that — an estimate,
  calibrated against a known one-page reference letter, not a real layout
  engine (there's no Word/LibreOffice in this setup to render an exact
  page count from). It's precise enough to drive the tightening loop, not
  to promise an exact line count.

## What's excluded from this repo

`resume_swe.md`, `resume_swe_finance.md`, `resume_swe_business.md` (and
their `.txt` counterparts, and the generic `resume.md`/`resume.txt`
fallback), `instructions.md`, `knowledge_base.md`, and every real letter in
`examples/` (including `examples/role_types.json`) are gitignored — they
contain real personal information: your name, contact details, employers,
and the companies you've actually applied to. Only their `.example`
counterparts (`resume.md.example`, `instructions.md.example`,
`knowledge_base.md.example`, `examples/sample_letter.txt.example`) are
tracked, showing the expected format with fictional placeholder content.
`output/` (your generated letters), `.embeddings_cache/` (cached
embeddings for both past letters and knowledge-base sections), and `.env`
(your API key) are gitignored the same way.
