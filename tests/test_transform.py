"""Tests for the parser/cleaner, mostly on the real-data fixture (see fixtures/README.md)."""

import csv
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.config import CATEGORY_MAP_PATH
from pipeline.extract import split_lines
from pipeline.transform import parse_nav_lines

FIXTURE = Path(__file__).parent / "fixtures" / "navall_sample.txt"
HEADER = "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date"  # noqa: E501
LARGE_CAP = "Open Ended Schemes(Equity Scheme - Large Cap Fund)"


@pytest.fixture(scope="module")
def result():
    lines = split_lines(FIXTURE.read_bytes().decode("utf-8"))
    return parse_nav_lines(lines)


def row(result, scheme_code):
    matches = result.clean[result.clean["scheme_code"] == scheme_code]
    assert len(matches) == 1
    return matches.iloc[0]


def parse(*body):
    """Parse a tiny hand-written file: header, one section, then the given lines."""
    return parse_nav_lines([HEADER, LARGE_CAP, "Some Mutual Fund", *body])


# --- the fixture -------------------------------------------------------------


def test_fixture_counts(result):
    assert len(result.clean) == 15
    assert len(result.quarantined) == 3
    assert result.duplicates_dropped == 1


def test_fixture_quarantine_reasons(result):
    reasons = dict(zip(result.quarantined["line_no"], result.quarantined["reason"], strict=True))
    assert reasons == {
        28: "nav is not a number: 'N.A.'",
        36: "nav is zero",
        37: "nav is zero",
    }
    assert result.quarantined.iloc[0]["raw_line"].startswith("112278;")


def test_fixture_clean_scheme_codes(result):
    assert sorted(result.clean["scheme_code"]) == sorted(
        [135762, 135765, 135759, 135760]
        + [119528, 119527, 103174, 103173]
        + [120465, 120466, 112277]
        + [118553]
        + [108844, 108846, 133680]
    )


def test_both_large_cap_spellings_get_one_category(result):
    assert row(result, 119528)["category"] == "Equity Scheme - Large Cap Fund"  # "Equity Scheme"
    assert row(result, 120465)["category"] == "Equity Scheme - Large Cap Fund"  # "Equity Schemes"


def test_curly_apostrophe_heading_is_mapped(result):
    assert row(result, 135762)["category"] == "Solution Oriented Scheme - Children's Fund"


def test_fund_house_is_remembered_per_section(result):
    assert row(result, 135762)["fund_house"] == "Axis Mutual Fund"
    assert row(result, 119528)["fund_house"] == "Aditya Birla Sun Life Mutual Fund"
    assert row(result, 120465)["fund_house"] == "Axis Mutual Fund"
    assert row(result, 108844)["fund_house"] == "Bandhan Mutual Fund"


def test_nav_is_exact_decimal(result):
    nav = row(result, 108844)["nav"]
    assert isinstance(nav, Decimal)
    assert nav == Decimal("14.86269632")


def test_date_parsed(result):
    assert row(result, 118553)["nav_date"] == date(2023, 6, 11)
    assert row(result, 135762)["nav_date"] == date(2026, 10, 21)


def test_scheme_name_and_isin(result):
    r = row(result, 120466)
    assert r["scheme_name"] == "Axis Large Cap Fund"
    assert r["isin_growth"] == "INF846K01DN3"


# --- small hand-written cases ------------------------------------------------


def test_conflicting_duplicates_are_both_quarantined():
    res = parse(
        "100001;INF000000001;-;Fund A;Direct Plan;Growth;10.5;21-Oct-2026",
        "100001;INF000000001;-;Fund A;Direct Plan;Growth;11.0;21-Oct-2026",
    )
    assert res.clean.empty
    assert res.duplicates_dropped == 0
    assert list(res.quarantined["reason"]) == ["conflicting duplicate: same scheme and date"] * 2


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("100001;X;-;Fund A;;;10.5", "expected 8 fields, got 7"),
        ("ABC;INF000000001;-;Fund A;;;10.5;21-Oct-2026", "scheme code is not a number: 'ABC'"),
        ("100001;INF000000001;-;;;;10.5;21-Oct-2026", "scheme name is empty"),
        ("100001;INF000000001;-;Fund A;;;1e5;21-Oct-2026", "nav is not a number: '1e5'"),
        ("100001;INF000000001;-;Fund A;;;-3.2;21-Oct-2026", "nav is not a number: '-3.2'"),
        ("100001;INF000000001;-;Fund A;;;123456789.5;21-Oct-2026", "nav too large: '123456789.5'"),
        ("100001;INF000000001;-;Fund A;;;10.5;2026-10-21", "date is not DD-Mon-YYYY: '2026-10-21'"),
        (
            "100001;INF000000001;-;Fund A;;;10.5;31-Feb-2026",
            "date is not DD-Mon-YYYY: '31-Feb-2026'",
        ),
    ],
)
def test_bad_rows_are_quarantined_with_reason(line, reason):
    res = parse(line)
    assert res.clean.empty
    assert list(res.quarantined["reason"]) == [reason]


def test_row_before_any_heading_is_quarantined():
    res = parse_nav_lines([HEADER, "100001;INF000000001;-;Fund A;;;10.5;21-Oct-2026"])
    assert list(res.quarantined["reason"]) == ["row is not under a category heading"]


def test_category_without_fund_house_heading_keeps_row_with_null_fund_house():
    # Real case (NAVAll.txt 21-Oct-2026, line 18148): a category heading followed directly by
    # rows. The NAV is valid, only the fund house label is missing, so keep it as NULL.
    res = parse_nav_lines([HEADER, LARGE_CAP, "100001;INF000000001;-;Fund A;;;10.5;21-Oct-2026"])
    assert res.quarantined.empty
    assert res.clean.iloc[0]["fund_house"] is None
    assert res.clean.iloc[0]["category"] == "Equity Scheme - Large Cap Fund"


def test_invalid_isin_becomes_none():
    res = parse("100001;Redeemed;-;Fund A;;;10.5;21-Oct-2026")
    assert res.clean.iloc[0]["isin_growth"] is None


def test_unknown_heading_passes_through_cleaned_with_warning(caplog):
    lines = [HEADER, "Open Ended Schemes(Brand  New – Category)", "Some Mutual Fund"]
    lines.append("100001;INF000000001;-;Fund A;;;10.5;21-Oct-2026")
    with caplog.at_level(logging.WARNING):
        res = parse_nav_lines(lines)

    assert res.clean.iloc[0]["category"] == "Open Ended Schemes(Brand New - Category)"
    assert "category_map.csv" in caplog.text


def test_empty_input_gives_empty_frames():
    res = parse_nav_lines([HEADER, " ", ""])
    assert res.clean.empty and res.quarantined.empty


# --- the category map file itself --------------------------------------------


def test_category_map_has_no_duplicate_or_empty_entries():
    with CATEGORY_MAP_PATH.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = [r["raw_heading"] for r in rows]
    assert len(keys) == len(set(keys)), "a raw heading is listed twice"
    assert all(r["raw_heading"].strip() and r["category"].strip() for r in rows)
