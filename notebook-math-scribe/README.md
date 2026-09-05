# Notebook Math Scribe

A Chrome extension that turns a screenshot of a math equation, proof, or derivation
(from lecture slides, a textbook, anywhere) into clean Jupyter-flavored markdown —
pasted straight into a floating panel inside the notebook, converted by a
vision-capable OpenAI model, and inserted into the current cell with one click.

## Key Features

- **In-page Jupyter integration** — injects a floating "📐" button and conversion
  panel directly into a Jupyter Notebook page via a Manifest V3 content script,
  isolated from Jupyter's own styles with a Shadow DOM.
- **Manually triggered, scoped paste handling** — the panel's paste target only
  listens for paste events on itself, and only exists once the button has been
  clicked. There is no global paste listener, so pasting images into notebook cells
  anywhere else on the page keeps working exactly as before.
- **Vision-model transcription** — sends the pasted image to the backend, which asks
  an OpenAI vision model to transcribe it into Jupyter markdown: `$...$` / `$$...$$`
  for math, with step numbering, bullet structure, and bold/italic annotations
  preserved.
- **Dual-frontend cell insertion** — detects whether the page is running classic
  Jupyter Notebook (`window.Jupyter`) or the Notebook 7 / JupyterLab-style frontend
  and inserts the converted markdown accordingly, falling back to "Copy to clipboard"
  if neither is found.
- **Configurable backend URL** — set on an options page and read from
  `chrome.storage.local` at request time; nothing is hardcoded in the shipped
  extension.

## Tech Stack

`JavaScript (Manifest V3) • Python • FastAPI • OpenAI API (vision) • Uvicorn • Pydantic • pytest • Railway`

## How It Works

```
Math screenshot (clipboard)
        │  user clicks 📐, pastes into the panel's paste target
        ▼
Chrome extension UI (Shadow DOM panel)
        │  POST /convert  {image_base64}
        ▼
FastAPI backend  (backend/routers/convert.py)
        │  chat.completions.create(... image_url ...)
        ▼
OpenAI API  (gpt-4o-mini by default, vision-capable)
        │  Jupyter-flavored markdown ($...$ / $$...$$)
        ▼
Panel shows markdown for review
        │  "Insert into cell" or "Copy to clipboard"
        ▼
Classic Notebook API  or  synthetic paste on CodeMirror
```

The backend is a thin, stateless relay: it holds the system prompt and the OpenAI
credentials, and has no database or user accounts. Each `/convert` call is
independent — there's no conversation state to carry between requests.

## Project Structure

```text
backend/            FastAPI service
  main.py             App entrypoint, CORS, route registration, /health
  config.py           Environment-based configuration (.env)
  routers/
    convert.py         POST /convert — transcribes an image via OpenAI
  tests/               pytest suite for the endpoint above
  requirements.txt     Runtime dependencies
  requirements-dev.txt Runtime + test dependencies
  Procfile             Railway start command

extension/           Chrome extension (Manifest V3)
  manifest.json        Extension manifest
  content.js           Floating button/panel UI, paste handling, cell insertion
  options.html          Settings page markup
  options.js            Settings page logic (backend URL, test connection)
```

## Getting Started

### 1. Clone

```bash
git clone https://github.com/viviankahm07/ai-productivity-tools.git
cd ai-productivity-tools/notebook-math-scribe
```

### 2. Run the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set OPENAI_API_KEY

uvicorn main:app --reload
```

The API is now available at `http://127.0.0.1:8000` (`/health` should return
`{"status": "ok"}`).

### 3. Load the extension

1. In Chrome, open `chrome://extensions`, enable **Developer mode**, and click **Load
   unpacked**.
2. Select the `extension/` folder.
3. Click the extension's **Details** → **Extension options** (or right-click its
   toolbar icon → **Options**) and set the **Backend URL** (defaults to
   `http://127.0.0.1:8000` if left blank). Use **Test connection** to confirm it can
   reach `/health`.
4. Open a notebook at `http://localhost/...` or `http://127.0.0.1/...` — a floating
   "📐" button appears in the bottom-right corner.
5. Copy a screenshot of an equation or derivation, click the button, click into the
   paste box, and press Ctrl/Cmd+V.

## Environment Variables

Defined in `backend/.env` (see `backend/.env.example` for the template — never commit
real values):

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | Your OpenAI API key. Without it, `/convert` returns a `500` with a clear message. |
| `OPENAI_MODEL` | No | Defaults to `gpt-4o-mini`. Must be a vision-capable model. |

## Testing

The backend has a pytest suite covering the endpoint (health check, missing-API-key
error path, and a mocked-OpenAI-response happy path — the real OpenAI API is never
called in tests):

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

The extension has no automated tests; use the options page's "Test connection" button
and DevTools console logging (`[notebook-math-scribe] ...`) for manual verification.

## Known Limitations

- Classic Jupyter Notebook's `window.Jupyter` global lives in the page's own
  JavaScript context, which an isolated-world content script can't read directly.
  `content.js` bridges this by injecting a small inline `<script>` tag and reading
  its result back off a shared DOM element — a standard technique, but one more
  moving part than a plain function call.
- The Notebook 7 / JupyterLab insertion path depends on `.jp-Cell.jp-mod-active
  .cm-content` remaining CodeMirror 6's active-cell selector; if that markup changes,
  insertion falls through to the "click into a cell first" error and "Copy to
  clipboard" remains available as a fallback.
- The deployed backend has no authentication and a permissive CORS policy
  (`allow_origins=["*"]`) — a deliberate tradeoff since it holds no user data or
  sessions, but it does mean anyone with the URL can call `/convert` and consume the
  configured OpenAI quota.
- Transcription quality depends entirely on the configured OpenAI model and the
  screenshot's legibility; handwritten or low-resolution images may transcribe
  imperfectly, and the system prompt explicitly avoids hedging in the output.

## Future Improvements

- Support pasting multiple images per conversion for multi-part derivations.
- Persist recent conversions locally so a panel accidentally closed mid-review isn't
  lost.
- Add lightweight rate limiting or an API key check on the backend before making it
  publicly reachable long-term.
- Detect and support additional Jupyter frontends (e.g. VS Code's notebook UI) beyond
  classic Notebook and Notebook 7/JupyterLab.
