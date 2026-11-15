// FFAI Connect for ESPN — background service worker.
//
// ESPN keeps you signed in with two cookies, espn_s2 and SWID. espn_s2 is
// HttpOnly, so no web page (and no bookmarklet) can read it; only the browser's
// cookies API can, which is why this needs to be an extension. The worker reads
// exactly those two cookies from espn.com, and only when one of this
// extension's own scripts asks: the content script that runs on the Fantasy
// Football AI site, or the popup.

const ESPN_URL = "https://www.espn.com/";

async function readEspnCookies() {
  const [s2, swid] = await Promise.all([
    chrome.cookies.get({ url: ESPN_URL, name: "espn_s2" }),
    chrome.cookies.get({ url: ESPN_URL, name: "SWID" }),
  ]);
  // Signed-out visitors still get an anonymous SWID; only espn_s2 proves a
  // session, and a league sync needs both.
  if (!s2 || !s2.value || !swid || !swid.value) {
    return { ok: false, reason: "signed_out" };
  }
  return { ok: true, espn_s2: s2.value, swid: swid.value };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !message) return undefined;

  if (message.type === "get-espn-cookies") {
    readEspnCookies().then(sendResponse, () =>
      sendResponse({ ok: false, reason: "error" }),
    );
    return true; // answered asynchronously
  }

  if (message.type === "espn-status") {
    // The popup only needs to know whether you're signed in, never the values.
    readEspnCookies().then(
      (result) => sendResponse({ signedIn: result.ok }),
      () => sendResponse({ signedIn: false }),
    );
    return true;
  }

  return undefined;
});
