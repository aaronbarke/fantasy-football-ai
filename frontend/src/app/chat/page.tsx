"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Navbar from "@/components/Navbar";
import ChatMessageBubble from "@/components/ChatMessage";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { Send } from "lucide-react";

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
  const sentPrefill = useRef(false);

  useEffect(() => {
    api<ChatMessage[]>("/api/chat/history?limit=50")
      .then(setMessages)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const resp = await api<{ response: string }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: q, connection_id: league?.id ?? null }),
      });
      setMessages((m) => [...m, { role: "assistant", content: resp.response }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `Something went wrong: ${err instanceof Error ? err.message : "unknown error"}`,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  // Prefill from dashboard quick-ask buttons (?q=...)
  useEffect(() => {
    const q = params.get("q");
    if (q && loaded && league && !sentPrefill.current) {
      sentPrefill.current = true;
      send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, loaded, league]);

  return (
    <div className="flex h-screen flex-col">
      <Navbar />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col overflow-hidden px-4">
        <div className="flex-1 space-y-4 overflow-y-auto py-6">
          {messages.length === 0 && loaded && (
            <div className="mt-16 text-center">
              <h2 className="text-xl font-bold">Ask anything about your league</h2>
              <p className="mt-1 text-sm text-gray-500">
                The AI sees your roster, matchup, waivers, injuries, Vegas lines,
                and weather.
              </p>
              <div className="mx-auto mt-6 flex max-w-md flex-col gap-2">
                {starters.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm hover:border-green-400 hover:bg-green-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessageBubble key={i} message={m} />
          ))}
          {busy && (
            <p className="text-sm text-gray-400">Checking the data…</p>
          )}
          <div ref={bottomRef} />
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex gap-2 border-t border-gray-200 py-4"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Should I start Chase or Lamb this week?"
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-green-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
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
