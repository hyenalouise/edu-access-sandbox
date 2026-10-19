CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_education_level_candidate USING DELTA AS
SELECT * FROM VALUES
  ('ES', 'Elementary School'),
  ('JHS', 'Junior High School'),
  ('SHS', 'Senior High School')
AS levels(education_level_code, education_level_name);

ALTER TABLE edu_access.`05-gold`.dim_education_level_candidate OWNER TO `reached-hq`;
