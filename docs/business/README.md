# Business framing

Planner needs and the business-to-analytics hierarchy: one business question, four analytical questions, and the comparison methods used to interpret them. Each need is tagged **documented**, **mentor-validated**, or **assumed** (D-001).

| Document | What it holds | Status |
|---|---|---|
| [business-analytics-problem.md](business-analytics-problem.md) | Mentor-approved BP/AP wording, decision purpose, question roles, and analytical boundaries (D-042) | Wording approved |
| [metric-specification.md](metric-specification.md) | AP1 to AP4 formulas, grains, source fields, source-availability rules, scope, missing-data rules, audit fields, dashboard fields, and validation gates | Gold implementation contract; dashboard publication remains gated |
| [national-benchmarks-and-indicators.md](national-benchmarks-and-indicators.md) | Official formulas, policy criteria, numeric references, national targets, data compatibility, and source citations | Research register; activation still requires metric-level approval |
| [dataset-use-map.md](dataset-use-map.md) | Route for all 23 profiled datasets: core calculations, method support, context, cross-checks, deferred use, and exclusions | Updated for approved questions; AP4 population source in Bronze (#165), Silver not yet built |
| [stakeholders.md](stakeholders.md) | Local education planners, sponsors, government agencies, user story, and persona stories | Updated for approved questions |
| [planner-needs.md](planner-needs.md) | Planner needs and roles behind the approved questions, each cited to a published document and tagged documented, mentor-validated, or assumed (D-001) | Draft for review (#7) |

The BP and AP wording was approved through mentor review on 2026-10-14. The metric specification is the implementation contract for Gold facts and Analytics calculations; dashboard publication still requires its validation gate. D-060 replaces percentile tiers with a bounded classroom review queue, and the planner needs in [planner-needs.md](planner-needs.md) remain a draft for review (#7). Data-model, ERD, Gold, analytics, and dashboard pull requests must preserve the stated source gaps and limitations.

## Research briefs

- [How Philippine public-school funding reaches schools](ph-public-school-budget-flow.md) — the national authorization process, school-level MOOE, centrally managed programs, infrastructure, local SEF, and accountability trail.
