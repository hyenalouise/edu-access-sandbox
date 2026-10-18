-- Silver build for psa_school_age_population. Generated from config/ingestion/psa_school_age_population.json
-- and config/mappings/psa_school_age_population.json by src/silver/psa_school_age_population.py:
--   python -m src.silver.cli sql --source psa_school_age_population > etl/03_silver/08_clean_psa_school_age_population.sql
-- Do not edit by hand; tests/test_silver_school_age.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each census year). Bronze is read, never changed.
-- Every count cell of a current batch becomes one candidate (census year, population concept, place,
-- sex, age), and ends in exactly one of the two tables:
--   psa_school_age_population_clean_candidate       one row per cell, typed, with the place's level and parents;
--   psa_school_age_population_quarantine_candidate  cells whose count is blank or not a whole number, with their reasons.
-- Wide rows (2020) give 60 cells each; long rows (2024) give 20, under the place row above them. Title,
-- header, note, source and blank rows stay in Bronze. Levels and parents come from the sums (D-053):
-- 3 passes over the places, one per level that has children (country, region, province), from the bottom.
-- The Silver tables are never written here: the gate (the next task) checks the candidates, the tree
-- included, and publishes them only if no check fails (D-025). It rebuilds on every run.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run; every row built here, and the gate's results, carry it
--   :code_revision  the commit that ran, from the job parameter; never a literal
--   :environment    the deploy target: local, dev, or prod

-- One run stamp for the whole file, so both tables carry the same run and the same time.
DECLARE OR REPLACE VARIABLE silver_run_id STRING;
SET VARIABLE silver_run_id = :run_id;
DECLARE OR REPLACE VARIABLE silver_code_revision STRING;
SET VARIABLE silver_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_environment STRING;
SET VARIABLE silver_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_cleaned_at_utc TIMESTAMP;
SET VARIABLE silver_cleaned_at_utc = current_timestamp();

