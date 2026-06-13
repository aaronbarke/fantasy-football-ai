# Enabling "Continue with Google"

The button is already built. It stays hidden until you give the app a Google
**OAuth Web Client ID**. There's **no client secret** — we verify the ID token
Google hands the browser, so nothing sensitive is stored.

## 1. Create the Client ID (free, ~5 min)

1. Go to <https://console.cloud.google.com/> and create a project (or pick one).
2. **APIs & Services → OAuth consent screen**
   - User type: **External** → Create.
   - Fill app name + your email. Add yourself under **Test users**. Save.
   - (You can leave it in "Testing" — no Google verification needed for personal use.)
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**.
   - **Authorized JavaScript origins** — add each dev URL you use:
     - `http://localhost:3000`
     - `http://localhost:3001`
   - (No redirect URI needed — we use the Identity Services token flow.)
   - Create, then copy the **Client ID** (looks like `1234567890-abc.apps.googleusercontent.com`).

## 2. Wire it in

**Backend** — `backend/.env`:

```
GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
```

**Frontend** — `frontend/.env.local` (create it if missing):

```
NEXT_PUBLIC_GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
```

Use the **same** Client ID in both.

## 3. Restart

- Backend reloads on its own (uvicorn `--reload`).
- Restart the frontend (`npm run dev`) so it picks up the new env var.

The real Google button now renders on `/login`. Signing in finds-or-creates a
user by the Google email and issues the app's own JWTs — same session system as
email/password.

## How it works

- Frontend loads Google Identity Services and renders the button.
- On sign-in, Google returns an **ID token** to the browser.
- Frontend POSTs it to `POST /api/auth/google`.
- Backend validates it via Google's `tokeninfo` endpoint, checks the audience
  matches `GOOGLE_CLIENT_ID` and the email is verified, then issues our tokens.
