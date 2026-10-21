# FundPulse — project guide for Claude Code

## What this project is
FundPulse is an automated daily data pipeline. It downloads the public mutual-fund NAV file
published by AMFI, cleans it, loads it into PostgreSQL safely (re-runs never duplicate data),
computes return and risk metrics with SQL window functions, and shows them on a Streamlit
dashboard. It is a portfolio project for software/data internships. Full spec: `docs/PRD.md` —
read it before starting any task.

## Who I am and how to work with me
- I'm a 2nd-year BTech CSBS student. I'm building this to LEARN, and I'll be asked to explain
  every file in interviews. Understanding beats speed.
- Work one phase at a time (see "Phases"). Before coding a phase, give a short plan: files you'll
  create/change and why. Wait for my "go".
- After each phase, explain in plain language:
  1. what you built and how the pieces connect,
  2. the 2–3 key concepts involved (e.g. idempotency, window functions),
  3. 2 interview questions I should be able to answer about it.
- Never claim something works unless you ran it. Run tests and lint after changes and show output.
- If something is ambiguous, ask me one short question instead of guessing.
- I'm on Windows. Give PowerShell commands, and note if a command differs on bash.
- Don't add features outside the PRD. If you have an idea, list it at the end instead of building it.

## Tech stack (do not change without asking)
- Python 3.12, virtual environment in `.venv`
- pandas for parsing and cleaning
- PostgreSQL 16 (Docker for local dev; hosted Postgres e.g. Supabase for production)
- psycopg 3 with plain SQL (no ORM — writing SQL myself is part of the learning)
- requests for downloading (with timeout + retries)
- pytest for tests, ruff for lint + formatting
- Streamlit for the dashboard
- GitHub Actions for CI and the daily scheduled run

## Non-negotiable rules
- **Idempotent loads:** upsert on `(scheme_code, nav_date)` with `INSERT ... ON CONFLICT DO UPDATE`.
  Running the same day twice must leave row counts unchanged.
- One day's load happens inside **one transaction** — all or nothing.
- NAV stored as `NUMERIC(16,8)`, never float.
- Bad rows are **quarantined with a reason**, never silently dropped.
- Keep raw and clean data separate: `raw_nav` holds lines exactly as received.
- Every run is logged in `pipeline_runs` (start, end, status, rows loaded, rows quarantined, error).
- Metrics are SQL **views**; the dashboard reads only views, never raw tables.
- Secrets (database URL) only in `.env` / GitHub secrets / Streamlit secrets. Commit `.env.example`.
- Be polite to data sources: timeouts, max 3 retries with backoff, cache backfill downloads.
- Dashboard shows "Data as of <date>" and "For learning only. Not investment advice."

## Decisions log
- 2026-10-22 (Phase 2): the real file has NAVs with up to 8 decimals → `nav NUMERIC(16,8)`.
- 2026-10-22 (Phase 2): NAV that is non-numeric (e.g. "N.A.") **or zero** (segregated
  portfolios, 241 rows on 21-Oct-2026) → quarantine with a reason.
- 2026-10-22 (Phase 2): AMFI uses two spellings/taxonomies for the same category
  (e.g. "Equity Scheme - Large Cap Fund" vs "Equity Schemes - Large Cap Fund"). Normalise
  every category heading to one canonical label before storing it in `schemes.category`.
  The mapping lives in `data/category_map.csv` (SEBI-style labels; debt "Term" names merged
  into "Duration" names; Sectoral + Thematic merged; Index/ETF/FoF labels kept as-is).
  Unknown headings pass through cleaned, with a warning.
- 2026-10-22 (Phase 3): in-file duplicates — same NAV → keep one (counted); different NAVs →
  quarantine all of them.
- 2026-10-22 (Phase 3): AMFI sometimes omits the fund-house heading (rows directly under a
  category heading). Those rows are kept with `fund_house = NULL`, not quarantined.

## Folder structure
```
fundpulse/
  pipeline/
    config.py       # env vars, watchlist path
    db.py           # connection helper
    extract.py      # download with timeout + retries; save raw lines
    transform.py    # parse + clean → (clean_rows, quarantined_rows)
    load.py         # upserts inside one transaction
    checks.py       # data-quality checks
    run.py          # orchestrates one daily run + logging
    backfill.py     # one-time history load for the watchlist
  sql/
    schema.sql
    views.sql
  dashboard/
    app.py
  data/
    watchlist.csv   # ~30 scheme codes + category
    category_map.csv  # AMFI heading -> one canonical category label
  tests/
    fixtures/       # small sample NAV files
  .github/workflows/
    ci.yml          # lint + tests on every push
    daily.yml       # scheduled daily run + manual trigger
docs/PRD.md
```

## Phases (build in this order, stop after each)
1. **Setup:** venv, requirements, ruff, pytest running one passing test, Docker Compose with
   Postgres, `db.py` connecting, `sql/schema.sql` applied.
2. **Inspect the source:** download the real AMFI file once, show me its first ~40 lines, and
   describe its exact format (separator, columns, section headings, date format) before
   writing the parser. Save a trimmed copy as a test fixture.
3. **Extract + transform:** download with retries; parser that tracks fund house/category
   headings, converts types, quarantines bad rows. Unit tests on the fixture.
4. **Load + run logging:** upserts in one transaction, `pipeline_runs` logging, `run.py`.
   Test that loading the same data twice doesn't change row counts.
5. **Data-quality checks:** volume, watchlist coverage, freshness (fail the run); big-move warning.
6. **Backfill:** load ~3 years of history for the watchlist, reusing transform + load.
7. **Analytics views:** daily return (LAG), 1-year return, annualised volatility, max drawdown
   (running MAX). pytest on a tiny hand-made series with known answers.
8. **Dashboard:** Compare, Fund detail and Pipeline health pages; cached queries.
9. **Automate + ship:** CI workflow, daily scheduled workflow (cron in UTC) with manual trigger,
   deploy DB + dashboard, README with diagram, live link, sample SQL and setup steps.

## Useful commands (fill in as they're created)
- `.venv\Scripts\Activate.ps1` — activate venv (PowerShell)
- `pip install -r requirements-dev.txt` — install runtime + dev packages
- `docker compose up -d --wait db` — start Postgres (waits until healthy)
- `docker compose exec db psql -U fundpulse -d fundpulse` — SQL shell (`\dt` lists tables)
- `docker compose down -v` — stop Postgres AND wipe data; next `up` re-applies schema.sql
- `python -m pipeline.db` — check the DB connection
- `python -m pipeline.run` — run one daily load
- `pytest` — run tests
- `ruff check .` / `ruff format .`
- `streamlit run dashboard/app.py`
