# ETL table registry

The machine-readable registry is [`config/tables.yml`](../../config/tables.yml).
It fixes the name of every table the job builds, from Bronze to Analytics.

## Finalized source-aligned names

| Dataset | Bronze table | Silver table | Silver quarantine |
|---|---|---|---|
| DepEd enrollment, SY 2020-21 through 2025-26 | `deped_enrollment_raw` | `deped_enrollment_clean` | `deped_enrollment_quarantine` |
| DepEd facilities, SY 2023-24 | `deped_facilities_raw` | `deped_facilities_clean` | `deped_facilities_quarantine` |
| DepEd personnel, SY 2023-24 | `deped_personnel_raw` | `deped_personnel_clean` | `deped_personnel_quarantine` |
| PSA PSGC workbook, `PSGC` sheet | `psa_psgc_raw` | `psa_psgc_clean` | `psa_psgc_quarantine` |
| PSA poverty statistics | `psa_poverty_stat_raw` | `psa_poverty_stat_clean` | `psa_poverty_stat_quarantine` |
| HDX ADM3 boundaries | `hdx_adm3_raw` | `hdx_adm3_clean` | `hdx_adm3_quarantine` |
| DepEd EMISD enrollment with PSGC and coordinates (the school-to-PSGC crosswalk) | `deped_enrollment_psgc_raw` | `deped_enrollment_psgc_clean` | `deped_enrollment_psgc_quarantine` |
| DepEd school-level enrollment with PSGC and coordinates, public schools only (a separate workbook) | `deped_psgc_coordinates_raw` | `deped_psgc_coordinates_clean` (placeholder) | `deped_psgc_coordinates_quarantine` (placeholder) |
| PSA school-age population, 2020 and 2024 census workbooks | `psa_school_age_population_raw` | `psa_school_age_population_clean` | `psa_school_age_population_quarantine` |

The registry and job configuration are the source of truth for implementation
and enablement status; this table fixes names and is not a progress checklist.

Each Silver table and Silver quarantine also has a **candidate** copy with the
suffix `_candidate` (for example `deped_enrollment_clean_candidate`): the build
writes it, the gate checks it, and only a build that passes is copied to the
Silver table, so a failed build never replaces the last good one (D-025, #119).
Candidate tables are not read downstream.

The enrollment school years belong in one table. `school_year` identifies
the delivery year; it should not be encoded in separate table names. Likewise,
the PSGC workbook and its `PSGC` sheet are one logical input, not separate
tables. The HDX name includes `adm3` because the current scope is specifically
the city/municipality layer.

Fully qualified names use the catalog and layer schema. For example:

```sql
edu_access.`02-bronze`.deped_enrollment_raw
edu_access.`03-silver`.deped_enrollment_clean
```

## File names

Bronze and Silver use the source order recorded in `config/tables.yml`; the
same number follows a dataset across both layers. Validation gates use `90`
because dependency order belongs in `databricks.yml`, not in the gate prefix:

```text
NN_create_<source>_raw.sql
NN_clean_<source>.sql
NN_map_<object>.sql
NN_build_<table>.sql
NN_answer_ap<N>.sql
90_validate_<table>.sql
```

The exact future file names are recorded beside each table in
`config/tables.yml`. A registry entry does not mean the SQL file has been
implemented.

## Integration tables

Implemented: `deped_annex_mother_map`, one row per annex school and school year.
It keeps the mother ID and match method NULL while the approved DepEd releases
provide no reliable link, and lists every unmatched annex with evidence (D-044).
Implemented: `hdx_adm3_psgc_map` (`03_map_hdx_adm3_psgc.sql`), one row per HDX ADM3
feature with its reviewed PSGC match, review status, and reason (D-052).
Implemented: `psa_poverty_psgc_map` (`02_map_psa_poverty_psgc.sql`), one row per PSA
poverty estimate row (`psgc_id`, `estimate_year`) with its `Correspondence Code` match
to PSGC and the estimate carried unchanged (D-054).
Implemented: `psa_school_age_population_psgc_map` (`05_map_psa_school_age_population_psgc.sql`),
one row per census year and city or municipality of the PSA school-age population, with its
reviewed PSGC match, the PSGC parent it was searched in, review status, and reason (D-055).
Implemented: `deped_school_psgc_map` (`01_map_deped_school_psgc.sql`), one row per enrollment
school, school year, and geographic level (`city_mun`, `bgy`), with its EMISD-code or reviewed
name match, including explicit unmatched, ambiguous, and excluded rows (#91, D-049).

No Integration working names remain. A new map follows the shape of `hdx_adm3_psgc_map`
(D-052) unless its own decision says otherwise.

## Gold names

| Table | Grain |
|---|---|
| `dim_city_municipality` | One PSGC city or municipality, plus technical members |
| `dim_barangay` | One PSGC barangay, plus technical members |
| `dim_school` | One DepEd school |
| `dim_school_year` | One school year |
| `dim_education_level` | One education reporting level: ES, JHS, or SHS |
| `dim_city_poverty` | One regular city or municipality with its selected 2023 poverty context; none for technical members |
| `fact_school_enrollment` | School x school year x education level |
| `fact_school_classroom_capacity` | School x school year |
| `fact_school_teacher_capacity` | School x school year x education level |
| `fact_city_population` | City or municipality x reference year |
| `fact_city_school_age_population` | City or municipality x reference year x single year of age x sex |
| `fact_school_year_source_availability` | School year x DepEd source (enrollment, facilities, personnel); added by D-051 |

All twelve are implemented and enabled in the job. Each build writes a
candidate and its gate publishes only after validation. Columns, keys, and the
ERD are in the [data model](../architecture/data-model.md).

## Analytics names

| Table | Grain |
|---|---|
| `ap1_school_provision` | One regular city or municipality, SY 2023-24 |
| `ap2_classroom_pressure` | One regular city or municipality, SY 2023-24 |
| `ap3_teacher_pressure` | One regular city or municipality, SY 2023-24, with ES, JHS, and SHS side by side |
| `ap4_enrollment_trend` | One city or municipality member (regular, `UNKNOWN`, or `EXCLUDED`) and school year |
| `lgu_priority_matrix` | One regular city or municipality, SY 2023-24, with its AP1 to AP4 evidence and its D-060 classroom review queue status |

All five are implemented and enabled in the job. Measures and the priority
rule are in [`etl/06_analytics/`](../../etl/06_analytics/README.md).
