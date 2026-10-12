# psa_poverty_stat: PSA city- and municipal-level poverty estimates (small area estimates), 2018, 2021, 2023

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | Annex 1. Statistical Table on 2018, 2021 and 2023 City- and Municipal-Level Poverty Estimates (file `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx`) |
| Publisher / agency | Philippine Statistics Authority (PSA) |
| Source system (as stated by the publisher) | "Source: Philippine Statistics Authority, through a national government-funded project on the generation of the small area estimates of poverty" (footer of the sheet) |
| Source URL or acquisition method | Manual download from the landing page https://psa.gov.ph/statistics/poverty-sae/stat-tables. Direct file URL: https://psa.gov.ph/sites/default/files/phdsd/2_2023%20SAE_with%20PSGC_noHUC_06Feb2026.xlsx (from the browser's download record). PSA may replace the file at that URL; the SHA-256 below identifies the exact file used. Press release for the same estimates: https://psa.gov.ph/statistics/poverty-sae/node/1684082420 (read in a browser on 2026-10-01) |
| Licensing or access restrictions | CC BY 4.0 unless otherwise stated: the PSA website footer says all its data and content are licensed under the Creative Commons Attribution 4.0 International License (read 2026-10-01). The workbook states no terms of its own. Acknowledge PSA as the source. |
| Owner (team member) | @maeveylain |
| Date acquired | 2026-09-29 10:00 UTC (downloaded file's timestamp) |

## Files

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx` | xlsx (1 sheet) | n/a (binary workbook; text is Unicode) | 369,977 | 1,630 data rows on sheet `2023_NoHUC_Maguindanao grouped` (rows 6 to 1635 of range A1:S1641; 5 header rows, 6 footer rows): 1,612 city or municipality rows and 18 region banner rows | `303fb0e87bff046acaa21e3ac586f6def6b737b9082eb1f51451a887fd93a026` | Team volume: `/Volumes/edu_access/00-source/raw/psa/2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx` (uploaded 2026-09-30, SHA-256 verified on the volume, see `/Volumes/edu_access/00-source/raw/psa/SHA256SUMS.txt`). Local copy for profiling: `raw-data/psa/original/` |

The file name carries `06Feb2026`. The PSA press release for these estimates, "881 Cities and Municipalities Recorded Poverty Incidence of 20 Percent or Lower in 2023" (Reference Number 2026-43), is dated 6 February 2026, which matches. The workbook reproduces the press release's figures: for example, 881 of the 1,611 units with a 2023 estimate have poverty incidence of 20 or less, the same count as the headline (`profile.md`, X-2).

## Publisher documentation

The workbook has no data dictionary or metadata sheet. Its own documentation is the title, three footnotes, and a source line. The PSA press release for the same estimates (below) adds a definition, the method, and the data inputs.

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| Title, footnotes and source line on the sheet | inside the workbook above | same as the file | Footnote 1 (standard deviation = poverty incidence x coefficient of variation / 100), footnote 2 (Bumbaran renamed Amai Manabilang), footnote 3 (no estimate for Kalayaan, Palawan) |
| PSA press release "881 Cities and Municipalities Recorded Poverty Incidence of 20 Percent or Lower in 2023", Reference Number 2026-43, released 6 February 2026 | https://psa.gov.ph/statistics/poverty-sae/node/1684082420 | not applicable (web page, read in a browser on 2026-10-01) | A. Methodology and Coverage; B. Highlights (definition of poverty incidence, Table 1); C. Reliability and Precision (Table 2) |

The press release defines poverty incidence as the proportion of the population with an income below the poverty threshold (persons, not families), and says the 2023 estimates use Small Area Estimation (Census Empirical Best/Bayes) with the 2020 census, the 2023 Family Income and Expenditure Survey, the January 2024 Labor Force Survey, and other sources. Still UNVERIFIED: the poverty threshold value (footnote 3 of the press release), the method behind the confidence interval and standard error, and whether the 2018 and 2021 estimates use the same method.

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines, 18 region banner rows (includes Negros Island Region) |
| Geographic level | City or municipality, one row each, under region and province labels. 14 rows are Manila sub-municipalities. Highly urbanized cities are not in the file (`noHUC` in the file name). The press release says the 2023 estimates cover the 14 sub-municipalities of Manila, 114 cities, and 1,483 municipalities, and exclude the highly urbanized cities and the Cities of Isabela and Cotabato, whose estimates are in the 2023 Official Poverty Statistics (direct estimation) |
| Time coverage | 2018, 2021 and 2023 estimates in one wide table |
| Time basis | The 2023 estimates use the 2023 Family Income and Expenditure Survey and the January 2024 Labor Force Survey (press release 2026-43). The inputs for 2018 and 2021 are not stated. UNVERIFIED whether the years are calendar years or survey reference periods |
| Update frequency | UNVERIFIED. Three estimate years so far |
| Population covered | 1,611 of 1,612 listed units have values. In PSGC 2Q 2026, 35 cities are not in the file (33 highly urbanized cities, Isabela, and Cotabato; explained by the press release) and 9 municipalities are not (Pateros and 8 Special Geographic Area municipalities; not explained). See `profile.md`, X-1 and S-2 |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per city or municipality (wide: five measures for each of three years). Region banner rows carry only a region name |
| Candidate primary key | `PSGC ID` (1,612 unit rows, 1,612 unique). Stored as a number, so leading zeros are lost |
| Candidate join keys | `PSGC ID` left-padded to 6 digits, plus `000`, equals the PSGC 2Q 2026 `Correspondence Code` for all 1,612 rows (checked in `profile.md`, X-1). Join on the ID; names are for display and review only. Names alone are ambiguous (1,397 distinct in 1,612 rows) and 61 differ from the PSGC spelling. To attach these values to a DepEd place name, go through the PSGC code, and match the name only inside its parent |
| PSGC available? | Yes, but as a 5- or 6-digit ID, not the 10-digit PSGC. It equals the first six digits of the older 9-digit PSGC, so it identifies the city or municipality only. Province, region and city are derived from the padded ID prefix. The PSGC version is not stated |
| Personally identifiable or sensitive fields | None. Area-level estimates |
| Provenance fields in the source | Title, three footnotes and a source line. No per-row provenance |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column | Expected | Actual | Notes |
|---|---|---|---|
| `PSGC ID` | identifier (text) | number | 1,073 of 1,612 IDs have 5 digits because the leading zero was dropped. Blank on region banner rows |
| `Region/Province` | text | text | Region name on banner rows; province or district label on the first row of each group. One `(Continued)` label and one misplaced label (see below) |
| `Municipality/City` | text | text | 37 names carry a former name in parentheses. Footer says Bumbaran was renamed, but the row still reads Bumbaran |
| `Poverty Incidence <year>` | decimal (percent) | number | Percent scale (1 to 90). 2018 has 2 decimals; 2021 and 2023 have 4 |
| `Coefficient of Variation <year>` | decimal | number | 2018 mostly 2 decimals; 2021 and 2023 full precision |
| `Standard Error <year>` | decimal | number | Full precision, except 2018 (about half are 2 decimals) |
| `90% Confidence Interval Lower/Upper Limit <year>` | decimal (percent) | number | 2023 has a lower limit below zero |
| (column S) | none | empty | Inside the filter range but has no values |

## Ingestion

Contract: [`config/ingestion/psa_poverty_stat.json`](../../../../config/ingestion/psa_poverty_stat.json) (format `xlsx_sheet`, D-018). It pins the workbook above by its SHA-256, the sheet, the layout found in O-1, the 18 column names, the used range A1:S1641, and the counts on this card (1,630 body rows: 1,612 unit rows and 18 region banner rows; 6 footer rows). Every row of the used range goes to Bronze, labelled title, header, unit, region banner, or footer, so no worksheet row is dropped; column S is empty and not loaded. The known problems below are recorded as WARN checks with their profiled counts on every load, and are kept as received in Bronze (`edu_access.`02-bronze`.psa_poverty_stat_raw`). How it loads and how to check it: [ingestion.md, PSA Poverty Stat](../../../operations/ingestion.md#psa-poverty-stat-xlsx-workbook). Status stays `profiled`; loading into `dev` does not accept the source. Silver (`psa_poverty_stat_clean`, one row per unit and estimate year, D-034) is described in [silver.md, PSA Poverty Stat](../../../operations/silver.md#psa-poverty-stat) and its [data dictionary](../../silver/psa-poverty-stat-clean.md).

## Known quality problems

See [profile.md](profile.md) for evidence.

- **Observed:** `PSGC ID` lost its leading zeros. 1,073 IDs have 5 digits and must be padded to 6.
- **Observed:** the file is wide by year, and only one row is missing all values (Kalayaan, Palawan, footnote 3).
- **Observed:** province labels appear on the first row of each group only, and some are wrong: one `(Continued)` label (row 1551, Pualas), and seven rows (Barobo to Carrascal) sit under `Surigao del Norte` although their codes are Surigao del Sur.
- **Observed:** `Lanao del Sur` appears as a label twice in a row, and Maguindanao del Norte and del Sur share province code `1538` because the workbook groups Maguindanao (sheet name).
- **Observed:** Negros Island Region rows carry two region prefixes in the ID (06 and 07, 31 rows each), so region cannot be derived from the ID alone.
- **Observed:** 2021 standard error disagrees with the coefficient of variation and interval for 133 rows, all in CALABARZON.
- **Observed:** three lower limits are zero or negative (Adams 2018, Port Area 2021, Ivana 2023).
- **Observed:** coverage gap: 33 highly urbanized cities, City of Isabela, City of Cotabato, Pateros, and 8 Special Geographic Area municipalities are not in the file.
- **Observed:** 61 names differ from PSGC spelling (for example `Tondo` vs `Tondo I/II`, `City of Baliuag` vs `City of Baliwag`).
- **Suspected:** the 2021 standard errors for CALABARZON were computed differently from the other regions. To test with the publisher.

## Limitations for analysis

- Estimates are model-based small-area estimates with wide uncertainty. Between 5% and 11% of estimates have a coefficient of variation above 20 in each year (10.6% in 2018, 5.2% in 2021, 9.7% in 2023). Compare units only with their intervals.
- Three time points, and UNVERIFIED whether they are comparable across years (method, definition, and geography may differ).
- Highly urbanized cities are missing, so school-level joins for those cities will have no poverty value.
- The ID is the city or municipality only, and it needs the padding rule and the PSGC version check before joining to the 10-digit PSGC.
- Names, labels and the hierarchy inside the sheet are not reliable keys. Use the ID.
- Cell values in 2021 and 2023 carry more decimals than the estimates justify. Do not treat the extra digits as precision.