-- The run starts. Its row stays 'running' until the gate records how it ended, so a
-- build that dies is never mistaken for a good one. run_id and job_run_id are both the job run,
-- so one filter on job_run_id finds a job run's Bronze loads and Silver builds (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.silver_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'psa_school_age_population', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every count cell of the current batches once, with its place, the published text, and the count
-- typed. A reason is decided with explicit NULL handling, and concat_ws never returns NULL, so
-- quarantine_reasons = '' and <> '' split the cells without losing any.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_work_cells USING DELTA AS
WITH bronze AS (
  SELECT r.*
  FROM edu_access.`02-bronze`.psa_school_age_population_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  WHERE c.source_id = 'psa_school_age_population'
),
-- Each place row and the rows that follow it until the next place row share place_pos, in Excel row
-- order within the batch and sheet: a 2024 Total / Male / Female row belongs to the place above it.
ordered AS (
  SELECT r.*,
         SUM(CASE WHEN r.source_row_kind = 'place' THEN 1 ELSE 0 END) OVER (
           PARTITION BY r.batch_id, r.source_sheet ORDER BY r.source_row_number
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS place_pos
  FROM bronze AS r
  WHERE r.source_row_kind IN ('place', 'sex_total', 'sex_male', 'sex_female')
),
places AS (
  SELECT batch_id, source_sheet, place_pos, source_row_number AS place_row_number, label AS place_label
  FROM ordered WHERE source_row_kind = 'place'
),
grid AS (SELECT * FROM (VALUES ('both', 5), ('both', 6), ('both', 7), ('both', 8), ('both', 9), ('both', 10), ('both', 11), ('both', 12), ('both', 13), ('both', 14), ('both', 15), ('both', 16), ('both', 17), ('both', 18), ('both', 19), ('both', 20), ('both', 21), ('both', 22), ('both', 23), ('both', 24), ('male', 5), ('male', 6), ('male', 7), ('male', 8), ('male', 9), ('male', 10), ('male', 11), ('male', 12), ('male', 13), ('male', 14), ('male', 15), ('male', 16), ('male', 17), ('male', 18), ('male', 19), ('male', 20), ('male', 21), ('male', 22), ('male', 23), ('male', 24), ('female', 5), ('female', 6), ('female', 7), ('female', 8), ('female', 9), ('female', 10), ('female', 11), ('female', 12), ('female', 13), ('female', 14), ('female', 15), ('female', 16), ('female', 17), ('female', 18), ('female', 19), ('female', 20), ('female', 21), ('female', 22), ('female', 23), ('female', 24)) AS g(sex, age)),
-- Unpivot: one candidate per cell, still as the published text.
cells AS (
  SELECT
    r.census_year, r.source_sheet, r.place_pos, g.sex, g.age,
    CASE r.schema_version
      WHEN 'v1' THEN CASE g.sex
        WHEN 'both' THEN CASE g.age WHEN 5 THEN r.`both_sexes_age_5` WHEN 6 THEN r.`both_sexes_age_6` WHEN 7 THEN r.`both_sexes_age_7` WHEN 8 THEN r.`both_sexes_age_8` WHEN 9 THEN r.`both_sexes_age_9` WHEN 10 THEN r.`both_sexes_age_10` WHEN 11 THEN r.`both_sexes_age_11` WHEN 12 THEN r.`both_sexes_age_12` WHEN 13 THEN r.`both_sexes_age_13` WHEN 14 THEN r.`both_sexes_age_14` WHEN 15 THEN r.`both_sexes_age_15` WHEN 16 THEN r.`both_sexes_age_16` WHEN 17 THEN r.`both_sexes_age_17` WHEN 18 THEN r.`both_sexes_age_18` WHEN 19 THEN r.`both_sexes_age_19` WHEN 20 THEN r.`both_sexes_age_20` WHEN 21 THEN r.`both_sexes_age_21` WHEN 22 THEN r.`both_sexes_age_22` WHEN 23 THEN r.`both_sexes_age_23` WHEN 24 THEN r.`both_sexes_age_24` END
        WHEN 'male' THEN CASE g.age WHEN 5 THEN r.`male_age_5` WHEN 6 THEN r.`male_age_6` WHEN 7 THEN r.`male_age_7` WHEN 8 THEN r.`male_age_8` WHEN 9 THEN r.`male_age_9` WHEN 10 THEN r.`male_age_10` WHEN 11 THEN r.`male_age_11` WHEN 12 THEN r.`male_age_12` WHEN 13 THEN r.`male_age_13` WHEN 14 THEN r.`male_age_14` WHEN 15 THEN r.`male_age_15` WHEN 16 THEN r.`male_age_16` WHEN 17 THEN r.`male_age_17` WHEN 18 THEN r.`male_age_18` WHEN 19 THEN r.`male_age_19` WHEN 20 THEN r.`male_age_20` WHEN 21 THEN r.`male_age_21` WHEN 22 THEN r.`male_age_22` WHEN 23 THEN r.`male_age_23` WHEN 24 THEN r.`male_age_24` END
        WHEN 'female' THEN CASE g.age WHEN 5 THEN r.`female_age_5` WHEN 6 THEN r.`female_age_6` WHEN 7 THEN r.`female_age_7` WHEN 8 THEN r.`female_age_8` WHEN 9 THEN r.`female_age_9` WHEN 10 THEN r.`female_age_10` WHEN 11 THEN r.`female_age_11` WHEN 12 THEN r.`female_age_12` WHEN 13 THEN r.`female_age_13` WHEN 14 THEN r.`female_age_14` WHEN 15 THEN r.`female_age_15` WHEN 16 THEN r.`female_age_16` WHEN 17 THEN r.`female_age_17` WHEN 18 THEN r.`female_age_18` WHEN 19 THEN r.`female_age_19` WHEN 20 THEN r.`female_age_20` WHEN 21 THEN r.`female_age_21` WHEN 22 THEN r.`female_age_22` WHEN 23 THEN r.`female_age_23` WHEN 24 THEN r.`female_age_24` END
      END
      WHEN 'v2' THEN CASE WHEN g.sex = CASE r.source_row_kind WHEN 'sex_total' THEN 'both' WHEN 'sex_male' THEN 'male' WHEN 'sex_female' THEN 'female' END THEN CASE g.age WHEN 5 THEN r.`age_5` WHEN 6 THEN r.`age_6` WHEN 7 THEN r.`age_7` WHEN 8 THEN r.`age_8` WHEN 9 THEN r.`age_9` WHEN 10 THEN r.`age_10` WHEN 11 THEN r.`age_11` WHEN 12 THEN r.`age_12` WHEN 13 THEN r.`age_13` WHEN 14 THEN r.`age_14` WHEN 15 THEN r.`age_15` WHEN 16 THEN r.`age_16` WHEN 17 THEN r.`age_17` WHEN 18 THEN r.`age_18` WHEN 19 THEN r.`age_19` WHEN 20 THEN r.`age_20` WHEN 21 THEN r.`age_21` WHEN 22 THEN r.`age_22` WHEN 23 THEN r.`age_23` WHEN 24 THEN r.`age_24` END END
    END AS population_published,
    r.logical_dataset,
    r.batch_id,
    r.delivery_version,
    r.schema_version,
    r.source_sha256,
    r.source_sheet,
    r.source_row_number
  FROM ordered AS r
  JOIN grid AS g ON r.schema_version IN ('v1') OR g.sex = CASE r.source_row_kind WHEN 'sex_total' THEN 'both' WHEN 'sex_male' THEN 'male' WHEN 'sex_female' THEN 'female' END
  WHERE ((r.schema_version IN ('v1') AND r.source_row_kind = 'place') OR (r.schema_version IN ('v2') AND r.source_row_kind IN ('sex_total', 'sex_male', 'sex_female')))
)
SELECT
  CAST(c.census_year AS INT) AS census_year,
  CASE WHEN c.source_sheet = c.census_year || ' Total Pop' THEN 'total' WHEN c.source_sheet = c.census_year || ' Household Pop' THEN 'household' END AS population_concept,
  c.place_pos,
  p.place_label,
  c.sex,
  c.age,
  c.population_published,
  CASE WHEN regexp_like(c.population_published, '^[0-9]{1,9}$') THEN TRY_CAST(c.population_published AS INT) END AS population,
  concat_ws(',',
      CASE WHEN c.population_published IS NULL OR c.population_published = '' THEN 'population_blank' END,
      CASE WHEN regexp_like(c.population_published, '^-[0-9]+$') THEN 'population_negative' END,
      CASE WHEN c.population_published <> '' AND NOT regexp_like(c.population_published, '^[0-9]{1,9}$')
                AND NOT regexp_like(c.population_published, '^-[0-9]+$') THEN 'population_not_whole_number' END
    ) AS quarantine_reasons,
  c.logical_dataset,
  c.batch_id,
  c.delivery_version,
  c.schema_version,
  c.source_sha256,
  c.source_sheet,
  c.source_row_number,
  p.place_row_number
FROM cells AS c
LEFT JOIN places AS p ON p.batch_id = c.batch_id AND p.source_sheet = c.source_sheet AND p.place_pos = c.place_pos;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_work_cells OWNER TO `reached-hq`;

-- Each place once, in workbook order within its batch and sheet.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_work_places USING DELTA AS
SELECT DISTINCT batch_id, source_sheet, place_pos, place_label FROM edu_access.`03-silver`.psa_school_age_population_work_cells;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_work_places OWNER TO `reached-hq`;

-- The aggregates, from the sums: one pass per level that has children, from the bottom.
-- Pass 1: every place counts.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_work_spans USING DELTA AS
WITH
c1 AS (
  SELECT c.batch_id, c.source_sheet, c.sex, c.age, c.place_pos, c.population, FALSE AS covered,
         SUM(c.population) OVER (PARTITION BY c.batch_id, c.source_sheet, c.sex, c.age ORDER BY c.place_pos
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
  FROM edu_access.`03-silver`.psa_school_age_population_work_cells AS c
),
m1 AS (
  SELECT i.batch_id, i.source_sheet, i.place_pos AS start_pos, j.place_pos AS end_pos
  FROM c1 AS i
  JOIN c1 AS j ON j.batch_id = i.batch_id AND j.source_sheet = i.source_sheet AND j.sex = i.sex AND j.age = i.age
   AND j.place_pos > i.place_pos AND j.running = i.running + i.population
  GROUP BY i.batch_id, i.source_sheet, i.place_pos, j.place_pos
  HAVING COUNT(*) = 60
)
SELECT batch_id, source_sheet, start_pos, MAX(end_pos) AS end_pos, 1 AS found_in_pass
FROM m1 GROUP BY batch_id, source_sheet, start_pos;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_work_spans OWNER TO `reached-hq`;

-- Pass 2: places inside an aggregate already found count once, as that aggregate.
INSERT INTO edu_access.`03-silver`.psa_school_age_population_work_spans (batch_id, source_sheet, start_pos, end_pos, found_in_pass)
WITH
in2 AS (
  SELECT DISTINCT p.batch_id, p.source_sheet, p.place_pos
  FROM edu_access.`03-silver`.psa_school_age_population_work_places AS p JOIN edu_access.`03-silver`.psa_school_age_population_work_spans AS s ON s.batch_id = p.batch_id AND s.source_sheet = p.source_sheet
   AND p.place_pos > s.start_pos AND p.place_pos <= s.end_pos
),
c2 AS (
  SELECT c.batch_id, c.source_sheet, c.sex, c.age, c.place_pos, c.population, n.place_pos IS NOT NULL AS covered,
         SUM(CASE WHEN n.place_pos IS NULL THEN c.population ELSE 0 END) OVER (PARTITION BY c.batch_id, c.source_sheet, c.sex, c.age ORDER BY c.place_pos
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
  FROM edu_access.`03-silver`.psa_school_age_population_work_cells AS c
  LEFT JOIN in2 AS n ON n.batch_id = c.batch_id AND n.source_sheet = c.source_sheet AND n.place_pos = c.place_pos
),
m2 AS (
  SELECT i.batch_id, i.source_sheet, i.place_pos AS start_pos, j.place_pos AS end_pos
  FROM c2 AS i
  JOIN c2 AS j ON j.batch_id = i.batch_id AND j.source_sheet = i.source_sheet AND j.sex = i.sex AND j.age = i.age
   AND j.place_pos > i.place_pos AND j.running = i.running + i.population
  LEFT JOIN edu_access.`03-silver`.psa_school_age_population_work_spans AS done ON done.batch_id = i.batch_id AND done.source_sheet = i.source_sheet AND done.start_pos = i.place_pos
  WHERE NOT i.covered AND done.start_pos IS NULL
  GROUP BY i.batch_id, i.source_sheet, i.place_pos, j.place_pos
  HAVING COUNT(*) = 60
)
SELECT batch_id, source_sheet, start_pos, MAX(end_pos) AS end_pos, 2 AS found_in_pass
FROM m2 GROUP BY batch_id, source_sheet, start_pos;

-- Pass 3: places inside an aggregate already found count once, as that aggregate.
INSERT INTO edu_access.`03-silver`.psa_school_age_population_work_spans (batch_id, source_sheet, start_pos, end_pos, found_in_pass)
WITH
in3 AS (
  SELECT DISTINCT p.batch_id, p.source_sheet, p.place_pos
  FROM edu_access.`03-silver`.psa_school_age_population_work_places AS p JOIN edu_access.`03-silver`.psa_school_age_population_work_spans AS s ON s.batch_id = p.batch_id AND s.source_sheet = p.source_sheet
   AND p.place_pos > s.start_pos AND p.place_pos <= s.end_pos
),
c3 AS (
  SELECT c.batch_id, c.source_sheet, c.sex, c.age, c.place_pos, c.population, n.place_pos IS NOT NULL AS covered,
         SUM(CASE WHEN n.place_pos IS NULL THEN c.population ELSE 0 END) OVER (PARTITION BY c.batch_id, c.source_sheet, c.sex, c.age ORDER BY c.place_pos
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
  FROM edu_access.`03-silver`.psa_school_age_population_work_cells AS c
  LEFT JOIN in3 AS n ON n.batch_id = c.batch_id AND n.source_sheet = c.source_sheet AND n.place_pos = c.place_pos
),
m3 AS (
  SELECT i.batch_id, i.source_sheet, i.place_pos AS start_pos, j.place_pos AS end_pos
  FROM c3 AS i
  JOIN c3 AS j ON j.batch_id = i.batch_id AND j.source_sheet = i.source_sheet AND j.sex = i.sex AND j.age = i.age
   AND j.place_pos > i.place_pos AND j.running = i.running + i.population
  LEFT JOIN edu_access.`03-silver`.psa_school_age_population_work_spans AS done ON done.batch_id = i.batch_id AND done.source_sheet = i.source_sheet AND done.start_pos = i.place_pos
  WHERE NOT i.covered AND done.start_pos IS NULL
  GROUP BY i.batch_id, i.source_sheet, i.place_pos, j.place_pos
  HAVING COUNT(*) = 60
)
SELECT batch_id, source_sheet, start_pos, MAX(end_pos) AS end_pos, 3 AS found_in_pass
FROM m3 GROUP BY batch_id, source_sheet, start_pos;

-- Each place's level, parents and parsed label. The levels come from the sums (D-053): an aggregate's
-- level is its depth, a place with no children is a city or municipality at a depth the rules allow.
-- A place the sums do not explain gets no level, and the gate fails.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_work_tree USING DELTA AS
WITH places AS (
  SELECT * FROM edu_access.`03-silver`.psa_school_age_population_work_places
),
-- An aggregate with a single child ends where that child's span ends.
e0 AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_work_spans),
e1 AS (
  SELECT s.batch_id, s.source_sheet, s.start_pos,
         CASE WHEN t.end_pos > s.end_pos THEN t.end_pos ELSE s.end_pos END AS end_pos, s.found_in_pass
  FROM e0 AS s
  LEFT JOIN e0 AS t ON t.batch_id = s.batch_id AND t.source_sheet = s.source_sheet AND t.start_pos = s.end_pos
),
e2 AS (
  SELECT s.batch_id, s.source_sheet, s.start_pos,
         CASE WHEN t.end_pos > s.end_pos THEN t.end_pos ELSE s.end_pos END AS end_pos, s.found_in_pass
  FROM e1 AS s
  LEFT JOIN e1 AS t ON t.batch_id = s.batch_id AND t.source_sheet = s.source_sheet AND t.start_pos = s.end_pos
),
e3 AS (
  SELECT s.batch_id, s.source_sheet, s.start_pos,
         CASE WHEN t.end_pos > s.end_pos THEN t.end_pos ELSE s.end_pos END AS end_pos, s.found_in_pass
  FROM e2 AS s
  LEFT JOIN e2 AS t ON t.batch_id = s.batch_id AND t.source_sheet = s.source_sheet AND t.start_pos = s.end_pos
),
spans AS (SELECT * FROM e3),
-- The aggregates around each place; the innermost (the last to start) is its parent.
enclosing AS (
  SELECT p.batch_id, p.source_sheet, p.place_pos, s.start_pos
  FROM places AS p JOIN spans AS s ON s.batch_id = p.batch_id AND s.source_sheet = p.source_sheet
   AND p.place_pos > s.start_pos AND p.place_pos <= s.end_pos
),
shaped AS (
  SELECT p.batch_id, p.source_sheet, p.place_pos,
         NULLIF(TRIM(regexp_replace(translate(p.place_label, chr(9) || chr(160), '  '), ' +', ' ')), '') AS label_text,
         COUNT(e.start_pos) AS depth, MAX(e.start_pos) AS parent_pos
  FROM places AS p
  LEFT JOIN enclosing AS e ON e.batch_id = p.batch_id AND e.source_sheet = p.source_sheet AND e.place_pos = p.place_pos
  GROUP BY p.batch_id, p.source_sheet, p.place_pos, p.place_label
),
parsed AS (
  SELECT
    p.batch_id,
    p.source_sheet,
    p.place_pos,
    p.depth,
    p.parent_pos,
    a.start_pos IS NOT NULL AS is_aggregate,
    NULLIF(regexp_extract(p.label_text, ' ([a-z0-9]{1,2}/)$', 1), '') AS footnote,
    NULLIF(array_join(regexp_extract_all(regexp_replace(regexp_replace(p.label_text, ' ([a-z0-9]{1,2}/)$', ''), ' *[(][ ]*[Cc][Aa][Pp][Ii][Tt][Aa][Ll][ ]*[)]', ''), '[(][ ]*([^()]*[^() ])[ ]*[)]', 1), ', '), '') AS old_name,
    COALESCE(regexp_like(p.label_text, '[(][ ]*[Cc][Aa][Pp][Ii][Tt][Aa][Ll][ ]*[)]'), FALSE) AS is_capital,
    NULLIF(upper(TRIM(regexp_replace(regexp_replace(regexp_replace(p.label_text, ' ([a-z0-9]{1,2}/)$', ''), ' *[(][^()]*[)]', ''), ' +', ' '))), '') AS place_name
  FROM shaped AS p
  LEFT JOIN spans AS a ON a.batch_id = p.batch_id AND a.source_sheet = p.source_sheet AND a.start_pos = p.place_pos
),
leveled AS (
  SELECT p.*, CASE WHEN p.is_aggregate AND p.depth = 0 THEN 'country' WHEN p.is_aggregate AND p.depth = 1 THEN 'region' WHEN p.is_aggregate AND p.depth = 2 THEN 'province' WHEN NOT p.is_aggregate AND p.depth IN (2, 3) THEN 'city_municipality' END AS level
  FROM parsed AS p
),
-- Region and province: the place itself or the aggregate around it at that level.
named AS (
  SELECT l.batch_id, l.source_sheet, l.place_pos,
         MAX(CASE WHEN a.level = 'region' THEN a.place_name END) AS region_name,
         MAX(CASE WHEN a.level = 'province' THEN a.place_name END) AS province_name
  FROM leveled AS l
  JOIN (SELECT batch_id, source_sheet, place_pos, start_pos AS around_pos FROM enclosing
        UNION ALL SELECT batch_id, source_sheet, place_pos, place_pos FROM places) AS x
    ON x.batch_id = l.batch_id AND x.source_sheet = l.source_sheet AND x.place_pos = l.place_pos
  JOIN leveled AS a ON a.batch_id = x.batch_id AND a.source_sheet = x.source_sheet AND a.place_pos = x.around_pos
  GROUP BY l.batch_id, l.source_sheet, l.place_pos
)
SELECT
  l.batch_id,
  l.source_sheet,
  l.place_pos,
  l.place_name,
  l.footnote,
  l.old_name,
  l.is_capital,
  l.level,
  CASE WHEN l.level = 'province' AND l.place_name IN ('INTERIM PROVINCE', 'SPECIAL GEOGRAPHIC AREA') THEN 'special_geographic_area' WHEN l.level = 'city_municipality' AND par.place_name IN ('INTERIM PROVINCE', 'SPECIAL GEOGRAPHIC AREA') AND regexp_like(l.place_name, ' CLUSTER( [IVX]+)?$') THEN 'sga_cluster' ELSE 'standard' END AS place_status,
  l.depth,
  n.region_name,
  n.province_name,
  par.place_name AS parent_name
FROM leveled AS l
LEFT JOIN leveled AS par ON par.batch_id = l.batch_id AND par.source_sheet = l.source_sheet AND par.place_pos = l.parent_pos
LEFT JOIN named AS n ON n.batch_id = l.batch_id AND n.source_sheet = l.source_sheet AND n.place_pos = l.place_pos;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_work_tree OWNER TO `reached-hq`;

-- Every cell with its place.
CREATE OR REPLACE TEMPORARY VIEW psa_school_age_population_classified AS
SELECT
  c.census_year,
  c.population_concept,
  NULLIF(TRIM(regexp_replace(translate(c.place_label, chr(9) || chr(160), '  '), ' +', ' ')), '') AS place_label,
  t.place_name,
  t.footnote,
  t.old_name,
  t.is_capital,
  t.level,
  t.place_status,
  t.region_name,
  t.province_name,
  t.parent_name,
  c.sex,
  c.age,
  c.population,
  c.quarantine_reasons,
  c.logical_dataset,
  c.batch_id,
  c.delivery_version,
  c.schema_version,
  c.source_sha256,
  c.source_sheet,
  c.source_row_number,
  c.place_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM edu_access.`03-silver`.psa_school_age_population_work_cells AS c
LEFT JOIN edu_access.`03-silver`.psa_school_age_population_work_tree AS t ON t.batch_id = c.batch_id AND t.source_sheet = c.source_sheet AND t.place_pos = c.place_pos;

-- One row per cell, with the Bronze row it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_clean_candidate USING DELTA AS
SELECT
  census_year,
  population_concept,
  place_label,
  place_name,
  footnote,
  old_name,
  is_capital,
  level,
  place_status,
  region_name,
  province_name,
  parent_name,
  sex,
  age,
  population,
  logical_dataset,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_sheet,
  source_row_number,
  place_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_school_age_population_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.psa_school_age_population_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_school_age_population_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_school_age_population_clean_candidate OWNER TO `reached-hq`;

-- Cells set aside, never deleted: the Bronze row, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_quarantine_candidate USING DELTA AS
SELECT
  census_year,
  population_concept,
  place_label,
  sex,
  age,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  logical_dataset,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_sheet,
  source_row_number,
  place_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_school_age_population_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.psa_school_age_population_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_school_age_population_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_school_age_population_quarantine_candidate OWNER TO `reached-hq`;

-- The work tables are not needed after the build.
DROP TABLE IF EXISTS edu_access.`03-silver`.psa_school_age_population_work_cells;
DROP TABLE IF EXISTS edu_access.`03-silver`.psa_school_age_population_work_places;
DROP TABLE IF EXISTS edu_access.`03-silver`.psa_school_age_population_work_spans;
DROP TABLE IF EXISTS edu_access.`03-silver`.psa_school_age_population_work_tree;
