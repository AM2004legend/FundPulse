"""One daily run: download -> save raw -> transform -> load, logged in pipeline_runs.

Usage: python -m pipeline.run   (exit code 0 = success, 1 = failure)
"""

import logging
import sys

from pipeline.db import get_connection
from pipeline.extract import download_nav_file
from pipeline.load import finish_run, load_day, save_raw_lines, start_run
from pipeline.transform import parse_nav_lines

logger = logging.getLogger("pipeline.run")


def run(fetch=download_nav_file, database_url: str | None = None) -> int:
    """Run the pipeline once and return its run_id. Re-raises any error after logging it.

    `fetch` returns the file's lines; tests pass a function that returns the fixture.
    """
    with get_connection(database_url, autocommit=True) as conn:
        # Committed straight away, so even a crash below leaves a visible 'running' row.
        run_id = start_run(conn)
        logger.info("Run %d started", run_id)

        try:
            lines = fetch()
            save_raw_lines(conn, run_id, lines)  # own transaction: kept even if later steps fail
            result = parse_nav_lines(lines)
            load_day(conn, run_id, result)  # one transaction: all or nothing
        except Exception as exc:
            finish_run(conn, run_id, "failed", error=f"{type(exc).__name__}: {exc}")
            raise

        finish_run(
            conn,
            run_id,
            "success",
            rows_loaded=len(result.clean),
            rows_quarantined=len(result.quarantined),
        )
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
    except Exception:
        logger.exception("Pipeline run failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
