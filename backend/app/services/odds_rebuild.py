"""Rebuild a matchup's win-probability curve after the fact from play-by-play.

Snapshots only exist for moments the app was watching. This rebuilds the whole
scoring period from what's knowable afterwards:

- each starter's points over time: every play he was part of (catch, run,
  touchdown, interception, fumble, kick) lands at its real wall-clock minute,
  and whatever those approximate points don't account for (league-specific
  scoring, bonuses, defense) is spread evenly over his game, so the curve ends
  exactly at his real total;
- how much of each game was left at that minute (the game clock);
- each starter's projection as the app saw it then (from recorded snapshots,
  so an injury designation shows up as a named drop when it happened), or his
  current projection when nothing was recorded.

Win probability at every moment then uses the same model as the live number
on the page, so the curve ends where the scoreboard's odds are.
"""

import bisect
import re
from datetime import datetime, timedelta

from app.services.nfl_plays_service import remaining_share
from app.services.odds_timeline import SWING_THRESHOLD
from app.services.projection_service import win_probability

# Same live model as the matchup preview: without play data, a game is
# assumed to run this long, its remaining share falling linearly.
GAME_MINUTES = 190.0
SAMPLE_EVERY = timedelta(minutes=5)
# Plays this close together count as one moment (a TD and the next kickoff,
# or two games scoring in the same minute).
CLUSTER_GAP = timedelta(seconds=90)
# A projection move smaller than this between snapshots is noise, not news.
NEWS_MIN_PROJ = 0.5
GAME_WINDOW = timedelta(hours=4)
MAX_DRIVERS = 3

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_REC_POINTS = {"ppr": 1.0, "half_ppr": 0.5, "standard": 0.0}


# ── Matching players to play text ─────────────────────────────────────────


def name_pattern(full_name: str) -> re.Pattern | None:
    """ESPN play text names players as initial + last name ("J.Love",
    "A.St. Brown", "Ja.Williams"). Suffixes are dropped."""
    parts = (full_name or "").replace("’", "'").split()
    while len(parts) > 2 and parts[-1].lower().strip(".") in _SUFFIXES:
        parts.pop()
    if len(parts) < 2:
        return None
    first, last = parts[0], " ".join(parts[1:])
    return re.compile(
        rf"(?<![A-Za-z.']){re.escape(first[0])}[A-Za-z']*\.\s?{re.escape(last)}(?![A-Za-z])"
    )


def _clean(text: str) -> str:
    """Drop formation tags and eligibility notes so the ball carrier or
    passer is the first name in the text."""
    t = re.sub(r"^.*?reported in as eligible\.\s*", "", text, flags=re.S)
    t = re.sub(r"^\s*(\([^)]*\)\s*)+", "", t)
    t = re.sub(r"^\s*Direct snap to \S+?\.\s+(?=[A-Z])", "", t)
    # Penalty write-ups and two-point tries name other players; the try's
    # points (if any) fall to the even spread.
    return re.split(r"PENALTY|Penalty on|TWO-POINT CONVERSION", t)[0].strip()


def _yards(play: dict, clean: str) -> int:
    if isinstance(play.get("yards"), (int, float)):
        return int(play["yards"])
    m = re.search(r"for (-?\d+) yards?", clean)
    return int(m.group(1)) if m else 0


