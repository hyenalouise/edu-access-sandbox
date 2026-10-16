# psa_school_age_population: PSA population aged 5-24 by single-year age, sex and city/municipality

**Status:** profiled

Issue: #154. The team's school-age population reference: the only source found with population by single year of age at city and municipality level, for the 2020 and 2024 censuses. It is the population side of AP4 (D-042): population aged 5-17, total population, both sexes, at the 2020 and 2024 censuses. It complements [psa_population_per_age_group](../psa_population_per_age_group/README.md), which stops at province or highly urbanized city and uses five-year bands.

## Identity

| Field | Value |
|---|---|
| Source name | School-Age Population by Single-Year Age, Sex and City/Municipality, 2020 and 2024 (the sheet titles are in [profile.md](profile.md), O-1) |
| Publisher / agency | Philippine Statistics Authority (PSA), Population and Housing Census Division, National Censuses Service |
| Source system (as stated by the publisher) | 2020 Census of Population and Housing (2020 CPH); 2024 Census of Population (2024 POPCEN). From the source lines of the sheets |
| Source URL or acquisition method | Not published in this form. The team asked PSA by email on 2026-10-13 for official 2023 school-age population estimates by city and municipality; PSA replied on 2026-10-15 with these two census workbooks attached and referred the 2023 request to its Demographic and Health Statistics Division (DHSD), still pending |
| Licensing or access restrictions | Provided by PSA "for your academic research" (PSA email). No license terms stated; required citation and whether derived results may be published are UNVERIFIED. Asked in the [profile](profile.md#questions-for-the-publisher-or-mentor) |
| Owner (team member) | @saraevcldn |
| Date acquired | 2026-10-15, 10:07 (+08:00): date of the PSA email |

## Files

Raw files are kept in raw storage, never in git. Record exactly what arrived.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `2020 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx` | xlsx, sheets `2020 Total Pop`, `2020 Household Pop` | n/a | 1,206,376 | 1,742 places per sheet, one row each (profile O-1, O-2); `2020 Total Pop` 1,748 rows, `2020 Household Pop` 1,748 rows (first local run, 2026-10-16) | `e40d71839b951926cd3c9515c1edafbb6a2121f734670716e3b21bd3f9dcd35f` | Databricks volume `/Volumes/edu_access/00-source/raw/psa/` (uploaded 2026-10-16; loaded by the `dev` job, which verifies the SHA-256). Local copy: `RAW_DATA_DIR/psa/original/` |
| `2024 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx` | xlsx, sheets `2024 Total Pop`, `2024 Household Pop` | n/a | 1,558,482 | 1,744 places per sheet, four rows each (O-1, O-2); `2024 Total Pop` 6,994 rows, `2024 Household Pop` 6,991 rows (first local run, 2026-10-16) | `49d15bb0cdd191cd6aef4a14f4b063da247ba791b32caa653c37c464dff15954` | Databricks volume `/Volumes/edu_access/00-source/raw/psa/` (uploaded 2026-10-16; loaded by the `dev` job, which verifies the SHA-256). Local copy: `RAW_DATA_DIR/psa/original/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| PSA email of 2026-10-15 replying to the team's request of 2026-10-13 | none (email) | not yet saved with the raw files | Publisher office, acquisition channel, census sources, terms ("for your academic research"), DHSD referral |
| Sheet titles, column bands, ages, source lines, and the 2024 notes inside the workbooks | in the files above | as above | Population concept, geographic levels, census, boundary changes (2024 notes 1/ to 8/, a/) |

No technical notes came with the files. The census reference dates (May 1, 2020 and July 1, 2024) are recorded under Time basis; the age definition is asked in the profile (S-2).

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines |
| Geographic level | Country, region, province (and, for highly urbanized and independent cities and NCR, the city directly under its region), and city or municipality: 1,642 cities and municipalities in each year (O-2) |
| Time coverage | Two censuses: 2020 and 2024 |
| Time basis | Census reference dates: May 1, 2020 (2020 CPH) and July 1, 2024 (2024 POPCEN), as recorded in the [dataset use map](../../../business/dataset-use-map.md#school-age-population-source); not stated in the files themselves |
| Update frequency | Census years; the next one is not scheduled in the files |
| Population covered | Ages 5 to 24 only, by single year and sex. Two concepts on separate sheets: total population and household population (O-5) |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One count per (census year, population concept, place, sex, single-year age 5-24) |
| Candidate primary key | (year, concept, place, sex, age). A place is identified by its cleaned name and its parent: names alone repeat (114 names shared by about 330 places), the (name, parent) pair never does (O-6) |
| Candidate join keys | City or municipality name within its province, to PSGC 2Q 2026 (X-2). Across years by the same pair, with known renames and the 2022-2024 boundary changes (O-7) |
| PSGC available? Which version? | **No.** Names only, no codes and no level column (O-2) |
| Personally identifiable or sensitive fields | None. Public aggregate counts |
| Provenance fields in the source | Sheet titles and the source line or notes below each table. No table ID, release date, or version |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column | Expected type | Actual type | Notes |
|---|---|---|---|
| Place name | text, with a code | text only | Level only from the sums (O-2); brackets and footnote markers in names (O-6) |
| Sex | a column | 2020: column bands (Both Sexes, Male, Female); 2024: `Total` / `Male` / `Female` rows | O-1 |
| Age | a column | 2020: 20 columns per sex band; 2024: 20 columns | Ages 5-24 in row 3 (O-1) |
| Counts | whole number | whole number | Complete; sexes add up; aggregates equal the sum of their places (O-2 to O-4) |

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** report layouts, different in each year: 2020 wide, 2024 long with a place row followed by three sex rows (O-1).
- **Observed:** no PSGC codes and no level column; levels are recovered from the sums, which close exactly in all four sheets (O-2).
- **Observed:** names carry old names and `(Capital)` in brackets (176 labels in 2020, 48 in 2024) and, in 2024, footnote markers such as `1/` (O-6).
- **Observed:** 77 cities and municipalities per year do not match the other year by name within province: Samar renamed Western Samar, Maguindanao split in two, 7 renames or spelling changes, and the 8 2020 Special Geographic Area "clusters" against the 8 municipalities created in 2024 (O-7).
- **Observed:** by name within province, with no alias, 1,602 of 1,642 places match one PSGC 2Q 2026 city or municipality in 2024 and 1,585 in 2020; the others are Western Samar, Maguindanao (2020), renamed or respelled LGUs, and the 8 Special Geographic Area units of each year (X-2).
- **Observed:** the 2024 household sheet equals psa_population_per_age_group in every cell both publish (X-1).
- **Suspected:** the 8 2020 clusters are PSA's grouping of the Special Geographic Area barangays by former Cotabato town, not LGUs (S-1).

## Limitations for analysis

- Census years only (2020, 2024). D-042 sets AP4 on exactly these two points, matched to SY 2020-21 and SY 2024-25, with no interpolation or extrapolation, so no other year is derived from this source.
- Total and household population are different concepts; never mix them, or this source with other population sources, in one ratio without saying which (O-5). AP4 uses total population, both sexes (D-042).
- No codes: every use needs a reviewed name match to PSGC (X-2), and the 2020 Special Geographic Area clusters cannot be matched one-to-one to the 2024 municipalities (O-7, S-1).
