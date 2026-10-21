# deped_psgc_coordinates: profile

## Run details

| Field | Value |
|---|---|
| Date profiled | 2026-10-21 |
| Profiled by | @catweyine |
| Tool | Python, run locally: [`analysis/profiling/profile_deped_psgc_coordinates.py`](../../../../analysis/profiling/profile_deped_psgc_coordinates.py). Row counts come from the Bronze contract's own checks (`src/ingestion/xlsx_report.py`) |
| File profiled | See [README.md](README.md#files). The script stops if the file's SHA-256 differs |
| How the file was read | Sheet `DB`, with the standard library (D-007); every cell as stored text; the 88 headers of row 8 must equal schema `v1` |

## How to rerun

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_deped_psgc_coordinates.py
```

Two runs on the same files give identical output.

## Observed findings

| ID | Finding | Evidence | Proposed handling |
|---|---|---|---|
| O-1 | A report layout, public only | One sheet `DB`; title rows 1-5 (enrollment from LIS as of 2024-01-31; PSGC from PSA Q4 2024; income class from DOF D.O. 74 s. 2024); row 6 holds `SECTOR: PUBLIC ONLY` in A6 and the PSGC and coordinate notes; header in row 8, identical to `v1`. 47,818 rows below the header (A1:CJ47826), all with a school ID: 0 blank, 0 without an ID, no appended block. `sector` is `Public` on all 47,818 | Bronze reads it with the `xlsx_report` format and schema `v1`; the A6 note is pinned in the approval, and `dq_sector_not_public` WARNs above 0 |
| O-2 | School ID is clean | 47,818 distinct, all 6 digits, 0 duplicate rows | None |
| O-3 | PSGC codes lost their leading zero | Stored as numbers: 28,811 lost their leading zero (region, province, city, barangay alike). `#N/A` on 204 schools (city and barangay). 0 blank | Pad to 10 digits and treat `#N/A` as missing, with counts, in Silver |
| O-4 | Coordinates: few missing | 47,139 numeric pairs; 47,080 inside lon 116-127, lat 4-21.5; 5 at (0, 0); 54 others outside the box. `#N/A` on 679 | Keep and flag in Silver, never correct |
| O-5 | Text and labels kept as published | Mojibake in 239 cells; `barangay` blank 14; income class `1St` 72; urban/rural `-` 29; 3,602 error cells (`#N/A`) | Bronze keeps them; Silver repairs, keeping the raw value |
| O-6 | Most coordinates sit near their own city or municipality | Distance from each school to the median point of the schools with in-box coordinates and the same PSGC city or municipality code, 47,080 schools: < 10 km 40,046; 10-25 km 5,937; 25-50 km 675; 50-100 km 162; > 100 km 260 | Read over 100 km as a flag, not a verdict: the median is a rough centre for large or island municipalities. Test against boundaries before distance measures (S-1) |

## Suspected findings

| ID | Suspicion | How to test | Status |
|---|---|---|---|
| S-1 | The 260 schools over 100 km from their city or municipality (O-6) are wrong locations | Point-in-polygon of each school against the approved HDX ADM3 and ADM4 boundaries, by PSGC code | open |

## Questions for the sender

- Are there terms on publishing results from it?
- On what date was it sent?
- Where do the 260 far-off coordinates (O-6) come from?
