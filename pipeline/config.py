"""Settings read from environment variables (and a local .env file in development)."""

import csv
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Fills os.environ from .env if the file exists. Real environment variables win,
# so GitHub Actions / Streamlit secrets override anything in a stray .env.
load_dotenv(PROJECT_ROOT / ".env")

WATCHLIST_PATH = PROJECT_ROOT / "data" / "watchlist.csv"
CATEGORY_MAP_PATH = PROJECT_ROOT / "data" / "category_map.csv"

NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"

# Backfill source: one fund's full history as JSON. Community-run, not official, so the
# backfill never overwrites a NAV that came from AMFI's own file.
MFAPI_URL = "https://api.mfapi.in/mf"
MFAPI_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "mfapi"

WATCHLIST_CATEGORIES = ("large-cap", "flexi-cap", "mid-cap", "index", "debt")

# raw_nav keeps each day's file for this many days. A full file is ~1.5 MB of text a day,
# which would fill a 500 MB free hosted database within months; the clean tables keep the
# history, and a month of raw lines is enough to investigate any recent bad load.
RAW_RETENTION_DAYS = 30


def read_watchlist(path=WATCHLIST_PATH) -> dict[int, str]:
    """Return {scheme_code: category}. Fails loudly on a typo rather than skipping a fund."""
    watchlist = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            code, category = int(row["scheme_code"]), row["category"].strip()
            if code in watchlist:
                raise ValueError(f"{path}: scheme_code {code} is listed twice")
            if category not in WATCHLIST_CATEGORIES:
                raise ValueError(f"{path}: unknown category {category!r} for {code}")
            watchlist[code] = category
    return watchlist


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return url
