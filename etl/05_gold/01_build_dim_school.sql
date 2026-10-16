CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school USING DELTA AS
WITH schools AS (
  SELECT DISTINCT school_id
  FROM edu_access.`03-silver`.deped_enrollment_clean
), ranked_names AS (
  SELECT school_id, school_name, ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY school_year DESC) AS name_rank
  FROM edu_access.`03-silver`.deped_enrollment_clean
  WHERE school_name IS NOT NULL
)
SELECT s.school_id, n.school_name
FROM schools AS s
LEFT JOIN ranked_names AS n ON n.school_id = s.school_id AND n.name_rank = 1;

ALTER TABLE edu_access.`05-gold`.dim_school OWNER TO `reached-hq`;
