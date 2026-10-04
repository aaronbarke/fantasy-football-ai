import os

# Use in-memory sqlite for tests, before app modules import settings
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ENABLE_SCHEDULER"] = "false"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_team_results_fetch(monkeypatch):
    """The DEF/kicker models pull team scores from nflverse; tests run
    offline with league-average teams unless a test supplies results."""
    from app.services import projection_service

    async def _none(seasons):
        return []

    monkeypatch.setattr(projection_service, "get_team_results", _none)

    async def _no_passing(season, week):
        return {}

    monkeypatch.setattr(projection_service, "get_external_passing", _no_passing)
