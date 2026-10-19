# 05 Gold

Facts and dimensions for the approved business question, built to the model in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).

**Sandbox build.** This is a draft built on top of #189 (school-to-PSGC map) and
#190 (D-057) so the team can draft a dashboard. The model is still under review
in #45, and the choices below that the model leaves open are this sandbox's, not
team decisions.

Each table has a `NN_build_<object>.sql` task that writes `<object>_candidate`
and a `90_validate_<object>.sql` gate that records its checks in
`01-control.data_quality_results` and publishes the candidate only when no check
FAILs, so a failed build keeps the last good table (as D-025 does for Silver).
Each build records a `gold_build` run in `01-control.pipeline_runs`.

| Table | Grain | Reads |
|---|---|---|
| `dim_school` | One enrollment school, named from its latest school year | enrollment Silver |
| `dim_school_year` | One enrollment school year | enrollment Silver |
| `dim_education_level` | ES, JHS, SHS | none |
| `dim_city_municipality` | 1,642 PSGC 2Q 2026 cities and municipalities, plus `UNKNOWN` and `EXCLUDED` | PSGC Silver, HDX map (land area) |
| `dim_barangay` | 42,010 PSGC barangays, one `UNK-<city code>` per city, plus `UNKNOWN` and `EXCLUDED` | PSGC Silver |
| `dim_city_poverty` | One regular city or municipality, poverty 2023 (D-046) | poverty map |
| `fact_school_enrollment` | School x school year x level, all sectors | enrollment Silver, school map |
| `fact_school_classroom_capacity` | School x school year | facilities Silver |
| `fact_school_teacher_capacity` | School x school year x level | personnel Silver |
| `fact_city_population` | Regular city x 2024 | PSGC Silver |
| `fact_city_school_age_population` | City x 2020/2024 x age 5-24 x sex | school-age Silver and map |
| `fact_school_year_source_availability` | School year x DepEd source | the three DepEd Silver tables |

Choices the model leaves open, made here:

- **Technical member codes.** `UNKNOWN` (city not matched: unmatched or
  ambiguous), `EXCLUDED` (Philippine Schools Overseas, the schools the map
  excludes, and the 2020 Special Geographic Area census clusters), and
  `UNK-<city code>` for a school matched to a city but not a barangay.
- **`psgc_match_status`** on `fact_school_enrollment` is the city-level map
  status. A barangay that did not match shows as the city's `UNK-` member.
- **Enrollment applicability.** The g11/g12 `unique` counts apply from SY
  2024-25 and the g11 SSHS counts from SY 2025-26, DepEd's published start years.
- **Geography comparability.** `is_2020_2024_geography_comparable` is false for
  Makati, Taguig and the 8 Special Geographic Area municipalities. Province and
  region moves leave a city comparable at city grain.
- **D-046 pinned counts** (1,597 / 1 / 44) FAIL only on the PSGC 2Q 2026 master
  (1,642 units); on test fixtures they WARN.
- `COUNT_IF` is wrapped in `COALESCE(..., 0)` because DuckDB returns NULL where
  Spark returns 0 (no rows, or every predicate NULL).

Local run on the real deliveries (2026-10-19): every Gold gate passes. WARNs
remain for the 8 SGA municipalities without HDX land area, 152 school-years in
the unknown city, 277 excluded, 583 in an unknown barangay, blank and partial
room and teacher counts, and SY 2025-26 levels published blank.
