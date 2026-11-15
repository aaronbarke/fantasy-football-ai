// Popup: says whether this browser is signed in to ESPN and links to the app.
// It never sees the cookie values — the worker only reports signed in or not.

const APP_CONNECT_URL = "https://fantasy-football-ai-theta.vercel.app/connect?platform=espn";
const ESPN_SIGN_IN_URL = "https://www.espn.com/fantasy/football/";

const dot = document.getElementById("dot");
const statusText = document.getElementById("status");
const hint = document.getElementById("hint");
const openEspn = document.getElementById("open-espn");

document.getElementById("open-app").addEventListener("click", () => {
  chrome.tabs.create({ url: APP_CONNECT_URL });
});
openEspn.addEventListener("click", () => {
  chrome.tabs.create({ url: ESPN_SIGN_IN_URL });
});

chrome.runtime.sendMessage({ type: "espn-status" }).then(
  (result) => {
    const signedIn = Boolean(result && result.signedIn);
    dot.className = `dot ${signedIn ? "on" : "off"}`;
    statusText.textContent = signedIn ? "Signed in to ESPN" : "Not signed in to ESPN";
    hint.textContent = signedIn
      ? "Open Fantasy Football AI and choose “Find my ESPN leagues”."
      : "Sign in to ESPN in this browser first, then connect from Fantasy Football AI.";
    openEspn.hidden = signedIn;
  },
  () => {
    dot.className = "dot off";
    statusText.textContent = "Couldn't check ESPN";
    hint.textContent = "Reload the extension and try again.";
  },
);
