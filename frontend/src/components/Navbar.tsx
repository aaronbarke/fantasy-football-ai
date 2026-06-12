"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, clearTokens, getSelectedLeague, getToken, setSelectedLeague } from "@/lib/api";
import type { LeagueConnection } from "@/lib/types";
import { ChevronDown, LogOut, Moon, Plus, Sun, Wrench } from "lucide-react";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/gameplan", label: "Game plan" },
  { href: "/chat", label: "Chat" },
  { href: "/roster", label: "Roster" },
  { href: "/matchup", label: "Matchup" },
  { href: "/waivers", label: "Waivers" },
];

const tools = [
  { href: "/trade", label: "Trade analyzer" },
  { href: "/schedule", label: "Schedule strength" },
  { href: "/compare", label: "Compare players" },
  { href: "/draft", label: "Draft assistant" },
  { href: "/betting", label: "Betting edge" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [leagueOpen, setLeagueOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSelectedId(getSelectedLeague());
    setDark(document.documentElement.classList.contains("dark"));
    const close = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setToolsOpen(false);
        setLeagueOpen(false);
      }
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  const { data: leagues } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api<LeagueConnection[]>("/api/leagues"),
    enabled: typeof window !== "undefined" && !!getToken(),
  });

  const active = leagues?.find((l) => l.id === selectedId) ?? leagues?.[0];

  function pickLeague(id: string) {
    setSelectedLeague(id);
    setSelectedId(id);
    setLeagueOpen(false);
    window.location.reload();
  }

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  const toolActive = tools.some((t) => t.href === pathname);

  return (
    <nav className="border-b border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
      <div ref={wrapRef} className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="text-lg font-bold text-green-700 dark:text-green-400">
            FF<span className="text-gray-900 dark:text-gray-100">AI</span>
          </Link>

          {/* League switcher */}
          {leagues && leagues.length > 0 && (
            <div className="relative">
              <button
                onClick={() => {
                  setLeagueOpen(!leagueOpen);
                  setToolsOpen(false);
                }}
                className="flex max-w-[180px] items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
              >
                <span className="truncate">{active?.league_name ?? "Select league"}</span>
                <span className="rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                  {active?.platform}
                </span>
                <ChevronDown className="h-3 w-3 shrink-0" />
              </button>
              {leagueOpen && (
                <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-900">
                  {leagues.map((l) => (
                    <button
                      key={l.id}
                      onClick={() => pickLeague(l.id)}
                      className={`block w-full px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-800 ${
                        l.id === active?.id ? "bg-green-50 dark:bg-green-950" : ""
                      }`}
                    >
                      <p className="truncate font-medium text-gray-900 dark:text-gray-100">
                        {l.league_name ?? l.league_id}
                      </p>
                      <p className="text-xs text-gray-500">
                        {l.platform} · {l.season} ·{" "}
                        {l.scoring_type?.replace("_", "-").toUpperCase()}
                      </p>
                    </button>
                  ))}
                  <Link
                    href="/connect"
                    className="flex items-center gap-1.5 border-t border-gray-100 px-3 py-2 text-sm font-medium text-green-700 hover:bg-gray-50 dark:border-gray-800 dark:text-green-400 dark:hover:bg-gray-800"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add league
                  </Link>
                </div>
              )}
            </div>
          )}

          <div className="hidden gap-1 md:flex">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                  pathname === l.href
                    ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
                    : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
              >
                {l.label}
              </Link>
            ))}

            {/* Tools dropdown */}
            <div className="relative">
              <button
                onClick={() => {
                  setToolsOpen(!toolsOpen);
                  setLeagueOpen(false);
                }}
                className={`flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium ${
                  toolActive
                    ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
                    : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
              >
                <Wrench className="h-3.5 w-3.5" /> Tools <ChevronDown className="h-3 w-3" />
              </button>
              {toolsOpen && (
                <div className="absolute left-0 top-full z-50 mt-1 w-48 rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-900">
                  {tools.map((t) => (
                    <Link
                      key={t.href}
                      href={t.href}
                      onClick={() => setToolsOpen(false)}
                      className={`block px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 ${
                        pathname === t.href
                          ? "font-semibold text-green-700 dark:text-green-400"
                          : "text-gray-700 dark:text-gray-200"
                      }`}
                    >
                      {t.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={toggleTheme}
            aria-label="Toggle dark mode"
            className="rounded-md p-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            onClick={() => {
              if (!window.confirm("Sign out of FFAI?")) return;
              clearTokens();
              router.push("/login");
            }}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
    </nav>
  );
}
