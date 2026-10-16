# deped_enrollment: profile

## Run details

| Field | Value |
|---|---|
| Date profiled | 2026-09-29 (SY 2023-24 to 2025-26); 2026-10-16 (SY 2020-21 added) |
| Profiled by | @hyenalouise |
| Tool | DuckDB 1.4.5 (Python), run locally: [`analysis/profiling/profile_deped.py`](../../../../analysis/profiling/profile_deped.py) |
| Files profiled (SHA-256) | See [README.md](README.md#files). The script stops if a zip's checksum differs |
| How files were read | Straight from the original zips, all columns as text (`all_varchar`), strict CSV parsing. SY 2025-26 is decoded from Windows-1252 in memory; raw files are never modified. SY 2021-22 and 2022-23 are not acquired, so SY 2020-21 is compared with SY 2023-24, a three-year gap |

## How to rerun

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_deped.py
```

`RAW_DATA_DIR` must contain `deped/original/` with the zips listed in the script. Every result prints under its finding ID below.

## Summary

Clean and usable at school level: `school_id` is a reliable key within each year, and every enrollment count is a valid whole number. The main work before analysis is matching place names to PSGC and harmonizing SY 2025-26, which changed encoding, columns, and category labels. SY 2020-21 has the same layout, labels, and README as SY 2023-24 and loads the same way; what differs is its content: 191 schools whose DepEd region label changes from Region XII in SY 2020-21 to BARMM in SY 2023-24, more private schools with no learners, and more school IDs that do not reach SY 2023-24.

## Observed findings

| ID | Finding | Evidence | Impact | Proposed handling |
|---|---|---|---|---|
| O-1 | `school_id` is clean in every year | 0 blank, 0 non-numeric, 0 not 6 digits, 0 duplicates, 0 fully duplicated rows in each of the four files | Safe primary key within a year | Check in Bronze validation: a blank `school_id` fails the delivery; a repeated one is recorded as WARN and every row is kept as evidence, so Silver decides which counts (D-015) |
| O-2 | Enrollment counts are valid | 0 non-integer and 0 negative values across all count columns; 0 schools with elementary learners that do not offer elementary | Counts can be typed as integers without loss | Type in Silver; keep a range check |
| O-3 | Total learners per file | 26,227,022 (2020-21); 27,081,292 (2023-24); 26,400,182 (2024-25); 25,935,863 (2025-26). By sector, 2020-21 vs 2023-24: public 22,712,409 vs 23,225,427; private 3,375,748 vs 3,731,936; SUC/LUC 118,755 vs 100,481; PSO 20,110 vs 23,448 | Baseline for reconciliation | Reconcile against DepEd's published totals: matches for SY 2020-21, not yet done for the other years (S-3) |
| O-4 | No PSGC codes | Location columns are names only | Joining to PSA data requires name matching | Match names to PSGC in integration; count and list unmatched. Done for SY 2023-24 in [deped-dataset-research.md](../../cross-source/deped-dataset-research.md): 97.9% of schools match to barangay |
| O-5 | Place names are not standardized | 5,450 rows (2023-24) have a "(Capital)" suffix in municipality, e.g. "CEBU CITY (Capital)" (269). Provinces are ALL CAPS; divisions are never ALL CAPS. In 2025-26, 220 rows have double spaces in municipality (e.g. "CITY OF MALOLOS  (Capital)"), 275 rows have leading or trailing spaces, and NCR district province names gained extra spaces (e.g. "NCR   SECOND DISTRICT"). Of 255 schools whose municipality text changed from 2024-25 to 2025-26, 213 differ only by spacing. SY 2020-21 looks like 2023-24: no double, leading, or trailing spaces | Direct name joins will miss | Documented normalization rules in Silver, with affected counts |
| O-6 | SY 2025-26 encoding differs | Windows-1252 with CRLF line endings; 1,892 lines fail UTF-8 decoding (e.g. `Do\xf1a`). Earlier years (2020-21, 2023-24, 2024-25) are UTF-8 with LF | A loader that assumes UTF-8 fails or corrupts names | Declare encoding per file in the source contract; fail loudly on mismatch |
| O-7 | SY 2025-26 adds columns | Undocumented `Modified Curricular Offering Classification` (values: Purely ES 42,118; JHS with SHS 7,901; All Offering 3,692; ES and JHS 3,384; Purely JHS 1,730; Purely SHS 1,347; ES with SHS 32), plus four documented `g11_sshs_*` columns. SY 2020-21 has the same 78 columns, in the same order, as 2023-24 | Schema drift between years | Schema-drift check in Bronze; map new columns explicitly |
| O-8 | SY 2025-26 relabels categories | `DepEd` → `DepED Managed`; `Non-Sectarian` → `Non-Sectarian ` (trailing space); `PSO` → `SCHOOL ABROAD`; `SUC/LUC` → `SUCsLUCs`; `True/False` → `Yes/No`; annex labels reworded (e.g. `Standalone School` → `School with no Annexes`). SY 2020-21 uses the 2023-24 labels, plus `Local Government` (154 schools) in `school_management`, which no later year has; 149 of them are `DepEd` in 2023-24, and the other 5 are public schools whose IDs appear in neither 2023-24 nor 2024-25 (dropped IDs, O-12) | Category comparisons across years break | Mapping table from each year's labels to one standard set |
| O-9 | README labels match no year exactly | README lists `DepEd Managed`; data has `DepEd` (2023-24, 2024-25) and `DepED Managed` (2025-26) | Documentation cannot be used as the accepted-values list | Build accepted values from observed data, per year |
| O-10 | New region NIR from SY 2024-25 | 2,704 schools in NIR in 2024-25 were in Region VI (1,586) or VII (1,118) in 2023-24; no other region changes. From 2020-21 to 2023-24, the DepEd region label changes from Region XII to BARMM for 191 schools and for no others: 111 in `NORTH COTABATO` whose division label changes from `North Cotabato` to `Special Geographic Area Division`, and 80 in `CITY OF COTABATO`. This reflects a change in DepEd's administrative labeling, not evidence that the schools physically moved or that the legal boundary changed during this period | Region-level trends are not comparable on the source labels alone | Place every year on a fixed PSGC geography (#91); until then, avoid region-level trends or compare at city or municipality level |
| O-11 | Province values change between years | Distinct province values (including `PSO`): 88 (2020-21), 88 (2023-24), 89 (2024-25), 88 (2025-26). `(SGA - North Cotabato)` appears from 2024-25. In 2025-26, `PSO` is no longer used as a province and the NCR district names change spacing (see O-5) | Province matching must handle it | Include in PSGC matching |
| O-12 | School ID churn | 2020-21 → 2023-24 (three years): 58,440 kept, 2,517 dropped (private 1,711, public 752, SUC/LUC 53, PSO 1), 1,727 new (public 1,149, private 568, SUC/LUC 9, PSO 1). 2023-24 → 2024-25: 59,537 kept, 630 dropped, 592 new. 2024-25 → 2025-26: 59,653 kept, 476 dropped, 551 new | School-level history is incomplete for about 1% of schools per year | Report churn; do not treat a dropped ID as a closed school |
| O-13 | Overseas schools included | 33 rows with region `PSO` (2020-21 and 2023-24). In 2025-26 their municipality is `CITY OF PASIG` | Would be wrongly placed in Pasig if matched by name | Exclude PSO from geographic analysis by rule |
| O-14 | Placeholder street addresses | 2020-21: 5,782 blank. 2023-24: 5,203 blank. 2025-26: 0 blank, but `-` (2,234), `n/a` (685), `N/A` (636) | Blank and placeholder mean the same thing | Standardize placeholders to NULL in Silver (not used for analysis) |
| O-15 | Barangay blanks | 84 (2020-21), 70 (2023-24), 65 (2024-25), 7 (2025-26) | Barangay-level placement incomplete for a few schools | Flag; analysis above barangay level is unaffected |
| O-16 | Entirely blank columns | `g11_unique_*` and `g12_unique_*` are blank in 2020-21 and 2023-24, as the README says ("only has values starting SY 2024-25") | None | Expected |
| O-17 | Place names contain mangled characters | `Ã‘` appears where `Ñ` belongs (e.g. `ALMEÃ‘ANA`, `AGUSAN PEQUEÃ‘O`): 265 rows and 173 distinct places in 2020-21, 260 and 173 in 2023-24, 261 and 173 in 2024-25, 263 and 173 in 2025-26; also 15, 11, 11, and 10 school names. Present in all four years, including the Windows-1252 file, so it is in the published data, not caused by decoding | Exact name matching fails for these places | Repair by re-reading the text as UTF-8 before matching; keep the raw value ([cross-source A-10](../../cross-source/deped-dataset-research.md#data-problems-in-depeds-place-names-a-10)) |
| O-18 | Barangay names appear to be capped at 40 characters | The longest barangay value in every year is exactly 40 characters, and 40 is far more common than 38 or 39 (2023-24: 8, 6, 24 rows). 13 distinct 40-character names per year, SY 2020-21 included; some end mid-word or with an open bracket (e.g. `AURORA HILL PROPER (MALVAR-SGT. FLORESCA`), while others are complete | Longer barangay names are probably cut off | Match a 40-character name only to the one PSGC barangay in its city or municipality that starts with it; otherwise list it as unmatched |

## Suspected findings

| ID | Suspicion | How to test | Status |
|---|---|---|---|
| S-1 | Zero-enrollment schools are closed or non-reporting. 2020-21: 439 (Private 407, Public 23, PSO 5, SUC/LUC 4); 2023-24: 115 (Private 103, PSO 7, Public 4, SUC/LUC 1); 2024-25: 24; 2025-26: 46 | Check whether their IDs appear in the next year and in facilities. Of the 439 in 2020-21, 172 appear in 2023-24 and 140 of those have learners there; 267 do not appear | open |
| S-2 | Some municipality changes between years are corrections, others real moves (e.g. LORETO → LA PAZ, SITANGKAI → SIBUTU) | Compare against PSGC and the school's barangay | open |
| S-3 | File totals match DepEd's official published enrollment | Find DepEd's official national totals per school year and compare. SY 2020-21: DepEd's [2021-09-23 news release](https://www.deped.gov.ph/2021/09/23/deped-credits-parents-learners-for-exceeding-100-enrollment-turnout-for-sy-2021-2022/) says "SY 2020-2021 had 26,227,022 enrollees.", equal to the file total in O-3 (all sectors, PSO included) | confirmed for SY 2020-21; open for SY 2023-24 to 2025-26 |
| S-4 | Three private schools in Maguindanao (BARMM) over-report Grade 11 strand enrollment. Their Grade 11 strand jumps 5 to 23 times in one year, to the largest counts in the data, and Grade 12 does not follow the cohort: 410978 HUMSS 183 → 4,270 → 7,858 (Grade 12 HUMSS 1,153 in 2024-25, after 183 in Grade 11 the year before); 410977 HUMSS 807 → 4,204 → 6,745; 410472 Arts 646 → 4,244 → 1,721. No other school has a Grade 11 strand of 1,000+ at 5 times the year before | Compare with DepEd's senior high school figures or the schools' own reports; check whether the SY 2025-26 Grade 11 learners appear in Grade 12 in SY 2026-27 | open |
| S-5 | SY 2020-21, the first school year of distance learning, has fewer private learners but more private schools than 2023-24: 13,256 private schools (12,113 in 2023-24) for 3,375,748 learners (3,731,936), with 407 private schools at zero learners (S-1) | Load SY 2021-22 and 2022-23 and check whether the private school count falls and the dropped IDs (O-12) disappear in those years | open |

## Changes across files or years

- SY 2020-21, 2023-24, and 2024-25: identical columns and column order (78 columns), and the same `README.md`.
- SY 2021-22 and 2022-23: not acquired, so 2020-21 is compared with 2023-24 across a three-year gap (O-10, O-12).
- SY 2025-26: 83 columns, Windows-1252 encoding, CRLF line endings, relabeled categories (O-6 to O-8).

## Questions for the publisher or mentor

- Is the SY 2025-26 encoding change intentional, and will earlier years be republished the same way?
- Is a school ID mapping file (mentioned in the README) planned, and when?
