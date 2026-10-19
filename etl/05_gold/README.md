# 05 Gold

Facts and dimensions for the approved business question.

The provisional model, grains, keys, analytical-question mapping, and ERD are in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).
The AP1 to AP4 implementation contract is D-050. Building these source-aligned
tables does not by itself make an analytical result or dashboard output ready.

Implemented dimensions whose reviewed inputs are available:

- `dim_school`
- `dim_school_year`
- `dim_education_level`

Implemented facts whose reviewed inputs are available:

- `fact_school_classroom_capacity`
- `fact_school_teacher_capacity`
- `fact_school_year_source_availability`

The following Gold tables are deliberately not implemented in this pull request
and remain assigned to follow-on work. Their disabled placeholders stay in the
job, and no empty substitute is published:

- `dim_city_municipality`
- `dim_barangay`
- `dim_city_poverty`
- `fact_school_enrollment`
- `fact_city_population`
- `fact_city_school_age_population`

Enrollment and `dim_school_year` cover SY 2020-21 through SY 2025-26. Classroom
and teacher capacity currently cover SY 2023-24 only.
`fact_school_year_source_availability` records those source-level gaps separately
from the school-level coverage checks.

Each build writes a candidate table. Its `90_validate_*` gate checks grain, foreign keys, source reconciliation, and coverage before replacing the published table. A failed gate leaves the last good Gold table unchanged. Job dependencies follow D-051, so each table waits only for the source and dimension gates it reads.
