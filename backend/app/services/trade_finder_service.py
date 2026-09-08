"""Automated trade finder.

Scans the rest of the league for 1-for-1 swaps that are (a) roughly fair by
trade value and (b) a genuine win-win — each side's optimal starting lineup
actually improves. No chat prompt required: this is deterministic and ranks the
candidates itself.

How it decides:
- **Fairness** uses the leaguewide trade-value currency (VOR-based, comparable
  across positions) from ``value_service``. A pair only qualifies if the two
  players' values are within ``FAIRNESS_PCT`` of the larger — "players of equal
  value".
- **Upgrade** uses the real lineup optimizer (``optimize_lineup``): we re-optimize
  each roster after the swap and keep only pairs where the user's optimal
  weekly points go UP and the partner's don't go down. That's what makes a deal
  realistic — it naturally trades from a bench/surplus into a starting need, and
  only proposes swaps the other manager would plausibly accept.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeagueConnection, Player, Roster
from app.services.gameplan_service import _lineup_slots, optimize_lineup
from app.services.value_service import compute_player_values

# Value gap (fraction of the larger side) still considered "roughly equal value".
FAIRNESS_PCT = 0.10
VALUED_POSITIONS = {"QB", "RB", "WR", "TE"}


def _lineup_points(slots: list[str], players: list[dict]) -> float:
    """Optimal starting-lineup points (uses ppg as each slot's score)."""
    lineup, _ = optimize_lineup(slots, players)
    return round(sum((s["player"] or {}).get("projected") or 0 for s in lineup), 2)


def _roster_dicts(
    ids: list[str], values: dict[str, dict], meta: dict[str, Player]
) -> list[dict]:
    """Optimizer-shaped player dicts for a roster: projected = weekly ppg."""
    out = []
    for pid in ids:
        p = meta.get(pid)
        if p is None:
            continue
        v = values.get(pid, {})
        out.append(
            {
                "id": pid,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "projected": v.get("ppg") or 0.0,
                "value": v.get("value"),
                "trend": v.get("trend"),
            }
        )
    return out


def rank_trades(
    my_players: list[dict],
    their_players: list[dict],
    slots: list[str],
    partner: dict,
) -> list[dict]:
    """Pure ranking of 1-for-1 swaps between two rosters. Returns win-win,
    roughly-even candidates, best (biggest lineup gain for the user) first."""
    my_base = _lineup_points(slots, my_players)
    their_base = _lineup_points(slots, their_players)

    out: list[dict] = []
    for give in my_players:
        vx = give["value"]
        if vx is None or give["position"] not in VALUED_POSITIONS:
            continue
        for recv in their_players:
            vy = recv["value"]
            if vy is None or recv["position"] not in VALUED_POSITIONS:
                continue
            bigger = max(vx, vy, 1.0)
            gap_pct = abs(vx - vy) / bigger
            if gap_pct > FAIRNESS_PCT:  # not roughly equal value
                continue

            my_after = [p for p in my_players if p["id"] != give["id"]] + [recv]
            their_after = [p for p in their_players if p["id"] != recv["id"]] + [give]
            my_gain = _lineup_points(slots, my_after) - my_base
            their_gain = _lineup_points(slots, their_after) - their_base
            # Must upgrade the user and not downgrade the partner (win-win).
            if my_gain <= 0 or their_gain < 0:
                continue

            out.append(
                {
                    "partner": partner,
                    "give": _player_view(give),
                    "receive": _player_view(recv),
                    "value_gap": round(abs(vx - vy), 1),
                    "your_lineup_gain": round(my_gain, 1),
                    "their_lineup_gain": round(their_gain, 1),
                    "rationale": (
                        f"Upgrade your {recv['position']}: give {give['name']} "
                        f"({vx:.0f}) for {recv['name']} ({vy:.0f}) — about "
                        f"+{my_gain:.1f} pts/wk to your lineup, and it also helps "
                        f"{partner['owner_name']} at {give['position']}."
                    ),
                }
            )
    out.sort(key=_trade_score, reverse=True)
    return out


def _trade_score(c: dict) -> tuple[float, float]:
    """Best upgrade first; tie-break toward mutually beneficial, fairer deals."""
    mutual = min(c["your_lineup_gain"], c["their_lineup_gain"])
    return (c["your_lineup_gain"] + 0.25 * mutual, -c["value_gap"])


def _player_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "position": p["position"],
        "team": p["team"],
        "value": p["value"],
        "ppg": p["projected"],
        "trend": p["trend"],
    }


async def find_trades(
    db: AsyncSession, conn: LeagueConnection, max_results: int = 8
) -> list[dict]:
    """Ranked win-win 1-for-1 trade candidates across the whole league."""
    rosters = (
        await db.execute(select(Roster).where(Roster.connection_id == conn.id))
    ).scalars().all()
    mine = next((r for r in rosters if r.team_id == conn.team_id), None)
    if mine is None or not mine.players:
        return []
    others = [r for r in rosters if r.team_id != conn.team_id and r.players]
    if not others:
        return []

    values = await compute_player_values(db)
    all_ids = set(mine.players)
    for r in others:
        all_ids.update(r.players)
    players = (
        await db.execute(select(Player).where(Player.id.in_(all_ids)))
    ).scalars().all()
    meta = {p.id: p for p in players}

    slots = _lineup_slots(conn)
    my_players = _roster_dicts(list(mine.players), values, meta)

    candidates: list[dict] = []
    for other in others:
        partner = {
            "team_id": other.team_id,
            "owner_name": other.owner_name or other.team_id,
            "record": f"{other.wins}-{other.losses}"
            + (f"-{other.ties}" if other.ties else ""),
        }
        their_players = _roster_dicts(list(other.players), values, meta)
        candidates.extend(rank_trades(my_players, their_players, slots, partner))

    candidates.sort(key=_trade_score, reverse=True)
    return candidates[:max_results]
