# 05 Gold

Facts and dimensions for the approved business question, built to the model in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).

**Sandbox build.** A draft for the dashboard, not team-approved. All twelve
tables are the pull-request versions, merged here before review: #168 (school,
school year, education level, classroom and teacher capacity, source
availability), #193 (city, barangay, school-age population), #194
(`dim_city_poverty`), #195 (`fact_city_population`) and #196
(`fact_school_enrollment`).

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
| `dim_city_poverty` | One regular city or municipality, poverty 2023 (D-046) | #194 |
| `fact_school_enrollment` | School x school year x level, all sectors | #196 |
| `fact_school_classroom_capacity` | Public school x school year (D-038) | #168 |
| `fact_school_teacher_capacity` | Public school x school year x level (D-038) | #168 |
| `fact_city_population` | Regular city x 2024 | #195 |
| `fact_city_school_age_population` | City x 2020/2024 x age 5-24 x sex | #193 |
| `fact_school_year_source_availability` | School year x DepEd source | #168 |

Sandbox changes on top of the pull requests:

- **Run logging.** Every Gold build records a `gold_build` run in
  `01-control.pipeline_runs`, and its gate marks the run failed or succeeded,
  as Silver and Integration do. None of the pull requests does this yet.
- **SGA census clusters go to `EXCLUDED`.** The 8 2020 Special Geographic Area
  clusters are PSA groupings with no PSGC unit, kept outside city analysis on
  purpose, which is the data model's `EXCLUDED` member. #193 uses `UNKNOWN`;
  this is the sandbox's answer to the open question there.
- **#194's pinned checks WARN on test data.** Its pinned D-046 counts
  (1,642 / 1,597 / 1 / 44), its two Manila checks and its two map-row checks
  FAIL on any data but the real masters, so the local job's
  `90_validate_dim_city_poverty` failed on the test fixtures once
  `dim_city_municipality` was built (#193). Here they WARN when the dimension
  has fewer than 1,000 regular members, which only test data has, and FAIL
  otherwise, so a member added to or lost from the 1,642 still fails. The team
  repo does not hit this yet: its poverty task waits on
  `90_validate_dim_city_municipality`, which is still disabled on main.

Left as #193 has it, to settle with Sara on #193: the 119 LGUs whose province
or region changed (Negros Island Region, Sulu, Maguindanao) are marked not
comparable 2020 to 2024, following the specification literally, although their
own territory did not change.
