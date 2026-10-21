"""Shared test fixtures: a separate test database that is emptied before every test."""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from pipeline.config import PROJECT_ROOT  # importing config also loads .env
from pipeline.extract import split_lines

SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "navall_sample.txt"
TABLES = ["quarantine", "raw_nav", "nav_history", "schemes", "pipeline_runs"]


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set. Copy it from .env.example into .env.")

    dbname = conninfo_to_dict(url)["dbname"]
    if not dbname.endswith("_test"):
        # Tests TRUNCATE every table. Never let that happen to a real database.
        pytest.exit(f"Refusing to run: test database {dbname!r} does not end with '_test'.")

    # CREATE DATABASE can't run inside the database being created, so use 'postgres'.
    with psycopg.connect(url, dbname="postgres", autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    return url


@pytest.fixture
def conn(test_db_url):
    """An autocommit connection to an empty test database."""
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        yield conn


@pytest.fixture(scope="session")
def fixture_lines() -> list[str]:
    return split_lines(FIXTURE_PATH.read_bytes().decode("utf-8"))
