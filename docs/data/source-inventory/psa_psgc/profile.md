# psa_psgc: profile

## Run details

| Field | Value |
|---|---|
| Date profiled | 2026-09-29 |
| Profiled by | @maeveylain |
| Tool | DuckDB 1.4.5 (Python), run locally: [`analysis/profiling/profile_psgc.py`](../../../../analysis/profiling/profile_psgc.py) |
| Files profiled (SHA-256) | See [README.md](README.md#files). The script stops if the file's checksum differs |
| How files were read | Sheet `PSGC` of the original xlsx, read with the standard library and loaded into DuckDB with every column as text (`all_varchar`), strict CSV parsing. Sheets `National Summary` and `Notes` were read for cross-checks |

## How to rerun

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_psgc.py
```

The file must be at `$RAW_DATA_DIR/psa/original/PSGC-2Q-2026-Publication-Datafile.xlsx`. Optional: if `PSGC-Q4_2023-API-all.csv` (the `Q4_2023` pull, see [README.md](README.md#files)) is in the same folder with its recorded SHA-256, the script also reruns the `Q4_2023` comparison under X-1; otherwise it prints `skipped`. The column statistics in [data_dictionary.md](data_dictionary.md) come from `analysis/profiling/dictionary_psgc.py`.

## Summary

Usable as the geographic reference for the project. `10-digit PSGC` is a clean, unique key, every barangay and municipality has its parent in the file, and unit counts and regional populations reconcile with the workbook's own `National Summary`. Watch for a small set of special rows (Special Geographic Area, City of Isabela) that lack a level or code, several undocumented columns, and codes that must be read as text to keep leading zeros.

## Observed findings

Each check prints under its ID when the script runs.

| ID | Finding | Evidence | Impact | Proposed handling |
|---|---|---|---|---|
| O-1 | `10-digit PSGC` is clean and unique | 43,768 rows: 0 blank, 0 not 10 characters, 0 non-numeric, 0 duplicates, 0 fully duplicated rows. 29,620 ids start with `0` (e.g. Region IX is `0900000000`) | Safe primary key, but only as text | Read as string everywhere; assert uniqueness and length 10 in Bronze validation |
| O-2 | 2 rows have a blank `Geographic Level` | `0990100000` City of Isabela (Not a Province), population `#N/A`; `1999900000` Special Geographic Area, population 214,703, no correspondence code | Level counts and level-based filters skip these rows | Flag both; assign an explicit level only with a documented rule |
| O-2 | `Notes` legend does not match the data | Legend lists `Reg, Prov, Mun, Bgy, Dist, SubMun`. `Dist` has 0 rows; `City` (149 rows) is not in the legend | Level list must come from the data, not the legend | Use the observed six values plus blank; record in the mapping |
| O-3 | `Correspondence Code` is blank for 50 rows | By level: Bgy 38, Mun 8, Prov 2, blank level 1, Reg 1. Provinces: Maguindanao del Norte and del Sur; region: Negros Island Region. All 43,718 filled values are unique and 9 digits | Cannot be used as a complete key. Code is not explained in the `Notes` sheet | Join on it only as [D-030](../../../governance/decisions.md#d-030-joins-through-correspondence-code) allows: for sources with old 9-digit codes, one-to-one, with names checked. The 50 blank rows match by name only. Ask the publisher what it means (see Questions) |
| O-4 | One population cell is not a number, and 12 barangays have 0 | `0990100000` City of Isabela: `#N/A`. Zero population: 12 rows, all barangays | `#N/A` breaks numeric typing | Cast with a safe cast, keep `#N/A` rows flagged, treat 0 as a value to review, not a missing value |
| O-4 | Regional populations reconcile with the national total | Sum of 18 regions 112,727,776; `National Summary` 112,729,484; difference 1,708, which is the count of Filipinos abroad stated in `Notes` D.2 | Population does not add up to national by design | Never compare a sum of units to the national figure without this adjustment |
| O-5 | Unit counts match the `National Summary` sheet | Provinces 82, cities 149, municipalities 1,493, barangays 42,010: all four match | The file is complete relative to its own summary | Assert these counts after each quarterly load |
| O-6 | Column J has no header and holds footnotes | 19 rows: provinces 16, regions 2, barangays 1. Text such as "(excluding CITY OF BAGUIO) " and markers `1/`, `2/`, `3/` | Looks like data but is annotation. Provincial population excludes component cities | Exclude from the model; keep a note that province populations exclude some cities |
| O-7 | `Income Classification` has non-class values | 8 municipalities in the Special Geographic Area are `-`; 6 municipalities have a starred class (`2nd*` 2, `3rd*` 2, `4th*` 2), e.g. Mankayan, Arteche, Lugait. Filled only on provinces, cities, municipalities (0 elsewhere) | A category with 9 spellings for 5 classes | Split into `class` and `retained_after_downgrade`; map `-` to unknown |
| O-8 | `Urban / Rural` is `-` for 38 barangays, and all 38 have no correspondence code | Values: R 34,054, U 7,918, `-` 38. The 38 with `-` are exactly the 38 barangays with a blank `Correspondence Code` (0 others). `-` includes 6 Caloocan barangays, so not every NCR barangay is `U` despite `Notes` C | Urban share must state its denominator | Report unknown separately; do not fold into rural |
| O-9 | Names are not keys and have trailing spaces | 27,391 distinct names in 43,768 rows; 4,041 barangay names occur more than once (e.g. `Poblacion` 607 times). 2,855 names end in a space, 2,846 of them on rows with a `Status` value; no leading or double spaces | Name joins are ambiguous and space-sensitive | Trim names in Silver; match only within a parent code |
| O-10 | The hierarchy is complete in the file | 0 barangays without their city or municipality (first 7 digits + `000`); 0 provinces, cities, or municipalities without their region; 0 non-NCR municipalities without their province | Parent lookups by code prefix are safe | Derive region, province, and city or municipality from the code and assert it; handle NCR (no provinces) and the special rows explicitly |
| O-11 | `Old names` is sparse | 1,699 rows filled (barangays 1,618, municipalities 75, cities 3, provinces 3), 1,439 distinct | Only a partial record of past names | Use for name matching to older sources, not as a full history |
| O-12 | `Status` marks capitals and poblaciones | `Pob.` 2,773 (all barangays); `Capital` 82 (cities 45, municipalities 37) | Only these two values exist | Keep as category; leave blank as blank |
| O-13 | Two header cells contain line breaks | Headers of `Income Classification` and `Urban / Rural` include `\n` | Column names break naive parsers | Normalize header whitespace when loading |

### Cross-check against Q4_2023 (D-012)

Runs only when `PSGC-Q4_2023-API-all.csv` is in the raw folder. These are the counts quoted in the README Version section.

| ID | Finding | Evidence | Impact | Proposed handling |
|---|---|---|---|---|
| X-1 | 2Q 2026 differs from `Q4_2023` mainly because of two moves, the Negros Island Region and Sulu | `Q4_2023` file: 43,758 rows, all `version` = `Q4_2023`. 41,903 codes are in both files, 1,855 only in `Q4_2023`, and 1,865 only in 2Q 2026. 1,420 codes in 2Q 2026 start with `18` (Negros Island Region). 430 codes start with `09066` (Sulu) in 2Q 2026, and 430 start with `19066` in `Q4_2023`. Of the 1,865 codes only in 2Q 2026, 1,853 have a `Correspondence Code` equal to that of a code only in `Q4_2023`, and 12 have none (11 barangays and the NIR region row). `Q4_2023` has 457 names with broken accents and 1,780 barangays with no 2024 population | Region and code for Negros and Sulu differ between SY 2023-24 and 2Q 2026. Name joins inside a parent are not affected by a code change | Use 2Q 2026 as the master reference and build no crosswalk (D-012). Flag renamed or split units as unmatched or ambiguous |

## Suspected findings

Hypotheses still to test.

| ID | Suspicion | How to test | Status |
|---|---|---|---|
| S-1 | The 38 barangays with `-` urban/rural and no correspondence code are new or split barangays created after the 2020 census (9 of 38 record an old name, e.g. `Muzon` split into East, South, West) | Compare with the previous PSGC quarter and the RA creating each barangay; check the other 29 for creation notes | open |
| S-2 | `Correspondence Code` is the older 9-digit PSGC code kept for continuity | Evidence so far: (1) for 1,853 of the 1,865 codes that exist only in 2Q 2026, the `Correspondence Code` matches the same unit in `Q4_2023` (X-1, README Version section). (2) The `Coding Structure` sheet documents an earlier 9-digit structure (region 2 + province 2 + municipality or city 2 + barangay 3). For 41,898 of 41,909 barangays the first 6 digits equal their city or municipality's, all 1,648 city, municipality, and sub-municipality codes end in `000`, and no 6-digit prefix is shared by two of them (printed under S-2 by the script). To confirm: ask the publisher. Evidence (1) is rerun by the script under X-1 when `PSGC-Q4_2023-API-all.csv` is in the raw folder | supported, not confirmed |
| S-3 | The Special Geographic Area rows (`19999...`, 8 municipalities) are not in a province, which is why they have no income class or correspondence code | Read the PSA notes on the Special Geographic Area and the Bangsamoro transfer | open |
| S-4 | DepEd place names will match PSGC names only after trimming, case changes, and parent scoping | Match rates in `docs/data/cross-source/` (cross-source work) | open |
| S-5 | `Status` `Capital` marks a provincial capital and `Pob.` marks the poblacion of its city or municipality | Check that each province has one `Capital` city or municipality under its code prefix; read the PSA notes or ask the publisher for the definition of `Pob.`; compare `Pob.` barangays with barangays named `Poblacion` (607, O-9) | open |

## Changes across files or years

Only the 2Q 2026 publication is profiled here, and the numbers in the observed findings come from that file alone. The `Q4_2023` version served by the PSA API was used for three things only, with the evidence in [README.md](README.md#version-used-and-sy-2023-24): (1) to count which codes differ (41,903 in both files, 1,855 only in `Q4_2023`, 1,865 only in 2Q 2026); (2) to explain why (the Negros Island Region and Sulu moves, special government units that became municipalities, and Barangay 176 in NCR split into 176-A to 176-F); and (3) as evidence for S-2 (1,853 of the 1,865 new codes carry a `Correspondence Code` matching the same unit in `Q4_2023`). The `Q4_2023` file is recorded in the README (Files), and the script reruns the comparison under X-1 when it is in the raw folder. No crosswalk is built (D-012). Codes and names change when local government units are created, merged, or renamed, so each quarterly file should be compared with the last before replacing it.

## Questions for the publisher or mentor

- What is the `Correspondence Code` and why is it blank for new units?
- Should the Special Geographic Area rows be treated as provinces, municipalities, or excluded from level counts?
- Is there an official list of changes between quarterly publications (new, renamed, and merged units)?
- Which PSGC quarter do the DepEd 2023-24 to 2025-26 files use for place names?
