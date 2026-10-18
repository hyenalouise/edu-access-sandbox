# Evidence: DepEd schools map to PSGC at city and barangay level

Issue #91 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8)

## The claim

The Integration build reads the published `deped_enrollment_clean`,
`deped_enrollment_psgc_clean`, and `psa_psgc_clean` Silver tables and publishes
`deped_school_psgc_map` only after its gate passes. The table retains every
enrollment school and produces exactly one `city_mun` and one `bgy` row for
each school year. Unmatched, ambiguous, overseas, and other excluded records
remain explicit rows rather than being dropped.

The implementation reproduces the rule reviewed in PR #153 for SY 2023-24.
For all 120,268 Philippine-school map rows in that analysis preview, the
production output has the same `match_status`, `psgc_code`, and
`match_method`, and the same `reason` on 120,262 (the other 6 are explained
below).

## What was run

The full local `edu_access_pipeline` ran three times on one new database
against the approved source deliveries, on branch `feat/91-deped-school-psgc-map`
at `23a9fa7` (this record changes no code). Runs 2 and 3 skipped every unchanged
Bronze delivery by SHA-256, then rebuilt and republished the Integration map.

```bash
python -m src.job.local_run \
  --landing "$RAW_DATA_DIR" \
  --db local_state/edu_access.duckdb \
  --code-revision "$(git rev-parse HEAD)"
```

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| `run_id` | `92031ab1-b7c9-4e99-a7f8-10b3a4f987d9` | `b544c025-ed7d-4fca-bfdc-5138504f7f9b` | `6070d1a2-985c-4056-8293-95328ac958c8` |
| Integration build / gate | 1.58 s / 0.78 s | 1.59 s / 0.83 s | 1.90 s / 0.89 s |
| Published rows | 482,914 | 482,914 | 482,914 |
| Gate results | 29 PASS, 5 WARN, 0 FAIL | same | same |
| Business-content SHA-256 | not kept (run 2 replaced the table) | `211a4c340f083547756a1c44fc86e60c67715652e940a33d2e97f3cac3ddcecc` | same |

The business-content SHA-256 hashes every column except `run_id`,
`built_at_utc` and `code_revision`, rows ordered by school year, school ID and
level.

The five WARN results are the intentionally visible `unmatched` (174),
`ambiguous` (337), `excluded` (414), `review_pending` (925) and
`override_without_unit` (3) counts. Every `match_rate_*` check is at or above
the 99.0% floor (lowest: SY 2020-21 barangay, 99.63%) and every
`profiled_*` check PASSes at the counts below.

## Results

There are 241,457 enrollment rows and 482,914 map rows: exactly two map rows
per enrollment row, and the key has no duplicates. All matched codes resolve
to the one master PSGC publication, every matched barangay belongs to its
accepted city or municipality, all lineage fields are populated, and the gate
recorded 0 FAIL.

| School year | Level | Matched | Ambiguous | Unmatched | Excluded | Total |
|---|---|---:|---:|---:|---:|---:|
| 2020-21 | city/municipality | 60,877 | 28 | 16 | 36 | 60,957 |
| 2020-21 | barangay | 60,693 | 153 | 75 | 36 | 60,957 |
| 2023-24 | city/municipality | 60,108 | 12 | 4 | 43 | 60,167 |
| 2023-24 | barangay | 60,050 | 56 | 18 | 43 | 60,167 |
| 2024-25 | city/municipality | 60,060 | 1 | 5 | 63 | 60,129 |
| 2024-25 | barangay | 60,040 | 13 | 13 | 63 | 60,129 |
| 2025-26 | city/municipality | 60,122 | 3 | 14 | 65 | 60,204 |
| 2025-26 | barangay | 60,039 | 71 | 29 | 65 | 60,204 |

Excluded is the Philippine Schools Overseas (33, 33, 35, 36) plus the Special
Geographic Area schools that D-031 still excludes (3, 10, 28, 29).

