# Evidence: the 2023 poverty statuses behind D-046 recount from Silver

Issue #104 · PR #151 · local run (DuckDB) at `4b0e6e8` · 2026-10-16 · checked by @Catweyine

## The claim

Joining PSA Poverty Stat Silver (2023 rows) to PSGC Silver (2Q 2026 master reference) gives the counts D-046 makes FAIL thresholds for `dim_city_poverty`: 1,642 cities and municipalities, of which 1,597 `estimated`, 1 `no_estimate` and 44 `not_in_source`. Every 2023 PSA row matches a PSGC city, municipality or Manila sub-municipality. This adds the per-status split to the [Bronze-to-Silver evidence](2026-10-09-psa-poverty-stat-bronze-to-silver.md), which has per-year totals only.

## What was run

Commit `4b0e6e831d84f8bca333a22d195d14b19cff432a`, macOS 26.4.1 (arm64), Python 3.12.14, DuckDB 1.4.5, a fresh database file. Inputs, both checksum-approved by their contracts:

- `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx`, SHA-256 `303fb0e87bff046acaa21e3ac586f6def6b737b9082eb1f51451a887fd93a026`
- `PSGC-2Q-2026-Publication-Datafile.xlsx`, SHA-256 `31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d`

The shared control tasks, then the `psa_psgc` and `psa_poverty_stat` lanes of `edu_access_pipeline`, were run through `src.job.local_run`'s task runner, as in the Bronze-to-Silver evidence. Every task succeeded, both Silver gates included. Then this query ran on the two Silver tables. It uses no local-only syntax, so it also runs unchanged in the Databricks SQL editor on `dev`. The join is coverage X-1: the poverty `correspondence_code` equals the PSGC `correspondence_code`.

```sql
-- D-046 recount: PSA poverty 2023 against PSGC 2Q 2026 cities and municipalities.
-- Reads the two Silver tables only. Join rule: coverage.md, X-1 (poverty correspondence_code = PSGC correspondence_code).
WITH psgc AS (
  SELECT psgc_code, correspondence_code, geographic_level, city_class
  FROM edu_access.`03-silver`.psa_psgc_clean
  WHERE is_master_reference AND geographic_level IN ('City', 'Mun', 'SubMun')
),
pov AS (
  SELECT correspondence_code, estimate_status, cv_over_20, se_cv_inconsistent, lower_limit_not_positive
  FROM edu_access.`03-silver`.psa_poverty_stat_clean
  WHERE estimate_year = 2023
),
matched AS (
  SELECT p.geographic_level, v.*
  FROM pov AS v LEFT JOIN psgc AS p USING (correspondence_code)
),
area AS (
  SELECT g.psgc_code, g.geographic_level, g.city_class, v.estimate_status, v.cv_over_20,
         v.se_cv_inconsistent, v.lower_limit_not_positive,
         CASE WHEN v.estimate_status IS NULL THEN 'not_in_source' ELSE v.estimate_status END AS status
  FROM psgc AS g LEFT JOIN pov AS v USING (correspondence_code)
  WHERE g.geographic_level IN ('City', 'Mun')
)
SELECT 'PSA rows for 2023 in Silver' AS step, COUNT(*) AS n FROM pov
UNION ALL SELECT 'PSA rows matching no PSGC city, municipality or sub-municipality', COUNT_IF(geographic_level IS NULL) FROM matched
UNION ALL SELECT 'Manila sub-municipalities', COUNT_IF(geographic_level = 'SubMun') FROM matched
UNION ALL SELECT 'Cities and municipalities in the PSA file', COUNT_IF(geographic_level IN ('City', 'Mun')) FROM matched
UNION ALL SELECT '  of which cities', COUNT_IF(geographic_level = 'City') FROM matched
UNION ALL SELECT '  of which municipalities', COUNT_IF(geographic_level = 'Mun') FROM matched
UNION ALL SELECT 'PSGC cities and municipalities', COUNT(*) FROM area
UNION ALL SELECT '  of which cities', COUNT_IF(geographic_level = 'City') FROM area
UNION ALL SELECT '  of which municipalities', COUNT_IF(geographic_level = 'Mun') FROM area
UNION ALL SELECT 'estimated', COUNT_IF(status = 'estimated') FROM area
UNION ALL SELECT 'no_estimate', COUNT_IF(status = 'no_estimate') FROM area
UNION ALL SELECT 'not_in_source', COUNT_IF(status = 'not_in_source') FROM area
UNION ALL SELECT '  of which highly urbanized cities', COUNT_IF(status = 'not_in_source' AND city_class = 'HUC') FROM area
UNION ALL SELECT 'cv_over_20 among estimated areas', COUNT_IF(status = 'estimated' AND cv_over_20) FROM area
UNION ALL SELECT 'cv_over_20 among Manila sub-municipalities', COUNT_IF(geographic_level = 'SubMun' AND cv_over_20) FROM matched
UNION ALL SELECT 'lower_limit_not_positive among estimated areas', COUNT_IF(status = 'estimated' AND lower_limit_not_positive) FROM area
UNION ALL SELECT 'se_cv_inconsistent among estimated areas', COUNT_IF(status = 'estimated' AND se_cv_inconsistent) FROM area
```

## Results

| Step | D-046 | Actual | Result |
|---|---:|---:|---|
| PSA rows for 2023 in Silver | 1,612 | 1,612 | OK |
| PSA rows matching no PSGC city, municipality or sub-municipality | 0 | 0 | OK |
| Manila sub-municipalities | 14 | 14 | OK |
| Cities and municipalities in the PSA file | 1,598 | 1,598 | OK |
| of which cities / municipalities | 114 / 1,484 | 114 / 1,484 | OK |
| PSGC 2Q 2026 cities and municipalities | 1,642 | 1,642 | OK |
| of which cities / municipalities | 149 / 1,493 | 149 / 1,493 | OK |
| `estimated` | 1,597 | 1,597 | OK |
| `no_estimate` (Kalayaan) | 1 | 1 | OK |
| `not_in_source` | 44 | 44 | OK |
| of which highly urbanized cities | 33 | 33 | OK |
| `cv_over_20` among estimated areas | 150 | 150 | OK |
| `cv_over_20` among Manila sub-municipalities | 6 | 6 | OK |
| `lower_limit_not_positive` among estimated areas (Ivana) | 1 | 1 | OK |
| `se_cv_inconsistent` among estimated areas | 1 | 1 | OK |

The 11 `not_in_source` areas that are not highly urbanized cities are Isabela City, Cotabato City, Pateros, and the 8 Special Geographic Area municipalities. The 8 have no PSGC `correspondence_code`, so they join nothing. 150 + 6 = 156, Silver's 2023 `cv_over_20` count.

## Not checked

- Databricks `dev`: not run there. Running the query above in the SQL editor should give the same counts.
- `dim_city_poverty` itself: it is not built yet (#174). These counts are what its gate must check.
