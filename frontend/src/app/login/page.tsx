"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { setTokens } from "@/lib/api";
import type { TokenResponse } from "@/lib/types";
import { Sparkles, Trophy } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

interface GoogleId {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (resp: { credential: string }) => void;
      }) => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}
declare global {
  interface Window {
    google?: GoogleId;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  const finish = useCallback(
    (data: TokenResponse) => {
      setTokens(data.access_token, data.refresh_token);
      router.push("/dashboard");
    },
    [router]
  );

  async function post(path: string, body?: unknown) {
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!resp.ok) {
        const b = await resp.json().catch(() => ({}));
        throw new Error(b.detail || "Something went wrong");
      }
      finish(await resp.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  const onGoogleCredential = useCallback(
    (credential: string) => post(`/api/auth/google`, { credential }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // Load Google Identity Services and render its button when configured.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const init = () => {
      if (!window.google || !googleBtnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp) => onGoogleCredential(resp.credential),
      });
      window.google.accounts.id.renderButton(googleBtnRef.current, {
        theme: "outline",
        size: "large",
        width: 320,
        text: "continue_with",
        shape: "pill",
      });
    };
    if (window.google) {
      init();
      return;
    }
    const existing = document.getElementById("gis-script");
    if (existing) {
      existing.addEventListener("load", init);
      return;
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.id = "gis-script";
    s.onload = init;
    document.body.appendChild(s);
  }, [onGoogleCredential]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    post(`/api/auth/${mode}`, { email, password });
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200/70 bg-white p-8 dark:border-gray-800/70">
        {/* Brand */}
        <div className="flex items-center justify-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-green-600 text-white">
            <Trophy className="h-5 w-5" />
          </span>
          <span className="text-lg font-extrabold tracking-tight text-gray-900 dark:text-gray-100">
            FF<span className="text-green-600 dark:text-green-400">AI</span>
          </span>
        </div>

        <h1 className="mt-6 text-center text-2xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
          {mode === "login" ? "Welcome back" : "Create your account"}
        </h1>
        <p className="mt-1 text-center text-sm text-gray-500">
          {mode === "login"
            ? "Sign in to your fantasy assistant."
            : "Your AI co-manager for the season."}
        </p>

        {/* Google sign-in */}
        <div className="mt-6 flex justify-center">
          {GOOGLE_CLIENT_ID ? (
            <div ref={googleBtnRef} />
          ) : (
            <button
              type="button"
              onClick={() =>
                setError(
                  "Google sign-in isn't set up yet — add a Google Client ID (see SETUP_GOOGLE_OAUTH.md)."
                )
              }
              className="flex w-full items-center justify-center gap-2 rounded-full border border-gray-300 bg-white py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              <GoogleGlyph /> Continue with Google
            </button>
          )}
        </div>

        {/* Divider */}
        <div className="my-5 flex items-center gap-3">
          <span className="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
          <span className="text-xs font-medium uppercase tracking-wider text-gray-400">
            or
          </span>
          <span className="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
        </div>

        {/* Email / password */}
        <form onSubmit={submit} className="space-y-3">
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none dark:border-gray-700"
          />
          <input
            type="password"
            required
            minLength={8}
            placeholder="Password (8+ characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none dark:border-gray-700"
          />
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-green-600 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
          >
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          className="mt-4 w-full text-center text-sm text-green-700 hover:underline dark:text-green-400"
        >
          {mode === "login"
            ? "New here? Create an account"
            : "Already have an account? Sign in"}
        </button>

        {/* Demo escape hatch */}
        <div className="mt-6 border-t border-gray-100 pt-5 dark:border-gray-800">
          <button
            onClick={() => post(`/api/auth/demo`)}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-green-200 bg-green-50 py-2.5 text-sm font-semibold text-green-700 hover:bg-green-100 disabled:opacity-50 dark:border-green-800/50 dark:bg-green-950/40 dark:text-green-300 dark:hover:bg-green-900/40"
          >
            <Sparkles className="h-4 w-4" />
            Just exploring? Try the demo
          </button>
          <p className="mt-2 text-center text-xs text-gray-400">
            Jump in instantly — no account needed.
          </p>
        </div>
      </div>
    </main>
  );
}

/* Google's multicolor "G", used only for the not-configured placeholder. */
function GoogleGlyph() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
