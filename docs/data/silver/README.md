# Silver tables

One data dictionary per Silver table, generated from the source's Bronze contract and reviewed Silver mapping (`python -m src.silver.cli dictionary`). How the tables are built, checked, and rerun: [docs/operations/silver.md](../../operations/silver.md).

| Source | Clean table | Quarantine | Dictionary |
|---|---|---|---|
| `deped_enrollment` | `deped_enrollment_clean` | `deped_enrollment_quarantine` | [deped-enrollment-clean.md](deped-enrollment-clean.md) |
| `psa_poverty_stat` | `psa_poverty_stat_clean` | `psa_poverty_stat_quarantine` | [psa-poverty-stat-clean.md](psa-poverty-stat-clean.md) |
| `deped_facilities` | `deped_facilities_clean` | `deped_facilities_quarantine` | [deped-facilities-clean.md](deped-facilities-clean.md) |
