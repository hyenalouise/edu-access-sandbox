# Analytics outputs

Every column of the five tables in `` edu_access.`06-analytics` ``, the tables planners and the dashboard read. Why each measure exists and its limits are in the [metric specification](../business/metric-specification.md); how the classroom queue is ranked is in [`etl/06_analytics/`](../../etl/06_analytics/README.md). The Gold tables they read are in the [data model](../architecture/data-model.md).

`tests/test_analytics_priority.py` builds each table and fails if its columns differ from this page.

| Table | Grain | Answers |
|---|---|---|
| [`ap1_school_provision`](#ap1_school_provision) | One regular city or municipality, SY 2023-24 | AP1 · Schools: context only, not ranked |
| [`ap2_classroom_pressure`](#ap2_classroom_pressure) | One regular city or municipality, SY 2023-24 | AP2 · Classrooms |
| [`ap3_teacher_pressure`](#ap3_teacher_pressure) | One regular city or municipality, SY 2023-24, with ES, JHS and SHS side by side | AP3 · Teachers: context only, not ranked |
| [`ap4_enrollment_trend`](#ap4_enrollment_trend) | One city or municipality member and school year, SY 2020-21 to 2025-26 | AP4 · Population and enrollment: context only |
| [`lgu_priority_matrix`](#lgu_priority_matrix) | One regular city or municipality, SY 2023-24 | AP1 to AP4 side by side, and the D-060 classroom review queue |

## Reading the columns

- **Types** are the Databricks types. The local DuckDB run shows counts as `HUGEINT` and text as `VARCHAR`.
- **Missing is not zero.** A count is 0 only when nothing was found. A ratio is NULL when its denominator is 0 or missing.
- **Percent:** a `_pct` column is 0 to 100, except the AP4 change columns (`enrollment_change_pct_*`, and `ap4_enrollment_change_pct` copied from them), which are fractions (0.05 is 5%). A `_share` column is a fraction.
- **Schools counted:** AP1 to AP3 count public schools matched to a city or municipality (`psgc_match_status = 'matched'`) in SY 2023-24. A school is **active** when an offered level has learners. A **blank** school offers a level but publishes no count for any of them: it is not active, but it counts against coverage as missing data.
- **Assessed:** each output has a coverage gate. When it is not met, `is_assessed` is FALSE and `not_assessed_reason` says why. The ratio stays in the row, but it must not be compared with other cities and municipalities.

## LGU columns

AP1, AP2, AP3 and `lgu_priority_matrix` start with these, from `dim_city_municipality` (`member_type = 'regular'`, 1,642 rows):

| Column | Type | Meaning |
|---|---|---|
| `city_mun_psgc_code` | STRING | Key: the city or municipality's PSGC code |
| `city_mun_name` | STRING | PSGC name |
| `lgu_type` | STRING | `city` or `municipality` |
| `province_psgc_code` | STRING | Parent province; NULL for highly urbanized cities and Pateros |
| `province_name` | STRING | Parent province name |
| `region_psgc_code` | STRING | Parent region |
| `region_name` | STRING | Parent region name |
| `school_year` | STRING | Always `2023-24`, the only year with classroom and teacher counts |

## `ap1_school_provision`

Built by `01_answer_ap1.sql`. Starts with the [LGU columns](#lgu-columns).

| Column | Type | Meaning |
|---|---|---|
| `population_reference_year` | INT | Always 2024, the census year of `school_age_population` |
| `active_public_school_count` | BIGINT | Active public schools |
| `annex_school_count` | BIGINT | Active schools that are annex or extension schools, counted on their own (D-044) |
| `complete_enrollment_school_count` | BIGINT | Active schools with a count for every level they offer |
| `incomplete_enrollment_school_count` | BIGINT | Active schools with at least one offered level blank |
| `blank_enrollment_school_count` | BIGINT | Blank schools |
| `public_school_enrollment` | BIGINT | Learners in the complete-enrollment schools |
| `school_age_population` | BIGINT | Residents aged 5 to 17, 2024 Census, male plus female; NULL when the census has no matched value |
| `learners_per_public_school` | DOUBLE | `public_school_enrollment` / `complete_enrollment_school_count` |
| `school_age_population_per_public_school` | DOUBLE | `school_age_population` / `active_public_school_count` |
| `coverage_pct` | DOUBLE | 100 × complete-enrollment schools / (active + blank schools) |
| `not_assessed_reason` | STRING | NULL when assessed; otherwise `no active public school`, `no school with complete enrollment`, or `coverage below 90%` |
| `is_assessed` | BOOLEAN | TRUE when `not_assessed_reason` is NULL |
| `measure_label` | STRING | Fixed text: a descriptive measure, not a school-establishment or priority measure |
| `code_revision` | STRING | Commit that built the row |

## `ap2_classroom_pressure`

Built by `02_answer_ap2.sql`. Starts with the [LGU columns](#lgu-columns). A school is **in the ratio** when it is active, has complete enrollment, and reports more than 0 instructional rooms (NSBI, all levels). It **passes the screen** when its learners / rooms is 50 or more.

| Column | Type | Meaning |
|---|---|---|
| `active_public_school_count` | BIGINT | Active public schools |
| `usable_room_school_count` | BIGINT | Active schools that report more than 0 instructional rooms |
| `ratio_school_count` | BIGINT | Schools in the ratio |
| `incomplete_enrollment_school_count` | BIGINT | Active schools with at least one offered level blank |
| `blank_enrollment_school_count` | BIGINT | Blank schools |
| `missing_room_school_count` | BIGINT | Active schools with no room count (not 0 rooms) |
| `zero_room_school_count` | BIGINT | Active schools that report 0 rooms |
| `public_school_enrollment` | BIGINT | Learners in active schools with complete enrollment |
| `eligible_learners` | BIGINT | Learners in the schools in the ratio |
| `reported_instructional_classrooms` | BIGINT | Rooms in the schools in the ratio |
| `congested_school_count` | BIGINT | Schools that pass the screen |
| `learners_in_congested_schools` | BIGINT | Learners in those schools: the affected learners |
| `learners_per_classroom` | DOUBLE | Pooled ratio: `eligible_learners` / `reported_instructional_classrooms` |
| `congested_learner_share_pct` | DOUBLE | 100 × `learners_in_congested_schools` / `public_school_enrollment` |
| `school_coverage_pct` | DOUBLE | 100 × schools in the ratio / (active + blank schools) |
| `learner_coverage_pct` | DOUBLE | 100 × `eligible_learners` / `public_school_enrollment`; the gate is 90 |
| `not_assessed_reason` | STRING | NULL when assessed; otherwise `no active public school`, `no usable classroom denominator`, or `learner coverage below 90%` |
| `is_assessed` | BOOLEAN | TRUE when `not_assessed_reason` is NULL |
| `congestion_benchmark` | DOUBLE | Always 50.0, the PIDS illustrative line |
| `benchmark_status` | STRING | `not assessed`, `reported congestion identified` (a school passes the screen), or `no reported congestion identified` |
| `measure_label` | STRING | Fixed text naming the PIDS-style illustrative screen |
| `code_revision` | STRING | Commit that built the row |

## `ap3_teacher_pressure`

Built by `03_answer_ap3.sql`. Starts with the [LGU columns](#lgu-columns). The `<level>_` columns appear three times, as `es_`, `jhs_` and `shs_`. A school offering a level is **usable** for it when it has a count for the level and more than 0 teachers there. An annex school that reports 0 teachers keeps its learners in the ratio instead of being dropped, since no mother-school link exists to move them to (D-044).

| Column | Type | Meaning |
|---|---|---|
| `offered_level_count` | BIGINT | Levels (of ES, JHS, SHS) that at least one active or blank public school offers |
| `passing_level_count` | BIGINT | Offered levels that pass the gate |
| `<level>_offered_school_count` | BIGINT | Active or blank public schools that offer the level |
| `<level>_incomplete_school_count` | BIGINT | Of those, schools with no count for the level |
| `<level>_usable_teacher_school_count` | BIGINT | Usable schools for the level |
| `<level>_zero_teacher_annex_school_count` | BIGINT | Annex schools with a count for the level and 0 teachers |
| `<level>_zero_teacher_annex_learners` | BIGINT | Learners at the level in those annex schools |
| `<level>_public_school_enrollment` | BIGINT | Learners at the level, in schools with a count for it |
| `<level>_eligible_learners` | BIGINT | Learners in usable schools and zero-teacher annexes |
| `<level>_teacher_count` | BIGINT | Teaching personnel at the level in usable schools (the positions listed in the metric specification) |
| `<level>_learners_per_teacher` | DOUBLE | `<level>_eligible_learners` / `<level>_teacher_count` |
| `<level>_school_coverage_pct` | DOUBLE | 100 × usable schools / offering schools |
| `<level>_learner_coverage_pct` | DOUBLE | 100 × `<level>_eligible_learners` / `<level>_public_school_enrollment` |
| `<level>_passes_gate` | BOOLEAN | Offered, has a ratio, and learner coverage is at least 90 |
| `is_assessed` | BOOLEAN | TRUE when at least one level is offered and every offered level passes |
| `not_assessed_reason` | STRING | NULL when assessed; otherwise `no active public school level` or `an offered level is below 90% learner coverage` (also used when an offered level has no ratio) |
| `<level>_benchmark_max_learners_per_teacher` | DOUBLE | ES 35 (historical study reference), JHS 36 and SHS 26.67 (80/3, derived deployment comparisons) |
| `<level>_benchmark_status` | STRING | `not applicable` (not offered), `not assessed` (fails the gate), or above / at or below the reference: `above historical study reference` for ES, `above derived deployment comparison` for JHS and SHS |
| `benchmark_status` | STRING | `pressure signal identified` (any passing level is above its reference), `not fully assessed` (none above, and an offered level fails the gate), `no pressure signal identified`, or `not assessed` (no level offered) |
| `measure_label` | STRING | Fixed text: the references do not estimate a teacher shortage |
| `code_revision` | STRING | Commit that built the row |

## `ap4_enrollment_trend`

Built by `04_answer_ap4.sql`. Key: `city_mun_psgc_code`, `school_year`. Unlike the other outputs, it has a row for the technical members too (`UNKNOWN`, `EXCLUDED`), so the rows add up to the national totals. Filter `member_type = 'regular'` for city and municipality results. It has no `code_revision` column.

| Column | Type | Meaning |
|---|---|---|
| `city_mun_psgc_code` | STRING | PSGC code, or `UNKNOWN` / `EXCLUDED` |
| `member_type` | STRING | `regular`, `unknown`, or `excluded` |
| `school_year` | STRING | e.g. `2023-24` |
| `school_year_start` | INT | First calendar year of the school year, e.g. 2023 |
| `enrollment_all_sectors` | BIGINT | Learners in Public, Private and SUC/LUC schools located there that year (Philippine Schools Overseas excluded); a school with any offered level blank is left out, not read as 0 |
| `public_school_enrollment` | BIGINT | The Public part of `enrollment_all_sectors` |
| `public_school_share` | DOUBLE | `public_school_enrollment` / `enrollment_all_sectors`, a fraction |
| `schools_counted` | BIGINT | Schools in `enrollment_all_sectors` |
| `schools_incomplete` | BIGINT | Schools left out because a level they offer is blank |
| `enrollment_change_from_previous_year` | BIGINT | Against the school year just before; NULL for the first year or when that year is missing |
| `enrollment_change_pct_from_previous_year` | DOUBLE | The same change as a fraction of the previous year |
| `first_school_year` | STRING | First school year in the data (`2020-21`) |
| `latest_school_year` | STRING | Latest school year in the data (`2025-26`) |
| `enrollment_first_school_year` | BIGINT | `enrollment_all_sectors` in the first school year |
| `enrollment_latest_school_year` | BIGINT | `enrollment_all_sectors` in the latest school year |
| `enrollment_change_first_to_latest` | BIGINT | Latest minus first |
| `enrollment_change_pct_first_to_latest` | DOUBLE | The same change as a fraction of the first year; NULL when the first year is 0 |
| `enrollment_trend` | STRING | `increasing`, `decreasing`, or `no change`, by the sign of the change, with no threshold; NULL for technical members |
| `census_year` | INT | 2020 on SY 2020-21, 2024 on SY 2024-25, NULL in other years |
| `population_source` | STRING | The census, e.g. `2024 Census of Population (POPCEN), PSA Total Population` |
| `population_reference_date` | DATE | Census reference date: 2020-05-01 or 2024-07-01 |
| `age_min` | INT | 5 on census years |
| `age_max` | INT | 17 on census years |
| `school_age_population` | BIGINT | Residents aged 5 to 17, male plus female, on census years |
| `population_enrollment_gap` | BIGINT | `school_age_population` − `enrollment_all_sectors`; negative where schools draw learners from outside |
| `gap_share` | DOUBLE | Gap / `school_age_population`, a fraction |
| `census_context` | STRING | `available`, `not available: no census in this school year`, or `not available: no census population for this member` |
| `is_2020_2024_geography_comparable` | BOOLEAN | FALSE where the territory changed between the censuses, for units in only one census, and for technical members |
| `enrollment_scope` | STRING | Fixed text: the sectors counted |
| `interpretation_note` | STRING | Fixed text: the gap is not an out-of-school count |

## `lgu_priority_matrix`

Built by `05_build_priority_matrix.sql` from the published AP1 to AP4 tables. Starts with the [LGU columns](#lgu-columns). It has no composite score, tier, or overall rank (D-060).

| Column | Type | Meaning |
|---|---|---|
| `ap1_learners_per_public_school` | DOUBLE | AP1 `learners_per_public_school` |
| `ap1_coverage_pct` | DOUBLE | AP1 `coverage_pct` |
| `ap1_assessed` | BOOLEAN | AP1 `is_assessed` |
| `ap1_public_school_enrollment` | BIGINT | AP1 `public_school_enrollment` |
| `ap1_school_age_population_per_public_school` | DOUBLE | AP1 `school_age_population_per_public_school` |
| `ap2_learners_per_reported_room` | DOUBLE | AP2 `learners_per_classroom` |
| `ap2_learner_coverage_pct` | DOUBLE | AP2 `learner_coverage_pct` |
| `ap2_assessed` | BOOLEAN | AP2 `is_assessed` |
| `ap2_screened_congested_school_count` | BIGINT | AP2 `congested_school_count` |
| `ap2_affected_learners` | BIGINT | AP2 `learners_in_congested_schools` |
| `ap2_affected_learner_share_pct` | DOUBLE | AP2 `congested_learner_share_pct` |
| `ap2_screen_status` | STRING | AP2 `benchmark_status` |
| `ap3_es_learners_per_teacher` | DOUBLE | AP3 `es_learners_per_teacher` |
| `ap3_jhs_learners_per_teacher` | DOUBLE | AP3 `jhs_learners_per_teacher` |
| `ap3_shs_learners_per_teacher` | DOUBLE | AP3 `shs_learners_per_teacher` |
| `ap3_fully_assessed` | BOOLEAN | AP3 `is_assessed` |
| `ap3_review_status` | STRING | AP3 `benchmark_status` |
| `ap4_gap_2020` | BIGINT | AP4 `population_enrollment_gap` on SY 2020-21 |
| `ap4_gap_2024` | BIGINT | AP4 `population_enrollment_gap` on SY 2024-25 |
| `ap4_gap_rate_2020_pct` | DOUBLE | 100 × AP4 `gap_share` on SY 2020-21 |
| `ap4_gap_rate_2024_pct` | DOUBLE | 100 × AP4 `gap_share` on SY 2024-25 |
| `ap4_gap_change` | BIGINT | 2024 gap − 2020 gap; NULL unless the geography is comparable |
| `ap4_enrollment_trend` | STRING | AP4 `enrollment_trend` |
| `ap4_enrollment_change_pct` | DOUBLE | AP4 `enrollment_change_pct_first_to_latest`: a fraction, not 0 to 100 |
| `classroom_priority_group` | STRING | `reported_congestion_screen` (AP2 assessed and has affected learners), `no_reported_congestion_screen` (assessed, none), or `data_review` (AP2 not assessed) |
| `classroom_priority_rank` | BIGINT | Only in `reported_congestion_screen`: `DENSE_RANK()` by affected learners, then affected schools, then pooled room ratio, all descending; ties share a rank. A triage order for review, not a shortage rank |
| `classroom_priority_basis` | STRING | Fixed text explaining the group |
| `rule_version` | STRING | `D-060` |
| `code_revision` | STRING | Commit that built the row |
