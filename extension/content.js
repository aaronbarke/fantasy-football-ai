// FFAI Connect for ESPN — content script.
//
// Runs only on the Fantasy Football AI site (see "matches" in manifest.json)
// and bridges it to the background worker. The page asks with
// window.postMessage; this script answers the same way. Nothing is sent
// anywhere unless the page asks, and the cookies are only handed over right
// after you click something on the page (a user gesture), so a script running
// in the page can't quietly collect them in the background.

(() => {
  const APP = "ffai-app";
  const EXTENSION = "ffai-espn-extension";
  const origin = window.location.origin;

  function post(message) {
    window.postMessage({ source: EXTENSION, ...message }, origin);
  }

  function announce() {
    let version = null;
    try {
      version = chrome.runtime.getManifest().version;
    } catch {
      return; // the extension was reloaded or removed: stay quiet
    }
    post({ type: "ready", version });
  }

  async function espnCookies() {
    const activation = navigator.userActivation;
    if (activation && !activation.isActive) {
      return { ok: false, reason: "no_gesture" };
    }
    try {
      const result = await chrome.runtime.sendMessage({ type: "get-espn-cookies" });
      return result || { ok: false, reason: "error" };
    } catch {
      // "Extension context invalidated": it was updated while this tab was open.
      return { ok: false, reason: "stale" };
    }
  }

  window.addEventListener("message", async (event) => {
    if (event.source !== window || event.origin !== origin) return;
    const data = event.data;
    if (!data || data.source !== APP) return;

    if (data.type === "ping") {
      announce();
    } else if (data.type === "get-espn-cookies") {
      const result = await espnCookies();
      post({ type: "espn-cookies", requestId: data.requestId, ...result });
    }
  });

  announce();
})();