def play_events(play: dict, players: list[dict], scoring: str = "ppr") -> list[dict]:
    """Approximate fantasy points each of ``players`` (with ``pattern``) got on
    one play, with a short description. Penalized-away plays score nothing."""
    ptype = play.get("type") or ""
    text = play.get("text") or ""
    if ptype == "Penalty" or "NO PLAY" in text.upper():
        return []
    clean = _clean(text)
    yards = _yards(play, clean)
    rec = _REC_POINTS.get(scoring or "ppr", 1.0)
    is_td = "TOUCHDOWN" in text.upper() and "Interception" not in ptype
    out = []
    for p in players:
        pat = p.get("pattern")
        if pat is None:
            continue
        hits = list(pat.finditer(clean))
        if not hits:
            xp = pat.search(text)
            if xp and re.match(r"\s*extra point is GOOD", text[xp.end():]):
                out.append(_ev(p, 1.0, "PAT", "kick"))
            continue
        first = hits[0].start() == 0
        after_first = clean[hits[0].end():].lstrip()
        passer = first and after_first.startswith("pass")
        receiver = any(clean[: h.start()].endswith("to ") for h in hits)
        if ptype in ("Pass Reception", "Passing Touchdown"):
            if passer:
                pts = yards * 0.04 + (4.0 if is_td else 0.0)
                out.append(_ev(p, pts, f"{yards}-yd TD pass" if is_td else f"{yards}-yd pass", "td" if is_td else "play"))
            elif receiver:
                pts = yards * 0.1 + rec + (6.0 if is_td else 0.0)
                out.append(_ev(p, pts, f"{yards}-yd TD catch" if is_td else f"{yards}-yd catch", "td" if is_td else "play"))
        elif ptype in ("Rush", "Rushing Touchdown") and first:
            pts = yards * 0.1 + (6.0 if is_td else 0.0)
            out.append(_ev(p, pts, f"{yards}-yd TD run" if is_td else f"{yards}-yd run", "td" if is_td else "play"))
        elif "Interception" in ptype and passer:
            out.append(_ev(p, -2.0, "INT", "turnover"))
        elif ptype in ("Fumble Recovery (Opponent)", "Sack Opp Fumble Recovery"):
            carrier = receiver or (first and not passer) or (first and "sacked" in after_first[:12])
            if carrier:
                out.append(_ev(p, -2.0, "fumble lost", "turnover"))
        elif ptype == "Field Goal Good" and first:
            m = re.search(r"(\d+) yard field goal", clean)
            dist = int(m.group(1)) if m else 30
            pts = 5.0 if dist >= 50 else 4.0 if dist >= 40 else 3.0
            out.append(_ev(p, pts, f"{dist}-yd FG", "kick"))
        # The extra point rides on the touchdown play's text.
        xp = pat.search(text)
        if xp and re.match(r"\s*extra point is GOOD", text[xp.end():]):
            out.append(_ev(p, 1.0, "PAT", "kick"))
    return out


def _ev(p: dict, pts: float, label: str, kind: str) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "position": p.get("position"),
        "side": p["side"],
        "pts": round(pts, 2),
        "label": label,
        "kind": kind,
    }


# ── Per-starter state over time ───────────────────────────────────────────


def _rf_wallclock(kickoff: datetime | None, t: datetime) -> float:
    if kickoff is None or kickoff > t:
        return 1.0
    return max(0.0, 1.0 - (t - kickoff).total_seconds() / 60.0 / GAME_MINUTES)


class _Game:
    """One NFL game: kickoff, its plays, and the game clock over time."""

    def __init__(self, kickoff: datetime | None, plays: list[dict] | None, final: bool, now: datetime):
        self.kickoff = kickoff
        self.plays = plays or []
        self.has_plays = bool(plays)
        self.final = final
        self.times = [datetime.fromisoformat(p["t"]) for p in self.plays]
        self.rf_after: list[float] = []
        for p in self.plays:
            if p.get("type") in ("End of Game",):
                self.rf_after.append(0.0)
            else:
                self.rf_after.append(remaining_share(p.get("period"), p.get("clock")))
        if final and self.times:
            self.end = self.times[-1]
        elif final and kickoff:
            self.end = kickoff + timedelta(minutes=GAME_MINUTES)
        else:
            self.end = None  # still on (or not started)
        self.now = now

    def remaining(self, t: datetime) -> float:
        if self.kickoff is None or t < self.kickoff:
            return 1.0
        if self.end is not None and t >= self.end:
            return 0.0
        if not self.has_plays:
            return _rf_wallclock(self.kickoff, t)
        i = bisect.bisect_right(self.times, t) - 1
        return 1.0 if i < 0 else self.rf_after[i]

    def accrual_end(self) -> datetime | None:
        """When the player's points stop accruing (his game's end, or now)."""
        if self.kickoff is None or self.kickoff > self.now:
            return None
        return self.end or self.now


