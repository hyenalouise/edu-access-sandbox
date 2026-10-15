DECLARE OR REPLACE VARIABLE annex_gate_started_at_utc TIMESTAMP;
SET VARIABLE annex_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_annex_mother_gate_summary USING DELTA AS
WITH source_annexes AS (
  SELECT school_year, school_id
  FROM edu_access.`03-silver`.deped_enrollment_clean
  WHERE annex_status = 'Annex/Extension School'
), map AS (
  SELECT * FROM edu_access.`04-integration`.deped_annex_mother_map
)
SELECT
  (SELECT COUNT(*) FROM source_annexes) AS source_annexes,
  (SELECT COUNT(*) FROM map) AS mapped_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT (school_year, annex_school_id)) FROM map) AS duplicate_keys,
  (SELECT COUNT(*) FROM source_annexes AS s LEFT JOIN map AS m ON m.school_year = s.school_year AND m.annex_school_id = s.school_id WHERE m.annex_school_id IS NULL) AS missing_annexes,
  (SELECT COUNT(*) FROM map AS m LEFT JOIN source_annexes AS s ON s.school_year = m.school_year AND s.school_id = m.annex_school_id WHERE s.school_id IS NULL) AS non_annex_rows,
  (SELECT COALESCE(COUNT_IF(mother_school_id IS NULL), 0) FROM map) AS unmatched_annexes,
  (SELECT COALESCE(COUNT_IF(mother_school_id IS NULL AND (match_status <> 'unmatched' OR match_method IS NOT NULL)), 0) FROM map) AS invalid_unmatched_rows,
  (SELECT COALESCE(COUNT_IF(mother_school_id IS NOT NULL AND (match_status <> 'matched' OR match_method IS NULL)), 0) FROM map) AS invalid_matched_rows,
  (SELECT COALESCE(COUNT_IF(evidence IS NULL OR batch_id IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR mapped_at_utc IS NULL OR code_revision IS NULL), 0) FROM map) AS missing_evidence_or_lineage,
  (SELECT COALESCE(COUNT_IF(run_id <> :run_id OR code_revision <> :code_revision), 0) FROM map) AS wrong_run_lineage;

ALTER TABLE edu_access.`04-integration`.deped_annex_mother_gate_summary OWNER TO `reached-hq`;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'deped_annex_mother', 'integration', 'edu_access.04-integration.deped_annex_mother_map', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN mapped_rows = source_annexes THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_annexes AS STRING) AS expected, CAST(mapped_rows AS STRING) AS actual FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'annex_key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'annexes_not_dropped', CASE WHEN missing_annexes = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_annexes AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'only_annexes_listed', CASE WHEN non_annex_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(non_annex_rows AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'match_fields_consistent', CASE WHEN invalid_unmatched_rows + invalid_matched_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_unmatched_rows + invalid_matched_rows AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'evidence_and_lineage_complete', CASE WHEN missing_evidence_or_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_evidence_or_lineage AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'rows_built_by_this_run', CASE WHEN wrong_run_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_run_lineage AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
  UNION ALL SELECT 'annexes_without_mother_school', CASE WHEN unmatched_annexes = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unmatched_annexes AS STRING) FROM edu_access.`04-integration`.deped_annex_mother_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Integration gate failed for deped_annex_mother_map: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'deped_annex_mother' AND layer = 'integration' AND status = 'FAIL' AND checked_at_utc >= session.annex_gate_started_at_utc;

DROP TABLE IF EXISTS edu_access.`04-integration`.deped_annex_mother_gate_summary;
