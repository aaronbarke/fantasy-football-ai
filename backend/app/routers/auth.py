import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import AvailablePlayer, LeagueConnection, Matchup, Roster, User
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.utils.security import (
    DEMO_EMAIL,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _tokens_for(user: User) -> TokenResponse:
    uid = str(user.id)
    return TokenResponse(
        access_token=create_access_token(uid),
        refresh_token=create_refresh_token(uid),
    )


def _unusable_password_hash() -> str:
    """A hash of a random secret — satisfies the NOT NULL column for accounts
    that authenticate via Google/demo and never use a password."""
    return hash_password(secrets.token_urlsafe(32))


async def _get_or_create_user(db: AsyncSession, email: str) -> User:
    email = email.lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        user = User(email=email, password_hash=_unusable_password_hash())
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _ensure_demo_league(db: AsyncSession, demo: User) -> None:
    """Seed the demo account with a snapshot of a populated league so it lands
    on a fully-loaded app, not the connect screen. Clones the most recently
    synced league that actually has drafted rosters (snapshot only — never
    copies private credentials). No-op if the demo already has a league or no
    populated source exists."""
    has_league = (
        await db.execute(
            select(LeagueConnection.id).where(LeagueConnection.user_id == demo.id)
        )
    ).first()
    if has_league:
        return

    candidates = (
        (
            await db.execute(
                select(LeagueConnection)
                .where(LeagueConnection.user_id != demo.id)
                .order_by(LeagueConnection.last_synced_at.desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    source = None
    source_rosters: list[Roster] = []
    for c in candidates:
        rosters = (
            (await db.execute(select(Roster).where(Roster.connection_id == c.id)))
            .scalars()
            .all()
        )
        if any(r.players for r in rosters):  # prefer a drafted, populated league
            source, source_rosters = c, rosters
            break
    if source is None:
        return

    clone = LeagueConnection(
        user_id=demo.id,
        platform=source.platform,
        platform_user_id=None,
        league_id=source.league_id,
        league_name=source.league_name,
        season=source.season,
        scoring_type=source.scoring_type,
        scoring_settings=source.scoring_settings,
        roster_positions=source.roster_positions,
        credentials=None,  # never copy private cookies into the shared demo
        team_id=source.team_id,
        last_synced_at=source.last_synced_at,
    )
    db.add(clone)
    await db.flush()  # assign clone.id

    for r in source_rosters:
        db.add(
            Roster(
                connection_id=clone.id,
                team_id=r.team_id,
                owner_name=r.owner_name,
                players=r.players,
                starters=r.starters,
                wins=r.wins,
                losses=r.losses,
                ties=r.ties,
                points_for=r.points_for,
                points_against=r.points_against,
            )
        )
    for m in (
        (await db.execute(select(Matchup).where(Matchup.connection_id == source.id)))
        .scalars()
        .all()
    ):
        db.add(
            Matchup(
                connection_id=clone.id,
                week=m.week,
                team_a_id=m.team_a_id,
                team_b_id=m.team_b_id,
                team_a_points=m.team_a_points,
                team_b_points=m.team_b_points,
            )
        )
    for a in (
        (
            await db.execute(
                select(AvailablePlayer).where(AvailablePlayer.connection_id == source.id)
            )
        )
        .scalars()
        .all()
    ):
        db.add(
            AvailablePlayer(
                connection_id=clone.id,
                player_id=a.player_id,
                trending_count=a.trending_count,
                recent_ppr_avg=a.recent_ppr_avg,
            )
        )
    await db.commit()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    return _tokens_for(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _tokens_for(user)


@router.post("/google", response_model=TokenResponse)
async def google_auth(body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Verify a Google ID token, then find-or-create the matching user.

    We validate the token via Google's tokeninfo endpoint (checks the signature
    and expiry server-side at Google), then confirm the audience matches our
    configured client ID and the email is verified. No client secret needed.
    """
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google sign-in is not configured on the server.",
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                GOOGLE_TOKENINFO_URL, params={"id_token": body.credential}
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not reach Google to verify sign-in."
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google token.")

    claims = resp.json()
    if claims.get("aud") != settings.google_client_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google token audience mismatch.")
    if str(claims.get("email_verified", "")).lower() != "true":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google email is not verified.")
    email = claims.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google token has no email.")

    user = await _get_or_create_user(db, email)
    return _tokens_for(user)


@router.post("/demo", response_model=TokenResponse)
async def demo_login(db: AsyncSession = Depends(get_db)):
    """One-click login to a shared demo account — no signup required. Seeds a
    populated league snapshot so the demo lands on a fully-loaded app."""
    user = await _get_or_create_user(db, DEMO_EMAIL)
    try:
        await _ensure_demo_league(db, user)
    except Exception:
        logger.exception("Demo league seed failed")
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    import uuid

    user_id = decode_token(body.refresh_token, expected_type="refresh")
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return _tokens_for(user)