class _Starter:
    def __init__(self, info: dict, game: _Game, events: list[tuple[datetime, dict]], history: list):
        self.info = info
        self.game = game
        self.events = sorted(events, key=lambda e: e[0])
        self.ev_times = [e[0] for e in self.events]
        cum, self.ev_cum = 0.0, []
        for _, e in self.events:
            cum += e["pts"]
            self.ev_cum.append(cum)
        total = float(info.get("points") or 0.0)
        self.residual = total - cum
        self.start = game.kickoff
        self.stop = game.accrual_end()
        # (time, proj, sd, status) as recorded; current values close it out.
        self.history = sorted(history, key=lambda h: h[0])
        self.hist_times = [h[0] for h in self.history]

    def banked(self, t: datetime) -> float:
        if self.stop is None or self.start is None or t < self.start:
            return 0.0
        i = bisect.bisect_right(self.ev_times, t) - 1
        pts = self.ev_cum[i] if i >= 0 else 0.0
        span = (self.stop - self.start).total_seconds()
        frac = 1.0 if span <= 0 else min(1.0, (t - self.start).total_seconds() / span)
        return pts + self.residual * frac

    def projection(self, t: datetime) -> tuple[float, float]:
        cur = (float(self.info.get("projected") or 0.0), float(self.info.get("stdev") or 0.0))
        if not self.history:
            return cur
        i = bisect.bisect_right(self.hist_times, t) - 1
        h = self.history[max(i, 0)]
        return float(h[1] or 0.0), float(h[2] or 0.0)


def _odds_at(starters: list[_Starter], t: datetime) -> tuple[float, float, float]:
    tot = {"user": 0.0, "opp": 0.0}
    var = {"user": 0.0, "opp": 0.0}
    pts = {"user": 0.0, "opp": 0.0}
    for s in starters:
        side = s.info["side"]
        banked = s.banked(t)
        proj, sd = s.projection(t)
        left = s.game.remaining(t)
        pts[side] += banked
        tot[side] += banked + proj * left
        var[side] += (sd**2) * left
    wp = win_probability(tot["user"], var["user"], tot["opp"], var["opp"])
    return wp, pts["user"], pts["opp"]


def _helps_user(e: dict) -> float:
    return e["pts"] if e["side"] == "user" else -e["pts"]


def _news_events(starters_info: list[dict], history: dict[str, list]) -> list[tuple[datetime, dict]]:
    """Recorded projection/status changes ("Adams → IR, −16.6 proj")."""
    out = []
    by_id = {s["id"]: s for s in starters_info}
    for pid, hist in history.items():
        s = by_id.get(pid)
        if s is None:
            continue
        hist = sorted(hist, key=lambda h: h[0])
        for prev, cur in zip(hist, hist[1:]):
            d = float(cur[1] or 0) - float(prev[1] or 0)
            status_changed = (prev[3] or "Active") != (cur[3] or "Active")
            if abs(d) < NEWS_MIN_PROJ and not status_changed:
                continue
            label = f"→ {cur[3]}" if status_changed and cur[3] else "projection"
            label += f", {d:+.1f} proj".replace("-", "−")
            out.append(
                (
                    cur[0],
                    {
                        "id": pid, "name": s["name"], "position": s.get("position"),
                        "side": s["side"], "pts": round(d, 2), "label": label, "kind": "news",
                    },
                )
            )
    return out


def _windows(kickoffs: list[datetime], ends: dict[datetime, datetime], now: datetime) -> list[tuple[datetime, datetime]]:
    """Game windows (Thu night, Sunday, Monday…) that have started by now."""
    out: list[list[datetime]] = []
    for k in sorted(set(kickoffs)):
        if k > now:
            break
        end = ends.get(k, k + GAME_WINDOW)
        if out and k <= out[-1][1] + timedelta(minutes=90):
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([k, end])
    return [(a, min(b, now)) for a, b in out]


