# Evidence: DepEd schools map to PSGC at city and barangay level

Issue #91 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8)

## The claim

The Integration build reads the published `deped_enrollment_clean`,
`deped_enrollment_psgc_clean`, and `psa_psgc_clean` Silver tables and publishes
`deped_school_psgc_map` only after its gate passes. The table retains every
enrollment school and produces exactly one `city_mun` and one `bgy` row for
each school year, SY 2020-21 to SY 2025-26. Unmatched, ambiguous, overseas,
and other excluded records remain explicit rows rather than being dropped.

The implementation reproduces the rule reviewed in PR #153 for SY 2023-24.
For all 120,268 Philippine-school map rows in that analysis preview, the
production output has the same `match_status`, `psgc_code`, and
`match_method`, and the same `reason` on 120,262 (the other 6 are explained
below).

## What was run

The full local `edu_access_pipeline` ran on one new database against the
approved source deliveries, on branch `feat/91-deped-school-psgc-map` rebased
on `main` at `917c50a`. Main now approves DepEd enrollment SY 2021-22 and
2022-23 (#185), so the map covers six school years. The landing folder is
`raw-data/` with the EMISD workbook from `school_coordinates/original/`
linked under `deped/original/`, where the `deped_enrollment_psgc` contract
looks for it.

The branch was then rebased again onto `main` at `1c18900` for #186 (SY 2021-22
and 2022-23 enrollment Silver). That change touches no file under `etl/` or
`src/` and no rule value, only the wording of rules and evidence in
`config/mappings/deped_enrollment.json` and the docs, so the Silver rows and
this map are the same; the runs below were not repeated.

After review (@maeveylain, @mafelisilda), `fc35756` and `25a0842` read the
Isabela province and Manila's districts from PSGC Silver and move the
Maguindanao split and the NCR scope into the rules file, and `b996426` adds four
gate checks that reconcile each row with its Silver inputs. Runs 5 and 6 below
ran at `b996426` on the same database.

```bash
python -m src.job.local_run \
  --landing "$RAW_DATA_DIR" \
  --db local_state/edu_access.duckdb \
  --code-revision "$(git rev-parse HEAD)"
```

| | Run 1 | Run 2 | Run 3 | Run 4 |
|---|---|---|---|---|
| `run_id` | `3f753a63-16fc-488f-b5ed-98cec63d024a` | `1294808f-c3ae-48de-b11a-7d6c45f9cb43` | `356e25fb-82fc-439c-b1c3-6b260db52dfd` | `cb805460-b6b2-4d6d-ba80-3d4cb347d49d` |
| Code | `1f55019` | `9ea9acb` | `9ea9acb` | `9ea9acb` |
| Integration build / gate | 2.37 s / 0.22 s | 2.15 s / 0.90 s | 2.24 s / 0.93 s | 2.47 s / 1.02 s |
| Gate results | 4 FAIL: `profiled_2021-22_*`, `profiled_2022-23_*` (not profiled); nothing published | 40 PASS, 5 WARN, 0 FAIL | same | same |
| Published rows | none | 724,044 | 724,044 | 724,044 |
| Business-content SHA-256 | none | not kept (run 3 replaced the table) | `2339a6e70b6c50784312ad37c98c3263eced319780021e7a25d72f8b0f18a9b2` | same |

| | Run 5 | Run 6 |
|---|---|---|
| `run_id` | `ec0f9007-9074-4849-b4ff-23a9037b55bf` | `b9c9332d-96f8-4cba-865c-324f572a9e18` |
| Code | `b996426` | `b996426` |
| Integration build / gate | 2.39 s / 1.00 s | 2.19 s / 0.91 s |
| Gate results | 44 PASS, 5 WARN, 0 FAIL | same |
| Published rows | 724,044 | 724,044 |
| Business-content SHA-256 | `2339a6e70b6c50784312ad37c98c3263eced319780021e7a25d72f8b0f18a9b2` | same |

Runs 5 and 6 have the same hash as runs 3 and 4, so reading Isabela and
Manila from Silver and moving the Maguindanao and NCR rules to the rules file
changed no row. The four new checks (`enrollment_fields_reconcile`,
`crosswalk_lineage_reconciles`, `psgc_fields_reconcile`, `review_fields_valid`)
PASS on every row.

Run 1 shows the gate holding back a delivery whose counts nobody has reviewed:
it built the map and published nothing. Its SY 2021-22 and 2022-23 counts are
the ones added to `gate.profiled_counts` in `7bf16ba`. Runs 2 to 4 skipped every
unchanged Bronze delivery by SHA-256, then rebuilt and republished the map.

The business-content SHA-256 hashes every column except `run_id`,
`built_at_utc` and `code_revision`, rows ordered by school year, school ID and
level:

```sql
SELECT COUNT(*) AS n, sha256(string_agg(t::VARCHAR, chr(10) ORDER BY school_year, school_id, geographic_level)) AS content_sha256
FROM (SELECT * EXCLUDE (run_id, built_at_utc, code_revision) FROM "04-integration".deped_school_psgc_map) AS t;
```

In runs 5 and 6, the five WARN results are the intentionally visible `unmatched` (276),
`ambiguous` (611), `excluded` (554), `review_pending` (1,441) and
`override_without_unit` (4) counts. `code_not_in_psgc` PASSes: every EMISD
code has a unit in the master PSGC. Every `match_rate_*` check is at or above
the 99.0% floor (lowest: SY 2020-21 barangay, 99.63%) and every `profiled_*`
check PASSes at the counts below.

## Results

