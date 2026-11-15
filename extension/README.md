# FFAI Connect for ESPN

A small browser extension that connects private ESPN leagues to Fantasy
Football AI without opening developer tools.

## Why an extension

ESPN keeps you signed in with two cookies, `espn_s2` and `SWID`, and the app
needs both to read a private league. `espn_s2` is HttpOnly: no web page and no
bookmarklet can read it, only the browser's cookies API, which is only open to
extensions. So the choice is this extension or copying the values by hand out
of the browser's developer tools.

## What it does

- On the Fantasy Football AI site, the Connect page shows **Find my ESPN
  leagues**. Clicking it asks the extension for your ESPN sign-in, lists the
  leagues on that ESPN account, and connects the one you pick.
- When ESPN signs you out and leagues stop updating, **Reconnect ESPN** on the
  Overview page replaces the stored cookies on every ESPN league in one click.

It reads exactly two cookies (`espn_s2`, `SWID`) from `espn.com`. It hands them
only to the Fantasy Football AI pages listed under `content_scripts.matches` in
`manifest.json`, only when the page asks, and only right after you click
something there. The popup shows whether you're signed in to ESPN; it never
sees the values.

## Install (unpacked)

1. Download `ffai-espn-connect.zip` from the Connect page and unzip it, or use
   this folder directly.
2. Open `chrome://extensions` and turn on **Developer mode**.
3. Choose **Load unpacked** and pick the folder.
4. Sign in to ESPN in the same browser, then reload the Fantasy Football AI
   tab.

Works in Chromium browsers on a computer: Chrome, Edge, Brave, Arc. Firefox,
Safari and phones aren't covered; the Connect page keeps a manual form for
those (paste the league's web address, and for a private league the two
cookies).

## Running the app on another address

The extension only talks to the sites in `manifest.json`. If you deploy the app
somewhere other than `https://fantasy-football-ai-theta.vercel.app`:

1. Add the new origin to `content_scripts.matches` in `manifest.json`.
2. Update `APP_CONNECT_URL` in `popup.js`.
3. Run `./package.sh` to rebuild `frontend/public/ffai-espn-connect.zip`, and
   reload the extension.

`http://localhost` and `http://127.0.0.1` (any port) are already included for
local development.

## Publishing to the Chrome Web Store

Loading unpacked is fine for you; for other people, a store listing is the
one-click install.

1. Register as a Chrome Web Store developer (one-time fee) and upload
   `frontend/public/ffai-espn-connect.zip`.
2. In the listing, justify the permissions: `cookies` and
   `https://*.espn.com/*` are used to read the two ESPN session cookies named
   above so the user can connect their own league.
3. Once it's live, set `NEXT_PUBLIC_ESPN_EXTENSION_URL` to the listing's
   address in the frontend's environment. The Connect page then links there
   instead of offering the zip.

## Files

| File | Role |
| --- | --- |
| `manifest.json` | Permissions and which sites the extension runs on |
| `background.js` | Reads the two ESPN cookies when asked by this extension's own scripts |
| `content.js` | Bridge between the Fantasy Football AI page and the worker |
| `popup.html`, `popup.js` | Toolbar popup: ESPN sign-in status and a link to the app |
| `package.sh` | Builds the downloadable zip |

The page side of the conversation is in `frontend/src/lib/espn.ts`.
