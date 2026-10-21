# FundPulse — Product Requirements

## Overview
FundPulse collects Indian mutual fund NAVs (price per unit) every day, stores a clean history in
PostgreSQL, computes performance and risk metrics with SQL, and shows them on a live dashboard.

**Problem:** NAV data is public but arrives as one large raw text file a day. Comparing funds fairly
needs clean history and risk numbers (volatility, drawdown), not just the latest return.

**Audience:** recruiters/interviewers for data, analytics and backend roles. Design persona: a
student comparing a few funds on return *and* risk before a first SIP.

**Goals**
1. Pipeline runs daily with no manual steps.
2. Loads are idempotent — re-running never duplicates data.
3. Metrics computed in SQL with window functions.
4. Public dashboard.

**Success metrics:** daily logged runs with visible failures · same row count on re-run · quality
checks every load, bad rows quarantined · parser, cleaner and metrics tested · live dashboard URL.

## Data sources
| Source | Gives | Used for | Notes |
|---|---|---|---|
| AMFI daily file `https://portal.amfiindia.com/spages/NAVAll.txt` | Latest NAV of every scheme | Daily run | Official. Inspect the raw format before writing the parser. |
| AMFI historical NAV download (amfiindia.com NAV download page) | History for a fund + date range | Backfill | Max 90 days per request |
| mfapi.in `https://api.mfapi.in/mf/<scheme_code>` | Full history of one scheme as JSON (`data: [{date: DD-MM-YYYY, nav}]`, newest first) | Faster backfill | Community-run, not official; check terms; one request per scheme, cached |

**Scope:** load the whole daily file into raw/clean tables, but compute metrics only for a
**watchlist of ~30 funds** across 4–5 categories (large-cap, flexi-cap, mid-cap, index, debt).

## User stories
| # | Story | Acceptance criteria |
|---|---|---|
| 1 | Download today's file | Up to 3 retries on network error; raw lines saved with run_id |
| 2 | Parse and clean | Headings/blank lines skipped but fund house + category remembered; NAV → number; date parsed; invalid NAV (non-numeric e.g. "N.A.", or zero) → quarantine with reason; category headings normalised to one spelling |
| 3 | Load into PostgreSQL | Upsert on (scheme_code, nav_date); re-run changes nothing |
| 4 | Data-quality checks | Fail if row volume < 90% of last success, a watchlist fund lacks latest NAV, or newest date > 4 days old; warn on >20% one-day move |
| 5 | Log every run | One pipeline_runs row: start, end, rows loaded, rows quarantined, status, error |
| 6 | Compare funds in a category | 1-yr return, volatility, max drawdown; sortable |
| 7 | One fund's history | NAV line chart with date range + drawdown chart |

**Should-have:** two funds on one chart; CSV download; pipeline health page with recent runs.

**Non-goals:** investment advice/recommendations, user accounts or portfolios, intraday data,
ML predictions.

## Data model
| Table | Layer | Columns | Keys / constraints |
|---|---|---|---|
| raw_nav | Raw | run_id, line_no, raw_line, loaded_at | PK (run_id, line_no) |
| schemes | Clean | scheme_code, scheme_name, fund_house, category, isin_growth, is_watchlist | PK scheme_code |
| nav_history | Clean | scheme_code → schemes, nav_date, nav NUMERIC(16,8) | PK (scheme_code, nav_date); CHECK nav > 0 |
| quarantine | Clean | run_id, raw_line, reason | — |
| pipeline_runs | Metadata | run_id, started_at, finished_at, status, rows_loaded, rows_quarantined, error | PK run_id |

## Pipeline (one daily run)
1. Insert pipeline_runs row (status "running").
2. Extract: download with timeout + 3 retries; save raw lines.
3. Transform: parse, track headings, convert types, quarantine bad rows, drop in-file duplicates.
4. Load: upsert schemes then nav_history in one transaction.
5. Check + finish: quality checks; mark success/failed with counts and error.

```sql
INSERT INTO nav_history (scheme_code, nav_date, nav)
VALUES (%s, %s, %s)
ON CONFLICT (scheme_code, nav_date) DO UPDATE SET nav = EXCLUDED.nav;
```

Backfill: one-time script for ~3 years of watchlist history, reusing transform + load.

## Metrics (SQL views)
| Metric | Meaning | Calculation |
|---|---|---|
| Daily return | Change since previous NAV date | nav / LAG(nav) − 1, PARTITION BY scheme_code ORDER BY nav_date |
| 1-year return | Gain over a year | latest NAV / NAV on last available date ≤ 365 days earlier − 1 |
| Annualised volatility | How bumpy | STDDEV(daily return) × √250 |
| Max drawdown | Worst fall from a peak | MIN(nav / running MAX(nav) − 1) |

Gotchas: NAV only on business days — use last available date on or before a target date; always
PARTITION BY scheme_code.

## Dashboard (Streamlit, reads views only)
| Page | Shows | Interaction |
|---|---|---|
| Compare | Watchlist funds in a category with 3 metrics | Category picker, sort, CSV |
| Fund detail | NAV history + drawdown chart | Fund picker, date range |
| Pipeline health | Last 30 runs: status, counts, duration | Click failed run for error |

Show "Data as of <latest date>" and "For learning only. Not investment advice. Past returns don't
predict future returns." Cache queries for a few minutes.

## Non-functional
- Schedule: GitHub Actions cron (UTC — convert from IST), a few hours after AMFI's file updates;
  plus `workflow_dispatch` for manual runs. Check GitHub's current rules on delays and inactive repos.
- Tests (pytest): parser on a fixture with headings, blanks, "N.A." and a duplicate; metrics on a
  hand-made series; idempotency (load twice, same count) on a test DB.
- CI: ruff + pytest against a Postgres service container on every push.
- Secrets: DB URL in GitHub/Streamlit secrets; `.env.example` only.
- Deploy: hosted Postgres + free Streamlit host (check current free-tier limits).

## Open questions
- History source: AMFI official (90-day chunks) vs mfapi.in.
- Exact NAVAll.txt format — confirm in Phase 2.
- What time AMFI updates the file — set cron after it.
- Which ~30 watchlist funds.
