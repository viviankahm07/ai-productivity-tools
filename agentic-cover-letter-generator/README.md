# Agentic Cover Letter Generator

An agentic CLI tool that drafts a tailored cover letter from a job posting.
Give it a job URL (or raw job description text) and it fetches the posting,
retrieves your most relevant past letters by embedding similarity, and runs
a **Planner &rarr; Generator &rarr; Reviewer** pipeline of Claude API calls to
produce a polished `.docx` draft — checked against your own resume and
writing instructions so it doesn't invent experience you don't have.

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
3. **Planner** (`src/agents/planner.py`) — extract structured fields (company,
   role title, role type, key requirements) from the job description.
4. **Generator** (`src/agents/generator.py`) — draft the letter using the
   plan, the retrieved past letters, your resume, and `instructions.md`.
5. **Reviewer** (`src/agents/reviewer.py`) — check the draft against the plan,
   resume, and instructions; flags issues that trigger one revise-and-retry
   pass through the Generator.
6. **docx writer** (`src/docx_writer.py`) — save the final letter as a
   formatted `.docx` file in `output/`.

Wired together end to end in `src/orchestrator.py`.

## Setup

```bash
git clone <this-repo-url>
cd agentic-cover-letter-generator

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then set up your personal, gitignored config and content files from their
`.example` templates:

```bash
# API key + contact info used in the letter header
cp .env.example .env
# then edit .env and add your ANTHROPIC_API_KEY and contact details

# your resume — used by the Generator/Reviewer to keep claims honest
cp resume.md.example resume.md
# then edit resume.md with your real education/experience/projects

# your fixed writing template and tone rules
cp instructions.md.example instructions.md
# then edit instructions.md with your real instructions

# a past cover letter to seed retrieval (repeat for each one you have)
cp examples/sample_letter.txt.example examples/your_company.txt
# then edit it, and add a matching entry to examples/role_types.json,
# e.g. {"your_company.txt": "swe"} — see examples/README.md for the format
```

## Usage

```bash
python3 src/orchestrator.py "<job_url>"
```

`<job_url>` can be a URL to a job posting, or raw job description text. The
generated draft is written to `output/`. (`python main.py "<job_url>"` is
equivalent and gives friendlier `--help` output.)

## What's excluded from this repo

`resume.md`, `instructions.md`, and every real letter in `examples/`
(including `examples/role_types.json`) are gitignored — they contain real
personal information: your name, contact details, employers, and the
companies you've actually applied to. Only their `.example` counterparts
(`resume.md.example`, `instructions.md.example`,
`examples/sample_letter.txt.example`) are tracked, showing the expected
format with fictional placeholder content. `output/` (your generated
letters) and `.env` (your API key) are gitignored the same way.
