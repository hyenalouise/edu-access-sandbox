# Reconciliation evidence

Store reviewed source-to-Bronze-to-Silver-to-Gold count and measure
reconciliations here once those layers exist. Each record must identify its code
revision, source versions, and limitations.

| Evidence | Claim | Issue |
|---|---|---|
| [2026-10-07-deped-enrollment-bronze-to-silver.md](2026-10-07-deped-enrollment-bronze-to-silver.md) | DepEd enrollment Bronze → Silver, local run on the real data (superseded: skip-when-unchanged design) | #85 |
| [2026-10-09-deped-enrollment-bronze-to-silver.md](2026-10-09-deped-enrollment-bronze-to-silver.md) | DepEd enrollment Bronze → Silver, two local job runs on the real data that rebuild identical content | #85 |
| [2026-10-09-psa-poverty-stat-bronze-to-silver.md](2026-10-09-psa-poverty-stat-bronze-to-silver.md) | PSA Poverty Stat Bronze → Silver, two local runs of its lane on the real workbook: 1,612 rows per estimate year, every value equal to Bronze, identical content on rebuild; then two Databricks `dev` runs at `6cc39ca`, every check OK | #89 |
