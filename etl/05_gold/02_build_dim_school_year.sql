CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_year USING DELTA AS
WITH enrollment_years AS (
  SELECT DISTINCT school_year FROM edu_access.`03-silver`.deped_enrollment_clean
), facilities_years AS (
  SELECT DISTINCT school_year FROM edu_access.`03-silver`.deped_facilities_clean
), personnel_years AS (
  SELECT DISTINCT school_year FROM edu_access.`03-silver`.deped_personnel_clean
)
SELECT
  e.school_year,
  CAST(SUBSTRING(e.school_year, 1, 4) AS INT) AS start_year,
  CAST(SUBSTRING(e.school_year, 1, 4) AS INT) + 1 AS end_year,
  true AS has_enrollment,
  f.school_year IS NOT NULL AS has_facilities,
  p.school_year IS NOT NULL AS has_personnel
FROM enrollment_years AS e
LEFT JOIN facilities_years AS f ON f.school_year = e.school_year
LEFT JOIN personnel_years AS p ON p.school_year = e.school_year;

ALTER TABLE edu_access.`05-gold`.dim_school_year OWNER TO `reached-hq`;
