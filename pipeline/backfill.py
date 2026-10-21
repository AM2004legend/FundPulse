"""One-time history load for the watchlist funds, from mfapi.in.

Usage: python -m pipeline.backfill [--years 3] [--refresh]

For each fund: fetch its history (cached in data/cache/mfapi/), turn the JSON into the same
";"-separated lines as AMFI's daily file, and run those lines through the normal parser —
so history gets exactly the same validation and quarantine rules as the daily data.
Each fund is loaded in its own transaction: one failing fund doesn't undo the others.
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

from pipeline.checks import today_in_india
from pipeline.config import MFAPI_CACHE_DIR, MFAPI_URL, read_watchlist
from pipeline.db import get_connection
from pipeline.extract import fetch_with_retries
from pipeline.load import finish_run, insert_missing_navs, start_run
from pipeline.transform import parse_nav_lines

logger = logging.getLogger("pipeline.backfill")

PAUSE_SECONDS = 1  # between network requests: be polite to a free community service
NAVALL_HEADER = (
    "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;"
    "Plan;Option;Net Asset Value;Date"
)


class BackfillError(Exception):
    """One or more funds could not be backfilled (the others were still loaded)."""


def fetch_history(
    scheme_code: int,
    session=None,
    sleep=time.sleep,
    cache_dir: Path = MFAPI_CACHE_DIR,
    refresh: bool = False,
) -> tuple[dict, bool]:
    """Return (mfapi JSON, came_from_cache). Only a valid answer is ever written to the cache."""
    path = cache_dir / f"{scheme_code}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8")), True

    body = fetch_with_retries(f"{MFAPI_URL}/{scheme_code}", session, sleep)
    data = json.loads(body)
    if not data.get("data") or data.get("meta", {}).get("scheme_code") != scheme_code:
        raise BackfillError(f"mfapi.in returned no NAV history for {scheme_code}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return data, False


def to_navall_lines(data: dict, since: date) -> list[str]:
    """Adapter: mfapi JSON -> lines in NAVAll.txt format (oldest first), dropping dates < since.

    A date that can't be read is passed through unchanged so the parser quarantines it.
    """
    meta = data["meta"]
    name = meta["scheme_name"].replace(";", ",")
    isin = meta.get("isin_growth") or "-"
    lines = [
        NAVALL_HEADER,
        f"{meta['scheme_type']}({meta['scheme_category']})",
        meta["fund_house"],
    ]
    for point in reversed(data["data"]):  # mfapi lists newest first
        try:
            day = datetime.strptime(point["date"], "%d-%m-%Y").date()
        except ValueError:
            day = None
        if day is not None and day < since:
            continue
        day_text = day.strftime("%d-%b-%Y") if day else point["date"]
        lines.append(f"{meta['scheme_code']};{isin};-;{name};;;{point['nav']};{day_text}")
    return lines


def years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year - years, day=28)


def backfill(
    watchlist: dict[int, str] | None = None,
    years: int = 3,
    refresh: bool = False,
    database_url: str | None = None,
    cache_dir: Path = MFAPI_CACHE_DIR,
    today: date | None = None,
    session=None,
    sleep=time.sleep,
) -> int:
    """Backfill every watchlist fund and return the run_id."""
    watchlist = read_watchlist() if watchlist is None else watchlist
    since = years_before(today or today_in_india(), years)
    inserted = quarantined = 0
    failures, warnings = [], []

    with get_connection(database_url, autocommit=True) as conn:
        run_id = start_run(conn, run_type="backfill")
        logger.info("Backfill run %d: %d funds, NAVs since %s", run_id, len(watchlist), since)
        try:
            known = {row[0] for row in conn.execute("SELECT scheme_code FROM schemes")}
            for code in watchlist:
                if code not in known:
                    failures.append(
                        f"{code}: not in schemes yet - run `python -m pipeline.run` first"
                    )
                    logger.error(failures[-1])
                    continue
                try:
                    data, from_cache = fetch_history(code, session, sleep, cache_dir, refresh)
                    if not from_cache:
                        sleep(PAUSE_SECONDS)
                    result = parse_nav_lines(to_navall_lines(data, since))
                    stats = insert_missing_navs(conn, run_id, result)
                except Exception as exc:
                    failures.append(f"{code}: {type(exc).__name__}: {exc}")
                    logger.error(failures[-1])
                    continue

                inserted += stats.inserted
                quarantined += len(result.quarantined)
                if stats.mismatched:
                    warnings.append(
                        f"{code}: {stats.mismatched} date(s) differ from the stored NAV, "
                        "kept the stored value"
                    )
                logger.info(
                    "%d: %d new, %d already stored, %d quarantined%s",
                    code,
                    stats.inserted,
                    stats.already_stored,
                    len(result.quarantined),
                    " (cache)" if from_cache else "",
                )
        except Exception as exc:  # e.g. the database went away: still record the failure
            finish_run(
                conn, run_id, "failed", inserted, quarantined, f"{type(exc).__name__}: {exc}"
            )
            raise

        error = "; ".join(failures) or None
        finish_run(
            conn,
            run_id,
            "failed" if failures else "success",
            rows_loaded=inserted,
            rows_quarantined=quarantined,
            error=error,
            warnings="; ".join(warnings) or None,
        )
    for w in warnings:
        logger.warning(w)
    if failures:
        raise BackfillError(error)
    logger.info(
        "Backfill run %d done: %d NAVs inserted, %d quarantined", run_id, inserted, quarantined
    )
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Load NAV history for the watchlist funds.")
    parser.add_argument("--years", type=int, default=3, help="how many years back (default 3)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and re-download")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        backfill(years=args.years, refresh=args.refresh)
    except BackfillError as exc:
        logger.error("Backfill finished with failures (other funds were loaded): %s", exc)
        return 1
    except Exception:
        logger.exception("Backfill failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
