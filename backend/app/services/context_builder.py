"""Assembles the structured data context injected into Claude prompts.

Pipeline: classify intent → find referenced players → gather only the data
that intent needs (roster, stats, matchups, game conditions, waivers). This
keeps prompts small and grounded — the AI never sees data it doesn't need.
"""

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AvailablePlayer,
    GameCondition,
    LeagueConnection,
    Matchup,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    Roster,
)
from app.services.schedule_service import (
    defense_vs_position_ranks,
    latest_stats_season,
)

INTENT_KEYWORDS = {
    "start_sit": ["start", "sit", "bench", "lineup", "flex", "who should i play"],
    "trade": ["trade", "deal", "swap", "give up", "package", "acquire"],
    "waiver": ["waiver", "pick up", "pickup", "add", "drop", "free agent", "stream"],
    "matchup": ["matchup", "opponent", "this week's game", "win this week", "projected"],
}


def classify_intent(question: str) -> str:
    q = question.lower()
    scores = {
        intent: sum(1 for kw in kws if kw in q) for intent, kws in INTENT_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] > 0 else "general"


async def find_mentioned_players(
    db: AsyncSession, question: str, limit: int = 4
) -> list[Player]:
    """Match capitalized word pairs and known-name fragments in the question
    against the players table."""
    candidates: set[str] = set()
    # Word pairs like "Ja'Marr Chase", "CeeDee Lamb"
    for m in re.finditer(r"\b([A-Z][\w.'-]+)\s+([A-Z][\w.'-]+)\b", question):
        candidates.add(f"{m.group(1)} {m.group(2)}")
    # Single capitalized words (last names) as fallback
    for m in re.finditer(r"\b([A-Z][a-z][\w.'-]{2,})\b", question):
        candidates.add(m.group(1))

    if not candidates:
        return []

    clauses = [Player.full_name.ilike(f"%{c}%") for c in candidates]
    result = await db.execute(
        select(Player)
        .where(or_(*clauses), Player.position.is_not(None))
        .order_by(Player.depth_chart_order.nulls_last())
        .limit(limit * 3)
    )
    players = list(result.scalars().all())

    # Prefer exact full-name matches, then dedupe
    exact = [p for p in players if p.full_name in candidates]
    rest = [p for p in players if p not in exact]
    out: list[Player] = []
    seen: set[str] = set()
    for p in exact + rest:
        if p.id not in seen:
            out.append(p)
            seen.add(p.id)
        if len(out) >= limit:
            break
    return out


