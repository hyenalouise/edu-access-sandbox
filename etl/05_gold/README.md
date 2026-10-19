# 05 Gold

Facts and dimensions for the approved business question.

The approved implementation contract, grains, keys, analytical-question mapping, and ERD are in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).

Implemented dimensions whose reviewed inputs are available:

- `dim_school`
- `dim_school_year`
- `dim_education_level`

Implemented facts whose reviewed inputs are available:

- `fact_school_classroom_capacity`
- `fact_school_teacher_capacity`
- `fact_school_year_source_availability`

The remaining Gold tables stay disabled until their reviewed Integration inputs are available. No empty substitute is published.

Enrollment and `dim_school_year` cover SY 2020-21 and SY 2023-24 through SY 2025-26. Classroom and teacher capacity currently cover SY 2023-24 only. `fact_school_year_source_availability` records those source-level gaps separately from the school-level coverage checks.

Each build writes a candidate table. Its `90_validate_*` gate checks grain, foreign keys, source reconciliation, and coverage before replacing the published table. A failed gate leaves the last good Gold table unchanged. Job dependencies follow D-051, so each table waits only for the source and dimension gates it reads.
