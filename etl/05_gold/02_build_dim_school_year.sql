CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_year_candidate USING DELTA AS
WITH enrollment_years AS (
  SELECT DISTINCT school_year FROM edu_access.`03-silver`.deped_enrollment_clean
)
SELECT
  school_year,
  CAST(SUBSTRING(school_year, 1, 4) AS INT) AS start_year,
  CAST(SUBSTRING(school_year, 1, 4) AS INT) + 1 AS end_year
FROM enrollment_years;

ALTER TABLE edu_access.`05-gold`.dim_school_year_candidate OWNER TO `reached-hq`;
