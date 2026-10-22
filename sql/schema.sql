-- FundPulse schema. Safe to re-run: every statement uses IF NOT EXISTS.
-- Order matters: tables that are referenced by foreign keys come first.

-- Metadata: one row per pipeline run.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_type         TEXT NOT NULL DEFAULT 'daily' CHECK (run_type IN ('daily', 'backfill')),
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_loaded      INTEGER NOT NULL DEFAULT 0,
    rows_quarantined INTEGER NOT NULL DEFAULT 0,
    error            TEXT,  -- why the run failed (exception or failed quality checks)
    warnings         TEXT   -- quality warnings that did not fail the run
);

-- Raw layer: every line of the downloaded file, exactly as received. Kept for the last
-- RAW_RETENTION_DAYS (pipeline/config.py) only; the clean tables keep the full history.
CREATE TABLE IF NOT EXISTS raw_nav (
    run_id    BIGINT NOT NULL REFERENCES pipeline_runs (run_id),
    line_no   INTEGER NOT NULL,
    raw_line  TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, line_no)
);

-- Clean layer: one row per scheme. A fund has several schemes (Direct/Regular x Growth/IDCW)
-- that share a scheme_name, so plan_type + option_type are needed to tell them apart.
CREATE TABLE IF NOT EXISTS schemes (
    scheme_code INTEGER PRIMARY KEY,
    scheme_name TEXT NOT NULL,
    plan_type   TEXT,  -- e.g. 'Direct Plan'; NULL when the file leaves it empty
    option_type TEXT,  -- e.g. 'Growth', 'IDCW Option'; free text in the file
    fund_house  TEXT,
    category    TEXT,  -- canonical AMFI category (data/category_map.csv)
    isin_growth TEXT
);

-- The ~30 funds we compute metrics for, synced from data/watchlist.csv on every run.
-- category is our own short label (large-cap, index, ...) used by the dashboard.
CREATE TABLE IF NOT EXISTS watchlist (
    scheme_code INTEGER PRIMARY KEY REFERENCES schemes (scheme_code),
    category    TEXT NOT NULL
);

-- Clean layer: one NAV per scheme per date. The primary key is what makes upserts idempotent.
CREATE TABLE IF NOT EXISTS nav_history (
    scheme_code INTEGER NOT NULL REFERENCES schemes (scheme_code),
    nav_date    DATE NOT NULL,
    nav         NUMERIC(16, 8) NOT NULL CHECK (nav > 0),  -- some AMFI NAVs have 8 decimals
    PRIMARY KEY (scheme_code, nav_date)
);

-- Rows we could not use, kept with the reason instead of being silently dropped.
CREATE TABLE IF NOT EXISTS quarantine (
    run_id   BIGINT NOT NULL REFERENCES pipeline_runs (run_id),
    raw_line TEXT NOT NULL,
    reason   TEXT NOT NULL
);