**SY 2023-24 against PR #153.** Subtracting the 33 overseas schools from the
excluded count gives the PR #153 preview exactly: city/municipality 60,108
matched, 12 ambiguous, 4 unmatched, and 10 excluded; barangay 60,050 matched,
56 ambiguous, 18 unmatched, and 10 excluded. The 6 rows whose `reason`
differs are barangays where several PSGC barangays share the best name: the
map says "4 (or 6) PSGC barangays match the best name tier" where the preview
says "no code, no name match".

```sql
-- work/deped_school_psgc_map_preview.csv is written by
-- analysis/cross_source/cross_source_deped_enrollment_psgc.py (EP-16).
SELECT COUNT(*) AS n,
       COUNT_IF(m.match_status = p.match_status) AS same_status,
       COUNT_IF(m.psgc_code IS NOT DISTINCT FROM NULLIF(p.psgc_code, '')) AS same_code,
       COUNT_IF(m.match_method IS NOT DISTINCT FROM NULLIF(p.match_method, '')) AS same_method,
       COUNT_IF(m.reason = p.match_detail
                OR m.reason = regexp_replace(p.match_detail, ' [(][^)]*[)]', '')) AS same_reason
FROM read_csv('work/deped_school_psgc_map_preview.csv', all_varchar = true) AS p
JOIN edu_access."04-integration".deped_school_psgc_map AS m
  ON m.school_year = '2023-24' AND m.school_id = p.school_id AND m.geographic_level = p.geographic_level;
-- 120268 | 120268 | 120268 | 120268 | 120262
```

The `regexp_replace` drops the name tier the preview adds in brackets
("name only (exact)"); the map says "name only".

**Other school years.** The EMISD crosswalk has SY 2023-24 school IDs and is
applied to every year by `school_id` (D-049): 58,531 of 60,957 SY 2020-21
rows, 59,542 of 60,129 SY 2024-25 rows and 59,106 of 60,204 SY 2025-26 rows
have a code; the rest use the name match only.

- SY 2020-21 files the 111 schools whose code is in a Special Geographic Area
  municipality under Region XII / NORTH COTABATO, so they are found by code:
  108 are matched by code because DepEd's barangay name supports it, and 3 are
  excluded.
- SY 2024-25 and 2025-26 exclude 28 and 29 Special Geographic Area schools,
  against 10 in SY 2023-24. 5 and 6 are new schools filed under
  `(SGA - North Cotabato)` with no EMISD code. The other 13 in each year were
  matched in SY 2023-24 and are schools DepEd now files under another
  barangay, so the SY 2023-24 code loses its barangay support (for example
  `129874`, Tapodoc ES, moves from TAPODOC to DUALING while its code is still
  the barangay Tapodoc).
- SY 2020-21 has 153 ambiguous barangays, all with an EMISD code: 123 where the
  code and the SY 2020-21 name disagree with no barangay support, 28 whose city
  is ambiguous, and 2 outside the accepted city.

## Cost and rerun behavior

Cities are matched once per distinct (province, municipality) pair, 1,653 on
these deliveries, and barangays once per distinct place inside the named city
(34,737), before the decisions are joined back to 241,457 school/year rows.
It does not compare every school with every PSGC barangay. Changing the city
match from places to pairs left all 482,914 rows identical. On the local
database the build plus gate took under 2.8 seconds per run. The candidate is
published only after all FAIL checks pass, so a failed rebuild leaves the last
published table intact.

## Limitations

- DuckDB validates the local translation of the generated SQL; Spark SQL,
  Delta publication, ownership, and the small Databricks SQL warehouse still
  need a `dev` bundle run before this draft is ready to merge.
- WARN rows are deliberately retained for review. This PR does not force the
  remaining ambiguous or unmatched schools onto a PSGC unit.
- SY 2020-21 rows are placed in PSGC 2Q 2026 geography, so the 108 Special
  Geographic Area schools sit in their 2026 municipalities, not the Cotabato
  municipalities the 2020 Census counts them under. Which geography AP4 needs
  is a team decision, not made here.
