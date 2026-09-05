console.log("Notebook Math Scribe: content script loaded");

// Local default only - never hardcode a real deployed backend URL here (or
// commit one). The real value lives in chrome.storage.local, set via the
// options page, and is read fresh on every request in getSettings() below.
const DEFAULT_BACKEND_URL = "https://REDACTED.up.railway.app/";

/**
 * getSettings()
 * Reads the backend URL from chrome.storage.local, falling back to the
 * local default backend URL if nothing has been configured yet.
 */
function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["backendUrl"], (result) => {
      const backendUrl = (result.backendUrl || DEFAULT_BACKEND_URL).replace(/\/$/, "");
      resolve({ backendUrl });
    });
  });
}

/**
 * requestConvert(imageDataUrl)
 * POSTs the pasted image to the backend's /convert endpoint and returns the
 * transcribed markdown. Throws with a user-facing message on any failure
 * (network error, backend error, etc.).
 */
async function requestConvert(imageDataUrl) {
  const { backendUrl } = await getSettings();

  let response;
  try {
    response = await fetch(`${backendUrl}/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_base64: imageDataUrl }),
    });
  } catch (err) {
    throw new Error(
      `Couldn't reach the backend at ${backendUrl}: ${err.message}. Check the backend URL in the options page.`
    );
  }

  if (!response.ok) {
    let detail = "";
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || "";
    } catch (_) {
      detail = await response.text().catch(() => "");
    }
    throw new Error(`Backend responded with ${response.status}${detail ? `: ${detail}` : ""}.`);
  }

  const data = await response.json();
  return data.markdown;
}

/**
 * tryClassicNotebookInsert(markdown)
 * Classic Jupyter Notebook exposes a `window.Jupyter` global in the page's
 * own JavaScript context. Content scripts run in an isolated JS world and
 * can't see page-created globals directly (they DO share the DOM, though),
 * so this bridges across by injecting an inline <script> tag - which always
 * runs in the page's main world - and reads its result back off a shared
 * DOM element's dataset rather than a JS return value.
 *
 * Returns { available, ok }: `available` is whether window.Jupyter.notebook
 * exists at all; `ok` is whether the insertion itself succeeded.
 */
function tryClassicNotebookInsert(markdown) {
  const marker = document.createElement("div");
  marker.style.display = "none";
  document.documentElement.appendChild(marker);

  const script = document.createElement("script");
  script.textContent = `
    (function() {
      var marker = document.currentScript.previousElementSibling;
      try {
        if (!window.Jupyter || !window.Jupyter.notebook) {
          marker.dataset.nmsAvailable = "false";
          return;
        }
        marker.dataset.nmsAvailable = "true";

        var notebook = window.Jupyter.notebook;
        var cell = notebook.get_selected_cell();
        if (!cell || cell.cell_type !== "markdown") {
          var index = notebook.get_selected_index();
          notebook.insert_cell_below("markdown", index);
          notebook.select_next();
          cell = notebook.get_selected_cell();
        }

        var existingText = (cell.get_text && cell.get_text()) || "";
        var addition = ${JSON.stringify(markdown)};
        cell.set_text(existingText ? existingText + "\\n\\n" + addition : addition);
        cell.render();
        marker.dataset.nmsOk = "true";
      } catch (err) {
        marker.dataset.nmsOk = "false";
      }
    })();
  `;
  marker.after(script);

  const available = marker.dataset.nmsAvailable === "true";
  const ok = marker.dataset.nmsOk === "true";

  script.remove();
  marker.remove();

  return { available, ok };
}

/**
 * trySyntheticPasteInsert(markdown)
 * Notebook 7 / JupyterLab-style frontend path: finds the active cell's
 * CodeMirror 6 editable root and dispatches a synthetic `paste`
 * ClipboardEvent carrying the markdown as text/plain, so CodeMirror's own
 * paste handling inserts it at the cursor. Pure DOM event dispatch, so it
 * works fine from this isolated-world content script - no page-context
 * bridge needed here.
 */
function trySyntheticPasteInsert(markdown) {
  const target = document.querySelector(".jp-Cell.jp-mod-active .cm-content");
  if (!target) return false;

  const dataTransfer = new DataTransfer();
  dataTransfer.setData("text/plain", markdown);

  const pasteEvent = new ClipboardEvent("paste", {
    clipboardData: dataTransfer,
    bubbles: true,
    cancelable: true,
  });

  target.focus();
  target.dispatchEvent(pasteEvent);
  return true;
}

/**
 * insertIntoCell(markdown)
 * Tries the classic Notebook API first, then falls back to the Notebook
 * 7 / JupyterLab synthetic-paste path. Returns { ok, error }.
 */
function insertIntoCell(markdown) {
  const classicResult = tryClassicNotebookInsert(markdown);
  if (classicResult.available) {
    if (classicResult.ok) {
      console.log("[notebook-math-scribe] inserted via classic API");
      return { ok: true };
    }
    return {
      ok: false,
      error: "Found classic Jupyter Notebook, but couldn't insert into a cell. Click into a cell and try again.",
    };
  }

  if (trySyntheticPasteInsert(markdown)) {
    console.log("[notebook-math-scribe] inserted via synthetic paste");
    return { ok: true };
  }

  return {
    ok: false,
    error: "Couldn't find an active notebook cell to insert into. Click into a cell first, or use Copy to clipboard instead.",
  };
}

