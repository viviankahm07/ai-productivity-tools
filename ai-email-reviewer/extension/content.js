console.log("Gmail AI Reply Reviewer: content script loaded");

// Points at a local backend by default (see backend/README.md to run one).
// If you deploy your own backend, set its URL here on your own machine —
// don't commit a real, publicly-reachable URL to a public repo, since
// anyone reading the source could call it directly and spend your API quota.
const BACKEND_BASE_URL = "http://127.0.0.1:8000";

/**
 * extractThread()
 * Finds the open Gmail thread container and pulls out a structured list of
 * messages (sender, body text, collapsed state) from it.
 *
 * DOM assumptions (confirmed via manual DevTools inspection on real threads,
 * may shift with Gmail's obfuscated class names over time):
 *   - div.aeJ                 -> scrollable container wrapping all messages in a thread
 *   - [role="listitem"]       -> individual message item, scoped inside div.aeJ
 *                                 (NOT div.aeF/div.aeG - those turned out to be a
 *                                 single message-list wrapper and an unrelated
 *                                 per-thread footer element, not per-message)
 *   - aria-expanded            -> "true"/"false" on the listitem, reflects real
 *                                 collapsed/expanded state (confirmed empirically)
 *   - .adn.ads[data-message-id] -> the actual message content element inside a
 *                                 listitem; used for body text + a stable rawId
 *   - span[email]              -> sender element, has `email` and `name` attributes
 */
function extractThread() {
  console.log("[EXTRACT] Starting thread extraction...");

  const threadContainer = document.querySelector("div.aeJ");
  if (!threadContainer) {
    console.log("[EXTRACT] No thread container (div.aeJ) found on this page. Are you viewing an open thread?");
    return [];
  }

  const messageEls = Array.from(threadContainer.querySelectorAll('[role="listitem"]'));
  console.log(`[EXTRACT] Found ${messageEls.length} message item(s) via [role="listitem"].`);

  if (messageEls.length === 0) {
    console.log("[EXTRACT] Zero messages found. The div.aeJ / [role=\"listitem\"] selectors may not match this thread's layout — Gmail may have changed its DOM structure.");
    return [];
  }

  const messages = messageEls.map((el, index) => {
    const ariaExpanded = el.getAttribute("aria-expanded");
    const isCollapsed = ariaExpanded === "false";

    const senderEl = el.querySelector("span[email]");
    let senderName = null;
    let senderEmail = null;
    if (senderEl) {
      senderEmail = senderEl.getAttribute("email");
      senderName = senderEl.getAttribute("name");
    }

    // .adn.ads is the actual message content element (confirmed via
    // data-message-id inspection). Fall back to the whole listitem's text
    // if that structure isn't present, so extraction degrades gracefully
    // rather than returning nothing.
    const bodyContainer = el.querySelector(".adn.ads");
    const bodyText = bodyContainer
      ? (bodyContainer.textContent ? bodyContainer.textContent.trim() : "")
      : (el.textContent ? el.textContent.trim() : "");

    const rawId = (bodyContainer && bodyContainer.getAttribute("data-message-id")) || el.id || null;

    return {
      senderName,
      senderEmail,
      bodyText,
      isCollapsed,
      rawId,
    };
  });

  console.log(`[EXTRACT] Finished extraction. ${messages.length} message(s) processed.`);
  return messages;
}

/**
 * redactEmails(messages)
 * Replaces every email address found in bodyText/senderEmail fields with a
 * consistent placeholder ([email-1], [email-2], ...). The same address
 * always maps to the same placeholder within a single call.
 */
function redactEmails(messages) {
  console.log("[REDACT] Starting email redaction...");

  const EMAIL_REGEX = /[\w.-]+@[\w.-]+\.\w+/g;
  const addressToPlaceholder = new Map();
  let nextPlaceholderNumber = 1;

  function getPlaceholderFor(address) {
    if (!addressToPlaceholder.has(address)) {
      const placeholder = `[email-${nextPlaceholderNumber}]`;
      addressToPlaceholder.set(address, placeholder);
      console.log(`[REDACT] New address found -> mapped "${address}" to "${placeholder}"`);
      nextPlaceholderNumber += 1;
    }
    return addressToPlaceholder.get(address);
  }

  function redactString(str) {
    if (!str) return str;
    return str.replace(EMAIL_REGEX, (match) => getPlaceholderFor(match));
  }

  const redacted = messages.map((msg) => ({
    ...msg,
    senderEmail: redactString(msg.senderEmail),
    bodyText: redactString(msg.bodyText),
  }));

  console.log(`[REDACT] Finished redaction. ${addressToPlaceholder.size} unique address(es) redacted.`);
  return redacted;
}

