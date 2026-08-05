"""Preseason draft market ingestion — ADP, auction values, season projections.

Two deliberately independent sources:

1. **ESPN** publishes an ADP plus season-long point projections drawn from its
   own very large, very casual userbase. One format-agnostic ADP.
2. **Fantasy Football Calculator** aggregates real mock drafts, per scoring
   format, on a rolling 7-day window — and ships the *standard deviation* of
   each player's draft slot, which is what lets us answer "will he still be
   there at my next pick?"

Where the two disagree is itself the signal: a player ESPN drafters reach for
but the mock-draft crowd lets slide is one you can wait on.

Both are unofficial public endpoints with no auth. Every fetch degrades to an
empty dict and logs a warning rather than raising — a stale board beats a 500.
"""

import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerDraftProfile
from app.services.cache import cache_get, cache_set
from app.utils.player_id_map import espn_to_sleeper_map, normalize_name

logger = logging.getLogger(__name__)

ESPN_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
    "/segments/0/leaguedefaults/3"
)
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}"

# Our scoring keys → FFC's URL slugs. ESPN returns the same ADP for every
# format, so only FFC actually varies here.
FFC_FORMATS = {"ppr": "ppr", "half_ppr": "half-ppr", "standard": "standard"}
SCORING_FORMATS = tuple(FFC_FORMATS)

# FFC is real drafts from the last 7 days; ESPN is a season-long average over a
# more casual pool. Lean on FFC, but keep ESPN in the blend so a thin FFC
# sample on a deep-bench player doesn't swing the consensus on its own.
FFC_WEIGHT = 0.6

CACHE_TTL = 6 * 3600
# Bump when the cached record shape changes. Without this, a deploy that adds a
# field keeps reading old-shaped entries for the whole TTL and silently drops
# whatever the new field fed (this cost us the entire DEF match once already).
CACHE_VERSION = 2
ESPN_PAGE_SIZE = 200
ESPN_MAX_PLAYERS = 400
DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# FFC's position labels differ from Sleeper's for kickers.
FFC_POSITION_ALIAS = {"PK": "K", "DST": "DEF", "D/ST": "DEF"}


def _espn_filter(limit: int, offset: int) -> str:
    return json.dumps(
        {
            "players": {
                "limit": limit,
                "offset": offset,
                "sortDraftRanks": {
                    "sortPriority": 1,
                    "sortAsc": True,
                    "value": "PPR",
                },
            }
        }
    )


def _season_totals(stats: list[dict], season: int) -> tuple[float | None, float | None]:
    """(this season's projection, last season's actual) from ESPN's stats array.

    Season totals are the entries with statSplitTypeId == 0 and
    scoringPeriodId == 0; statSourceId 1 is a projection, 0 is an actual.
    Everything else in that array is a per-week row.
    """
    projected = prior_actual = None
    for s in stats or []:
        if s.get("statSplitTypeId") != 0 or s.get("scoringPeriodId") != 0:
            continue
        total = s.get("appliedTotal")
        if total is None:
            continue
        if s.get("statSourceId") == 1 and s.get("seasonId") == season:
            projected = float(total)
        elif s.get("statSourceId") == 0 and s.get("seasonId") == season - 1:
            prior_actual = float(total)
    return projected, prior_actual


async def fetch_espn_draft_data(season: int) -> dict[str, dict]:
    """espn_id → {adp, auction_value, percent_owned, season_proj, prior_actual}."""
    key = f"espnadp:v{CACHE_VERSION}:{season}"
    cached = await cache_get(key)
    if cached is not None:
        return cached

    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for offset in range(0, ESPN_MAX_PLAYERS, ESPN_PAGE_SIZE):
                resp = await client.get(
                    ESPN_URL.format(season=season),
                    params={"view": "kona_player_info"},
                    headers={"x-fantasy-filter": _espn_filter(ESPN_PAGE_SIZE, offset)},
                )
                resp.raise_for_status()
                players = resp.json().get("players") or []
                if not players:
                    break
                for entry in players:
                    p = entry.get("player") or {}
                    espn_id = str(p.get("id") or "")
                    if not espn_id:
                        continue
                    own = p.get("ownership") or {}
                    adp = own.get("averageDraftPosition")
                    auction = own.get("auctionValueAverage")
                    projected, prior_actual = _season_totals(p.get("stats"), season)
                    out[espn_id] = {
                        # ESPN reports 0 for never-drafted players — that's a
                        # missing value, not pick zero.
                        "adp": float(adp) if adp else None,
                        "auction_value": float(auction) if auction else None,
                        "percent_owned": float(own.get("percentOwned") or 0) or None,
                        "season_proj": projected,
                        "prior_actual": prior_actual,
                    }
    except (httpx.HTTPError, ValueError, KeyError):
        logger.warning("ESPN draft data unavailable for %s", season, exc_info=True)
        return {}

    if out:
        await cache_set(key, out, CACHE_TTL)
    return out