/**
 * readPastedImage(event)
 * Pulls the first pasted image (if any) off a paste event's clipboard data
 * and resolves it as a data URL. Resolves null if no image was found.
 */
function readPastedImage(event) {
  return new Promise((resolve) => {
    const items = event.clipboardData ? Array.from(event.clipboardData.items) : [];
    const imageItem = items.find((item) => item.kind === "file" && item.type.startsWith("image/"));

    if (!imageItem) {
      resolve(null);
      return;
    }

    const file = imageItem.getAsFile();
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

/**
 * injectMathScribeUI()
 * Injects a floating "📐" button and a conversion panel into the page,
 * both inside a shadow root so Jupyter's page CSS can't bleed into our UI
 * (and vice versa). Safe to call more than once - only injects if not
 * already present.
 *
 * IMPORTANT: the paste listener below is attached to a single small element
 * inside this panel, not to `document`/`window`. It only fires when that
 * element itself has focus, so pasting images into notebook cells anywhere
 * else on the page is completely unaffected and keeps working exactly as
 * before - this extension never listens for paste globally.
 */
function injectMathScribeUI() {
  if (document.getElementById("notebook-math-scribe-host")) return;

  const host = document.createElement("div");
  host.id = "notebook-math-scribe-host";
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }

    .fab {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      border: none;
      font-size: 24px;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.25);
      z-index: 2147483000;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.15s ease;
    }
    .fab:hover { transform: scale(1.08); }
    .fab:active { transform: scale(0.96); }

    .panel {
      position: fixed;
      bottom: 92px;
      right: 24px;
      width: 380px;
      max-width: min(90vw, 720px);
      max-height: 85vh;
      background: white;
      border-radius: 16px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.2);
      z-index: 2147483000;
      display: none;
      flex-direction: column;
      overflow: hidden;
      border: 1px solid #e5e7eb;
    }
    .panel.open { display: flex; }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      flex-shrink: 0;
    }
    .panel-title { font-size: 15px; font-weight: 600; }
    .panel-close {
      background: none;
      border: none;
      color: white;
      font-size: 18px;
      cursor: pointer;
      line-height: 1;
      opacity: 0.85;
      padding: 4px;
    }
    .panel-close:hover { opacity: 1; }

    .panel-body {
      flex: 1;
      min-height: 0;
      padding: 16px;
      overflow-y: auto;
      font-size: 13.5px;
      line-height: 1.5;
      color: #1f2937;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .paste-target {
      border: 2px dashed #c7c8fb;
      border-radius: 10px;
      padding: 18px 12px;
      text-align: center;
      color: #6b7280;
      font-size: 12.5px;
      cursor: text;
      outline: none;
    }
    .paste-target:focus { border-color: #6366f1; background: #f5f5ff; }

    .thumbnail-wrap { text-align: center; }
    .thumbnail {
      max-width: 100%;
      max-height: 160px;
      border-radius: 8px;
      border: 1px solid #e5e7eb;
    }

    button.action {
      background: #6366f1;
      color: white;
      border: none;
      border-radius: 10px;
      padding: 9px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    button.action:hover:not(:disabled) { background: #4f46e5; }
    button.action:disabled { background: #c7c8fb; cursor: default; }

    .row { display: flex; gap: 8px; }
    .row button.action { flex: 1; }

    .markdown-output {
      width: 100%;
      min-height: 120px;
      resize: vertical;
      padding: 8px 10px;
      font-size: 12.5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      color: #1f2937;
      background: #f9fafb;
    }

    .loading {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #6b7280;
    }
    .spinner {
      width: 16px;
      height: 16px;
      border: 2px solid #e5e7eb;
      border-top-color: #6366f1;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .error {
      color: #b91c1c;
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 12.5px;
    }

    .status {
      color: #15803d;
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 12.5px;
    }
  `;
  shadow.appendChild(style);

  const fab = document.createElement("button");
  fab.className = "fab";
  fab.title = "Convert a math screenshot to markdown";
  fab.textContent = "📐";
  shadow.appendChild(fab);

  const panel = document.createElement("div");
  panel.className = "panel";

  const panelHeader = document.createElement("div");
  panelHeader.className = "panel-header";

  const panelTitle = document.createElement("span");
  panelTitle.className = "panel-title";
  panelTitle.textContent = "Math → Markdown";
  panelHeader.appendChild(panelTitle);

  const closeBtn = document.createElement("button");
  closeBtn.className = "panel-close";
  closeBtn.title = "Close";
  closeBtn.textContent = "✕";
  panelHeader.appendChild(closeBtn);

  panel.appendChild(panelHeader);

  const panelBody = document.createElement("div");
  panelBody.className = "panel-body";
  panel.appendChild(panelBody);

  const pasteTarget = document.createElement("div");
  pasteTarget.className = "paste-target";
  pasteTarget.tabIndex = 0;
  pasteTarget.textContent = "Click here and press Ctrl/Cmd+V to paste an image";
  panelBody.appendChild(pasteTarget);

  const thumbnailWrap = document.createElement("div");
  thumbnailWrap.className = "thumbnail-wrap";
  thumbnailWrap.hidden = true;
  const thumbnail = document.createElement("img");
  thumbnail.className = "thumbnail";
  thumbnailWrap.appendChild(thumbnail);
  panelBody.appendChild(thumbnailWrap);

  const convertBtn = document.createElement("button");
  convertBtn.className = "action";
  convertBtn.textContent = "Convert";
  convertBtn.disabled = true;
  panelBody.appendChild(convertBtn);

  const loadingEl = document.createElement("div");
  loadingEl.className = "loading";
  loadingEl.hidden = true;
  const spinnerEl = document.createElement("div");
  spinnerEl.className = "spinner";
  loadingEl.appendChild(spinnerEl);
  loadingEl.appendChild(document.createTextNode("Converting..."));
  panelBody.appendChild(loadingEl);

  const markdownOutput = document.createElement("textarea");
  markdownOutput.className = "markdown-output";
  markdownOutput.readOnly = true;
  markdownOutput.hidden = true;
  markdownOutput.placeholder = "Converted markdown will appear here...";
  panelBody.appendChild(markdownOutput);

  const actionRow = document.createElement("div");
  actionRow.className = "row";
  const insertBtn = document.createElement("button");
  insertBtn.className = "action";
  insertBtn.textContent = "Insert into cell";
  insertBtn.disabled = true;
  const copyBtn = document.createElement("button");
  copyBtn.className = "action";
  copyBtn.textContent = "Copy to clipboard";
  copyBtn.disabled = true;
  actionRow.appendChild(insertBtn);
  actionRow.appendChild(copyBtn);
  panelBody.appendChild(actionRow);

  const errorEl = document.createElement("div");
  errorEl.className = "error";
  errorEl.hidden = true;
  panelBody.appendChild(errorEl);

  const statusEl = document.createElement("div");
  statusEl.className = "status";
  statusEl.hidden = true;
  panelBody.appendChild(statusEl);

  panel.appendChild(panelBody);
  shadow.appendChild(panel);

  // --- state ---
  let pastedImageDataUrl = null;
  let markdown = null;
  let isBusy = false;
  let errorMessage = null;
  let statusMessage = null;

  function render() {
    thumbnailWrap.hidden = !pastedImageDataUrl;
    if (pastedImageDataUrl) thumbnail.src = pastedImageDataUrl;

    convertBtn.disabled = !pastedImageDataUrl || isBusy;
    loadingEl.hidden = !isBusy;

    markdownOutput.hidden = !markdown;
    markdownOutput.value = markdown || "";

    insertBtn.disabled = !markdown || isBusy;
    copyBtn.disabled = !markdown || isBusy;

    errorEl.hidden = !errorMessage;
    errorEl.textContent = errorMessage || "";

    statusEl.hidden = !statusMessage;
    statusEl.textContent = statusMessage || "";
  }

  // Scoped to this one element only - see the function-level comment above
  // for why this is safe to leave attached at all times.
  pasteTarget.addEventListener("paste", async (event) => {
    event.preventDefault();
    const imageDataUrl = await readPastedImage(event);

    if (!imageDataUrl) {
      errorMessage = "No image found on the clipboard. Copy an image (e.g. a screenshot) and try pasting again.";
      statusMessage = null;
      render();
      return;
    }

    pastedImageDataUrl = imageDataUrl;
    markdown = null;
    errorMessage = null;
    statusMessage = null;
    render();
  });

  convertBtn.addEventListener("click", async () => {
    if (!pastedImageDataUrl || isBusy) return;

    isBusy = true;
    errorMessage = null;
    statusMessage = null;
    render();

    try {
      markdown = await requestConvert(pastedImageDataUrl);
    } catch (err) {
      errorMessage = err.message;
      markdown = null;
    }

    isBusy = false;
    render();
  });

  insertBtn.addEventListener("click", () => {
    if (!markdown) return;

    const result = insertIntoCell(markdown);
    if (result.ok) {
      errorMessage = null;
      statusMessage = "Inserted into the notebook cell.";
    } else {
      statusMessage = null;
      errorMessage = result.error;
    }
    render();
  });

  copyBtn.addEventListener("click", async () => {
    if (!markdown) return;

    try {
      await navigator.clipboard.writeText(markdown);
      errorMessage = null;
      statusMessage = "Copied to clipboard.";
    } catch (err) {
      statusMessage = null;
      errorMessage = `Couldn't copy to clipboard: ${err.message}`;
    }
    render();
  });

  closeBtn.addEventListener("click", () => {
    panel.classList.remove("open");
  });

  fab.addEventListener("click", () => {
    panel.classList.add("open");
    pastedImageDataUrl = null;
    markdown = null;
    isBusy = false;
    errorMessage = null;
    statusMessage = null;
    render();
    pasteTarget.focus();
  });

  render();
}

injectMathScribeUI();
