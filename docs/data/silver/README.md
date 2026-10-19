# Silver tables

One data dictionary per Silver table, generated from the source's Bronze contract and reviewed Silver mapping (`python -m src.silver.cli dictionary`). How the tables are built, checked, and rerun: [docs/operations/silver.md](../../operations/silver.md).

| Source | Clean table | Quarantine | Dictionary |
|---|---|---|---|
| `deped_enrollment` | `deped_enrollment_clean` | `deped_enrollment_quarantine` | [deped-enrollment-clean.md](deped-enrollment-clean.md) |
| `deped_personnel` | `deped_personnel_clean` | `deped_personnel_quarantine` | [deped-personnel-clean.md](deped-personnel-clean.md) |
| `psa_poverty_stat` | `psa_poverty_stat_clean` | `psa_poverty_stat_quarantine` | [psa-poverty-stat-clean.md](psa-poverty-stat-clean.md) |
| `psa_psgc` | `psa_psgc_clean` | `psa_psgc_quarantine` | [psa-psgc-clean.md](psa-psgc-clean.md) |
| `deped_facilities` | `deped_facilities_clean` | `deped_facilities_quarantine` | [deped-facilities-clean.md](deped-facilities-clean.md) |
| `hdx_boundaries` | `hdx_adm3_clean` | `hdx_adm3_quarantine` | [hdx-adm3-clean.md](hdx-adm3-clean.md) |
| `psa_school_age_population` | `psa_school_age_population_clean` | `psa_school_age_population_quarantine` | [psa-school-age-population-clean.md](psa-school-age-population-clean.md) |
