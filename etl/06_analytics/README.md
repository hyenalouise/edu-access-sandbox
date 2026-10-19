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
| `05_answer_lgu_priority` | `lgu_priority_outlier_schools` | Flagged public school x measure (AP2, or AP3 by level), SY 2023-24 |

Every regular LGU has a row even with no public school, so a missing value shows
as NULL with a `*_null_reason`, never as a dropped LGU or a 0. Ratios divide
summed numerators by summed denominators over the same schools, and each comes
with its coverage and the counts left out.

`lgu_priority` is the one answer for the slide, the dashboard and Genie.
`tier_code`, `tier_label`, `priority_rank` and `rank_within_tier` give the
ordered list. Each measure keeps its own value, coverage, percentile and status.
AP1 to AP3 also publish a same-type baseline and relative pressure. The baseline
is the eligible cities' or municipalities' summed learners divided by their
summed schools, rooms or teachers; relative pressure is the LGU value divided by
that baseline. It explains magnitude (`1.20` means 20% above the same-type
baseline) but does not set the tier. AP4 publishes enrollment school coverage
and remains context only: it never enters the tier.
`is_stable`, the `critical_at_*` columns and `tier_code_without_outliers` are
the checks D-057 reports beside the ranking; none of them changes a tier.

The outlier check flags public schools above Q3 + 3 x IQR of their school-level
ratio, with quartiles within LGU type over the schools with a usable
denominator: learners per room (AP2) and learners per teacher at each level
(AP3). `lgu_priority_outlier_schools` lists them with the run's `run_id`, the
ratio and the fence. The flagged schools stay in every published total (metric
specification rule 8). `tier_code_without_outliers` reruns the rule with them
out of AP2 and of each AP3 level, both the ratio and its coverage base; AP1 does
not change. `outlier_schools` counts the flagged schools in each LGU.

The measure-overlap check is in the gate only: by LGU type, the Spearman rank
correlation of each pair of AP1 to AP3, and the share of LGUs high on one measure
that are also high on the other (10% if they were unrelated). Gate rows report
every check. Spearman is a validation diagnostic, not a score or tier input. The
revisit trigger (fewer than 80% of Critical LGUs kept and at
least 3 leave) is a WARN at the 95% gate and without outliers.

Poverty is not in this table (D-046): join `dim_city_poverty` for context.

The sandbox reading of the zero-teacher annex exception is an annex that reports
0 teachers at every level (48 annexes, 21,114 learners in SY 2023-24, the metric
specification's figures). An annex with teachers at another level is a
zero-teacher school at that level.

Local run on the real deliveries (2026-10-19): Critical 31 (24 Stable), Elevated
104, Targeted 155, Monitor 1,230, Data review 122. About 10% of assessed LGUs are
high on each measure, as D-057 expects. The outlier fence flags 2.4% of city and
2.8% of municipal schools on AP2, and 0.0% to 8.6% per AP3 level (JHS the most).
Without them, 30 of the 31 Critical LGUs stay Critical and 5 join, so the
revisit trigger is not met. 108 LGUs change tier (48 up, 43 down, 17 to or from
Data review). Spearman between the measures is 0.52 to 0.76, and 20% to 73% of
the LGUs high on one measure are high on another.
