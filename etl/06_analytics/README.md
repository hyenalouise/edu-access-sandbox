# 06 Analytics

This layer publishes one dataset per analytical question and the LGU priority table. The metrics follow the team's BP and AP metrics and the [metric specification](../../docs/business/metric-specification.md), and the priority rule is [D-057](../../docs/governance/decisions.md#d-057-lgu-priority-rule-version-1). Analytics owns ratios, percentiles, tiers and context labels. Gold remains reusable and holds no prioritization rule.

AP1 to AP3 and the priority table have one row per regular city or municipality. AP4 has one row per city member (regular, `UNKNOWN` or `EXCLUDED`) and school year, so its totals add up; the priority table reads its regular rows. Each build writes a candidate table, its paired `90_validate_*` gate recomputes it from Gold, and only a passing candidate replaces the published table.

| Build | Gate | Output | Measure |
|---|---|---|---|
| `01_answer_ap1.sql` | `90_validate_ap1.sql` | `ap1_school_provision` | SY 2023-24 learners per public school (ranked), and 2024 school-age population (5–17) per public school (context) |
| `02_answer_ap2.sql` | `90_validate_ap2.sql` | `ap2_classroom_pressure` | SY 2023-24 learners per reported instructional room (ranked) |
| `03_answer_ap3.sql` | `90_validate_ap3.sql` | `ap3_teacher_pressure` | SY 2023-24 learners per teacher for ES, JHS and SHS, re-ranked into one AP3 percentile (ranked) |
| `04_answer_ap4.sql` | `90_validate_ap4.sql` | `ap4_enrollment_trend` | One row per city member and school year: all-sector enrollment, its change and `increasing` / `decreasing` / `no change` trend, with school-age population and the gap on SY 2020-21 and 2024-25 (context) |
| `05_build_priority_matrix.sql` | `90_validate_priority_matrix.sql` | `lgu_priority_matrix` | D-057 tier from the AP1 to AP3 high measures, order within the tier, Stable flag, and AP4 as context |

**Ranking (D-057).** A measure is ranked only when its coverage is at least 90%: learner coverage for AP2 and each AP3 level, and for AP1 the share of active public schools with complete all-level enrollment (schools whose offered counts are all blank are added to the denominator as missing data). Each measure is ranked with `PERCENT_RANK()` within LGU type, and it is high at 0.90 or above. AP3 ranks each level, then re-ranks each LGU's highest level, and names that level.

**Tier (D-057).** Critical (3 high), Elevated (2), Targeted (1, naming the measure), Monitor (0), or Data review when a measure is not assessed. The order within a tier is affected learners, then the lowest percentile. The same rule run nationally gives the Stable flag. A count of high measures is not a weighted score, and the result is relative pressure, not a shortage.

**Context, never changing a tier.** AP1's school-age population per school, AP4's gap and enrollment direction, outlier school counts, poverty and Similar LGUs (#96). D-057's checks beside the ranking (the 0.85 and 0.80 lines, the 95% gate, tier changes without outlier schools, and measure overlap) are a follow-up.

Each gate writes its one-row check summary to a table named for the run (`<output>_gate_summary_r_<sha256(run_id)>`) and drops it once the checks are recorded, as the Gold gates do (#202). Gates also record unplaced schools and learners as `WARN`, and the priority gate records the number of LGUs per tier.

Files follow `NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see [File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
