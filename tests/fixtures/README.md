# Test fixtures

## navall_sample.txt

A trimmed copy of AMFI's `NAVAll.txt`, downloaded 2026-10-21 (Last-Modified 20:47 GMT).
Every line is copied byte-for-byte from the real file — CRLF endings, the single-space
"blank" lines, the curly apostrophe (U+2019) on line 3, and the empty last line — except
for two hand edits. `.gitattributes` stops git from changing the line endings.

| Line | What it tests | Source |
|---|---|---|
| 1 | Header row (must be skipped) | real |
| 2, 4, 6, … | "Blank" lines that are actually one space `" "` | real |
| 3 | Category heading with a non-ASCII apostrophe | real |
| 12, 21 | Same category spelt two ways: `Equity Scheme` vs `Equity Schemes` | real |
| 5, 23 | Same fund house appearing under two categories | real |
| 17, 43, 44 | Empty `Plan` and `Option` columns | real |
| **28** | NAV `N.A.` → must be quarantined | **hand edit** (real value was `16.71`) |
| **29** | Exact duplicate of line 25 → must be dropped as an in-file duplicate | **hand edit** |
| 35 | Stale date (11-Jun-2023) in today's file | real |
| 36, 37 | NAV `0.0000` (segregated portfolio) → violates `nav > 0`, must be quarantined | real |
| 43, 44 | NAV with 8 decimal places | real |
| 46 | Empty last line (file ends `\r\n\r\n`) | real |

Expected after parsing: 19 data rows → 15 clean rows, 1 in-file duplicate dropped,
3 quarantined (1 × `N.A.`, 2 × zero NAV). 5 category/fund-house section pairs.

## mfapi_sample.json

A trimmed copy of `https://api.mfapi.in/mf/119018` (HDFC Large Cap Fund – Direct – Growth),
downloaded 2026-10-22. `meta` is unchanged; `data` keeps 8 of the 3,396 points, newest first
like the real API, with their real values — except one hand edit.

| Date | Why it's there |
|---|---|
| 19, 16, 14, 13-10-2026 | Recent NAVs (5 decimals, as mfapi sends them) |
| **15-10-2026** | **Hand edit:** NAV changed from `1169.41900` to `N.A.` → must be quarantined |
| 23-10-2023 | First trading day after the 3-year cutoff (22-10-2023) used in tests → kept |
| 20-10-2023, 01-01-2013 | Before the cutoff → dropped by the adapter |

Expected with `since=2023-10-22`: 6 lines → 5 clean, 1 quarantined.
