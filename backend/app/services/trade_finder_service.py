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

from itertools import combinations

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


def _side_value(players: list[dict]) -> float:
    return sum(p["value"] or 0.0 for p in players)


def _package_rationale(give: list[dict], recv: list[dict], my_gain: float, owner: str) -> str:
    gives = " + ".join(p["name"] for p in give)
    gets = " + ".join(p["name"] for p in recv)
    shape = "consolidate" if len(give) > len(recv) else "add depth" if len(recv) > len(give) else "swap"
    return (
        f"Give {gives} for {gets} ({shape}) — about +{my_gain:.1f} pts/wk to your "
        f"starting lineup, and it doesn't set back {owner}."
    )


def rank_trades(
    my_players: list[dict],
    their_players: list[dict],
    slots: list[str],
    partner: dict,
) -> list[dict]:
    """Pure ranking of win-win, roughly-even packages between two rosters —
    1-for-1, 2-for-1 (consolidate) and 1-for-2 (add depth). Best lineup gain for
    the user first. The value-fairness check runs BEFORE the (costlier) lineup
    re-optimization, so most combinations are rejected cheaply."""
    my_base = _lineup_points(slots, my_players)
    their_base = _lineup_points(slots, their_players)

    my_pool = [p for p in my_players if p["value"] is not None and p["position"] in VALUED_POSITIONS]
    their_pool = [p for p in their_players if p["value"] is not None and p["position"] in VALUED_POSITIONS]

    my_singles = [[p] for p in my_pool]
    my_pairs = [list(c) for c in combinations(my_pool, 2)]
    their_singles = [[p] for p in their_pool]
    their_pairs = [list(c) for c in combinations(their_pool, 2)]

    # (give options, receive options): 1-for-1, 2-for-1 (consolidate), 1-for-2 (depth)
    shapes = [
        (my_singles, their_singles),
        (my_pairs, their_singles),
        (my_singles, their_pairs),
    ]

    out: list[dict] = []
    for give_opts, recv_opts in shapes:
        for give in give_opts:
            gv = _side_value(give)
            for recv in recv_opts:
                rv = _side_value(recv)
                bigger = max(gv, rv, 1.0)
                if abs(gv - rv) / bigger > FAIRNESS_PCT:  # not roughly equal value
                    continue

                give_ids = {p["id"] for p in give}
                recv_ids = {p["id"] for p in recv}
                my_after = [p for p in my_players if p["id"] not in give_ids] + recv
                their_after = [p for p in their_players if p["id"] not in recv_ids] + give
                my_gain = _lineup_points(slots, my_after) - my_base
                their_gain = _lineup_points(slots, their_after) - their_base
                if my_gain <= 0 or their_gain < 0:  # must be a genuine win-win
                    continue

                out.append(
                    {
                        "partner": partner,
                        "give": [_player_view(p) for p in give],
                        "receive": [_player_view(p) for p in recv],
                        "give_value": round(gv, 1),
                        "receive_value": round(rv, 1),
                        "value_gap": round(abs(gv - rv), 1),
                        "your_lineup_gain": round(my_gain, 1),
                        "their_lineup_gain": round(their_gain, 1),
                        "rationale": _package_rationale(
                            give, recv, my_gain, partner["owner_name"]
                        ),
                    }
                )
    out.sort(key=_trade_score, reverse=True)
    return out


def _trade_score(c: dict) -> tuple[float, float, float]:
    """Best upgrade first; tie-break toward mutually beneficial, fairer, and
    simpler (fewer players) deals."""
    mutual = min(c["your_lineup_gain"], c["their_lineup_gain"])
    simplicity = -(len(c["give"]) + len(c["receive"]))
    return (c["your_lineup_gain"] + 0.25 * mutual, simplicity, -c["value_gap"])


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
