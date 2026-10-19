# 05 Gold

Facts and dimensions for the approved business question, built to the model in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).

**Sandbox build.** A draft for the dashboard, not team-approved. Nine tables are
the pull-request versions, merged here before review: #168 (school, school
year, education level, classroom and teacher capacity, source availability)
and #193 (city, barangay, school-age population). The other three are this
sandbox's own, kept as a reference for their follow-on issues:
`fact_school_enrollment`, `dim_city_poverty` and `fact_city_population`.

Each build writes `<table>_candidate`, and its `90_validate_<table>.sql` gate
publishes it only when no check FAILs, so a failed gate keeps the last good
table. The job waits only for the gates each table reads (D-051).

| Table | Grain | From |
|---|---|---|
| `dim_school` | One enrollment school, latest non-blank name | #168 |
| `dim_school_year` | One enrollment school year | #168 |
| `dim_education_level` | ES, JHS, SHS | #168 |
| `dim_city_municipality` | 1,642 PSGC cities and municipalities, plus `UNKNOWN` and `EXCLUDED` | #193 |
| `dim_barangay` | PSGC barangays, one `<city code>-UNKNOWN` per city, plus `UNKNOWN` and `EXCLUDED` | #193 |
| `dim_city_poverty` | One regular city or municipality, poverty 2023 (D-046) | sandbox |
| `fact_school_enrollment` | School x school year x level, all sectors | sandbox |
| `fact_school_classroom_capacity` | Public school x school year (D-038) | #168 |
| `fact_school_teacher_capacity` | Public school x school year x level (D-038) | #168 |
| `fact_city_population` | Regular city x 2024 | sandbox |
| `fact_city_school_age_population` | City x 2020/2024 x age 5-24 x sex | #193 |
| `fact_school_year_source_availability` | School year x DepEd source | #168 |

Sandbox changes on top of the pull requests:

- **Run logging.** Every Gold build records a `gold_build` run in
  `01-control.pipeline_runs`, and its gate marks the run failed or succeeded,
  as Silver and Integration do. Neither pull request does this yet.
- **SGA census clusters go to `EXCLUDED`.** The 8 2020 Special Geographic Area
  clusters are PSA groupings with no PSGC unit, kept outside city analysis on
  purpose, which is the data model's `EXCLUDED` member. #193 uses `UNKNOWN`;
  this is the sandbox's answer to the open question there.

Left as #193 has it, to settle with Sara on #193: the 119 LGUs whose province
or region changed (Negros Island Region, Sulu, Maguindanao) are marked not
comparable 2020 to 2024, following the specification literally, although their
own territory did not change.

The sandbox's own three tables, choices the model leaves open:

- **`fact_school_enrollment` geography** comes from the #189 school map: a
  matched city and barangay keep their codes, a matched city without a
  barangay uses `<city code>-UNKNOWN`, an unmatched or ambiguous city
  `UNKNOWN`, and an excluded one `EXCLUDED`. `psgc_match_status` is the
  city-level map status.
- **Enrollment applicability.** The g11/g12 `unique` counts apply from SY
  2024-25 and the g11 SSHS counts from SY 2025-26, DepEd's published start years.
- **D-046 pinned counts** (1,597 / 1 / 44) FAIL only on the PSGC 2Q 2026 master
  (1,642 units); on test fixtures they WARN.
- `COUNT_IF` is wrapped in `COALESCE(..., 0)` because DuckDB returns NULL where
  Spark returns 0 (no rows, or every predicate NULL).