def rebuild_timeline(
    starters_info: list[dict],
    games: dict[str, dict],
    week_kickoffs: list[datetime],
    now: datetime,
    scoring: str = "ppr",
    proj_history: dict[str, list] | None = None,
    threshold: float = SWING_THRESHOLD,
) -> dict:
    """The win-probability curve from the first kickoff to ``now``.

    ``starters_info``: both teams' starters ({id, name, position, team, side,
    points, projected, stdev, injury_status}). ``games``: team → {kickoff,
    plays (or None), final}. ``proj_history``: player → [(time, proj, sd,
    status)] from recorded snapshots."""
    proj_history = proj_history or {}
    game_objs: dict[str, _Game] = {}
    by_team_game: dict[int, _Game] = {}
    for team, g in games.items():
        key = id(g)
        if key not in by_team_game:
            by_team_game[key] = _Game(g.get("kickoff"), g.get("plays"), bool(g.get("final")), now)
        game_objs[team] = by_team_game[key]
    no_game = _Game(None, None, False, now)

    # Every play a starter took part in, once per game.
    for s in starters_info:
        s["pattern"] = name_pattern(s.get("name") or "")
    events: dict[str, list[tuple[datetime, dict]]] = {s["id"]: [] for s in starters_info}
    by_game: dict[int, list[dict]] = {}
    for s in starters_info:
        g = game_objs.get((s.get("team") or "").upper())
        if g is not None and (s.get("position") or "").upper() not in ("DEF", "DST", "D/ST"):
            by_game.setdefault(id(g), []).append(s)
    for g in by_team_game.values():
        players = by_game.get(id(g), [])
        if not players:
            continue
        for play, t in zip(g.plays, g.times):
            if t > now:
                break
            for e in play_events(play, players, scoring):
                events[e["id"]].append((t, e))

    starters = [
        _Starter(
            s,
            game_objs.get((s.get("team") or "").upper(), no_game),
            events[s["id"]],
            proj_history.get(s["id"], []),
        )
        for s in starters_info
    ]

    # Moments that matter: plays/news (just before and at), a regular grid
    # through each game window, game ends, and now.
    moments: list[tuple[datetime, dict]] = [
        (t, e) for evs in events.values() for t, e in evs
    ] + _news_events(starters_info, proj_history)
    moments.sort(key=lambda m: m[0])
    clusters: list[list[tuple[datetime, dict]]] = []
    for m in moments:
        if clusters and m[0] - clusters[-1][-1][0] <= CLUSTER_GAP:
            clusters[-1].append(m)
        else:
            clusters.append([m])

    ends: dict[datetime, datetime] = {}
    for g in by_team_game.values():
        if g.kickoff and g.end:
            ends[g.kickoff] = max(ends.get(g.kickoff, g.end), g.end)
    windows = _windows(week_kickoffs, ends, now)
    if not windows:
        return {"points": [], "windows": []}
    samples: set[datetime] = set()
    for a, b in windows:
        t = a
        while t < b:
            samples.add(t)
            t += SAMPLE_EVERY
        samples.add(b)
    samples.add(now)
    first = windows[0][0]
    cluster_at: dict[datetime, list[tuple[datetime, dict]]] = {}
    for c in clusters:
        start, end = c[0][0], c[-1][0]
        if end < first or start > now:
            continue
        samples.add(start - timedelta(seconds=1))
        samples.add(end)
        cluster_at[end] = c

    points = []
    for t in sorted(x for x in samples if first - timedelta(seconds=1) <= x <= now):
        wp, up, op = _odds_at(starters, t)
        point = {
            "t": t.isoformat(),
            "win_probability": round(wp, 4),
            "user_points": round(up, 1),
            "opp_points": round(op, 1),
        }
        c = cluster_at.get(t)
        if c is not None:
            before, _, _ = _odds_at(starters, c[0][0] - timedelta(seconds=1))
            delta = wp - before
            evs = [e for _, e in c]
            point["events"] = sorted(evs, key=lambda e: -abs(e["pts"]))[:6]
            point["delta"] = round(delta, 4)
            if abs(delta) >= threshold - 1e-9:
                direction = 1 if delta >= 0 else -1
                pushing = sorted(
                    (e for e in evs if _helps_user(e) * direction > 0),
                    key=lambda e: -abs(e["pts"]),
                )
                point["swing"] = {
                    "delta": round(delta, 4),
                    "drivers": (pushing or evs)[:MAX_DRIVERS],
                }
        points.append(point)
    for s in starters_info:
        s.pop("pattern", None)
    return {
        "points": points,
        "windows": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in windows],
    }



