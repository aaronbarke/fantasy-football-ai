"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { setTokens } from "@/lib/api";
import type { TokenResponse } from "@/lib/types";
import { ArrowRight, Sparkles } from "lucide-react";
import Brand from "@/components/Brand";
import PlaybookField from "@/components/PlaybookField";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

interface GoogleId {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (resp: { credential: string }) => void;
      }) => void;
      renderButton: (
        parent: HTMLElement,
        options: Record<string, unknown>,
      ) => void;
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
    [router],
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
    [],
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
    <main className="auth-page">
      <aside className="auth-story">
        <Brand href="/" light />
        <h2>Your next great call starts here.</h2>
        <PlaybookField />
        <p>YOUR ROSTER. YOUR RESEARCH. ONE WORKSPACE.</p>
      </aside>
      <div className="auth-form-area">
        <div className="auth-form">
          <div className="mb-10 sm:hidden">
            <Brand href="/" />
          </div>
          <p className="eyebrow">Welcome to your workspace</p>
          <h1>
            {mode === "login" ? "Back in the game." : "Make it your season."}
          </h1>
          <p className="auth-description">
            {mode === "login"
              ? "Sign in to pick up where you left off. Your league and your next decision are waiting."
              : "Create an account, connect your league, and put your next move in perspective."}
          </p>
          {GOOGLE_CLIENT_ID && (
            <>
              <div className="mt-7 flex justify-center">
                <div ref={googleBtnRef} />
              </div>
              <div className="auth-divider">or use your email</div>
            </>
          )}
          <form onSubmit={submit} className="mt-7 space-y-5">
            <div>
              <label htmlFor="email" className="field-label">
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="form-input"
              />
            </div>
            <div>
              <label htmlFor="password" className="field-label">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                minLength={mode === "register" ? 8 : undefined}
                placeholder={
                  mode === "login"
                    ? "Enter your password"
                    : "At least 8 characters"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="form-input"
              />
            </div>
            {error && (
              <p
                role="alert"
                className="text-sm text-red-600 dark:text-red-400"
              >
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="button-primary w-full"
            >
              {busy
                ? "Connecting…"
                : mode === "login"
                  ? "Sign in"
                  : "Create account"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </form>
          <p className="mt-6 text-center text-xs text-gray-500">
            {mode === "login" ? "New to FFAI? " : "Already have an account? "}
            <button
              disabled={busy}
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
              className="font-semibold text-green-700 hover:underline"
            >
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
          <div className="auth-divider">take a look around</div>
          <button
            onClick={() => post("/api/auth/demo")}
            disabled={busy}
            className="button-secondary w-full"
          >
            <Sparkles className="h-4 w-4 text-green-700" />
            Explore the demo
          </button>
          <p className="mt-3 text-center text-xs leading-5 text-gray-500">
            A sample league, ready to explore. No signup needed.
          </p>
          <Link
            href="/"
            className="mt-9 block text-center text-xs text-gray-500 hover:text-green-700"
          >
            ← Back to FFAI
          </Link>
        </div>
      </div>
    </main>
  );
}
