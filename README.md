# AI Productivity Tools

A collection of small, independent AI-powered tools built to automate parts of the internship/job search — from finding roles, to writing the cover letter, to reviewing the emails that follow. Each tool lives in its own folder with its own dependencies and its own README; nothing here shares code or state.

| Tool | What it does | Stack |
|---|---|---|
| [`internship-watcher`](internship-watcher) | Scrapes company career pages daily, filters for U.S. software engineering internships, and opens a GitHub Issue when a new one appears. | Python, GitHub Actions |
| [`agentic-cover-letter-generator`](agentic-cover-letter-generator) | Give it a job posting URL; a Planner → Generator → Reviewer pipeline of Claude API calls drafts a tailored `.docx` cover letter grounded in your real resume and past letters. | Python, Claude API, sentence-transformers |
| [`ai-email-reviewer`](ai-email-reviewer) | A Chrome extension that reads the open Gmail thread and your in-progress reply, then gives live tone/clarity/completeness feedback via a FastAPI backend. | JavaScript (Manifest V3), FastAPI, OpenAI API |

## Why these three

They cover three different stages of the same workflow: **finding** a role (`internship-watcher`), **applying** to it (`agentic-cover-letter-generator`), and **communicating** afterward (`ai-email-reviewer`). Each was built to remove one specific piece of manual, repetitive work from job searching.

## Repo structure

```
ai-productivity-tools/
├── internship-watcher/              scrape → filter → dedupe → GitHub Issue
├── agentic-cover-letter-generator/  job posting → tailored .docx cover letter
├── ai-email-reviewer/               Gmail extension + FastAPI review backend
│   ├── backend/
│   └── extension/
└── README.md                        you are here
```

## Getting started

Each project is self-contained — `cd` into it and follow its own README for setup, environment variables, and usage. General shape across all three:

```bash
git clone https://github.com/viviankahm07/ai-productivity-tools.git
cd ai-productivity-tools/<project-name>

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in the required keys — see that project's README
```

- `internship-watcher` needs no API key to scrape, but a `GITHUB_TOKEN` is required if you want it to file issues.
- `agentic-cover-letter-generator` needs an `ANTHROPIC_API_KEY`, plus your own `resume.md` and `instructions.md` (copied from the tracked `.example` templates).
- `ai-email-reviewer` needs an `OPENAI_API_KEY` for the backend, then the `extension/` folder loaded unpacked in Chrome.

## A note on personal data

None of these tools ship with real personal content. Resumes, cover letter instructions, past letters, personal watchlists, and API keys are all gitignored in their respective projects — only `.example` templates with placeholder content are tracked. See each project's README for exactly what's excluded and why.

## License

No license file is currently included — all rights reserved by default until one is added.
