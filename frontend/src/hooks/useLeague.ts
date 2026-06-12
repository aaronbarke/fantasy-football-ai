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
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    setSelectedId(getSelectedLeague());
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
    if (!selectedId || !leagues.some((l) => l.id === selectedId)) {
      setSelectedLeague(leagues[0].id);
      setSelectedId(leagues[0].id);
    }
  }, [leagues, isFetching, selectedId, router]);

  const league = leagues?.find((l) => l.id === selectedId) ?? leagues?.[0] ?? null;

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
