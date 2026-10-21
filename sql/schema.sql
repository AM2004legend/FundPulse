-- FundPulse schema. Safe to re-run: every statement uses IF NOT EXISTS.
-- Order matters: tables that are referenced by foreign keys come first.

-- Metadata: one row per pipeline run.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_loaded      INTEGER NOT NULL DEFAULT 0,
    rows_quarantined INTEGER NOT NULL DEFAULT 0,
    error            TEXT
);

-- Raw layer: every line of the downloaded file, exactly as received.
CREATE TABLE IF NOT EXISTS raw_nav (
    run_id    BIGINT NOT NULL REFERENCES pipeline_runs (run_id),
    line_no   INTEGER NOT NULL,
    raw_line  TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, line_no)
);

-- Clean layer: one row per scheme (fund plan).
CREATE TABLE IF NOT EXISTS schemes (
    scheme_code  INTEGER PRIMARY KEY,
    scheme_name  TEXT NOT NULL,
    fund_house   TEXT,
    category     TEXT,
    isin_growth  TEXT,
    is_watchlist BOOLEAN NOT NULL DEFAULT false
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
