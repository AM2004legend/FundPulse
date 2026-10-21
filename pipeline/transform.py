"""Parse AMFI's NAVAll.txt lines into clean rows and quarantined rows.

The file is a flat list of lines in this shape (see tests/fixtures/README.md):

    header row
    <category heading>          e.g. Open Ended Schemes(Equity Scheme - Large Cap Fund)
    <fund house heading>        e.g. Axis Mutual Fund
    data rows                   8 fields separated by ";"
    ...                         lines holding a single space separate the blocks

Step 1 walks the lines and remembers the current category and fund house.
Step 2 validates every data row with pandas; each bad row gets the first reason found.
"""

import csv
import logging
from decimal import Decimal
from functools import cache
from typing import NamedTuple

import pandas as pd

from pipeline.config import CATEGORY_MAP_PATH

logger = logging.getLogger(__name__)

N_FIELDS = 8
CATEGORY_PREFIXES = ("Open Ended Schemes", "Close Ended Schemes", "Interval Fund Schemes")
NAV_PATTERN = r"\d+(\.\d+)?"  # plain positive decimal: rejects "N.A.", "-3.2", "1e5", "NaN"
NAV_LIMIT = Decimal(10) ** 8  # NUMERIC(16,8) leaves 8 digits before the decimal point
ISIN_PATTERN = r"INF[A-Z0-9]{9}"  # Indian mutual-fund ISINs start with INF

CLEAN_COLUMNS = [
    "scheme_code",
    "scheme_name",
    "plan_type",
    "option_type",
    "fund_house",
    "category",
    "isin_growth",
    "nav",
    "nav_date",
]
QUARANTINE_COLUMNS = ["line_no", "raw_line", "reason"]


class TransformResult(NamedTuple):
    clean: pd.DataFrame  # one row per (scheme_code, nav_date), columns CLEAN_COLUMNS
    quarantined: pd.DataFrame  # columns QUARANTINE_COLUMNS
    duplicates_dropped: int  # exact in-file duplicates removed


def clean_heading(text: str) -> str:
    """Normalise quotes, dashes and spacing so tiny typing differences don't matter."""
    text = text.replace("’", "'").replace("–", "-")
    return " ".join(text.split())


@cache
def load_category_map() -> dict[str, str]:
    with CATEGORY_MAP_PATH.open(encoding="utf-8", newline="") as f:
        return {row["raw_heading"]: row["category"] for row in csv.DictReader(f)}


def normalize_category(heading: str) -> str:
    key = clean_heading(heading)
    category = load_category_map().get(key)
    if category is None:
        logger.warning("Unknown category heading %r - add it to data/category_map.csv", key)
        return key
    return category


def _none_for_missing(series: pd.Series) -> pd.Series:
    """pandas marks missing text as NaN; the database needs None (-> NULL)."""
    return series.astype(object).where(series.notna(), None)


def _read_sections(lines: list[str]) -> list[dict]:
    """Step 1: keep the data lines, tagged with the headings they appear under."""
    records = []
    category = fund_house = None

    for line_no, line in enumerate(lines, start=1):
        if not line.strip() or line.startswith("Scheme Code;"):
            continue
        if ";" in line:
            records.append(
                {
                    "line_no": line_no,
                    "raw_line": line,
                    "category": category,
                    "fund_house": fund_house,
                }
            )
        elif line.startswith(CATEGORY_PREFIXES):
            category = normalize_category(line)
            fund_house = None  # a new category always starts with a fund house heading
        else:
            fund_house = line.strip()

    return records


def parse_nav_lines(lines: list[str]) -> TransformResult:
    records = _read_sections(lines)
    if not records:
        return TransformResult(
            pd.DataFrame(columns=CLEAN_COLUMNS), pd.DataFrame(columns=QUARANTINE_COLUMNS), 0
        )

    df = pd.DataFrame(records)
    parts = df["raw_line"].str.split(";")
    n_fields = parts.str.len()
    # Rows with the wrong field count get 8 empty fields so the column logic still works.
    fields = pd.DataFrame(
        [p if len(p) == N_FIELDS else [""] * N_FIELDS for p in parts], index=df.index
    ).apply(lambda col: col.str.strip())
    # Column 2 (ISIN Div Reinvestment) isn't stored.
    code_text = fields[0]
    isin_text = fields[1]
    name_text = fields[3]
    plan_text = fields[4]
    option_text = fields[5]
    nav_text = fields[6]
    date_text = fields[7]

    nav_is_number = nav_text.str.fullmatch(NAV_PATTERN)
    df["nav"] = [Decimal(t) if ok else None for t, ok in zip(nav_text, nav_is_number, strict=True)]
    df["nav_date"] = pd.to_datetime(date_text, format="%d-%b-%Y", errors="coerce").dt.date
    df["scheme_name"] = name_text
    df["plan_type"] = _none_for_missing(plan_text.where(plan_text != ""))
    df["option_type"] = _none_for_missing(option_text.where(option_text != ""))
    df["isin_growth"] = _none_for_missing(isin_text.where(isin_text.str.fullmatch(ISIN_PATTERN)))
    df["fund_house"] = _none_for_missing(df["fund_house"])

    # Each check only fills rows that don't already have a reason, so the first problem wins.
    reason = pd.Series(None, index=df.index, dtype="object")

    def flag(mask, text):
        nonlocal reason
        reason = reason.mask(reason.isna() & mask, text)

    # A missing fund house is allowed: AMFI sometimes puts rows straight under a category
    # heading. The NAV is still valid, so the row is kept with fund_house = NULL.
    flag(df["category"].isna(), "row is not under a category heading")
    flag(n_fields != N_FIELDS, "expected 8 fields, got " + n_fields.astype(str))
    flag(~code_text.str.fullmatch(r"\d+"), "scheme code is not a number: '" + code_text + "'")
    flag(name_text == "", "scheme name is empty")
    flag(~nav_is_number, "nav is not a number: '" + nav_text + "'")
    flag(df["nav"].map(lambda n: n == 0), "nav is zero")
    flag(
        df["nav"].map(lambda n: n is not None and n >= NAV_LIMIT),
        "nav too large: '" + nav_text + "'",
    )
    flag(df["nav_date"].isna(), "date is not DD-Mon-YYYY: '" + date_text + "'")

    valid = reason.isna()
    df.loc[valid, "scheme_code"] = code_text[valid].astype(int)

    # In-file duplicates: same NAV twice -> keep one; different NAVs -> we can't know
    # which is right, so quarantine all of them.
    key = ["scheme_code", "nav_date"]
    navs_per_key = df[valid].groupby(key)["nav"].transform("nunique")
    flag(
        navs_per_key.reindex(df.index, fill_value=0) > 1,
        "conflicting duplicate: same scheme and date",
    )

    valid = reason.isna()
    exact_duplicate = df[valid].duplicated(key, keep="first")
    duplicates_dropped = int(exact_duplicate.sum())

    clean = df[valid][~exact_duplicate][CLEAN_COLUMNS].reset_index(drop=True)
    clean["scheme_code"] = clean["scheme_code"].astype(int)
    quarantined = df.assign(reason=reason)[~valid][QUARANTINE_COLUMNS].reset_index(drop=True)

    return TransformResult(clean, quarantined, duplicates_dropped)
