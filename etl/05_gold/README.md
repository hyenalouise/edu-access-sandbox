# 05 Gold

Facts and dimensions for the approved business question.

The proposed model, grains, keys, analytical-question mapping, and ERD are in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).
They remain design-only until the team and mentor approve them under #45 and
Integration prerequisite #44 is ready. The placeholder SQL files remain
non-executable during that review: each dimension and fact has a disabled
`NN_build_<object>.sql` task and its `90_validate_<object>.sql` gate in the job,
wired to the gates it reads (D-051).

Proposed dimensions:

- `dim_city_municipality`
- `dim_barangay`
- `dim_school`
- `dim_school_year`
- `dim_education_level`
- `dim_city_poverty`

Proposed facts:

- `fact_school_enrollment`
- `fact_school_classroom_capacity`
- `fact_school_teacher_capacity`
- `fact_city_population`
- `fact_city_school_age_population`
- `fact_school_year_source_availability`

When approved, use one dimension or fact per file and give each dimension gate
a uniqueness check on its declared key. Files follow `NN_<verb>_<object>.sql`,
with checks in `90_validate_<object>.sql` (see [File naming and
layout](../../docs/architecture/overview.md#file-naming-and-layout)).