async def rebuild_odds_history(db, conn, now: datetime | None = None) -> dict:
    """The odds-history payload for a connection's current matchup, rebuilt
    from play-by-play (see module docstring)."""
    import asyncio

    from sqlalchemy import select

    from app.models import MatchupOdds
    from app.services.gameplan_service import build_matchup_preview
    from app.services.nfl_plays_service import game_plays, week_games
    from app.services.odds_timeline import week_kickoffs
    from app.services.schedule_service import utc_now

    now = now or utc_now()
    preview = await build_matchup_preview(db, conn, now=now, record=False)
    if preview.get("status") != "ok":
        return {"week": None, "points": [], "kickoffs": [], "window_start": None}
    week = preview["week"]
    kicks = await week_kickoffs(db, conn.season, week)
    kick_by_team: dict[str, datetime] = {}
    for k in kicks:
        t = datetime.fromisoformat(k["t"])
        kick_by_team[(k["home"] or "").upper()] = t
        kick_by_team[(k["away"] or "").upper()] = t

    starters: list[dict] = []
    for row in preview["rows"]:
        for key, side in (("user", "user"), ("opponent", "opp")):
            p = row.get(key)
            if not p or not p.get("id"):
                continue
            starters.append(
                {
                    "id": str(p["id"]),
                    "name": p.get("name") or str(p["id"]),
                    "position": p.get("position"),
                    "team": (p.get("team") or "").upper(),
                    "side": side,
                    "points": float(p.get("actual_points") or 0.0),
                    "projected": float(p.get("projected") or 0.0),
                    "stdev": float(p.get("stdev") or 0.0),
                    "injury_status": p.get("injury_status"),
                }
            )

    # Games: ESPN's scoreboard for event ids and status; plays for the games
    # our starters are in. Without ESPN, fall back to the stored kickoffs.
    espn = await week_games(conn.season, week)
    games: dict[str, dict] = {}
    for g in espn:
        kickoff = kick_by_team.get((g["home"] or "").upper())
        if kickoff is None:
            try:
                kickoff = datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).replace(tzinfo=None)
            except (AttributeError, ValueError):
                kickoff = None
        entry = {"kickoff": kickoff, "plays": None, "final": g["state"] == "post",
                 "event_id": g["event_id"], "state": g["state"]}
        for team in (g["home"], g["away"]):
            if team:
                games[team.upper()] = entry
    for team, kickoff in kick_by_team.items():
        games.setdefault(
            team,
            {"kickoff": kickoff, "plays": None, "final": now > kickoff + GAME_WINDOW,
             "event_id": None, "state": None},
        )
    needed = {
        id(games[s["team"]]): games[s["team"]]
        for s in starters
        if s["team"] in games
        and games[s["team"]].get("event_id")
        and games[s["team"]]["kickoff"] is not None
        and games[s["team"]]["kickoff"] <= now
    }
    fetched = await asyncio.gather(
        *(game_plays(g["event_id"], g["final"]) for g in needed.values())
    )
    for g, plays in zip(needed.values(), fetched):
        g["plays"] = plays

    # What the app believed about each starter's projection over time.
    snaps = (
        await db.execute(
            select(MatchupOdds)
            .where(MatchupOdds.connection_id == conn.id, MatchupOdds.week == week)
            .order_by(MatchupOdds.captured_at.asc(), MatchupOdds.id.asc())
        )
    ).scalars().all()
    history: dict[str, list] = {}
    for snap in snaps:
        for pid, v in (snap.player_proj or {}).items():
            history.setdefault(pid, []).append(
                (snap.captured_at, v.get("proj"), v.get("sd"), v.get("status"))
            )
    for s in starters:
        if s["id"] in history:
            history[s["id"]].append((now, s["projected"], s["stdev"], s["injury_status"]))

    # The chart covers the games this matchup's starters play in: a Thursday
    # or London game with none of them is dead air, not part of the story.
    teams = {s["team"] for s in starters}
    mine = [k for k in kicks if (k["home"] or "").upper() in teams or (k["away"] or "").upper() in teams]
    kicks = mine or kicks
    built = rebuild_timeline(
        starters,
        games,
        [datetime.fromisoformat(k["t"]) for k in kicks],
        now,
        conn.scoring_type or "ppr",
        history,
    )
    ends = {}
    for g in games.values():
        plays = g.get("plays")
        if g.get("final") and plays:
            ends[id(g)] = plays[-1]["t"]
    for k in kicks:
        g = games.get((k["home"] or "").upper())
        if g is not None and id(g) in ends:
            k["end"] = ends[id(g)]
    return {
        "week": week,
        "source": "plays" if needed and any(g.get("plays") for g in needed.values()) else "estimate",
        "swing_threshold": SWING_THRESHOLD,
        "window_start": kicks[0]["t"] if kicks else None,
        "now": now.isoformat(),
        "kickoffs": kicks,
        "windows": built["windows"],
        "points": built["points"],
    }
