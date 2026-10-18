-- Bronze gate for psa_school_age_population. Generated from config/ingestion/psa_school_age_population.json:
--   python -m src.ingestion.cli gate --source psa_school_age_population
-- Do not edit by hand; tests/test_ingestion_pipeline.py fails if it differs.
--
-- Runs after every load, over the whole table. Each check writes one row to
-- data_quality_results. The last statement fails on any FAIL recorded for this
-- run (including a batch's own checks), so nothing downstream runs on an
-- unreconciled table.
--
-- Parameters, supplied by the job (or the local CLI):
--   :run_id         the ingestion run being checked
--   :code_revision  the commit that ran, from the job parameter; never a literal

-- The same source row twice means a load ran twice without the MERGE guard.
INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'psa_school_age_population', 'bronze', 'edu_access.02-bronze.psa_school_age_population_raw',
       'no_pipeline_duplicates', CASE WHEN extra = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(extra AS STRING),
       current_timestamp(), :code_revision
FROM (
  SELECT COUNT(*) - COUNT(DISTINCT source_sha256 || ':' || source_sheet || ':' || CAST(source_row_number AS STRING)) AS extra
  FROM edu_access.`02-bronze`.psa_school_age_population_raw
) AS t;

-- Every Bronze row must point to a batch the control table knows about.
INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'psa_school_age_population', 'bronze', 'edu_access.02-bronze.psa_school_age_population_raw',
       'rows_have_a_known_batch', CASE WHEN orphans = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(orphans AS STRING),
       current_timestamp(), :code_revision
FROM (
  SELECT COUNT(*) AS orphans
  FROM edu_access.`02-bronze`.psa_school_age_population_raw AS r
  LEFT JOIN edu_access.`01-control`.ingestion_batches AS b ON r.batch_id = b.batch_id
  WHERE b.batch_id IS NULL
) AS t;

-- Every succeeded batch has exactly as many Bronze rows as its file had.
INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'psa_school_age_population', 'bronze', 'edu_access.02-bronze.psa_school_age_population_raw',
       'succeeded_batches_reconcile', CASE WHEN mismatched = 0 THEN 'PASS' ELSE 'FAIL' END, '0',
       CAST(mismatched AS STRING), current_timestamp(), :code_revision
FROM (
  SELECT COUNT(*) AS mismatched
  FROM edu_access.`01-control`.ingestion_batches AS b
  LEFT JOIN (
    SELECT source_sha256, COUNT(*) AS n
    FROM edu_access.`02-bronze`.psa_school_age_population_raw
    GROUP BY source_sha256
  ) AS r ON r.source_sha256 = b.source_sha256
  WHERE b.source_id = 'psa_school_age_population' AND b.status = 'succeeded'
    AND (r.n IS NULL OR r.n <> b.source_rows OR b.source_rows <> b.expected_rows)
) AS t;

-- Stop here if anything failed in this run.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Bronze gate failed for psa_school_age_population: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_school_age_population' AND status = 'FAIL';
