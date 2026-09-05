// Options page for Notebook Math Scribe. Runs as a normal extension page
// (not a content script), so it has full access to chrome.storage directly.

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

const backendUrlInput = document.getElementById("backend-url");
const saveBtn = document.getElementById("save-btn");
const testBtn = document.getElementById("test-btn");
const statusEl = document.getElementById("status");

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = kind || "";
}

function loadSettings() {
  chrome.storage.local.get(["backendUrl"], (result) => {
    backendUrlInput.value = result.backendUrl || DEFAULT_BACKEND_URL;
  });
}

function saveSettings() {
  const backendUrl = (backendUrlInput.value.trim() || DEFAULT_BACKEND_URL).replace(/\/$/, "");

  chrome.storage.local.set({ backendUrl }, () => {
    setStatus("Saved.", "ok");
  });
}

async function testConnection() {
  const backendUrl = (backendUrlInput.value.trim() || DEFAULT_BACKEND_URL).replace(/\/$/, "");
  setStatus("Testing...", "");

  try {
    const response = await fetch(`${backendUrl}/health`);
    if (!response.ok) {
      setStatus(`Backend responded with ${response.status}.`, "error");
      return;
    }
    const data = await response.json();
    if (data && data.status === "ok") {
      setStatus("Connected — backend is reachable.", "ok");
    } else {
      setStatus('Backend responded, but not with the expected {"status": "ok"} body.', "error");
    }
  } catch (err) {
    setStatus(`Couldn't reach the backend: ${err.message}`, "error");
  }
}

saveBtn.addEventListener("click", saveSettings);
testBtn.addEventListener("click", testConnection);

loadSettings();
