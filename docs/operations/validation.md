# Validation: totals from source to Gold

Issue #48. This page shows the key totals at every layer, from the published source file through Bronze, Silver and Integration to Gold. It explains each difference by a recorded cleaning rule or an unmatched count. Where an independent published figure exists, Gold is compared with it.

**As of:** Databricks `dev`, commit `7542cc0` (`main` after #202), job runs `1085767927326340` and `575313135268521` on 2026-10-20 (evidence `evidence/pipeline-runs/2026-10-20-gold-databricks-dev.md`, PR #204). Both runs gave the same values. The figures below are read from run `575313135268521` with read-only queries on warehouse `ba94770acbbc293c`. Reference values come from the source profiles in `docs/data/source-inventory/<source_id>/profile.md`.

**Result:**
- Every total reconciles.
- Every difference between layers is a recorded quarantine rule, a source row that is not a data unit, or a counted unmatched or excluded record.
- `data_quality_results` has **0 FAIL** in every layer for both runs: control 16, Bronze 24, Silver 649, Integration 177 and Gold 315 results each.
- The two published totals that can be checked independently, DepEd SY 2020-21 enrollment and PSA's 2024 census, both match.

## Source file → Bronze

Every current Bronze batch holds exactly the rows its source file has, and none is rejected (`01-control.ingestion_batches` joined to `current_batches`).

| Source | Period | Expected rows (contract) | Source rows | Bronze rows | Rejected |
|---|---|---:|---:|---:|---:|
| `deped_enrollment` | SY 2020-21 | 60,957 | 60,957 | 60,957 | 0 |
| | SY 2021-22 | 60,429 | 60,429 | 60,429 | 0 |
| | SY 2022-23 | 60,137 | 60,137 | 60,137 | 0 |
| | SY 2023-24 | 60,167 | 60,167 | 60,167 | 0 |
| | SY 2024-25 | 60,129 | 60,129 | 60,129 | 0 |
| | SY 2025-26 | 60,204 | 60,204 | 60,204 | 0 |
| `deped_enrollment_psgc` (EMISD) | SY 2023-24 | 60,285 | 60,285 | 60,285 | 0 |
| `deped_facilities` | SY 2023-24 | 60,167 | 60,167 | 60,167 | 0 |
| `deped_personnel` | SY 2023-24 | 60,167 | 60,167 | 60,167 | 0 |
| `psa_psgc` | 2026-Q2 | 43,768 | 43,768 | 43,768 | 0 |
| `hdx_boundaries` (ADM3) | 2025-02-13 | 1,642 | 1,642 | 1,642 | 0 |
| `psa_poverty_stat` | 2018, 2021, 2023 | 1,641 | 1,641 | 1,641 | 0 |
| `psa_school_age_population` | 2020 | 3,496 | 3,496 | 3,496 | 0 |
| | 2024 | 13,985 | 13,985 | 13,985 | 0 |

## DepEd enrollment

### Rows and learners, each layer

Learners are the sum of every count cell. Gold sums `learner_count` over ES, JHS and SHS from the `learners/<year>/<level>` gate results.

| School year | Profile total (O-3) | Silver rows (clean + quarantined) | Silver learners | Gold schools | Gold learners | Difference |
|---|---:|---:|---:|---:|---:|---|
| 2020-21 | 26,227,022 | 60,957 + 0 | 26,227,022 | 60,957 | 26,227,022 | none |
| 2021-22 | 27,560,661 | 60,429 + 0 | 27,560,661 | 60,429 | 27,560,661 | none |
| 2022-23 | 27,794,282 | 60,136 + 1 | 27,794,274 | 60,136 | 27,794,274 | 8 learners, 1 school (below) |
| 2023-24 | 27,081,292 | 60,167 + 0 | 27,081,292 | 60,167 | 27,081,292 | none |
| 2024-25 | 26,400,182 | 60,129 + 0 | 26,400,182 | 60,129 | 26,400,182 | none |
| 2025-26 | 25,935,863 | 60,204 + 0 | 25,935,863 | 60,204 | 25,935,863 | none |

- **SY 2022-23, 1 school, 8 learners:** quarantined in Silver with `school_id_malformed`. School `1404066` has a seven-digit ID; it is Immaculate Conception Academy of Dancalan Inc., with 8 Kindergarten learners (profile O-1, D-024). The Silver gate's `learners_reconcile` (27,794,274) counts the clean table.
- **Gold has three rows per school and year** (ES, JHS, SHS): 1,086,066 rows = 3 × 362,022 Silver rows (`rows_reconcile`). `learner_count_matches_silver` and `rows_match_silver` are 0.
- **The SY 2025-26 blanks do not change the totals.** The 189 offered levels with every count blank (40 ES, 29 JHS, 120 SHS; WARN `offered_all_blank`) have `learner_count` NULL in Gold and contribute 0 to the file total too.

### Where the learners are placed (Silver → Integration → Gold)

Each school year's geography comes from the school-to-PSGC map (D-049). An unmatched or ambiguous school goes to the `UNKNOWN` member, and a reviewed exclusion goes to `EXCLUDED`: overseas schools, and Special Geographic Area schools whose barangay does not match (D-031). No school is dropped.

| School year | Schools: matched / `UNKNOWN` / `EXCLUDED` | Learners: matched | `UNKNOWN` (ambiguous + unmatched) | `EXCLUDED` | Total |
|---|---|---:|---:|---:|---:|
| 2020-21 | 60,877 / 44 / 36 | 26,193,844 | 12,430 | 20,748 | 26,227,022 |
| 2021-22 | 60,356 / 38 / 35 | 27,528,668 | 13,435 | 18,558 | 27,560,661 |
| 2022-23 | 60,070 / 31 / 35 | 27,758,059 | 14,403 | 21,812 | 27,794,274 |
| 2023-24 | 60,108 / 16 / 43 | 27,049,274 | 4,825 | 27,193 | 27,081,292 |
| 2024-25 | 60,060 / 6 / 63 | 26,365,125 | 2,030 | 33,027 | 26,400,182 |
| 2025-26 | 60,122 / 17 / 65 | 25,899,213 | 3,043 | 33,607 | 25,935,863 |

In every year, matched + `UNKNOWN` + `EXCLUDED` equals the Silver total. The Gold gate counts these schools as WARN `schools_city_unknown` (152 across the six years) and `schools_barangay_unknown` (583).

### By region, SY 2024-25

Silver keeps DepEd's own region label. Gold places each school in its PSGC 2Q 2026 city and that city's region (D-012). The two agree except where PSGC places a school elsewhere, or where it is on a technical member:

| DepEd region | Schools | PSGC region in Gold | Schools | Learners |
|---|---:|---|---:|---:|
| BARMM | 2,951 | BARMM | 2,445 | 913,944 |
| | | Region IX: Sulu, moved by EO No. 91, s. 2025 (D-012) | 478 | 162,014 |
| | | `EXCLUDED`: Special Geographic Area schools not matched (D-031) | 28 | 8,172 |
| PSO | 35 | `EXCLUDED`: Philippine Schools Overseas | 35 | 24,855 |
| Region II | 2,908 | Region II / `UNKNOWN` | 2,906 / 2 | 867,019 / 320 |
| Region III | 5,193 | Region III / `UNKNOWN` | 5,192 / 1 | 2,907,339 / 1,178 |
| Region IV-A | 6,011 | Region IV-A / `UNKNOWN` | 6,009 / 2 | 3,871,329 / 432 |
| Region IX | 2,877 | Region IX / `UNKNOWN` | 2,876 / 1 | 1,021,297 / 100 |
| The other 13 regions | | Same region | as DepEd | |

So Gold's Region IX has 3,354 schools (2,876 + 478) and BARMM 2,445. Both region columns add up to 60,129 schools and 26,400,182 learners.

## DepEd facilities and personnel (SY 2023-24, public schools)

| Measure | Source / Bronze | Silver | Gold | Difference |
|---|---:|---:|---:|---|
| Schools | 60,167 | 60,167 | 47,818 public (`fact_school_classroom_capacity`) | The facility measures are public only (profile O-3). Private, SUC/LUC and PSO rows carry no facility values |
| All facility count cells | | 1,213,740 (`counts_reconcile` = Bronze) | | |
| Instructional rooms (ES + JHS + SHS) | | 656,360 | 656,360 | none. 608 schools have every room count blank, so their total is NULL, not 0 (D-047, WARN 669 offered levels) |
| Teacher rows (school × level) | 60,167 schools | 60,167 | 143,454 = 47,818 × 3 | `source_totals_and_nulls_reconcile` 0 |
| Approved teachers (`teacher_count`) | | | 935,421 | 85,810 of the 143,454 school-and-level rows are NULL (no value published for an included role), kept NULL, never 0 |

## PSGC and population

| Measure | Source | Bronze / Silver | Gold | Difference |
|---|---:|---:|---:|---|
| PSGC rows (2Q 2026) | 43,768 | 43,768 / 43,768 | | none |
| Provinces / cities / municipalities / barangays | 82 / 149 / 1,493 / 42,010 (`National Summary`, O-5) | same | 149 + 1,493 = 1,642 regular `dim_city_municipality` members; 42,010 regular `dim_barangay` members | Gold adds technical members only: `UNKNOWN`, `EXCLUDED`, and one `<code>-UNKNOWN` per city or municipality |
| Population, 18 regions | 112,727,776 (O-4) | | 112,727,776 (`fact_city_population`, `total_equals_regions`) | none |

## PSA school-age population (2020 and 2024 censuses)

| Measure | 2020 | 2024 |
|---|---:|---:|
| Silver, country row, ages 5–24, male + female, Total Population | 42,869,567 | 42,178,032 |
| Silver, sum of the city and municipality rows | 42,869,567 | 42,178,032 |
| Gold `fact_city_school_age_population`, ages 5–24 | 42,869,567 | 42,178,032 |
| Gold, ages 5–17 | 28,680,299 | 27,569,038 |
| Map: places matched / unmatched | 1,634 / 8 | 1,642 / 0 |

- **The 8 unmatched 2020 places are the Interim Province clusters.** They are not LGUs and were reviewed as such (D-055). Their 96,899 people (ages 5–24) sit on `EXCLUDED` in Gold, so the total still reconciles (WARN `excluded_member_population`).
- **The cells reconcile too.** `cells_match_silver` is 0: every Gold row equals its Silver male or female cell.

## PSA poverty and HDX boundaries

| Measure | Source | Silver | Integration | Gold |
|---|---:|---:|---:|---:|
| Poverty rows | 1,641 sheet rows | 1,612 units × 3 years = 4,836 | 4,836 matched | `dim_city_poverty`: 1,642 = 1,597 `estimated` + 1 `no_estimate` (Kalayaan) + 44 `not_in_source` |
| HDX ADM3 features | 1,642 | 1,642 | 1,634 matched, 8 unmatched | 1,634 cities and municipalities with `land_area_sqkm`; 8 without |

- **Poverty, sheet rows:** the 29 rows between 1,641 sheet rows and 1,612 units are headers, region banners, footnotes and the source line (Silver `rows_kind_*`, `bronze_rows_accounted`).
- **Poverty, the 44 `not_in_source`:** 33 highly urbanized cities, Isabela City, Cotabato City, Pateros, and the 8 Special Geographic Area municipalities (D-046).
- **HDX, the 8 unmatched features:** the Special Geographic Area units, reviewed unmatched (D-052). So the 8 SGA municipalities have no land area (WARN `regular_without_land_area`).

## DepEd school-to-PSGC crosswalk (EMISD, SY 2023-24)

| Measure | Rows |
|---|---:|
| Bronze | 60,285 |
| School rows in Bronze (`profiled_bronze_unit_rows`) | 60,275 = 60,167 main block + 108 appended (profile O-2) |
| Other Bronze rows: titles, notes, blank (`profiled_bronze_other_rows`) | 10 |
| Silver clean | 60,273 |
| Silver quarantined | 2: `1406363` `school_id_malformed`, and one copy of `404520` `school_id_identical_copy` (profile O-3) |

## Independent published figures

| Figure | Published | Pipeline | Result |
|---|---:|---:|---|
| DepEd enrollment, SY 2020-21, all sectors | 26,227,022: DepEd news release, [2021-09-23](https://www.deped.gov.ph/2021/09/23/deped-credits-parents-learners-for-exceeding-100-enrollment-turnout-for-sy-2021-2022/) | 26,227,022 in Bronze, Silver and Gold | equal |
| PSA 2024 Census of Population, Philippines | 112,729,484, of which 112,727,776 are in the 18 regions and the rest are Filipinos in Philippine embassies, consulates and missions abroad: [PSA press release](https://psa.gov.ph/content/2024-census-population-popcen-population-counts-declared-official-president), declared official by Proclamation No. 973, s. 2025 | 112,727,776 in `fact_city_population` (the 18 regions) | equal; the 1,708 difference is the Filipinos abroad, as the PSGC `Notes` D.2 also states (profile O-4) |

DepEd's final totals for SY 2021-22 to 2025-26 have not been found: the figures DepEd announced were counts taken while enrollment was still open (deped_enrollment profile S-3, open). The PSA school-age workbooks have no separate published national total to compare with: their national row is the publisher's own.

## Not covered

- **Analytics** (AP1 to AP4, the priority matrix): not built in this deployment (#199, #203).
- **Row-level hashes on Databricks:** rows are compared through the gates' reconciliation checks and the identical check values of the two runs.
- **Bronze learner sums:** Bronze keeps the published text. The learner total per file is the profile's (O-3), and Silver's `learners_reconcile` compares the clean table with it.

## Rerunning this page

After a new full run, rerun these read-only queries against the run's `run_id` and update the tables in the same pull request as the change that moved them:
- Bronze: `01-control.ingestion_batches` joined to `current_batches`
- Silver: row counts of each `*_clean` and `*_quarantine` table, and the `learners_reconcile` / `rows_reconcile` / `counts_reconcile` results
- Gold: `fact_school_enrollment` grouped by `school_year`, member and `psgc_match_status`, and the Gold `rows_reconcile` and `learners/<year>/<level>` results
- `data_quality_results` grouped by `layer` and `status`

A changed total that no rule or unmatched count explains is a finding: open a data issue for it.
