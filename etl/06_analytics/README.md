# 06 Analytics

One dataset per analytical question, plus the LGU priority table, ready for the
dashboard. Formulas follow the
[metric specification](../../docs/business/metric-specification.md) and the
priority rule follows D-057.

**Sandbox build**, like [Gold](../05_gold/README.md): a draft for the dashboard,
not team-approved. Each output has an `NN_answer_<object>.sql` task that writes
`<table>_candidate` and a `90_validate_<object>.sql` gate that publishes it only
when no check FAILs. Each records an `analytics_build` run.

| Task | Table | Grain |
|---|---|---|
| `01_answer_ap1` | `ap1_school_provision` | Regular LGU x school year |
| `02_answer_ap2` | `ap2_classroom_pressure` | Regular LGU x facilities school year (SY 2023-24) |
| `03_answer_ap3` | `ap3_teacher_pressure` | Regular LGU x personnel school year (SY 2023-24) x level |
| `04_answer_ap4` | `ap4_population_enrollment_gap` | Regular LGU x census period (2020, 2024) |
| `05_answer_lgu_priority` | `lgu_priority` | Regular LGU, SY 2023-24 |

Every regular LGU has a row even with no public school, so a missing value shows
as NULL with a `*_null_reason`, never as a dropped LGU or a 0. Ratios divide
summed numerators by summed denominators over the same schools, and each comes
with its coverage and the counts left out.

`lgu_priority` is the one answer for the slide, the dashboard and Genie.
`tier_code`, `tier_label`, `priority_rank` and `rank_within_tier` give the
ordered list. Each measure keeps its own value, coverage, percentile and status.
`is_stable` and the `critical_at_*` columns are the checks D-057 reports beside
the ranking. The outlier and measure-overlap checks of D-057 are not built yet.
Poverty is not in this table (D-046): join `dim_city_poverty` for context.

The sandbox reading of the zero-teacher annex exception is an annex that reports
0 teachers at every level (48 annexes, 21,114 learners in SY 2023-24, the metric
specification's figures). An annex with teachers at another level is a
zero-teacher school at that level.

Local run on the real deliveries (2026-10-19): Critical 31 (24 Stable), Elevated
104, Targeted 155, Monitor 1,230, Data review 122. About 10% of assessed LGUs are
high on each measure, as D-057 expects.
