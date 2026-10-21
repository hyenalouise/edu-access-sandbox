# 06 Analytics

This layer publishes one dataset per analytical question and an evidence-based LGU planning table. The metrics follow the [metric specification](../../docs/business/metric-specification.md). Gold remains reusable and contains no prioritization rule.

AP1 to AP3 and the planning table have one row per regular city or municipality. AP4 has one row per city member and school year. Each build writes a candidate table, its paired `90_validate_*` gate independently recomputes the result from Gold, and only a passing candidate replaces the published table.

| Build | Output | Approved use |
|---|---|---|
| `01_answer_ap1.sql` | `ap1_school_provision` | Descriptive school-provision context; not a school-establishment or priority measure |
| `02_answer_ap2.sql` | `ap2_classroom_pressure` | School-level PIDS-style illustrative screen at >=50 learners per reported NSBI instructional room, aggregated to the LGU |
| `03_answer_ap3.sql` | `ap3_teacher_pressure` | Descriptive ES, JHS and SHS learner-per-teacher comparisons; not a teacher-shortage rank |
| `04_answer_ap4.sql` | `ap4_enrollment_trend` | Enrollment trend and census-year population context |
| `05_build_priority_matrix.sql` | `lgu_priority_matrix` | D-060 evidence table and classroom review queue; no composite score, percentile tier, or teacher rank |

## D-060 classroom review queue

AP2 evaluates each usable school first. A school passes the illustrative screen when its complete all-level enrollment divided by its reported total NSBI instructional rooms is at least 50. The LGU row reports the number of screened schools, affected learners, and affected-learner share.

An LGU is queued as `reported_congestion_screen` when at least one school passes and AP2 learner coverage is at least 90%. It is `no_reported_congestion_screen` when assessed with no passing school, and `data_review` when coverage is below 90% or the ratio is unavailable.

Only LGUs in `reported_congestion_screen` receive `classroom_priority_rank`. `DENSE_RANK()` orders them by affected learners, affected schools, then pooled reported-room ratio, all descending. Exact ties share a rank. These are triage ranks for validating classroom conditions, not official shortage or construction-entitlement ranks.

The PIDS paper defines its 1:50 line for illustration and analyzes congestion at school and education-level grain. The current Gold facilities data provide a broader all-level NSBI instructional-room total, including room types outside a K–12-classroom-only denominator. The implementation is therefore labelled **PIDS-style illustrative reported-room screen** and does not claim to reproduce the paper or DepEd's official classroom–learner indicator.

## Teacher context

AP3 preserves ES 35 as a **historical study reference** and JHS 36 and SHS 80/3 as **derived deployment comparisons**. The latter convert published class-size maxima and teacher-to-class factors into a compatible unit. None is a current national staffing entitlement or teacher-shortage formula, so AP3 does not assign a teacher priority rank.

The overall AP3 status is `pressure signal identified` when any offered, adequately covered level is above its reference, even if another offered level is incomplete. It is `not fully assessed` only when no passing level is above reference and at least one offered level fails coverage. This preserves the usable evidence without treating missing data as absence of pressure.

All outputs retain coverage and missingness fields. A recorded zero remains zero; an all-NULL component total remains NULL. Every gate writes a one-row run-specific summary, records its checks, and removes the temporary summary after validation.
