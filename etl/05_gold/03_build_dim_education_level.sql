CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_education_level USING DELTA AS
SELECT * FROM VALUES
  ('ES', 'Elementary School'),
  ('JHS', 'Junior High School'),
  ('SHS', 'Senior High School')
AS levels(education_level_code, education_level_name);

ALTER TABLE edu_access.`05-gold`.dim_education_level OWNER TO `reached-hq`;
