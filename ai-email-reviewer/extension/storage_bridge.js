// Storage bridge for Gmail AI Reply Reviewer.
//
// content.js runs in the page's MAIN world (see manifest.json), which has no
// access to chrome.* APIs at all - including chrome.storage. This script
// runs in the default isolated world, which does have that access, and
// relays chrome.storage.local reads to content.js over window.postMessage
// (both worlds share the same window/DOM, so postMessage crosses the
// boundary between them).

const REQUEST_TYPE = "gmail-ai-reviewer:get-backend-url-request";
const RESPONSE_TYPE = "gmail-ai-reviewer:get-backend-url-response";

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.type !== REQUEST_TYPE) return;

  const requestId = event.data.requestId;
  chrome.storage.local.get(["backendUrl"], (result) => {
    window.postMessage(
      { type: RESPONSE_TYPE, requestId, backendUrl: result.backendUrl || null },
      "*"
    );
  });
});