There are 362,022 enrollment rows and 724,044 map rows: exactly two map rows
per enrollment row, no missing or extra source key, and no duplicate key. All
matched codes resolve to the one master PSGC publication, every matched
barangay belongs to its accepted city or municipality, all lineage fields are
populated, every row's carried values and lineage reconcile with the current
Silver rows, and the gate recorded 0 FAIL.

| School year | Level | Matched | Ambiguous | Unmatched | Excluded | Total |
|---|---|---:|---:|---:|---:|---:|
| 2020-21 | city/municipality | 60,877 | 28 | 16 | 36 | 60,957 |
| 2020-21 | barangay | 60,693 | 153 | 75 | 36 | 60,957 |
| 2021-22 | city/municipality | 60,356 | 26 | 12 | 35 | 60,429 |
| 2021-22 | barangay | 60,210 | 129 | 55 | 35 | 60,429 |
| 2022-23 | city/municipality | 60,070 | 24 | 7 | 35 | 60,136 |
| 2022-23 | barangay | 59,978 | 95 | 28 | 35 | 60,136 |
| 2023-24 | city/municipality | 60,108 | 12 | 4 | 43 | 60,167 |
| 2023-24 | barangay | 60,050 | 56 | 18 | 43 | 60,167 |
| 2024-25 | city/municipality | 60,060 | 1 | 5 | 63 | 60,129 |
| 2024-25 | barangay | 60,040 | 13 | 13 | 63 | 60,129 |
| 2025-26 | city/municipality | 60,122 | 3 | 14 | 65 | 60,204 |
| 2025-26 | barangay | 60,039 | 71 | 29 | 65 | 60,204 |

Excluded is the Philippine Schools Overseas (33, 32, 32, 33, 35, 36) plus the
Special Geographic Area schools that D-031 still excludes (3, 3, 3, 10, 28,
29).

**The rebase changed no earlier row.** Against the pre-rebase run at `23a9fa7`
(run `6070d1a2-985c-4056-8293-95328ac958c8`), the SY 2020-21, 2023-24, 2024-25
and 2025-26 rows are identical row for row: 482,914 on each side, 0 only in
either, comparing every column except the run stamp and the Bronze, crosswalk
and PSGC batch IDs, which a new database assigns again. That includes the
stale-code change in `1f55019`, which no real row reaches.

**SY 2023-24 against PR #153.** Subtracting the 33 overseas schools from the
excluded count gives the PR #153 preview exactly: city/municipality 60,108
matched, 12 ambiguous, 4 unmatched, and 10 excluded; barangay 60,050 matched,
56 ambiguous, 18 unmatched, and 10 excluded. The 6 rows whose `reason`
differs are barangays where several PSGC barangays share the best name: the
map says "4 (or 6) PSGC barangays match the best name tier" where the preview
says "no code, no name match". This query ran on the pre-rebase run; the
SY 2023-24 rows are unchanged since.

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
applied to every year by `school_id` (D-049). These rows have a crosswalk
entry; the rest use the name match only:

| School year | In the crosswalk | Rows |
|---|---:|---:|
| 2020-21 | 58,531 | 60,957 |
| 2021-22 | 59,030 | 60,429 |
| 2022-23 | 59,497 | 60,136 |
| 2023-24 | 60,167 | 60,167 |
| 2024-25 | 59,542 | 60,129 |
| 2025-26 | 59,106 | 60,204 |

- SY 2020-21 files the 111 schools whose code is in a Special Geographic Area
  municipality under Region XII / NORTH COTABATO, so they are found by code:
  108 are matched by code because DepEd's barangay name supports it, and 3 are
  excluded. SY 2021-22 and 2022-23 file their 112 under BARMM (the Region XII
  to BARMM relabel, #185): 109 matched, 3 excluded each.
- SY 2024-25 and 2025-26 exclude 28 and 29 Special Geographic Area schools,
  against 10 in SY 2023-24. 5 and 6 are new schools filed under
  `(SGA - North Cotabato)` with no EMISD code. The other 13 in each year were
  matched in SY 2023-24 and are schools DepEd now files under another
  barangay, so the SY 2023-24 code loses its barangay support (for example
  `129874`, Tapodoc ES, moves from TAPODOC to DUALING while its code is still
  the barangay Tapodoc).
- SY 2020-21 has 153 ambiguous barangays, all with an EMISD code: 123 where the
  code and the SY 2020-21 name disagree with no barangay support, 28 whose city
  is ambiguous, and 2 outside the accepted city. SY 2021-22 (129) and 2022-23
  (95) sit between SY 2020-21 and 2023-24, as expected for names that drift
  from the SY 2023-24 codes over time (suspected; not reviewed one by one).
- The SY 2022-23 seven-digit school ID noted in #185 does not reach the map:
  no SY 2022-23 Silver row has a seven-digit ID.
- `override_without_unit` is 4: the Signal Village override finds no unit for
  2 SY 2020-21 rows, 1 SY 2021-22 row and 1 SY 2025-26 row.

## Unresolved schools

The runbook query in [docs/operations/integration.md](../../docs/operations/integration.md)
lists every unmatched and ambiguous row with the DepEd place, the EMISD code,
and the reason. On run 3:

| Status | Map rows | School-year rows | Schools |
|---|---:|---:|---:|
| ambiguous | 611 | 517 | 218 |
| unmatched | 276 | 218 | 100 |

A school-year row counts once even when both its levels are unresolved.

## Cost and rerun behavior

Cities are matched once per distinct (province, municipality) pair, 1,655 on
these deliveries, and barangays once per distinct place inside the named city
(34,742), before the decisions are joined back to 362,022 school/year rows.
It does not compare every school with every PSGC barangay. On the local
database the build plus gate took under 3.5 seconds per run. The candidate is
published only after all FAIL checks pass, so a failed rebuild leaves the last
published table intact; run 1 above is one.

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
