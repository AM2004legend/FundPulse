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