/**
 * readDraft()
 * Finds the currently open compose box and returns its text content, or
 * null if no compose box is present on the page.
 */
function readDraft() {
  console.log("[EXTRACT] Looking for open compose box...");

  const composeBox = document.querySelector('div[aria-label="Message Body"][contenteditable="true"]');
  if (!composeBox) {
    console.log("[EXTRACT] No compose box found — is a reply/compose window currently open?");
    return null;
  }

  const draftText = composeBox.textContent ? composeBox.textContent.trim() : "";
  console.log(`[EXTRACT] Compose box found. Draft text length: ${draftText.length} character(s).`);
  return draftText;
}

/**
 * expandCollapsedMessages()
 * Detects collapsed messages and logs them for manual expansion.
 *
 * Programmatic click-to-expand was tried and confirmed NOT to work: neither
 * a bare el.click() nor a full pointerdown/mousedown/pointerup/mouseup/click
 * sequence (with correct coordinates) triggered Gmail's expand handler, and
 * nothing changed visually on the page either. Every event dispatched from
 * page JavaScript has isTrusted: false, which cannot be faked from a content
 * script - if Gmail's handler checks event.isTrusted (a standard defense
 * against automated UI interaction), no synthetic event will ever satisfy
 * it. So this only detects and reports collapsed messages; the user must
 * click them manually before re-running extraction.
 *
 * Two distinct collapse patterns were found empirically:
 *   1. Individually collapsed messages: [role="listitem"][aria-expanded="false"]
 *   2. A run of older messages hidden behind a single non-listitem "N hidden
 *      messages" badge (a sibling of the listitems, no role attribute, short
 *      numeric text like "5") - these messages don't exist in the DOM at all
 *      until that badge is manually clicked.
 */
function expandCollapsedMessages() {
  console.log("[COLLAPSE] Checking for collapsed messages...");

  const threadContainer = document.querySelector("div.aeJ");
  if (!threadContainer) {
    console.log("[COLLAPSE] No thread container (div.aeJ) found on this page.");
    return [];
  }

  const listContainer = threadContainer.querySelector('[role="list"]');
  if (listContainer) {
    const batchEl = Array.from(listContainer.children).find((el) => {
      if (el.getAttribute("role") === "listitem") return false;
      const text = el.textContent.trim();
      return text.length > 0 && text.length <= 8 && /\d/.test(text);
    });
    if (batchEl) {
      console.log(
        `[COLLAPSE] Found a batched-messages indicator (badge text "${batchEl.textContent.trim()}") hiding older messages - click-to-expand logic not possible programmatically, please manually click it and re-run`
      );
    }
  }

  const collapsedEls = Array.from(threadContainer.querySelectorAll('[role="listitem"][aria-expanded="false"]'));

  const collapsedIds = collapsedEls.map(
    (el, index) => (el.querySelector(".adn.ads")?.getAttribute("data-message-id")) || el.id || `index-${index}`
  );

  console.log(
    collapsedIds.length === 0
      ? "[COLLAPSE] No collapsed messages found."
      : `[COLLAPSE] ${collapsedIds.length} collapsed message(s) found - click-to-expand isn't possible programmatically (see comment above), please manually expand and re-run.`
  );

  return collapsedIds;
}

/**
 * buildReviewConversation(messages, draftText)
 * Formats the redacted thread + draft into the single opening "user"
 * message the backend's /review endpoint expects (see
 * backend/routers/review.py: SYSTEM_PROMPT describes a thread-for-context
 * plus a draft reply). Returns a conversation array so later turns
 * (follow-up questions) can just be appended to it.
 */
function buildReviewConversation(messages, draftText) {
  const threadText = messages
    .map((msg) => {
      const sender = msg.senderName || msg.senderEmail || "Unknown sender";
      return `${sender} wrote:\n${msg.bodyText}`;
    })
    .join("\n\n---\n\n");

  const content = `THREAD:\n${threadText}\n\nDRAFT REPLY:\n${draftText || "(no draft written yet)"}`;

  return [{ role: "user", content }];
}

/**
 * requestReview(conversation)
 * POSTs the conversation to the backend's /review endpoint and returns the
 * assistant's reply text, or null if the request failed for any reason
 * (network error, non-2xx response, etc).
 */
