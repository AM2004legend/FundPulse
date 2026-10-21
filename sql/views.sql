-- FundPulse analytics views. The dashboard reads only these, never the tables.
-- Safe to re-run: views are dropped and recreated (CREATE OR REPLACE VIEW can't remove or
-- rename columns). Apply with: python -m pipeline.db --init

DROP VIEW IF EXISTS v_pipeline_runs, v_fund_metrics, v_drawdown, v_daily_returns CASCADE;


-- One row per pipeline run, for the Pipeline health page. Times are converted to India time
-- here, in the database, which has the timezone rules built in.
CREATE VIEW v_pipeline_runs AS
SELECT
    run_id,
    run_type,
    status,
    started_at AT TIME ZONE 'Asia/Kolkata'                       AS started_at_ist,
    finished_at AT TIME ZONE 'Asia/Kolkata'                      AS finished_at_ist,
    round(EXTRACT(EPOCH FROM finished_at - started_at)::numeric, 1) AS duration_seconds,
    rows_loaded,
    rows_quarantined,
    error,
    warnings
FROM pipeline_runs;


-- One row per fund per NAV date: the change since the fund's previous NAV.
-- LAG looks at the previous row *of the same fund* (PARTITION BY) in date order, so a
-- return across a weekend or market holiday is one step: Friday -> Monday.
CREATE VIEW v_daily_returns AS
SELECT
    scheme_code,
    nav_date,
    nav,
    LAG(nav_date) OVER w     AS prev_nav_date,
    LAG(nav) OVER w          AS prev_nav,
    nav / LAG(nav) OVER w - 1 AS daily_return  -- NULL on a fund's first date
FROM nav_history
WINDOW w AS (PARTITION BY scheme_code ORDER BY nav_date);


-- One row per fund per NAV date: how far below its highest NAV so far the fund is.
-- running_peak = MAX over every row from the fund's first date up to this one.
CREATE VIEW v_drawdown AS
SELECT
    scheme_code,
    nav_date,
    nav,
    MAX(nav) OVER w         AS running_peak,
    nav / MAX(nav) OVER w - 1 AS drawdown  -- 0 at a new peak, negative below it
FROM nav_history
WINDOW w AS (
    PARTITION BY scheme_code ORDER BY nav_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
);


-- One row per watchlist fund: the three numbers on the Compare page, all over the same
-- trailing year so funds compare fairly. The year runs from the "base" NAV (last available
-- NAV on or before latest_date - 365 days) to the fund's own latest NAV. A fund with less
-- than a year of history gets NULL metrics rather than numbers over a shorter period.
--
-- Volatility is annualised with sqrt(250) trading days for every fund. Liquid funds publish
-- on more days (~326 a year), so theirs is understated by about 14% - tiny either way.
CREATE VIEW v_fund_metrics AS
WITH latest AS (
    -- DISTINCT ON keeps the first row per fund in ORDER BY order: its newest NAV
    SELECT DISTINCT ON (scheme_code)
        scheme_code, nav_date AS latest_date, nav AS latest_nav
    FROM nav_history
    WHERE scheme_code IN (SELECT scheme_code FROM watchlist)
    ORDER BY scheme_code, nav_date DESC
),
base AS (
    -- NAVs exist only on business days, so take the last one on or before the target date
    SELECT l.*, b.nav_date AS base_date, b.nav AS base_nav
    FROM latest l
    LEFT JOIN LATERAL (
        SELECT n.nav_date, n.nav
        FROM nav_history n
        WHERE n.scheme_code = l.scheme_code
          AND n.nav_date <= l.latest_date - 365
        ORDER BY n.nav_date DESC
        LIMIT 1
    ) b ON true
),
year_returns AS (
    -- daily returns after the base date: the first one is (next NAV / base NAV - 1)
    SELECT b.scheme_code,
           STDDEV_SAMP(r.daily_return) AS daily_volatility,
           COUNT(r.daily_return)       AS n_returns
    FROM base b
    JOIN v_daily_returns r
      ON r.scheme_code = b.scheme_code
     AND r.nav_date > b.base_date
     AND r.nav_date <= b.latest_date
    GROUP BY b.scheme_code
),
year_drawdown AS (
    -- the running peak restarts at the base date, so only falls inside the year count
    SELECT scheme_code, MIN(nav / peak - 1) AS max_drawdown
    FROM (
        SELECT n.scheme_code,
               n.nav,
               MAX(n.nav) OVER (
                   PARTITION BY n.scheme_code ORDER BY n.nav_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS peak
        FROM base b
        JOIN nav_history n
          ON n.scheme_code = b.scheme_code
         AND n.nav_date >= b.base_date
         AND n.nav_date <= b.latest_date
    ) with_peaks
    GROUP BY scheme_code
)
SELECT
    w.category,
    b.scheme_code,
    s.scheme_name,
    s.plan_type,
    s.option_type,
    s.fund_house,
    b.latest_date,
    b.latest_nav,
    b.base_date                                   AS nav_1y_ago_date,
    b.base_nav                                    AS nav_1y_ago,
    b.latest_nav / b.base_nav - 1                 AS return_1y,
    yr.daily_volatility * sqrt(250::numeric)      AS volatility_1y,
    yd.max_drawdown                               AS max_drawdown_1y,
    yr.n_returns
FROM base b
JOIN watchlist w USING (scheme_code)
JOIN schemes s USING (scheme_code)
LEFT JOIN year_returns yr USING (scheme_code)
LEFT JOIN year_drawdown yd USING (scheme_code);
