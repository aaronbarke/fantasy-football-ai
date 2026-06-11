"""Game-day weather via Open-Meteo (free, no key)."""

from datetime import datetime

import httpx

from app.utils.constants import STADIUMS

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DOME_CONDITIONS = {"temp_f": 72.0, "wind_mph": 0.0, "precipitation_pct": 0.0, "dome": True}


async def get_game_weather(home_team: str, game_time: datetime) -> dict:
    """Forecast at the home stadium for the hour closest to kickoff."""
    stadium = STADIUMS.get(home_team)
    if stadium is None:
        return {"temp_f": None, "wind_mph": None, "precipitation_pct": None, "dome": False}
    if stadium["dome"]:
        return dict(DOME_CONDITIONS)

    date_str = game_time.strftime("%Y-%m-%d")
    params = {
        "latitude": stadium["lat"],
        "longitude": stadium["lon"],
        "hourly": "temperature_2m,windspeed_10m,precipitation_probability",
        "start_date": date_str,
        "end_date": date_str,
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return {"temp_f": None, "wind_mph": None, "precipitation_pct": None, "dome": False}

    # Pick the hour closest to kickoff
    target = game_time.replace(minute=0, second=0, microsecond=0)
    idx = min(
        range(len(times)),
        key=lambda i: abs(datetime.fromisoformat(times[i]) - target),
    )
    return {
        "temp_f": hourly.get("temperature_2m", [None] * len(times))[idx],
        "wind_mph": hourly.get("windspeed_10m", [None] * len(times))[idx],
        "precipitation_pct": hourly.get("precipitation_probability", [None] * len(times))[idx],
        "dome": False,
    }
