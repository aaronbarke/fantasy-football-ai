"""Mock draft simulation — practice opponents that draft like people do.

A useful mock has to be wrong in the same ways a real draft is wrong. Bots here
don't take the best player by our own board (that would make every mock a
formality where value falls to you forever); they draft near **consensus ADP**,
scattered by each player's own observed draft-slot standard deviation. A player
real drafters disagree about goes unpredictably here too, while a consensus
first-rounder never falls to the third.

On top of that they respect roster construction — they fill starting slots
before hoarding a sixth running back, and they stop at one kicker — because a
bot that ignores its roster hands you an unrealistically easy draft.
"""

import logging
import math
import random
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MockDraft, MockDraftPick
from app.services.draft_service import (
    VOR_POSITIONS,
    compute_draft_board,
    late_round_board,
    starters_per_team,
)

logger = logging.getLogger(__name__)

# How far a bot strays from consensus ADP, as a multiple of that player's own
# ADP standard deviation. Below ~0.8 every mock plays out identically; above
# ~1.5 the first round stops resembling a real draft.
BOT_NOISE = 1.0
DEFAULT_STDEV = 6.0  # for players with no observed spread
# Only the next few players by ADP are realistically in play at any pick.
BOT_WINDOW = 14
# Picks of "attractiveness" a bot gives a player who fills an empty starter.
NEED_BONUS = 12.0
# Roster caps per team. Kicker and defense at one apiece: nobody carries two.
MAX_PER_POSITION = {"QB": 3, "RB": 8, "WR": 8, "TE": 3, "K": 1, "DEF": 1}


def snake_slot(overall_pick: int, teams: int) -> tuple[int, int]:
    """(round, team_slot) for an overall pick in a snake draft."""
    rnd = (overall_pick - 1) // teams + 1
    index = (overall_pick - 1) % teams + 1
    slot = index if rnd % 2 == 1 else teams - index + 1
    return rnd, slot


def user_pick_numbers(teams: int, slot: int, rounds: int) -> list[int]:
    """Every overall pick belonging to one seat."""
    return [
        (r - 1) * teams + (slot if r % 2 == 1 else teams - slot + 1)
        for r in range(1, rounds + 1)
    ]


def _can_roster(position: str, roster: Counter) -> bool:
    return roster[position] < MAX_PER_POSITION.get(position, 6)


def bot_pick(
    pool: list[dict],
    taken: set[str],
    roster: Counter,
    needs: dict[str, int],
    rng: random.Random,
) -> dict | None:
    """Pick for a simulated opponent. `pool` must be sorted by ADP ascending."""
    candidates: list[tuple[float, dict]] = []
    for player in pool:
        if player["player_id"] in taken:
            continue
        position = player["position"]
        if not _can_roster(position, roster):
            continue

        adp = player["adp"]
        spread = (player.get("adp_stdev") or DEFAULT_STDEV) * BOT_NOISE
        perceived = adp + rng.gauss(0, spread)
        if roster[position] < needs.get(position, 0):
            perceived -= NEED_BONUS
        candidates.append((perceived, player))
        if len(candidates) >= BOT_WINDOW:
            break

    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]


async def build_pool(
    db: AsyncSession, season: int, scoring: str, teams: int, roster_positions
) -> list[dict]:
    """Every draftable player with an ADP, best pick first.

    Kickers and defenses are folded back in here even though the ranked board
    deliberately excludes them — a mock draft where nobody ever takes a kicker
    would misrepresent how the last rounds actually go.
    """
    board = await compute_draft_board(
        db,
        season=season,
        scoring=scoring,
        league_size=teams,
        roster_positions=roster_positions,
    )
    late = await late_round_board(db, season, scoring)

    pool = [dict(row) for row in board if row["adp"]]
    for row in late:
        if not row["adp"]:
            continue
        pool.append(
            {
                **row,
                # K/DEF carry no meaningful value over replacement, so they
                # score zero rather than a fabricated number.
                "vor": 0.0,
                "proj_points": 0.0,
                "tier": None,
                "overall_rank": None,
                "adp_delta": None,
                "value_score": 0.0,
            }
        )
    pool.sort(key=lambda r: r["adp"])
    return pool


def simulate_until_user(
    pool: list[dict],
    picks: list[dict],
    teams: int,
    rounds: int,
    my_slot: int,
    rng: random.Random,
    roster_positions: list[str] | None = None,
) -> list[dict]:
    """Run bot picks from the current state up to (not including) the user's turn.

    Returns only the newly made picks. Pure function over the pool + existing
    picks so it can be tested without a database.
    """
    taken = {p["player_id"] for p in picks}
    rosters: dict[int, Counter] = {slot: Counter() for slot in range(1, teams + 1)}
    for p in picks:
        rosters[p["team_slot"]][p["position"]] += 1

    starters = starters_per_team(roster_positions)
    needs = {pos: round(starters.get(pos, 0)) for pos in VOR_POSITIONS}

    made: list[dict] = []
    total = teams * rounds
    while len(picks) + len(made) < total:
        overall = len(picks) + len(made) + 1
        rnd, slot = snake_slot(overall, teams)
        if slot == my_slot:
            break
        choice = bot_pick(pool, taken, rosters[slot], needs, rng)
        if choice is None:
            break
        taken.add(choice["player_id"])
        rosters[slot][choice["position"]] += 1
        made.append(
            {
                "overall_pick": overall,
                "round": rnd,
                "team_slot": slot,
                "player_id": choice["player_id"],
                "position": choice["position"],
                "is_user": False,
                "snapshot": choice,
            }
        )
    return made


