"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  clearTokens,
  getSelectedLeague,
  getToken,
  setSelectedLeague,
} from "@/lib/api";
import type { LeagueConnection } from "@/lib/types";
import {
  ArrowLeftRight,
  ArrowUpRight,
  CalendarDays,
  BarChart3,
  ChevronDown,
  ClipboardList,
  Columns2,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Plus,
  Radio,
  Sun,
  Swords,
  Trophy,
  Users,
  X,
} from "lucide-react";
import Brand from "./Brand";

const groups = [
  {
    label: "Your team",
    links: [
      { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
      { href: "/gameplan", label: "Game plan", icon: ClipboardList },
      { href: "/roster", label: "Roster", icon: Users },
      { href: "/matchup", label: "Matchup", icon: Swords },
      { href: "/waivers", label: "Waiver wire", icon: Plus },
    ],
  },
  {
    label: "Make your move",
    links: [
      { href: "/chat", label: "Ask your assistant", icon: MessageSquare },
      { href: "/trade", label: "Trade analyzer", icon: ArrowLeftRight },
      { href: "/compare", label: "Compare players", icon: Columns2 },
      { href: "/schedule", label: "Schedule strength", icon: CalendarDays },
    ],
  },
  {
    label: "Draft & research",
    links: [
      { href: "/draft", label: "Draft room", icon: Radio },
      { href: "/mock", label: "Mock draft", icon: Trophy },
      { href: "/betting", label: "Sportsbook lines", icon: BarChart3 },
    ],
  },
];

export default function Navbar() {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [leagueOpen, setLeagueOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectorRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setSelectedId(getSelectedLeague());
    setDark(document.documentElement.classList.contains("dark"));
    const close = (event: MouseEvent) => {
      if (!selectorRef.current?.contains(event.target as Node))
        setLeagueOpen(false);
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
    setLeagueOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current?.querySelector<HTMLElement>("a,button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
      if (event.key === "Tab") {
        const items = drawerRef.current?.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled])",
        );
        if (!items?.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      menuButtonRef.current?.focus();
    };
  }, [mobileOpen]);

  const { data: leagues } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api<LeagueConnection[]>("/api/leagues"),
    enabled: typeof window !== "undefined" && !!getToken(),
  });
  const active = leagues?.find((l) => l.id === selectedId) ?? leagues?.[0];
  const current = groups
    .flatMap((g) => g.links)
    .find((l) => l.href === pathname);

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  return (
    <header className="app-navigation">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      {mobileOpen && (
        <div
          className="nav-backdrop"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside
        ref={drawerRef}
        className={`app-sidebar ${mobileOpen ? "is-open" : ""}`}
        id="app-sidebar"
        aria-label="Workspace navigation"
        role={mobileOpen ? "dialog" : undefined}
        aria-modal={mobileOpen || undefined}
      >
        <div className="flex items-center justify-between">
          <Brand />
          <button
            onClick={() => setMobileOpen(false)}
            className="icon-button lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="sidebar-links" aria-label="Main navigation">
          {groups.map((group) => (
            <div key={group.label} className="nav-group">
              <p>{group.label}</p>
              {group.links.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`sidebar-link ${pathname === link.href ? "is-active" : ""}`}
                  aria-current={pathname === link.href ? "page" : undefined}
                >
                  <link.icon
                    className="h-[18px] w-[18px]"
                    strokeWidth={1.7}
                    aria-hidden="true"
                  />
                  <span>{link.label}</span>
                  {pathname === link.href && <span className="active-dot" />}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Link href="/connect" className="sidebar-add">
            <Plus className="h-4 w-4" />
            Connect a league
            <ArrowUpRight className="ml-auto h-4 w-4" />
          </Link>
          <div className="flex items-center justify-between pt-3">
            <span className="text-[11px] text-gray-500">
              Built for your next move.
            </span>
            <button
              className="icon-button"
              aria-label="Sign out"
              title="Sign out"
              onClick={() => {
                clearTokens();
                queryClient.clear();
                window.location.href = "/login";
              }}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-bar">
        <div className="flex min-w-0 items-center gap-3">
          <button
            ref={menuButtonRef}
            className="icon-button lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-controls="app-sidebar"
            aria-expanded={mobileOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="hidden text-xs text-gray-400 sm:inline">
            Workspace
          </span>
          <span className="hidden text-gray-300 sm:inline">/</span>
          <span className="truncate text-sm font-medium">
            {current?.label ?? "Your league"}
          </span>
        </div>
        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          <div
            ref={selectorRef}
            className="league-selector"
            onKeyDown={(e) => {
              if (e.key === "Escape") setLeagueOpen(false);
            }}
          >
            {active ? (
              <>
                <button
                  className="league-trigger"
                  aria-expanded={leagueOpen}
                  aria-controls="league-options"
                  onClick={() => setLeagueOpen(!leagueOpen)}
                >
                  <span className="league-avatar">
                    {active.league_name?.slice(0, 1) ?? "L"}
                  </span>
                  <span className="truncate">
                    {active.league_name ?? "Your league"}
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                </button>
                {leagueOpen && (
                  <div id="league-options" className="league-options">
                    <p className="eyebrow px-3 py-2">Switch league</p>
                    {leagues?.map((l) => (
                      <button
                        key={l.id}
                        className="league-option"
                        aria-pressed={l.id === active.id}
                        onClick={() => {
                          setSelectedLeague(l.id);
                          window.location.reload();
                        }}
                      >
                        <span className="block truncate font-semibold">
                          {l.league_name ?? l.league_id}
                        </span>
                        <span className="mt-1 block text-xs text-gray-500">
                          {l.platform.toUpperCase()} · {l.season} ·{" "}
                          {l.scoring_type?.replace("_", "-").toUpperCase()}
                        </span>
                      </button>
                    ))}
                    <Link
                      href="/connect"
                      className="league-option flex items-center gap-2 text-green-700"
                    >
                      <Plus className="h-4 w-4" />
                      Connect another league
                    </Link>
                  </div>
                )}
              </>
            ) : (
              <Link
                href="/connect"
                className="text-xs font-semibold text-green-700"
              >
                Connect league
              </Link>
            )}
          </div>
          <button
            className="icon-button"
            onClick={toggleTheme}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
            title={dark ? "Light mode" : "Dark mode"}
          >
            {dark ? (
              <Sun className="h-[18px] w-[18px]" />
            ) : (
              <Moon className="h-[18px] w-[18px]" />
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
