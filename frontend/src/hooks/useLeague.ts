"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, getSelectedLeague, getToken, setSelectedLeague } from "@/lib/api";
import type { LeagueConnection } from "@/lib/types";
import { useRouter } from "next/navigation";

/** Loads the user's leagues, keeps a selected league in localStorage, and
 * redirects to /login (no token) or /connect (no leagues). */
export function useLeague() {
  const router = useRouter();
  // Initialize synchronously from localStorage so navigating between tabs keeps
  // the chosen league instead of snapping back to the first one. (Reading it in
  // an effect lets the fallback below clobber it before the read lands.)
  const [selectedId, setSelectedId] = useState<string | null>(() => getSelectedLeague());

  useEffect(() => {
    if (!getToken()) router.push("/login");
  }, [router]);

  const { data: leagues, isLoading, isFetching } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api<LeagueConnection[]>("/api/leagues"),
    enabled: typeof window !== "undefined" && !!getToken(),
  });

  useEffect(() => {
    if (!leagues || isFetching) return;
    if (leagues.length === 0) {
      router.push("/connect");
      return;
    }
    // Honor a valid stored selection; only fall back to the first league when
    // there's genuinely no stored choice (or it points at a league that's gone).
    // Reading localStorage here — not `selectedId` — avoids clobbering the
    // selection during the first render after a tab switch.
    const stored = getSelectedLeague();
    if (stored && leagues.some((l) => l.id === stored)) {
      if (selectedId !== stored) setSelectedId(stored);
    } else {
      setSelectedLeague(leagues[0].id);
      setSelectedId(leagues[0].id);
    }
  }, [leagues, isFetching, selectedId, router]);

  const league =
    (selectedId ? leagues?.find((l) => l.id === selectedId) : undefined) ??
    leagues?.[0] ??
    null;

  return {
    league,
    leagues: leagues ?? [],
    isLoading,
    selectLeague: (id: string) => {
      setSelectedLeague(id);
      setSelectedId(id);
    },
  };
}