async function requestReview(conversation) {
  console.log("[REVIEW] Sending review request to backend...");
  console.log(`[REVIEW] Backend URL: ${BACKEND_BASE_URL}/review`);

  try {
    const response = await fetch(`${BACKEND_BASE_URL}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.log(`[REVIEW] Backend responded with an error: ${response.status} ${response.statusText} - ${errorBody}`);
      return null;
    }

    const data = await response.json();
    console.log("[REVIEW] Received review from backend.");
    return data.reply;
  } catch (err) {
    console.log(`[REVIEW] Request failed: ${err.message}`);
    console.log("[REVIEW] If this is a CSP/mixed-content error rather than a plain network failure, the fetch may need to move to a background service worker instead of running directly in this page's context.");
    return null;
  }
}

/**
 * runExtraction()
 * Manual-testing orchestration entry point. Runs the full pipeline,
 * requests a review from the backend, and logs a readable summary.
 * Exposed on window so it can be called from the DevTools console.
 */
async function runExtraction() {
  console.log("========================================");
  console.log("[RUN] Starting Gmail AI Reply Reviewer extraction...");
  console.log("========================================");

  const collapsedIds = expandCollapsedMessages();
  console.log(`[RUN] Collapsed messages found: ${collapsedIds.length}`);

  const rawMessages = extractThread();
  const redactedMessages = redactEmails(rawMessages);
  const draftText = readDraft();

  const conversation = buildReviewConversation(redactedMessages, draftText);
  const reviewReply = await requestReview(conversation);
  if (reviewReply !== null) {
    conversation.push({ role: "assistant", content: reviewReply });
  }

  console.log("========================================");
  console.log("[RUN] SUMMARY");
  console.log("========================================");
  console.log(`[RUN] Total messages found: ${rawMessages.length}`);
  console.log(`[RUN] Collapsed messages: ${collapsedIds.length}`);
  console.log("[RUN] Redacted thread content:");
  console.log(redactedMessages);
  console.log("[RUN] Draft text:");
  console.log(draftText === null ? "(no compose box open)" : draftText);
  console.log("[RUN] AI review:");
  console.log(reviewReply === null ? "(review request failed - see [REVIEW] logs above)" : reviewReply);
  console.log("========================================");
  console.log("[RUN] Extraction complete.");
  console.log("========================================");

  return {
    totalMessages: rawMessages.length,
    collapsedCount: collapsedIds.length,
    messages: redactedMessages,
    draftText,
    reviewReply,
    conversation,
  };
}

// Exposed for manual testing from the DevTools console.
window.runGmailReviewExtraction = runExtraction;

/**
 * injectReviewUI()
 * Injects a floating "Review Draft" button and a results panel into the
 * page, both inside a shadow root so Gmail's page CSS can't bleed into our
 * UI (and our styles can't bleed onto Gmail's). Safe to call more than
 * once - only injects if not already present.
 */
function injectReviewUI() {
  if (document.getElementById("gmail-ai-reviewer-host")) return;

  const host = document.createElement("div");
  host.id = "gmail-ai-reviewer-host";
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: 'Google Sans', Roboto, Arial, sans-serif; }

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
      height: 520px;
      min-width: 300px;
      min-height: 320px;
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
      resize: both;
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
      line-height: 1.55;
      color: #1f2937;
    }

    .meta {
      font-size: 11.5px;
      color: #6b7280;
      margin-bottom: 10px;
      padding-bottom: 10px;
      border-bottom: 1px solid #e5e7eb;
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
    }

    .chat {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .bubble {
      max-width: 85%;
      padding: 8px 12px;
      border-radius: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .bubble.assistant {
      align-self: flex-start;
      background: #f3f4f6;
      color: #1f2937;
      border-bottom-left-radius: 4px;
    }
    .bubble.user {
      align-self: flex-end;
      background: #6366f1;
      color: white;
      border-bottom-right-radius: 4px;
    }

    .panel-footer {
      display: flex;
      align-items: flex-end;
      gap: 8px;
      padding: 10px 12px;
      border-top: 1px solid #e5e7eb;
      flex-shrink: 0;
    }

    .footer-input {
      flex: 1;
      resize: none;
      max-height: 80px;
      padding: 8px 10px;
      font-size: 13px;
      font-family: inherit;
      border: 1px solid #d1d5db;
      border-radius: 10px;
      outline: none;
    }
    .footer-input:focus { border-color: #6366f1; }
    .footer-input:disabled { background: #f3f4f6; color: #9ca3af; }

    .send-btn {
      flex-shrink: 0;
      background: #6366f1;
      color: white;
      border: none;
      border-radius: 10px;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .send-btn:hover:not(:disabled) { background: #4f46e5; }
    .send-btn:disabled { background: #c7c8fb; cursor: default; }
  `;
  shadow.appendChild(style);

  const fab = document.createElement("button");
  fab.className = "fab";
  fab.title = "Review draft with AI";
  fab.textContent = "✨";
  shadow.appendChild(fab);

  // Gmail enforces Trusted Types (require-trusted-types-for 'script'), which
  // blocks any raw string assignment to .innerHTML - even fully static
  // markup. Everything below is built with createElement/textContent
  // instead, which Trusted Types has no objection to.
  const panel = document.createElement("div");
  panel.className = "panel";

  const panelHeader = document.createElement("div");
  panelHeader.className = "panel-header";

  const panelTitle = document.createElement("span");
  panelTitle.className = "panel-title";
  panelTitle.textContent = "AI Reply Review";
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

  const panelFooter = document.createElement("div");
  panelFooter.className = "panel-footer";

  const footerInput = document.createElement("textarea");
  footerInput.className = "footer-input";
  footerInput.rows = 1;
  footerInput.placeholder = "Ask a follow-up...";
  footerInput.disabled = true;
  panelFooter.appendChild(footerInput);

  const sendBtn = document.createElement("button");
  sendBtn.className = "send-btn";
  sendBtn.textContent = "Send";
  sendBtn.disabled = true;
  panelFooter.appendChild(sendBtn);

  panel.appendChild(panelFooter);

  shadow.appendChild(panel);

  // State for the current review session. Reset each time the fab is
  // clicked to start a fresh review; conversation[0] is the auto-built
  // THREAD/DRAFT context message (not something the user typed), so it's
  // excluded when rendering chat bubbles but still sent to the backend on
  // every follow-up turn since the API is stateless.
  let conversation = [];
  let threadMeta = null;
  let errorMessage = null;
  let isBusy = false;

  function renderPanel() {
    panelBody.textContent = "";

    if (threadMeta) {
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent =
        `${threadMeta.totalMessages} message${threadMeta.totalMessages === 1 ? "" : "s"} in thread` +
        (threadMeta.collapsedCount > 0 ? ` · ${threadMeta.collapsedCount} collapsed (not included)` : "") +
        (threadMeta.draftText === null ? " · no draft open" : "");
      panelBody.appendChild(meta);
    }

    const chat = document.createElement("div");
    chat.className = "chat";
    conversation.slice(1).forEach((msg) => {
      const bubble = document.createElement("div");
      bubble.className = `bubble ${msg.role}`;
      bubble.textContent = msg.content;
      chat.appendChild(bubble);
    });
    panelBody.appendChild(chat);

    if (isBusy) {
      const loadingEl = document.createElement("div");
      loadingEl.className = "loading";
      const spinnerEl = document.createElement("div");
      spinnerEl.className = "spinner";
      loadingEl.appendChild(spinnerEl);
      loadingEl.appendChild(document.createTextNode(conversation.length === 0 ? "Reviewing your draft..." : "Thinking..."));
      panelBody.appendChild(loadingEl);
    }

    if (errorMessage) {
      const errorEl = document.createElement("div");
      errorEl.className = "error";
      errorEl.textContent = errorMessage;
      panelBody.appendChild(errorEl);
    }

    panelBody.scrollTop = panelBody.scrollHeight;

    // conversation[0] is the auto-built context message; length > 1 means at
    // least one assistant reply has actually been received.
    const canSend = conversation.length > 1 && !isBusy;
    footerInput.disabled = !canSend;
    sendBtn.disabled = !canSend;
  }

  async function sendFollowUp() {
    const text = footerInput.value.trim();
    if (!text || isBusy) return;

    footerInput.value = "";
    conversation.push({ role: "user", content: text });
    errorMessage = null;
    isBusy = true;
    renderPanel();

    const reply = await requestReview(conversation);
    isBusy = false;

    if (reply === null) {
      errorMessage = "Couldn't reach the review backend. Check the console for details.";
    } else {
      conversation.push({ role: "assistant", content: reply });
    }
    renderPanel();
  }

  closeBtn.addEventListener("click", () => {
    panel.classList.remove("open");
  });

  sendBtn.addEventListener("click", sendFollowUp);
  footerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendFollowUp();
    }
  });

  fab.addEventListener("click", async () => {
    panel.classList.add("open");
    conversation = [];
    threadMeta = null;
    errorMessage = null;
    isBusy = true;
    renderPanel();

    let result;
    try {
      result = await runExtraction();
    } catch (err) {
      isBusy = false;
      errorMessage = `Something went wrong: ${err.message}`;
      renderPanel();
      return;
    }

    isBusy = false;
    threadMeta = {
      totalMessages: result.totalMessages,
      collapsedCount: result.collapsedCount,
      draftText: result.draftText,
    };
    conversation = result.conversation;

    if (result.reviewReply === null) {
      errorMessage = "Couldn't reach the review backend. Check the console for details.";
    }

    renderPanel();
  });
}

injectReviewUI();