async def load_picks(db: AsyncSession, draft_id: uuid.UUID) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(MockDraftPick)
                .where(MockDraftPick.draft_id == draft_id)
                .order_by(MockDraftPick.overall_pick)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "overall_pick": r.overall_pick,
            "round": r.round,
            "team_slot": r.team_slot,
            "player_id": r.player_id,
            "is_user": r.is_user,
            "position": (r.snapshot or {}).get("position"),
            "snapshot": r.snapshot,
        }
        for r in rows
    ]


def _persist(db: AsyncSession, draft: MockDraft, made: list[dict]) -> None:
    for p in made:
        db.add(
            MockDraftPick(
                draft_id=draft.id,
                overall_pick=p["overall_pick"],
                round=p["round"],
                team_slot=p["team_slot"],
                player_id=p["player_id"],
                is_user=p["is_user"],
                snapshot=p["snapshot"],
            )
        )


async def advance(
    db: AsyncSession, draft: MockDraft, pool: list[dict], rng: random.Random
) -> list[dict]:
    """Run the bots up to the user's next turn, persisting what they take."""
    picks = await load_picks(db, draft.id)
    made = simulate_until_user(
        pool,
        picks,
        draft.teams,
        draft.rounds,
        draft.my_slot,
        rng,
        draft.roster_positions,
    )
    _persist(db, draft, made)
    if len(picks) + len(made) >= draft.teams * draft.rounds:
        draft.status = "complete"
    await db.commit()
    return picks + made


async def make_user_pick(
    db: AsyncSession,
    draft: MockDraft,
    pool: list[dict],
    player_id: str,
    rng: random.Random,
) -> list[dict]:
    """Record the user's selection, then let the bots run to their next turn."""
    picks = await load_picks(db, draft.id)
    taken = {p["player_id"] for p in picks}
    if player_id in taken:
        raise ValueError("That player is already off the board")

    by_id = {p["player_id"]: p for p in pool}
    chosen = by_id.get(player_id)
    if chosen is None:
        raise ValueError("Unknown player")

    overall = len(picks) + 1
    rnd, slot = snake_slot(overall, draft.teams)
    if slot != draft.my_slot:
        raise ValueError("It isn't your pick")

    _persist(
        db,
        draft,
        [
            {
                "overall_pick": overall,
                "round": rnd,
                "team_slot": slot,
                "player_id": player_id,
                "position": chosen["position"],
                "is_user": True,
                "snapshot": chosen,
            }
        ],
    )
    await db.commit()
    return await advance(db, draft, pool, rng)


def grade(picks: list[dict], teams: int, my_slot: int) -> dict:
    """Score every team by the value it accumulated, and rank yours.

    Each pick contributes `max(0, vor)`. Floored deliberately: summing raw VOR
    would score a kicker (exactly 0) *above* a last-round sleeper at -30, which
    is backwards — you have to fill the roster with someone, and the dart throw
    at least has upside. Grading is about the value you captured, not a penalty
    for the picks where none was available.
    """
    totals: dict[int, float] = {slot: 0.0 for slot in range(1, teams + 1)}
    for p in picks:
        vor = (p.get("snapshot") or {}).get("vor") or 0.0
        totals[p["team_slot"]] += max(0.0, vor)

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    placement = next(i + 1 for i, (slot, _) in enumerate(ranked) if slot == my_slot)

    mine = [p for p in picks if p["team_slot"] == my_slot]
    # Best/worst are judged on value against the market, which only means
    # something for ranked skill players — a defense has no meaningful ADP edge.
    rated = [
        p
        for p in mine
        if (p.get("snapshot") or {}).get("overall_rank")
        and (p.get("snapshot") or {}).get("adp_delta") is not None
    ]
    by_value = sorted(
        rated, key=lambda p: (p.get("snapshot") or {}).get("value_score") or 0.0
    )
    return {
        "your_rank": placement,
        "teams": teams,
        "your_total_vor": round(totals[my_slot], 1),
        "league_average_vor": round(sum(totals.values()) / teams, 1),
        "standings": [
            {"team_slot": slot, "total_vor": round(v, 1), "is_you": slot == my_slot}
            for slot, v in ranked
        ],
        "best_pick": (by_value[-1].get("snapshot") if by_value else None),
        "worst_pick": (by_value[0].get("snapshot") if by_value else None),
        "roster": [p.get("snapshot") for p in mine],
    }


def make_rng(draft_id: uuid.UUID, pick_count: int) -> random.Random:
    """Deterministic per draft and pick, so a refresh can't reroll the bots."""
    return random.Random(f"{draft_id}:{pick_count}")
