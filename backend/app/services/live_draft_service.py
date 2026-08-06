"""Live draft sync — read an in-progress ESPN draft and mirror it to the board.

ESPN's mDraftDetail exposes every pick slot with the drafting team and, once the
pick is made, the ESPN player id. Polling it during a live draft lets the draft
room auto-mark players off the board and highlight your own picks, so you're not
hand-tracking a 14-team room while it's your turn to think.

ESPN player ids map to our canonical Sleeper ids through the same crosswalk the
rest of the app uses. A pick we can't map (a player missing from our pool) is
counted and reported rather than silently dropped, so a thin crosswalk is
visible instead of quietly desyncing the board.
"""

import logging

from app.models import LeagueConnection
from app.services.espn_service import ESPNClient
from app.utils.player_id_map import espn_to_sleeper_map

logger = logging.getLogger(__name__)


def _parse_picks(
    raw_picks: list[dict], espn_map: dict[str, str], my_team: str | None
) -> dict:
    picks: list[dict] = []
    drafted_ids: list[str] = []
    your_ids: list[str] = []
    unmapped = 0
    made = 0
    your_slot = None

    for p in raw_picks:
        espn_pid = p.get("playerId", -1)
        team = str(p.get("teamId"))
        overall = p.get("overallPickNumber")
        round_id = p.get("roundId")
        round_pick = p.get("roundPickNumber")
        is_you = my_team is not None and team == my_team
        if is_you and round_id == 1:
            your_slot = round_pick

        is_made = bool(espn_pid and espn_pid != -1)
        player_sleeper = None
        if is_made:
            made += 1
            player_sleeper = espn_map.get(str(espn_pid))
            if player_sleeper:
                drafted_ids.append(player_sleeper)
                if is_you:
                    your_ids.append(player_sleeper)
            else:
                unmapped += 1

        picks.append(
            {
                "overall_pick": overall,
                "round": round_id,
                "round_pick": round_pick,
                "team_id": team,
                "player_id": player_sleeper,
                "is_you": is_you,
                "made": is_made,
            }
        )

    on_the_clock = next((p for p in picks if not p["made"]), None)
    return {
        "picks": picks,
        "drafted_player_ids": drafted_ids,
        "your_player_ids": your_ids,
        "unmapped_count": unmapped,
        "picks_made": made,
        "on_the_clock": on_the_clock,
        "your_slot": your_slot,
    }


def build_demo_state(
    board: list[dict], teams: int, rounds: int, my_slot: int, picks_made: int
) -> dict:
    """A synthetic in-progress draft for previewing the live room without a real
    draft to poll. Fills picks in snake order from the top of the board so the
    feed, auto-marking, and roster-fill all exercise real player data. Not wired
    to ESPN — purely a dry run of what draft day will look like.
    """
    ordered = [p for p in board if p.get("adp")]
    ordered.sort(key=lambda p: p["adp"])
    total = teams * rounds

    picks: list[dict] = []
    drafted_ids: list[str] = []
    your_ids: list[str] = []
    for overall in range(1, total + 1):
        rnd = (overall - 1) // teams + 1
        idx = (overall - 1) % teams + 1
        slot = idx if rnd % 2 == 1 else teams - idx + 1
        is_you = slot == my_slot
        made = overall <= picks_made
        player = ordered[overall - 1] if made and overall - 1 < len(ordered) else None
        pid = player["player_id"] if player else None
        if made and pid:
            drafted_ids.append(pid)
            if is_you:
                your_ids.append(pid)
        picks.append(
            {
                "overall_pick": overall,
                "round": rnd,
                "round_pick": idx,
                "team_id": str(slot),
                "player_id": pid,
                "is_you": is_you,
                "made": made,
            }
        )

    on_the_clock = next((p for p in picks if not p["made"]), None)
    return {
        "status": "in_progress" if picks_made < total else "complete",
        "total_picks": total,
        "picks_made": picks_made,
        "your_team_id": str(my_slot),
        "your_slot": my_slot,
        "on_the_clock": on_the_clock,
        "drafted_player_ids": drafted_ids,
        "your_player_ids": your_ids,
        "unmapped_count": 0,
        "picks": picks,
        "demo": True,
    }


async def espn_live_draft_state(db, conn: LeagueConnection) -> dict:
    """Current state of the connected ESPN league's draft.

    Degrades to a `not_started` shell on any fetch error — a live draft room
    should keep working off the static board rather than blow up mid-pick.
    """
    creds = conn.credentials or {}
    client = ESPNClient(
        conn.league_id,
        conn.season,
        espn_s2=creds.get("espn_s2"),
        swid=creds.get("swid"),
    )
    try:
        data = await client.get_draft_detail()
    except Exception:
        logger.warning("ESPN draft detail unavailable for %s", conn.league_id)
        return {
            "status": "unavailable",
            "total_picks": 0,
            "picks_made": 0,
            "on_the_clock": None,
            "your_team_id": str(conn.team_id) if conn.team_id else None,
            "your_slot": None,
            "drafted_player_ids": [],
            "your_player_ids": [],
            "unmapped_count": 0,
            "picks": [],
        }
    finally:
        await client.close()

    detail = data.get("draftDetail") or {}
    raw_picks = detail.get("picks") or []
    espn_map = await espn_to_sleeper_map(db)
    my_team = str(conn.team_id) if conn.team_id else None

    parsed = _parse_picks(raw_picks, espn_map, my_team)

    if detail.get("drafted"):
        status = "complete"
    elif detail.get("inProgress") or parsed["picks_made"] > 0:
        status = "in_progress"
    else:
        status = "not_started"

    return {
        "status": status,
        "total_picks": len(raw_picks),
        "your_team_id": my_team,
        **parsed,
    }
