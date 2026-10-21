"""Settings read from environment variables (and a local .env file in development)."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Fills os.environ from .env if the file exists. Real environment variables win,
# so GitHub Actions / Streamlit secrets override anything in a stray .env.
load_dotenv(PROJECT_ROOT / ".env")

WATCHLIST_PATH = PROJECT_ROOT / "data" / "watchlist.csv"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return url
