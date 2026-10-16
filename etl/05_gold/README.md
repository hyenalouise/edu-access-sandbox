# 05 Gold

Facts and dimensions for the approved business question.

The approved model, grains, keys, analytical-question mapping, and ERD are in
[`docs/architecture/data-model.md`](../../docs/architecture/data-model.md).

Implemented dimensions whose reviewed inputs are available:

- `dim_school`
- `dim_school_year`
- `dim_education_level`

Implemented facts whose reviewed inputs are available:

- `fact_school_classroom_capacity`
- `fact_school_teacher_capacity`

Deferred until their required inputs are implemented and pass their gates:

- `dim_city_municipality` and `dim_barangay`: require the reviewed HDX-to-PSGC
  mapping and the approved technical geography members from Integration.
- `dim_city_poverty`: requires the reviewed poverty-to-PSGC mapping.
- `fact_school_enrollment`: requires the reviewed school-to-PSGC mapping so no
  school receives an invented or silently NULL geography key.
- `fact_city_population`: requires `dim_city_municipality` for its foreign key.
- `fact_city_school_age_population`: requires ingestion, Silver cleaning, and
  reviewed PSGC matching for the profiled 2020 and 2024 single-year-age source.

The unavailable tables have no empty or partially populated substitutes. They
are added only when their source and Integration prerequisites are executable.
This keeps missing data distinguishable from a legitimate zero.

The current builds follow these source periods:

- enrollment and `dim_school`: SY 2023-24 through SY 2025-26;
- classroom capacity: SY 2023-24 only;
- teacher capacity: SY 2023-24 only.

Each implemented table has a `90_validate_*` gate. The gates stop the Gold run
for duplicate grains, unresolved foreign keys, source reconciliation failures,
invalid derived totals, or joins that multiply rows. Missing, zero, and partial
denominators are retained and reported rather than repaired.
