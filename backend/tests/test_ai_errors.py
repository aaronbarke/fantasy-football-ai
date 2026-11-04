"""A failed Claude call must come back as a readable JSON error the browser can
see — not a bare 500 without CORS headers, which the page only reports as
"Failed to fetch"."""

import anthropic
import httpx
import pytest

from app.main import app

ORIGIN = "http://localhost:3000"
_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, code: int):
    return cls("upstream said no", response=httpx.Response(code, request=_REQ), body=None)


@pytest.fixture
async def raising_client():
    """The real app plus one throwaway route that raises whatever the test
    stores in `box`, so the handler and middleware order are exercised as
    deployed."""
    box: dict = {}

    async def boom():
        raise box["exc"]

    path = "/api/_test_ai_error"
    app.add_api_route(path, boom, methods=["POST"])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

            async def call(exc):
                box["exc"] = exc
                return await c.post(path, headers={"Origin": ORIGIN})

            yield call
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != path]


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(anthropic.AuthenticationError, 401),
        _status_error(anthropic.BadRequestError, 400),  # e.g. credit balance too low
        _status_error(anthropic.NotFoundError, 404),  # retired model id
        anthropic.APIConnectionError(request=_REQ),
    ],
)
async def test_unavailable_errors_are_readable_503s(raising_client, exc):
    resp = await raising_client(exc)
    assert resp.status_code == 503
    assert resp.json()["detail"] == (
        "The AI service is unavailable right now — please try again later."
    )
    assert resp.headers.get("access-control-allow-origin") == ORIGIN
    # Upstream details stay in the server log.
    assert "upstream said no" not in resp.text


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(anthropic.RateLimitError, 429),
        _status_error(anthropic.InternalServerError, 529),  # overloaded
        anthropic.APITimeoutError(request=_REQ),
    ],
)
async def test_transient_errors_say_try_again(raising_client, exc):
    resp = await raising_client(exc)
    assert resp.status_code == 503
    assert "busy" in resp.json()["detail"]
    assert resp.headers.get("access-control-allow-origin") == ORIGIN
