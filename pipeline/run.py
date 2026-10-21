"""One daily run: download -> save raw -> transform -> load -> checks, logged in pipeline_runs.

Usage: python -m pipeline.run   (exit code 0 = success, 1 = failure)
"""

import logging
import sys
from datetime import date

from pipeline.checks import run_checks, today_in_india
from pipeline.config import read_watchlist
from pipeline.db import get_connection
from pipeline.extract import download_nav_file
from pipeline.load import finish_run, load_day, save_raw_lines, start_run, sync_watchlist
from pipeline.transform import parse_nav_lines

logger = logging.getLogger("pipeline.run")


class QualityCheckError(Exception):
    """One or more data-quality checks failed. The data was still loaded."""


def run(
    fetch=download_nav_file,
    database_url: str | None = None,
    watchlist: dict[int, str] | None = None,
    today: date | None = None,
) -> int:
    """Run the pipeline once and return its run_id. Re-raises any error after logging it.

    `fetch`, `watchlist` and `today` can be replaced in tests (fixture, small list, fixed date).
    """
    with get_connection(database_url, autocommit=True) as conn:
        # Committed straight away, so even a crash below leaves a visible 'running' row.
        run_id = start_run(conn)
        logger.info("Run %d started", run_id)

        try:
            watchlist = read_watchlist() if watchlist is None else watchlist
            lines = fetch()
            save_raw_lines(conn, run_id, lines)  # own transaction: kept even if later steps fail
            result = parse_nav_lines(lines)
            load_day(conn, run_id, result)  # one transaction: all or nothing
            sync_watchlist(conn, watchlist)
            results = run_checks(conn, run_id, result, watchlist, today or today_in_india())
        except Exception as exc:
            finish_run(conn, run_id, "failed", error=f"{type(exc).__name__}: {exc}")
            raise

        for r in results:
            label = "PASS" if r.passed else r.severity.upper()
            logger.log(
                logging.INFO if r.passed else logging.WARNING, "%s %s: %s", label, r.name, r.message
            )

        failures = [r for r in results if not r.passed and r.severity == "fail"]
        warnings = [r for r in results if not r.passed and r.severity == "warn"]
        error = "; ".join(f"{r.name}: {r.message}" for r in failures) or None
        finish_run(
            conn,
            run_id,
            "failed" if failures else "success",
            rows_loaded=len(result.clean),
            rows_quarantined=len(result.quarantined),
            error=error,
            warnings="; ".join(f"{r.name}: {r.message}" for r in warnings) or None,
        )
        if failures:
            raise QualityCheckError(error)

        logger.info(
            "Run %d succeeded: %d lines, %d rows loaded, %d quarantined, %d duplicates dropped",
            run_id,
            len(lines),
            len(result.clean),
            len(result.quarantined),
            result.duplicates_dropped,
        )
        return run_id


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        run()
    except QualityCheckError as exc:
        logger.error("Run failed quality checks (data was loaded): %s", exc)
        return 1
    except Exception:
        logger.exception("Pipeline run failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
