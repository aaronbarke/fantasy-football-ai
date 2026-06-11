"""NFL team data: stadium coordinates, dome flags, and name mappings."""

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Stadium coordinates for weather lookups. dome=True includes fixed and retractable
# roofs that are typically closed.
STADIUMS: dict[str, dict] = {
    "ARI": {"lat": 33.5276, "lon": -112.2626, "dome": True},
    "ATL": {"lat": 33.7554, "lon": -84.4010, "dome": True},
    "BAL": {"lat": 39.2780, "lon": -76.6227, "dome": False},
    "BUF": {"lat": 42.7738, "lon": -78.7870, "dome": False},
    "CAR": {"lat": 35.2258, "lon": -80.8528, "dome": False},
    "CHI": {"lat": 41.8623, "lon": -87.6167, "dome": False},
    "CIN": {"lat": 39.0955, "lon": -84.5161, "dome": False},
    "CLE": {"lat": 41.5061, "lon": -81.6995, "dome": False},
    "DAL": {"lat": 32.7473, "lon": -97.0945, "dome": True},
    "DEN": {"lat": 39.7439, "lon": -105.0201, "dome": False},
    "DET": {"lat": 42.3400, "lon": -83.0456, "dome": True},
    "GB": {"lat": 44.5013, "lon": -88.0622, "dome": False},
    "HOU": {"lat": 29.6847, "lon": -95.4107, "dome": True},
    "IND": {"lat": 39.7601, "lon": -86.1639, "dome": True},
    "JAX": {"lat": 30.3239, "lon": -81.6373, "dome": False},
    "KC": {"lat": 39.0489, "lon": -94.4839, "dome": False},
    "LAC": {"lat": 33.9535, "lon": -118.3392, "dome": True},
    "LAR": {"lat": 33.9535, "lon": -118.3392, "dome": True},
    "LV": {"lat": 36.0909, "lon": -115.1833, "dome": True},
    "MIA": {"lat": 25.9580, "lon": -80.2389, "dome": False},
    "MIN": {"lat": 44.9735, "lon": -93.2575, "dome": True},
    "NE": {"lat": 42.0909, "lon": -71.2643, "dome": False},
    "NO": {"lat": 29.9511, "lon": -90.0812, "dome": True},
    "NYG": {"lat": 40.8128, "lon": -74.0742, "dome": False},
    "NYJ": {"lat": 40.8128, "lon": -74.0742, "dome": False},
    "PHI": {"lat": 39.9008, "lon": -75.1675, "dome": False},
    "PIT": {"lat": 40.4468, "lon": -80.0158, "dome": False},
    "SEA": {"lat": 47.5952, "lon": -122.3316, "dome": False},
    "SF": {"lat": 37.4032, "lon": -121.9697, "dome": False},
    "TB": {"lat": 27.9759, "lon": -82.5033, "dome": False},
    "TEN": {"lat": 36.1665, "lon": -86.7713, "dome": False},
    "WAS": {"lat": 38.9077, "lon": -76.8645, "dome": False},
}

# The Odds API uses full team names
TEAM_NAME_TO_ABBR: dict[str, str] = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Las Vegas Raiders": "LV",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

# ESPN team IDs for injury endpoints
ESPN_TEAM_IDS: dict[str, int] = {
    "ATL": 1, "BUF": 2, "CHI": 3, "CIN": 4, "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8,
    "GB": 9, "TEN": 10, "IND": 11, "KC": 12, "LV": 13, "LAR": 14, "MIA": 15, "MIN": 16,
    "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "ARI": 22, "PIT": 23, "LAC": 24,
    "SF": 25, "SEA": 26, "TB": 27, "WAS": 28, "CAR": 29, "JAX": 30, "BAL": 33, "HOU": 34,
}
