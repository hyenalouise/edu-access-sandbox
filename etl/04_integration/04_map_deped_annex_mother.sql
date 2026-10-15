-- DepEd publishes which schools are annexes, but the acquired machine-ready files do not
-- publish the mother-school ID. keep every annex visible and unmatched until a reviewed
-- crosswalk is available (D-044).
CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_annex_mother_map USING DELTA AS
SELECT
  e.school_year,
  e.school_id AS annex_school_id,
  CAST(NULL AS STRING) AS mother_school_id,
  'unmatched' AS match_status,
  CAST(NULL AS STRING) AS match_method,
  'deped_enrollment_annex_status_only' AS evidence,
  e.batch_id,
  e.source_sha256,
  e.source_row_number,
  :run_id AS run_id,
  current_timestamp() AS mapped_at_utc,
  :code_revision AS code_revision
FROM edu_access.`03-silver`.deped_enrollment_clean AS e
WHERE e.annex_status = 'Annex/Extension School';

ALTER TABLE edu_access.`04-integration`.deped_annex_mother_map OWNER TO `reached-hq`;
