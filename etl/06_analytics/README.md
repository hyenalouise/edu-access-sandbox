# 06 Analytics

This layer publishes one dashboard-ready dataset per analytical question and a final LGU priority matrix. Analytics owns ratios, comparisons, classifications, and priority logic. Gold remains reusable and does not contain prioritization rules.

All outputs have one row per regular city or municipality. Each build writes a candidate table, its paired `90_validate_*` gate checks the result independently, and only a passing candidate replaces the published table.

| Build | Output | Method |
|---|---|---|
| `01_answer_ap1.sql` | `answer_ap1` | 2024 school-age population aged 5–17 per active public school |
| `02_answer_ap2.sql` | `answer_ap2` | SY 2023-24 eligible public-school learners per reported instructional classroom |
| `03_answer_ap3.sql` | `answer_ap3` | SY 2023-24 eligible public-school learners per approved teacher count |
| `04_answer_ap4.sql` | `answer_ap4` | All-sector enrollment direction from SY 2020-21 through SY 2025-26, excluding Philippine Schools Overseas |
| `05_build_priority_matrix.sql` | `priority_matrix` | Explainable priority from the three validated pressure signals and AP4 enrollment direction |

AP1 to AP3 compare each LGU with a pooled national reference for the same LGU type. The reference is `SUM(numerator) / SUM(denominator)`, never an average of LGU ratios. A valid ratio above that reference is `Above Reference`; otherwise it is `At or Below Reference`. The reference pools only LGUs with no input issue. Coverage below 90% or a missing required value produces `Data Review`. Observed outliers remain in every total and are never capped or removed; an LGU with flagged schools goes to `Data Review` only when its ratio without them falls on the other side of the reference.

AP4 is a direction signal, not a pressure score. It retains each annual enrollment value and classifies the endpoint change as `Growing` (above +5%), `Declining` (below −5%) or `Stable`. A national matched-learner share that moves more than 2 points between SY 2020-21 and SY 2025-26 sends the trend to `Data Review`. The matrix counts growth only when the trend status is `Complete`. It has no national comparison or percentile.

The final matrix preserves every component ratio, reference, coverage measure, quality flag, classification, and trend. It counts AP1 to AP3 `Above Reference` results and applies D-058's explicit priority case. No percentile or weighted score sets priority.

Each gate writes its one-row check summary to a table named for the run (`<output>_gate_summary_r_<sha256(run_id)>`) and drops it once the checks are recorded, as the Gold gates do (#202). Gates also record unplaced schools and learners as `WARN`, and the priority gate records the number of LGUs per tier.

Files follow `NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see [File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
