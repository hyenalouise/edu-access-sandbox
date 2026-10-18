# Reconciliation evidence

Store reviewed source-to-Bronze-to-Silver-to-Gold count and measure
reconciliations here once those layers exist. Each record must identify its code
revision, source versions, and limitations.

| Evidence | Claim | Issue |
|---|---|---|
| [2026-10-07-deped-enrollment-bronze-to-silver.md](2026-10-07-deped-enrollment-bronze-to-silver.md) | DepEd enrollment Bronze → Silver, local run on the real data (superseded: skip-when-unchanged design) | #85 |
| [2026-10-09-deped-enrollment-bronze-to-silver.md](2026-10-09-deped-enrollment-bronze-to-silver.md) | DepEd enrollment Bronze → Silver, two local job runs on the real data that rebuild identical content | #85 |
| [2026-10-09-psa-poverty-stat-bronze-to-silver.md](2026-10-09-psa-poverty-stat-bronze-to-silver.md) | PSA Poverty Stat Bronze → Silver, two local runs of its lane on the real workbook: 1,612 rows per estimate year, every value equal to Bronze, identical content on rebuild; then two Databricks `dev` runs at `6cc39ca`, every check OK | #89 |
| [2026-10-10-psa-psgc-bronze-to-silver.md](2026-10-10-psa-psgc-bronze-to-silver.md) | PSA PSGC Bronze → Silver, local run at `9d2ee01` on the real 2Q 2026 workbook: 43,768 clean rows, 0 quarantined, 50 checks PASS, identical content on rebuild; then two Databricks `dev` runs at `a6d34a9` and, after review, at `a4d21b0` (52 checks), every check OK | #88 |
| [2026-10-15-hdx-adm3-psgc-map.md](2026-10-15-hdx-adm3-psgc-map.md) | HDX ADM3 Silver to the PSGC map, local run at `adcbf0c` and, after review, at `882873e`: 1,642 rows, 1,634 matched, 12 reviewed, 0 pending, no FAIL | #93 |
| [2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md](2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md) | DepEd enrollment SY 2020-21 as the fourth delivery: two local job runs at `98487d6` on the real data, 60,957 rows per layer, 26,227,022 learners, 153 Silver checks PASS, the earlier years' Silver hash unchanged, and identical content on rebuild. Local only | #170 |
| [2026-10-18-psa-school-age-population-bronze-to-silver.md](2026-10-18-psa-school-age-population-bronze-to-silver.md) | PSA school-age population Bronze → Silver, two local runs of its lane at `6bb76a6` on the real 2020 and 2024 workbooks: 418,320 clean rows, 0 quarantined, levels from the sums equal the profile's place counts, 116 checks with 0 FAIL / 4 WARN, identical content on rebuild | #158 |
| [2026-10-19-deped-enrollment-2021-23-bronze.md](2026-10-19-deped-enrollment-2021-23-bronze.md) | DepEd enrollment SY 2021-22 and 2022-23 as the fifth and sixth deliveries: two local job runs at `68f6c68` on the real data, 60,429 and 60,137 Bronze rows, one `school_id_format` WARN, the four other years' Bronze hash equal to `main`, and nothing inserted on rerun |
| [2026-10-19-deped-enrollment-2021-23-silver.md](2026-10-19-deped-enrollment-2021-23-silver.md) | DepEd enrollment SY 2021-22 and 2022-23 in Silver: two local job runs at `263ce85`, 60,429 and 60,136 clean rows, 1 quarantined (`1404066`), 227 checks with 2 WARN, the other four years' Silver hash unchanged, and identical content on rebuild |
