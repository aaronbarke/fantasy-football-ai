"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Navbar from "@/components/Navbar";
import ChatMessageBubble from "@/components/ChatMessage";
import { api, apiStream } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { Send, Square, ArrowUpRight, MessageSquare } from "lucide-react";

const starters = [
  "Who should I start at FLEX this week?",
  "Break down my matchup this week",
  "What trades should I target to improve my RB depth?",
  "Who are the best waiver pickups right now?",
];

function ChatInner() {
  const params = useSearchParams();
  const { league } = useLeague();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sentPrefill = useRef(false);

  // History is scoped to the active league. A quick-ask deep link (?q=) starts
  // a clean thread instead of loading the running conversation, so the answer
  // isn't colored by an unrelated last chat.
  useEffect(() => {
    if (!league) return;
    setLoaded(false);
    if (params.get("q")) {
      setMessages([]);
      setLoaded(true);
      return;
    }
    api<ChatMessage[]>(`/api/chat/history?limit=50&connection_id=${league.id}`)
      .then(setMessages)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [league?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string, fresh = false) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setMessages((m) => [
      ...m,
      { role: "user", content: q },
      { role: "assistant", content: "" },
    ]);
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      await apiStream(
        "/api/chat/stream",
        { message: q, connection_id: league?.id ?? null, fresh },
        (chunk) => {
          setMessages((m) => {
            const next = [...m];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, content: last.content + chunk };
            return next;
          });
        },
        abortRef.current.signal,
      );
      // Strip the PICK: line the backend uses for accuracy tracking
      setMessages((m) => {
        const next = [...m];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          ...last,
          content: last.content.replace(/\n?PICK:\s*.+\s*$/, "").trimEnd(),
        };
        return next;
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = {
            role: "assistant",
            content: `Something went wrong: ${err instanceof Error ? err.message : "unknown error"}`,
          };
          return next;
        });
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  // Prefill from dashboard quick-ask buttons (?q=...)
  useEffect(() => {
    const q = params.get("q");
    if (q && loaded && league && !sentPrefill.current) {
      sentPrefill.current = true;
      send(q, true); // deep-linked quick-ask: fresh, standalone answer
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, loaded, league]);

  return (
    <div className="chat-page flex h-dvh flex-col">
      <Navbar />
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto flex w-full max-w-3xl flex-1 flex-col overflow-hidden px-4"
      >
        <div className="chat-heading">
          <div>
            <p className="eyebrow">Think it through</p>
            <h1>Your assistant</h1>
          </div>
          <span className="chat-context">
            {league?.league_name ?? "Your league"}
          </span>
        </div>
        <div className="chat-scroll flex-1 space-y-5 overflow-y-auto py-6">
          {messages.length === 0 && loaded && (
            <div className="chat-welcome">
              <span className="empty-state-icon">
                <MessageSquare className="h-6 w-6" />
              </span>
              <p className="eyebrow">Your league. A little perspective.</p>
              <h2>What’s your next move?</h2>
              <p>
                Talk through a close call, explore a trade, or get a second look
                at your lineup.
              </p>
              <div className="chat-prompts">
                {starters.map((s, i) => (
                  <button key={s} onClick={() => send(s)}>
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-green-700">
                      {
                        [
                          "Set your lineup",
                          "Scout the matchup",
                          "Explore a trade",
                          "Find an addition",
                        ][i]
                      }
                    </span>
                    <span className="mt-3 block text-sm leading-6">{s}</span>
                    <ArrowUpRight className="mt-4 h-4 w-4 text-gray-400" />
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessageBubble key={i} message={m} />
          ))}
          {busy && messages[messages.length - 1]?.content === "" && (
            <p className="text-sm text-gray-400">Checking the data…</p>
          )}
          <div ref={bottomRef} />
        </div>
        {messages.length > 0 && !busy && (
          <div className="flex flex-wrap items-center gap-2 pb-2">
            {starters.slice(0, 3).map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs text-gray-600 hover:border-green-400 hover:bg-green-50"
              >
                {s}
              </button>
            ))}
            <button
              onClick={async () => {
                if (
                  !league ||
                  !window.confirm("Clear this league's chat history?")
                )
                  return;
                await api(`/api/chat/history?connection_id=${league.id}`, {
                  method: "DELETE",
                });
                setMessages([]);
              }}
              className="ml-auto rounded-full px-3 py-1 text-xs text-gray-400 hover:text-red-500"
            >
              Clear chat
            </button>
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="chat-composer"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Your fantasy football question"
            placeholder="Ask about your lineup, a trade, or a player…"
            className="min-w-0 flex-1 rounded-lg border-0 bg-transparent px-3 py-2.5 text-sm"
          />
          {busy ? (
            <button
              type="button"
              onClick={stop}
              className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-red-700"
              aria-label="Stop generating"
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() || !league}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
              aria-label="Send"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </form>
        <p className="chat-note">
          Use the analysis as a starting point. Confirm player status before
          making a move.
        </p>
      </main>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense>
      <ChatInner />
    </Suspense>
  );
}
