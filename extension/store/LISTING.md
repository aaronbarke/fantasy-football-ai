# Chrome Web Store submission

Everything the Developer Dashboard asks for, ready to paste. Dashboard:
https://chrome.google.com/webstore/devconsole

## Before you start

1. Register a developer account at the dashboard above (one-time $5 fee) and
   turn on 2-Step Verification for that Google account. Google requires it
   before you can publish.
2. Deploy the site so `/privacy` is live. The form asks for that address.
3. Rebuild the upload if the extension changed: `sh extension/package.sh`.

## Package

Upload `frontend/public/ffai-espn-connect.zip` ("New item" in the dashboard).

## Store listing tab

**Name** (read from the manifest): FFAI Connect for ESPN

**Summary** (read from the manifest):
Connect your private ESPN fantasy leagues to Fantasy Football AI in one click. No developer tools, no copying cookies.

**Description:**

```
FFAI Connect for ESPN links your private ESPN fantasy football league to Fantasy Football AI in one click.

Private ESPN leagues can only be read by someone signed in to ESPN. Until now that meant opening your browser's developer tools and copying two cookies by hand. This extension does that step for you.

HOW IT WORKS
1. Sign in to ESPN in this browser, as you normally do.
2. Open Fantasy Football AI and go to Connect > ESPN.
3. Click "Find my ESPN leagues" and pick your league.

When ESPN signs you out and a league stops updating, click "Reconnect ESPN" in the app. One click refreshes every ESPN league on your account.

WHAT IT ACCESSES
- Two cookies from espn.com: espn_s2 and SWID. Together they are your ESPN sign-in.
- Nothing else. No browsing history, no other cookies, no other websites.

WHEN
- Only when you click "Find my ESPN leagues" or "Reconnect ESPN" on the Fantasy Football AI site. Nothing runs in the background.

WHERE IT GOES
- Only to Fantasy Football AI, over HTTPS, where it is stored encrypted and used only to read your league's teams, rosters, matchups and settings from ESPN. The app never changes your lineup or anything else on ESPN.

You need a free Fantasy Football AI account: https://fantasy-football-ai-theta.vercel.app

Privacy policy: https://fantasy-football-ai-theta.vercel.app/privacy
Source code: https://github.com/aaronbarke/fantasy-football-ai/tree/main/extension

This extension is an independent project. It is not affiliated with, endorsed by, or sponsored by ESPN.
```

**Category:** Tools (under Productivity). If the reviewer disagrees, Entertainment is the other fit.

**Language:** English

**Store icon (128x128):** `extension/icons/icon-128.png`

**Screenshots (1280x800):**
- `extension/store/screenshot-1-find-leagues.png`
- `extension/store/screenshot-2-pick-league.png`

**Small promo tile (440x280, optional):** `extension/store/promo-small-440x280.png`

**Homepage URL:** https://fantasy-football-ai-theta.vercel.app

**Support URL:** https://github.com/aaronbarke/fantasy-football-ai/issues

## Privacy practices tab

**Single purpose:**

```
Let a user connect their own private ESPN fantasy football league to Fantasy Football AI by passing their ESPN sign-in cookies to that site when they click a button on it.
```

**Justification for the `cookies` permission:**

```
The extension reads exactly two cookies, espn_s2 and SWID, from espn.com. ESPN requires both to read a private fantasy league. espn_s2 is HttpOnly, so a web page cannot read it; the cookies API is the only way to let a user connect a private league without copying values out of developer tools. No other cookies are read, and nothing is written or removed.
```

**Justification for host permissions (`https://*.espn.com/*`):**

```
The cookies API only returns cookies for hosts the extension has permission for. The two ESPN sign-in cookies are set on espn.com, so this permission is required to read them. The extension does not inject scripts into, read content from, or modify any espn.com page.
```

**Justification for the content script on `https://fantasy-football-ai-theta.vercel.app/*`:**

```
The content script runs only on the Fantasy Football AI site. It passes the two ESPN cookies to that page when the page asks, and only immediately after a user click (it checks navigator.userActivation). It does not run on any other site.
```

**Are you using remote code?** No. All code is in the package.

**Data usage — what the extension collects:** tick only
- Authentication information

Leave the rest unticked (no personally identifiable information, health,
financial, personal communications, location, web history, user activity or
website content).

**Certifications:** tick all three.
- I do not sell or transfer user data to third parties, outside of the approved use cases.
- I do not use or transfer user data for purposes that are unrelated to my item's single purpose.
- I do not use or transfer user data to determine creditworthiness or for lending purposes.

**Privacy policy URL:** https://fantasy-football-ai-theta.vercel.app/privacy

## Distribution tab

- Payments: Free
- Visibility: Public
- Regions: All regions

## Test instructions tab (notes for the reviewer)

```
No test account is needed; sign-up is free and instant.

1. Go to https://fantasy-football-ai-theta.vercel.app/login and create an account with any email and password.
2. In the same browser, sign in to an ESPN account at https://www.espn.com/fantasy/football/.
3. Go to https://fantasy-football-ai-theta.vercel.app/connect?platform=espn.
4. Click "Find my ESPN leagues". The extension passes the ESPN sign-in to the page, which lists the fantasy football leagues on that ESPN account. An ESPN account with no fantasy football league shows an empty-list message.

The extension does nothing on any other site and nothing without that click. The toolbar popup only shows whether the browser is signed in to ESPN.
```

## After it is approved

1. Copy the listing's address from the dashboard
   (`https://chromewebstore.google.com/detail/...`).
2. In Vercel, set `NEXT_PUBLIC_ESPN_EXTENSION_URL` to that address and
   redeploy. The Connect page then shows "Add the extension" instead of the
   download and Developer mode steps.

## Updating later

Raise `version` in `extension/manifest.json`, run `sh extension/package.sh`,
and upload the new zip as an update. Each update is reviewed again.
