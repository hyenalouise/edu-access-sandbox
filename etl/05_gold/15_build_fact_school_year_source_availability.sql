CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate USING DELTA AS
WITH years AS (
  SELECT school_year FROM edu_access.`05-gold`.dim_school_year
), sources AS (
  SELECT * FROM VALUES ('deped_enrollment'), ('deped_facilities'), ('deped_personnel') AS s(source_id)
), available AS (
  SELECT school_year, 'deped_enrollment' AS source_id FROM edu_access.`03-silver`.deped_enrollment_clean GROUP BY school_year
  UNION ALL
  SELECT school_year, 'deped_facilities' AS source_id FROM edu_access.`03-silver`.deped_facilities_clean GROUP BY school_year
  UNION ALL
  SELECT school_year, 'deped_personnel' AS source_id FROM edu_access.`03-silver`.deped_personnel_clean GROUP BY school_year
)
SELECT y.school_year, s.source_id, a.school_year IS NOT NULL AS has_data
FROM years AS y
CROSS JOIN sources AS s
LEFT JOIN available AS a ON a.school_year = y.school_year AND a.source_id = s.source_id;

ALTER TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate OWNER TO `reached-hq`;