async def player_package(
    db: AsyncSession, player: Player, season: int, scoring_type: str
) -> dict[str, Any]:
    """Stats + matchup + game conditions for one player."""
    # Use the most recent stats available — pre-season the league year has no
    # data yet, so fall back to the prior season rather than returning nothing.
    stats = (
        await db.execute(
            select(PlayerStatsWeekly)
            .where(
                PlayerStatsWeekly.player_id == player.id,
                PlayerStatsWeekly.season <= season,
            )
            .order_by(PlayerStatsWeekly.season.desc(), PlayerStatsWeekly.week.desc())
            .limit(5)
        )
    ).scalars().all()
    stats_season = stats[0].season if stats else None

    fp_field = {
        "ppr": "fantasy_points_ppr",
        "half_ppr": "fantasy_points_half",
        "standard": "fantasy_points_std",
    }.get(scoring_type, "fantasy_points_ppr")

    last_weeks = [
        {
            "week": s.week,
            "opponent": s.opponent,
            "targets": s.targets,
            "receptions": s.receptions,
            "receiving_yards": float(s.receiving_yards or 0),
            "rush_yards": float(s.rush_yards or 0),
            "pass_yards": float(s.pass_yards or 0),
            "total_tds": (s.pass_tds or 0) + (s.rush_tds or 0) + (s.receiving_tds or 0),
            "target_share": float(s.target_share) if s.target_share else None,
            "fantasy_points": float(getattr(s, fp_field) or 0),
        }
        for s in stats
    ]

    fps = [w["fantasy_points"] for w in last_weeks]
    targets = [w["targets"] for w in last_weeks]

    # Upcoming game conditions for the player's team
    conditions = None
    if player.team:
        gc = (
            await db.execute(
                select(GameCondition)
                .where(
                    GameCondition.season == season,
                    or_(
                        GameCondition.home_team == player.team,
                        GameCondition.away_team == player.team,
                    ),
                )
                .order_by(GameCondition.week.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if gc:
            is_home = gc.home_team == player.team
            conditions = {
                "opponent": gc.away_team if is_home else gc.home_team,
                "home": is_home,
                "spread": float(gc.spread) if gc.spread is not None else None,
                "over_under": float(gc.over_under) if gc.over_under is not None else None,
                "implied_team_total": float(
                    (gc.implied_total_home if is_home else gc.implied_total_away) or 0
                )
                or None,
                "weather": {
                    "temp_f": float(gc.temp_f) if gc.temp_f is not None else None,
                    "wind_mph": float(gc.wind_mph) if gc.wind_mph is not None else None,
                    "precipitation_pct": float(gc.precipitation_pct)
                    if gc.precipitation_pct is not None
                    else None,
                    "dome": gc.dome,
                },
            }

    # Opponent defense vs this position: rank, points allowed, and how far
    # above/below league average — captures tough/easy matchups (e.g. a
    # shadow-corner defense that suppresses WR production).
    matchup_difficulty = None
    opponent = (conditions or {}).get("opponent")
    if opponent is None and player.team:
        next_game = (
            await db.execute(
                select(NflSchedule)
                .where(
                    NflSchedule.season == season,
                    or_(
                        NflSchedule.home_team == player.team,
                        NflSchedule.away_team == player.team,
                    ),
                )
                .order_by(NflSchedule.week.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if next_game:
            opponent = (
                next_game.away_team
                if next_game.home_team == player.team
                else next_game.home_team
            )
    if opponent and player.position in {"QB", "RB", "WR", "TE"}:
        dvp_season = await latest_stats_season(db)
        if dvp_season:
            ranks = await defense_vs_position_ranks(db, dvp_season)
            info = ranks.get((opponent, player.position))
            if info:
                pos_avgs = [
                    v["pts_allowed_avg"]
                    for (_, pos), v in ranks.items()
                    if pos == player.position
                ]
                league_avg = round(sum(pos_avgs) / len(pos_avgs), 1)
                matchup_difficulty = {
                    "opponent": opponent,
                    "defense_rank_vs_position": info["rank"],
                    "rank_meaning": "1 = allows most fantasy points to this position (easiest matchup), 32 = toughest",
                    "pts_allowed_per_game_to_position": info["pts_allowed_avg"],
                    "league_avg_for_position": league_avg,
                    "delta_vs_league_avg": round(
                        info["pts_allowed_avg"] - league_avg, 1
                    ),
                    "based_on_season": dvp_season,
                }

    return {
        "id": player.id,
        "name": player.full_name,
        "team": player.team,
        "position": player.position,
        "injury_status": player.injury_status or "Healthy",
        "injury_body_part": player.injury_body_part,
        "stats_season": stats_season,
        "matchup_difficulty": matchup_difficulty,
        "last_5_weeks": last_weeks,
        "averages": {
            "fantasy_points": round(sum(fps) / len(fps), 1) if fps else None,
            "targets": round(sum(targets) / len(targets), 1) if targets else None,
        },
        "upcoming_game": conditions,
    }


async def _roster_names(
    db: AsyncSession, roster: Roster
) -> tuple[list[dict], list[dict]]:
    """Resolve roster player IDs to readable starter/bench lists."""
    all_ids = list(roster.players or [])
    if not all_ids:
        return [], []
    players = (
        (await db.execute(select(Player).where(Player.id.in_(all_ids)))).scalars().all()
    )
    by_id = {p.id: p for p in players}
    starter_ids = roster.starters or []

    def brief(pid: str) -> dict:
        p = by_id.get(pid)
        if p is None:
            return {"id": pid, "name": pid}
        return {
            "name": p.full_name,
            "position": p.position,
            "team": p.team,
            "injury_status": p.injury_status or "Healthy",
        }

    starters = [brief(pid) for pid in starter_ids if pid in by_id]
    bench = [brief(pid) for pid in all_ids if pid not in set(starter_ids)]
    return starters, bench


async def build_context(
    db: AsyncSession, conn: LeagueConnection | None, question: str
) -> tuple[str, dict[str, Any]]:
    """Returns (intent, context dict) ready for prompt injection."""
    intent = classify_intent(question)
    season = conn.season if conn else 2026
    scoring_type = (conn.scoring_type if conn else None) or "ppr"

    context: dict[str, Any] = {"question_type": intent}

    if conn:
        context["league_settings"] = {
            "platform": conn.platform,
            "league_name": conn.league_name,
            "scoring": scoring_type,
            "roster_positions": conn.roster_positions,
        }

        user_roster = (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == conn.team_id
                )
            )
        ).scalar_one_or_none()
        if user_roster:
            starters, bench = await _roster_names(db, user_roster)
            context["user_roster"] = {
                "record": f"{user_roster.wins}-{user_roster.losses}",
                "starters": starters,
                "bench": bench,
            }

    # Player deep-dives for any mentioned players
    mentioned = await find_mentioned_players(db, question)
    if mentioned:
        context["players"] = [
            await player_package(db, p, season, scoring_type) for p in mentioned
        ]

    # Intent-specific extras
    if intent == "waiver" and conn:
        available = (
            await db.execute(
                select(AvailablePlayer, Player)
                .join(Player, Player.id == AvailablePlayer.player_id)
                .where(AvailablePlayer.connection_id == conn.id)
                .order_by(AvailablePlayer.trending_count.desc().nulls_last())
                .limit(15)
            )
        ).all()
        context["waiver_wire"] = [
            {
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "injury_status": p.injury_status or "Healthy",
                "trending_adds": ap.trending_count,
                "recent_ppr_avg": float(ap.recent_ppr_avg) if ap.recent_ppr_avg else None,
            }
            for ap, p in available
        ]

    if intent == "matchup" and conn and conn.team_id:
        latest_week = (
            await db.execute(
                select(Matchup.week)
                .where(Matchup.connection_id == conn.id)
                .order_by(Matchup.week.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_week:
            m = (
                await db.execute(
                    select(Matchup).where(
                        Matchup.connection_id == conn.id,
                        Matchup.week == latest_week,
                        or_(
                            Matchup.team_a_id == conn.team_id,
                            Matchup.team_b_id == conn.team_id,
                        ),
                    )
                )
            ).scalar_one_or_none()
            if m:
                opp_id = m.team_b_id if m.team_a_id == conn.team_id else m.team_a_id
                opp_roster = (
                    await db.execute(
                        select(Roster).where(
                            Roster.connection_id == conn.id, Roster.team_id == opp_id
                        )
                    )
                ).scalar_one_or_none()
                if opp_roster:
                    opp_starters, _ = await _roster_names(db, opp_roster)
                    context["opponent"] = {
                        "owner_name": opp_roster.owner_name,
                        "record": f"{opp_roster.wins}-{opp_roster.losses}",
                        "starters": opp_starters,
                    }

    return intent, context
