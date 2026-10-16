# ETL table registry

The machine-readable registry is [`config/tables.yml`](../../config/tables.yml).
It fixes source-aligned Bronze and Silver names for the datasets already known,
without pretending that the business problem or analytical questions are final.

## Finalized source-aligned names

| Dataset | Bronze table | Silver table | Silver quarantine |
|---|---|---|---|
| DepEd enrollment, SY 2023-24 through 2025-26 | `deped_enrollment_raw` | `deped_enrollment_clean` | `deped_enrollment_quarantine` |
| DepEd facilities, SY 2023-24 | `deped_facilities_raw` | `deped_facilities_clean` | `deped_facilities_quarantine` |
| DepEd personnel, SY 2023-24 | `deped_personnel_raw` | `deped_personnel_clean` | `deped_personnel_quarantine` |
| PSA PSGC workbook, `PSGC` sheet | `psa_psgc_raw` | `psa_psgc_clean` | `psa_psgc_quarantine` |
| PSA poverty statistics | `psa_poverty_stat_raw` | `psa_poverty_stat_clean` | `psa_poverty_stat_quarantine` |
| HDX ADM3 boundaries | `hdx_adm3_raw` | `hdx_adm3_clean` | `hdx_adm3_quarantine` |
| DepEd EMISD enrollment with PSGC and coordinates | `deped_enrollment_psgc_raw` | not named yet (its Silver issue, #137) | not named yet |

Implemented source-aligned Bronze and Silver tables are listed in
[`etl/03_silver/README.md`](../../etl/03_silver/README.md). Gold tables supported
by the current reviewed inputs are listed below.

Each Silver table and Silver quarantine also has a **candidate** copy with the
suffix `_candidate` (for example `deped_enrollment_clean_candidate`): the build
writes it, the gate checks it, and only a build that passes is copied to the
Silver table, so a failed build never replaces the last good one (D-025, #119).
Candidate tables are not read downstream. This is unrelated to the draft
Integration names below, which the registry calls candidates too.

The three enrollment school years belong in one table. `school_year` identifies
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
90_validate_<table>.sql
```

The exact future file names are recorded beside each table in
`config/tables.yml`. A registry entry does not mean the SQL file has been
implemented.

## Integration drafts

Implemented: `deped_annex_mother_map`, one row per annex school and school year.
It keeps the mother ID and match method NULL while the approved DepEd releases
provide no reliable link, and lists every unmatched annex with evidence (D-044).

These are working names only:

| Candidate table | Candidate file | Intended grain |
|---|---|---|
| `deped_school_psgc_map` | `01_map_deped_school_psgc.sql` | One reviewed DepEd school-geography mapping to PSGC |
| `psa_poverty_psgc_map` | `02_map_psa_poverty_psgc.sql` | One reviewed poverty-statistic geography mapping to PSGC |
| `hdx_adm3_psgc_map` | `03_map_hdx_adm3_psgc.sql` | One reviewed HDX ADM3 feature mapping to PSGC |

Do not create these tables until their keys, match statuses, review workflow,
and PSGC-version behavior are agreed. Gold names proposed in #45 are documented
in [`docs/architecture/data-model.md`](../architecture/data-model.md). They
remain design-only until the team and mentor approve the ERD and Integration
prerequisite #44 is ready. Analytics names remain deferred until the metric
contract is approved.

## Gold tables

| Table | Grain | Status |
|---|---|---|
| `dim_city_municipality` | One PSGC city or municipality, plus technical members | Deferred for Integration geography maps |
| `dim_barangay` | One PSGC barangay, plus technical members | Deferred for Integration geography maps |
| `dim_school` | One DepEd school | Implemented |
| `dim_school_year` | One school year | Implemented |
| `dim_education_level` | One education reporting level: ES, JHS, or SHS | Implemented |
| `dim_city_poverty` | One city or municipality with its selected 2023 poverty context | Deferred for poverty-to-PSGC mapping |
| `fact_school_enrollment` | School x school year x education level | Deferred for school-to-PSGC mapping |
| `fact_school_classroom_capacity` | School x school year | Implemented for SY 2023-24 |
| `fact_school_teacher_capacity` | School x school year x education level | Implemented for SY 2023-24 |
| `fact_city_population` | City or municipality x reference year | Deferred with `dim_city_municipality` |
| `fact_city_school_age_population` | City or municipality x reference year x single year of age x sex | Deferred until its source reaches Silver and Integration |