async def fetch_ffc_adp(scoring: str, season: int) -> dict[str, dict]:
    """normalized_name → {adp, stdev, high, low, bye, times_drafted, position}."""
    fmt = FFC_FORMATS.get(scoring)
    if fmt is None:
        return {}

    key = f"ffcadp:v{CACHE_VERSION}:{season}:{scoring}"
    cached = await cache_get(key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                FFC_URL.format(fmt=fmt), params={"teams": 12, "year": season}
            )
            resp.raise_for_status()
            rows = resp.json().get("players") or []
    except (httpx.HTTPError, ValueError):
        logger.warning("FFC ADP unavailable for %s %s", season, scoring)
        return {}

    out: dict[str, dict] = {}
    for row in rows:
        name = row.get("name")
        adp = row.get("adp")
        if not name or adp is None:
            continue
        position = (row.get("position") or "").upper()
        out[normalize_name(name)] = {
            "adp": float(adp),
            "stdev": float(row.get("stdev") or 0) or None,
            "high": row.get("high"),
            "low": row.get("low"),
            "bye": row.get("bye"),
            "times_drafted": row.get("times_drafted"),
            # FFC calls kickers PK; the rest of the app calls them K.
            "position": FFC_POSITION_ALIAS.get(position, position) or None,
            "team": (row.get("team") or "").upper() or None,
        }
    if out:
        await cache_set(key, out, CACHE_TTL)
    return out


def _consensus(espn_adp: float | None, ffc_adp: float | None) -> float | None:
    """Weighted blend of the two ADP sources; whichever exists if only one does."""
    if espn_adp is not None and ffc_adp is not None:
        return round(FFC_WEIGHT * ffc_adp + (1 - FFC_WEIGHT) * espn_adp, 2)
    return ffc_adp if ffc_adp is not None else espn_adp


async def _name_lookup(db: AsyncSession) -> tuple[dict, dict, dict]:
    """Build the maps used to resolve an FFC row to our canonical player id.

    FFC identifies skill players by name only, so we match on name+position
    first — that disambiguates the genuinely common case of two players sharing
    a normalized name at different positions.

    Defenses need their own path: FFC calls them "Denver Defense" while Sleeper
    stores them under the bare team code ("DEN"), so no name match is ever
    possible. Both agree on the team abbreviation, so that's the join.
    """
    rows = (
        await db.execute(
            select(Player.id, Player.full_name, Player.position, Player.team).where(
                Player.position.in_(DRAFTABLE_POSITIONS)
            )
        )
    ).all()
    by_name_pos: dict[tuple[str, str], str] = {}
    by_name: dict[str, str] = {}
    def_by_team: dict[str, str] = {}
    ambiguous: set[str] = set()
    for pid, full_name, position, team in rows:
        if position == "DEF" and team:
            def_by_team.setdefault(team.upper(), pid)
            continue
        if not full_name:
            continue
        key = normalize_name(full_name)
        if position:
            by_name_pos.setdefault((key, position), pid)
        if key in by_name:
            ambiguous.add(key)
        else:
            by_name[key] = pid
    for key in ambiguous:
        by_name.pop(key, None)  # too risky to guess without a position
    return by_name_pos, by_name, def_by_team


async def sync_draft_profiles(db: AsyncSession, season: int) -> int:
    """Refresh player_draft_profiles for every scoring format. Returns rows written."""
    espn_data = await fetch_espn_draft_data(season)
    espn_map = await espn_to_sleeper_map(db)
    by_name_pos, by_name, def_by_team = await _name_lookup(db)

    # ESPN keyed by our canonical sleeper id
    espn_by_player: dict[str, dict] = {}
    for espn_id, payload in espn_data.items():
        pid = espn_map.get(espn_id)
        if pid:
            espn_by_player[pid] = payload

    existing = {
        (row.player_id, row.scoring): row
        for row in (
            await db.execute(
                select(PlayerDraftProfile).where(PlayerDraftProfile.season == season)
            )
        )
        .scalars()
        .all()
    }

    written = 0
    for scoring in SCORING_FORMATS:
        ffc = await fetch_ffc_adp(scoring, season)
        unmatched: list[str] = []

        ffc_by_player: dict[str, dict] = {}
        for name_key, payload in ffc.items():
            position = payload.get("position") or ""
            if position == "DEF":
                pid = def_by_team.get(payload.get("team") or "")
            else:
                pid = by_name_pos.get((name_key, position)) or by_name.get(name_key)
            if pid is None:
                unmatched.append(name_key)
                continue
            ffc_by_player[pid] = payload

        if unmatched:
            # Surfaced rather than swallowed — a name-match regression should be
            # visible in the logs, not silently thin out the board.
            logger.warning(
                "FFC %s: %d players unmatched (e.g. %s)",
                scoring,
                len(unmatched),
                ", ".join(sorted(unmatched)[:5]),
            )

        for pid in set(espn_by_player) | set(ffc_by_player):
            e = espn_by_player.get(pid) or {}
            f = ffc_by_player.get(pid) or {}
            adp_espn = e.get("adp")
            adp_ffc = f.get("adp")
            if adp_espn is None and adp_ffc is None:
                continue  # undrafted in both pools — not a draftable player

            profile = existing.get((pid, scoring))
            if profile is None:
                profile = PlayerDraftProfile(
                    player_id=pid, season=season, scoring=scoring
                )
                db.add(profile)
                existing[(pid, scoring)] = profile

            profile.adp_espn = adp_espn
            profile.adp_ffc = adp_ffc
            profile.adp_consensus = _consensus(adp_espn, adp_ffc)
            profile.adp_stdev = f.get("stdev")
            profile.adp_high = f.get("high")
            profile.adp_low = f.get("low")
            profile.times_drafted = f.get("times_drafted")
            profile.bye_week = f.get("bye")
            profile.auction_value = e.get("auction_value")
            profile.percent_owned = e.get("percent_owned")
            profile.espn_season_proj = e.get("season_proj")
            profile.prior_season_actual = e.get("prior_actual")
            written += 1

            if written % 500 == 0:
                await db.flush()

    await db.commit()
    logger.info("Draft profile sync: %d rows for season %s", written, season)
    return written
