"""Player news ingestion from ESPN's public NFL feed.

In August the draft-relevant information isn't in last season's box scores —
it's in camp reports, depth-chart moves, holdouts, and soft-tissue injuries. A
ranking that updates weekly is stale by the time you're on the clock.

Tagging is exact rather than fuzzy: each article carries `categories` entries
of type "athlete" whose `athleteId` is an ESPN player id, which is the same ID
space as `Player.espn_id`. So a story maps to players by join, not by scraping
names out of the headline.
"""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerNews
from app.utils.player_id_map import espn_to_sleeper_map

logger = logging.getLogger(__name__)

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
FEED_LIMIT = 50
# Keep the table from growing without bound; the draft only cares about now.
MAX_ARTICLES_PER_SYNC = 200


def _published(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _article_url(article: dict) -> str | None:
    web = ((article.get("links") or {}).get("web") or {}).get("href")
    return web or (article.get("links") or {}).get("api", {}).get("news", {}).get("href")


async def fetch_news(limit: int = FEED_LIMIT) -> list[dict]:
    """Raw articles from ESPN. Empty list rather than an exception on failure."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(NEWS_URL, params={"limit": limit})
            resp.raise_for_status()
            return resp.json().get("articles") or []
    except (httpx.HTTPError, ValueError):
        logger.warning("ESPN news feed unavailable", exc_info=True)
        return []


async def sync_news(db: AsyncSession, limit: int = FEED_LIMIT) -> int:
    """Store news items tagged to players we know. Returns rows inserted."""
    articles = await fetch_news(limit)
    if not articles:
        return 0

    espn_map = await espn_to_sleeper_map(db)
    if not espn_map:
        logger.warning("No espn_id crosswalk yet — news cannot be tagged")
        return 0

    existing = {
        (player_id, url)
        for player_id, url in (
            await db.execute(select(PlayerNews.player_id, PlayerNews.url))
        ).all()
    }

    inserted = 0
    for article in articles[:MAX_ARTICLES_PER_SYNC]:
        url = _article_url(article)
        headline = article.get("headline")
        if not url or not headline:
            continue

        published = _published(article.get("published"))
        summary = article.get("description")
        category = article.get("type")

        for cat in article.get("categories") or []:
            if cat.get("type") != "athlete":
                continue
            athlete_id = cat.get("athleteId") or (cat.get("athlete") or {}).get("id")
            if athlete_id is None:
                continue
            player_id = espn_map.get(str(athlete_id))
            if player_id is None:
                continue  # not a fantasy-relevant player we track
            key = (player_id, url)
            if key in existing:
                continue
            existing.add(key)
            db.add(
                PlayerNews(
                    player_id=player_id,
                    headline=headline[:500],
                    summary=summary,
                    source="ESPN",
                    url=url[:1000],
                    category=category,
                    published_at=published,
                )
            )
            inserted += 1

    await db.commit()
    logger.info("News sync: %d new items", inserted)
    return inserted


async def recent_news_by_player(
    db: AsyncSession, player_ids: list[str], per_player: int = 2
) -> dict[str, list[dict]]:
    """player_id → most recent news items, for decorating the draft board."""
    if not player_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(PlayerNews)
                .where(PlayerNews.player_id.in_(player_ids))
                .order_by(PlayerNews.published_at.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, list[dict]] = {}
    for row in rows:
        bucket = out.setdefault(row.player_id, [])
        if len(bucket) >= per_player:
            continue
        bucket.append(
            {
                "headline": row.headline,
                "summary": row.summary,
                "url": row.url,
                "source": row.source,
                "published_at": row.published_at.isoformat()
                if row.published_at
                else None,
            }
        )
    return out
