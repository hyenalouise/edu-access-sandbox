-- Silver gate for psa_school_age_population. Generated from config/ingestion/psa_school_age_population.json
-- and config/mappings/psa_school_age_population.json by src/silver/psa_school_age_population.py:
--   python -m src.silver.cli gate --source psa_school_age_population > etl/03_silver/90_validate_psa_school_age_population_clean.sql
-- Do not edit by hand; tests/test_silver_school_age.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results: the whole build, each current batch (one census year), and each
-- batch and population concept (check names end in the concept). On any FAIL it records the run
-- 'failed' and stops the task before publishing, so the Silver tables keep the last build that passed
-- and nothing downstream runs. Otherwise it copies the candidates to the Silver tables and records
-- the run 'succeeded'. PASS: as expected. WARN: recorded, the build is published (zero counts).
-- FAIL: the candidate cannot be trusted. Results hold counts, never row values; the national totals
-- by age are recorded so a rerun shows any change.
--
-- The tree is checked here independently of how the build found it: every place except the country
-- resolves to exactly one parent by name (the region qualifying a province), every aggregate equals
-- the sum of its children in every cell, no place is 0 in every cell (the sums cannot place it), and
-- the places per level and per place_status are the counts pinned for the workbook in the Silver
-- rules (D-053).
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run that built the tables
--   :code_revision  the commit that ran, from the job parameter; never a literal

-- Only this execution's results decide: a repaired job run keeps its run_id, and the
-- results of an earlier attempt must not fail it again.
DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;
SET VARIABLE silver_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, batch_id, 'psa_school_age_population', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id FROM edu_access.`01-control`.current_batches WHERE source_id = 'psa_school_age_population'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.psa_school_age_population_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_quarantine_candidate),
concepts AS (SELECT * FROM (VALUES ('total', 'Total Pop'), ('household', 'Household Pop')) AS v(population_concept, sheet_suffix)),
pins AS (SELECT * FROM (VALUES ('e40d71839b951926cd3c9515c1edafbb6a2121f734670716e3b21bd3f9dcd35f', 1, 17, 82, 1642, 1, 8), ('49d15bb0cdd191cd6aef4a14f4b063da247ba791b32caa653c37c464dff15954', 1, 18, 83, 1642, 1, 0)) AS v(workbook_sha256, country, region, province, city_municipality, special_geographic_area, sga_cluster)),
-- Every current batch and population concept: the grid every sheet check is written for.
grid AS (SELECT cur.batch_id, k.population_concept FROM cur CROSS JOIN concepts AS k),
-- Each current batch: its census year and workbook, and its Bronze rows by kind and sheet.
batches AS (
  SELECT cur.batch_id,
         MAX(b.census_year) AS census_year,
         MAX(b.source_sha256) AS source_sha256,
         COUNT(b.source_row_number) AS bronze_rows,
         COUNT_IF(b.source_row_kind IS NULL OR b.source_row_kind NOT IN ('place', 'sex_total', 'sex_male', 'sex_female', 'title', 'header', 'note', 'source', 'blank')) AS other_rows,
         COUNT_IF(b.source_row_kind IN ('title', 'header', 'note', 'source', 'blank')) AS structural_rows,
         COUNT_IF(b.source_row_kind = 'place') AS kind_place,
         COUNT_IF(b.source_row_kind = 'sex_total') AS kind_sex_total,
         COUNT_IF(b.source_row_kind = 'sex_male') AS kind_sex_male,
         COUNT_IF(b.source_row_kind = 'sex_female') AS kind_sex_female,
         COUNT_IF(b.source_row_kind = 'title') AS kind_title,
         COUNT_IF(b.source_row_kind = 'header') AS kind_header,
         COUNT_IF(b.source_row_kind = 'note') AS kind_note,
         COUNT_IF(b.source_row_kind = 'source') AS kind_source,
         COUNT_IF(b.source_row_kind = 'blank') AS kind_blank,
         COUNT_IF(b.source_row_number IS NOT NULL AND k.population_concept IS NULL) AS unknown_sheet_rows,
         COUNT(DISTINCT k.population_concept) AS concept_sheets
  FROM cur
  LEFT JOIN bronze AS b ON b.batch_id = cur.batch_id
  LEFT JOIN concepts AS k ON b.source_sheet = b.census_year || ' ' || k.sheet_suffix
  GROUP BY cur.batch_id
),
found AS (
  SELECT COUNT(*) AS current_batches, COUNT(*) - COUNT(DISTINCT census_year) AS repeated_years FROM batches
),
-- Each Bronze sheet: how many count cells its rows hold.
bronze_sheets AS (
  SELECT b.batch_id, k.population_concept, SUM(CASE WHEN b.schema_version IN ('v1') AND b.source_row_kind = 'place' THEN 60 WHEN b.schema_version IN ('v2') AND b.source_row_kind IN ('sex_total', 'sex_male', 'sex_female') THEN 20 ELSE 0 END) AS count_cells
  FROM bronze AS b JOIN concepts AS k ON b.source_sheet = b.census_year || ' ' || k.sheet_suffix
  GROUP BY b.batch_id, k.population_concept
),
-- Each clean cell beside its Bronze row and the place row above it: the value is the published
-- cell, and the label is parsed as the rules say.
clean_sheets AS (
  SELECT
    c.batch_id,
    c.population_concept,
    COUNT(*) AS clean_cells,
    COUNT_IF(c.population IS NULL) AS null_population,
    COUNT_IF(c.population = 0) AS zero_cells,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.population IS NOT DISTINCT FROM CASE WHEN regexp_like((CASE b.schema_version
        WHEN 'v1' THEN CASE c.sex
          WHEN 'both' THEN CASE c.age WHEN 5 THEN b.`both_sexes_age_5` WHEN 6 THEN b.`both_sexes_age_6` WHEN 7 THEN b.`both_sexes_age_7` WHEN 8 THEN b.`both_sexes_age_8` WHEN 9 THEN b.`both_sexes_age_9` WHEN 10 THEN b.`both_sexes_age_10` WHEN 11 THEN b.`both_sexes_age_11` WHEN 12 THEN b.`both_sexes_age_12` WHEN 13 THEN b.`both_sexes_age_13` WHEN 14 THEN b.`both_sexes_age_14` WHEN 15 THEN b.`both_sexes_age_15` WHEN 16 THEN b.`both_sexes_age_16` WHEN 17 THEN b.`both_sexes_age_17` WHEN 18 THEN b.`both_sexes_age_18` WHEN 19 THEN b.`both_sexes_age_19` WHEN 20 THEN b.`both_sexes_age_20` WHEN 21 THEN b.`both_sexes_age_21` WHEN 22 THEN b.`both_sexes_age_22` WHEN 23 THEN b.`both_sexes_age_23` WHEN 24 THEN b.`both_sexes_age_24` END
          WHEN 'male' THEN CASE c.age WHEN 5 THEN b.`male_age_5` WHEN 6 THEN b.`male_age_6` WHEN 7 THEN b.`male_age_7` WHEN 8 THEN b.`male_age_8` WHEN 9 THEN b.`male_age_9` WHEN 10 THEN b.`male_age_10` WHEN 11 THEN b.`male_age_11` WHEN 12 THEN b.`male_age_12` WHEN 13 THEN b.`male_age_13` WHEN 14 THEN b.`male_age_14` WHEN 15 THEN b.`male_age_15` WHEN 16 THEN b.`male_age_16` WHEN 17 THEN b.`male_age_17` WHEN 18 THEN b.`male_age_18` WHEN 19 THEN b.`male_age_19` WHEN 20 THEN b.`male_age_20` WHEN 21 THEN b.`male_age_21` WHEN 22 THEN b.`male_age_22` WHEN 23 THEN b.`male_age_23` WHEN 24 THEN b.`male_age_24` END
          WHEN 'female' THEN CASE c.age WHEN 5 THEN b.`female_age_5` WHEN 6 THEN b.`female_age_6` WHEN 7 THEN b.`female_age_7` WHEN 8 THEN b.`female_age_8` WHEN 9 THEN b.`female_age_9` WHEN 10 THEN b.`female_age_10` WHEN 11 THEN b.`female_age_11` WHEN 12 THEN b.`female_age_12` WHEN 13 THEN b.`female_age_13` WHEN 14 THEN b.`female_age_14` WHEN 15 THEN b.`female_age_15` WHEN 16 THEN b.`female_age_16` WHEN 17 THEN b.`female_age_17` WHEN 18 THEN b.`female_age_18` WHEN 19 THEN b.`female_age_19` WHEN 20 THEN b.`female_age_20` WHEN 21 THEN b.`female_age_21` WHEN 22 THEN b.`female_age_22` WHEN 23 THEN b.`female_age_23` WHEN 24 THEN b.`female_age_24` END
        END
        WHEN 'v2' THEN CASE WHEN c.sex = CASE b.source_row_kind WHEN 'sex_total' THEN 'both' WHEN 'sex_male' THEN 'male' WHEN 'sex_female' THEN 'female' END THEN CASE c.age WHEN 5 THEN b.`age_5` WHEN 6 THEN b.`age_6` WHEN 7 THEN b.`age_7` WHEN 8 THEN b.`age_8` WHEN 9 THEN b.`age_9` WHEN 10 THEN b.`age_10` WHEN 11 THEN b.`age_11` WHEN 12 THEN b.`age_12` WHEN 13 THEN b.`age_13` WHEN 14 THEN b.`age_14` WHEN 15 THEN b.`age_15` WHEN 16 THEN b.`age_16` WHEN 17 THEN b.`age_17` WHEN 18 THEN b.`age_18` WHEN 19 THEN b.`age_19` WHEN 20 THEN b.`age_20` WHEN 21 THEN b.`age_21` WHEN 22 THEN b.`age_22` WHEN 23 THEN b.`age_23` WHEN 24 THEN b.`age_24` END END
      END), '^[0-9]{1,9}$') THEN TRY_CAST((CASE b.schema_version
        WHEN 'v1' THEN CASE c.sex
          WHEN 'both' THEN CASE c.age WHEN 5 THEN b.`both_sexes_age_5` WHEN 6 THEN b.`both_sexes_age_6` WHEN 7 THEN b.`both_sexes_age_7` WHEN 8 THEN b.`both_sexes_age_8` WHEN 9 THEN b.`both_sexes_age_9` WHEN 10 THEN b.`both_sexes_age_10` WHEN 11 THEN b.`both_sexes_age_11` WHEN 12 THEN b.`both_sexes_age_12` WHEN 13 THEN b.`both_sexes_age_13` WHEN 14 THEN b.`both_sexes_age_14` WHEN 15 THEN b.`both_sexes_age_15` WHEN 16 THEN b.`both_sexes_age_16` WHEN 17 THEN b.`both_sexes_age_17` WHEN 18 THEN b.`both_sexes_age_18` WHEN 19 THEN b.`both_sexes_age_19` WHEN 20 THEN b.`both_sexes_age_20` WHEN 21 THEN b.`both_sexes_age_21` WHEN 22 THEN b.`both_sexes_age_22` WHEN 23 THEN b.`both_sexes_age_23` WHEN 24 THEN b.`both_sexes_age_24` END
          WHEN 'male' THEN CASE c.age WHEN 5 THEN b.`male_age_5` WHEN 6 THEN b.`male_age_6` WHEN 7 THEN b.`male_age_7` WHEN 8 THEN b.`male_age_8` WHEN 9 THEN b.`male_age_9` WHEN 10 THEN b.`male_age_10` WHEN 11 THEN b.`male_age_11` WHEN 12 THEN b.`male_age_12` WHEN 13 THEN b.`male_age_13` WHEN 14 THEN b.`male_age_14` WHEN 15 THEN b.`male_age_15` WHEN 16 THEN b.`male_age_16` WHEN 17 THEN b.`male_age_17` WHEN 18 THEN b.`male_age_18` WHEN 19 THEN b.`male_age_19` WHEN 20 THEN b.`male_age_20` WHEN 21 THEN b.`male_age_21` WHEN 22 THEN b.`male_age_22` WHEN 23 THEN b.`male_age_23` WHEN 24 THEN b.`male_age_24` END
          WHEN 'female' THEN CASE c.age WHEN 5 THEN b.`female_age_5` WHEN 6 THEN b.`female_age_6` WHEN 7 THEN b.`female_age_7` WHEN 8 THEN b.`female_age_8` WHEN 9 THEN b.`female_age_9` WHEN 10 THEN b.`female_age_10` WHEN 11 THEN b.`female_age_11` WHEN 12 THEN b.`female_age_12` WHEN 13 THEN b.`female_age_13` WHEN 14 THEN b.`female_age_14` WHEN 15 THEN b.`female_age_15` WHEN 16 THEN b.`female_age_16` WHEN 17 THEN b.`female_age_17` WHEN 18 THEN b.`female_age_18` WHEN 19 THEN b.`female_age_19` WHEN 20 THEN b.`female_age_20` WHEN 21 THEN b.`female_age_21` WHEN 22 THEN b.`female_age_22` WHEN 23 THEN b.`female_age_23` WHEN 24 THEN b.`female_age_24` END
        END
        WHEN 'v2' THEN CASE WHEN c.sex = CASE b.source_row_kind WHEN 'sex_total' THEN 'both' WHEN 'sex_male' THEN 'male' WHEN 'sex_female' THEN 'female' END THEN CASE c.age WHEN 5 THEN b.`age_5` WHEN 6 THEN b.`age_6` WHEN 7 THEN b.`age_7` WHEN 8 THEN b.`age_8` WHEN 9 THEN b.`age_9` WHEN 10 THEN b.`age_10` WHEN 11 THEN b.`age_11` WHEN 12 THEN b.`age_12` WHEN 13 THEN b.`age_13` WHEN 14 THEN b.`age_14` WHEN 15 THEN b.`age_15` WHEN 16 THEN b.`age_16` WHEN 17 THEN b.`age_17` WHEN 18 THEN b.`age_18` WHEN 19 THEN b.`age_19` WHEN 20 THEN b.`age_20` WHEN 21 THEN b.`age_21` WHEN 22 THEN b.`age_22` WHEN 23 THEN b.`age_23` WHEN 24 THEN b.`age_24` END END
      END) AS INT) END)) AS mismatched,
    COUNT_IF(pb.source_row_number IS NULL OR c.place_label IS DISTINCT FROM NULLIF(TRIM(regexp_replace(translate(pb.label, chr(9) || chr(160), '  '), ' +', ' ')), '')
        OR NOT (c.footnote IS NOT DISTINCT FROM NULLIF(regexp_extract(c.place_label, ' ([a-z0-9]{1,2}/)$', 1), '')) OR NOT (c.old_name IS NOT DISTINCT FROM NULLIF(array_join(regexp_extract_all(regexp_replace(regexp_replace(c.place_label, ' ([a-z0-9]{1,2}/)$', ''), ' *[(][ ]*[Cc][Aa][Pp][Ii][Tt][Aa][Ll][ ]*[)]', ''), '[(][ ]*([^()]*[^() ])[ ]*[)]', 1), ', '), '')) OR NOT (c.is_capital IS NOT DISTINCT FROM COALESCE(regexp_like(c.place_label, '[(][ ]*[Cc][Aa][Pp][Ii][Tt][Aa][Ll][ ]*[)]'), FALSE)) OR NOT (c.place_name IS NOT DISTINCT FROM NULLIF(upper(TRIM(regexp_replace(regexp_replace(regexp_replace(c.place_label, ' ([a-z0-9]{1,2}/)$', ''), ' *[(][^()]*[)]', ''), ' +', ' '))), ''))
        OR c.place_name IS NULL OR regexp_like(c.place_name, '[()/]')) AS misparsed,
    COUNT(DISTINCT CASE WHEN c.level IS NULL THEN c.place_row_number END) AS unleveled_places,
    COUNT(DISTINCT CASE WHEN c.level = 'country' THEN c.place_row_number END) AS places_country,
    COUNT(DISTINCT CASE WHEN c.level = 'region' THEN c.place_row_number END) AS places_region,
    COUNT(DISTINCT CASE WHEN c.level = 'province' THEN c.place_row_number END) AS places_province,
    COUNT(DISTINCT CASE WHEN c.level = 'city_municipality' THEN c.place_row_number END) AS places_city_municipality,
    COUNT(DISTINCT CASE WHEN c.place_status = 'special_geographic_area' THEN c.place_row_number END) AS status_special_geographic_area,
    COUNT(DISTINCT CASE WHEN c.place_status = 'sga_cluster' THEN c.place_row_number END) AS status_sga_cluster,
    COUNT(DISTINCT CASE WHEN c.place_status IS DISTINCT FROM CASE WHEN c.level = 'province' AND c.place_name IN ('INTERIM PROVINCE', 'SPECIAL GEOGRAPHIC AREA') THEN 'special_geographic_area' WHEN c.level = 'city_municipality' AND c.parent_name IN ('INTERIM PROVINCE', 'SPECIAL GEOGRAPHIC AREA') AND regexp_like(c.place_name, ' CLUSTER( [IVX]+)?$') THEN 'sga_cluster' ELSE 'standard' END THEN c.place_row_number END) AS misflagged_places,
    COUNT(DISTINCT CASE WHEN c.footnote IS NOT NULL THEN c.place_row_number END) AS footnote_places,
    COUNT(DISTINCT CASE WHEN c.old_name IS NOT NULL THEN c.place_row_number END) AS old_name_places,
    COUNT(DISTINCT CASE WHEN c.is_capital THEN c.place_row_number END) AS capital_places
  FROM clean AS c
  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_sheet = c.source_sheet
   AND b.source_row_number = c.source_row_number AND ((b.schema_version IN ('v1') AND b.source_row_kind = 'place') OR (b.schema_version IN ('v2') AND b.source_row_kind IN ('sex_total', 'sex_male', 'sex_female')))
  LEFT JOIN bronze AS pb ON pb.source_sha256 = c.source_sha256 AND pb.source_sheet = c.source_sheet
   AND pb.source_row_number = c.place_row_number AND pb.source_row_kind = 'place'
  GROUP BY c.batch_id, c.population_concept
),
-- Places whose every cell is 0: the sums cannot say where such a place belongs.
zero_places AS (
  SELECT batch_id, population_concept, COUNT(*) AS all_zero_places FROM (
    SELECT batch_id, population_concept, place_row_number
    FROM clean GROUP BY batch_id, population_concept, place_row_number
    HAVING COUNT_IF(population <> 0) = 0
  ) AS z GROUP BY batch_id, population_concept
),
-- The key: one row per census year, concept, place name, parent, sex and age.
repeated AS (
  SELECT batch_id, population_concept, SUM(n - 1) AS repeated_keys FROM (
    SELECT batch_id, population_concept, place_name, parent_name, sex, age, COUNT(*) AS n
    FROM clean GROUP BY batch_id, population_concept, place_name, parent_name, sex, age
  ) AS k WHERE n > 1 GROUP BY batch_id, population_concept
),
-- The tree, checked from the published names: each place's parent is the aggregate of the level above
-- it with its parent_name (in the same region below the country).
links AS (
  SELECT c.batch_id, c.population_concept, c.place_row_number, c.sex, c.age, c.population, c.parent_name,
         c.region_name, CASE WHEN c.level = 'region' THEN 'country' WHEN c.level = 'province' THEN 'region' WHEN c.level = 'city_municipality' AND c.province_name IS NOT NULL THEN 'province' WHEN c.level = 'city_municipality' THEN 'region' END AS parent_level
  FROM clean AS c WHERE c.level IS NOT NULL AND c.level <> 'country'
),
aggregates AS (
  SELECT * FROM clean WHERE level IN ('country', 'region', 'province')
),
resolved AS (
  SELECT l.batch_id, l.population_concept, l.place_row_number, l.sex, l.age, l.population,
         COUNT(p.place_row_number) AS parents, MAX(p.place_row_number) AS parent_row
  FROM links AS l
  LEFT JOIN aggregates AS p ON p.batch_id = l.batch_id AND p.population_concept = l.population_concept
   AND p.sex = l.sex AND p.age = l.age AND p.place_name = l.parent_name AND p.level = l.parent_level
   AND (l.parent_level = 'country' OR p.region_name = l.region_name)
  GROUP BY l.batch_id, l.population_concept, l.place_row_number, l.sex, l.age, l.population
),
child_sums AS (
  SELECT batch_id, population_concept, parent_row, sex, age, SUM(CAST(population AS BIGINT)) AS children
  FROM resolved WHERE parents = 1
  GROUP BY batch_id, population_concept, parent_row, sex, age
),
tree AS (
  SELECT g.batch_id, g.population_concept,
         COALESCE(u.unresolved_parents, 0) AS unresolved_parents, COALESCE(a.unclosed, 0) AS unclosed
  FROM grid AS g
  LEFT JOIN (SELECT batch_id, population_concept, COUNT_IF(parents <> 1) AS unresolved_parents
             FROM resolved GROUP BY batch_id, population_concept) AS u
    ON u.batch_id = g.batch_id AND u.population_concept = g.population_concept
  LEFT JOIN (SELECT p.batch_id, p.population_concept,
                    COUNT_IF(s.children IS NULL OR p.population IS NULL OR s.children <> p.population) AS unclosed
             FROM aggregates AS p
             LEFT JOIN child_sums AS s ON s.batch_id = p.batch_id AND s.population_concept = p.population_concept
              AND s.parent_row = p.place_row_number AND s.sex = p.sex AND s.age = p.age
             GROUP BY p.batch_id, p.population_concept) AS a
    ON a.batch_id = g.batch_id AND a.population_concept = g.population_concept
),
-- Both sexes = male + female for every place and age (profile O-4).
sex_sums AS (
  SELECT batch_id, population_concept, COUNT_IF(both_sexes IS NULL OR male IS NULL OR female IS NULL
                                                 OR both_sexes <> male + female OR n <> 3) AS sex_problems
  FROM (
    SELECT batch_id, population_concept, place_row_number, age, COUNT(*) AS n,
           SUM(CASE WHEN sex = 'both' THEN CAST(population AS BIGINT) END) AS both_sexes,
           SUM(CASE WHEN sex = 'male' THEN CAST(population AS BIGINT) END) AS male,
           SUM(CASE WHEN sex = 'female' THEN CAST(population AS BIGINT) END) AS female
    FROM clean GROUP BY batch_id, population_concept, place_row_number, age
  ) AS s
  GROUP BY batch_id, population_concept
),
-- The national totals by age, both sexes, recorded so a rerun shows any change.
national AS (
  SELECT batch_id, population_concept, COALESCE(CAST(SUM(CASE WHEN age = 5 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 6 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 7 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 8 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 9 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 10 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 11 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 12 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 13 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 14 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 15 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 16 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 17 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 18 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 19 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 20 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 21 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 22 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 23 THEN population END) AS STRING), '-') || ',' || COALESCE(CAST(SUM(CASE WHEN age = 24 THEN population END) AS STRING), '-') AS national_by_age
  FROM clean WHERE level = 'country' AND sex = 'both' AND age IN (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)
  GROUP BY batch_id, population_concept
),
quarantine_sheets AS (
  SELECT q.batch_id, q.population_concept, COUNT(*) AS quarantined_cells,
         COUNT_IF(array_contains(q.quarantine_reasons, 'population_blank')) AS reason_population_blank,
         COUNT_IF(array_contains(q.quarantine_reasons, 'population_negative')) AS reason_population_negative,
         COUNT_IF(array_contains(q.quarantine_reasons, 'population_not_whole_number')) AS reason_population_not_whole_number
  FROM quarantined AS q GROUP BY q.batch_id, q.population_concept
),
sheets AS (
  SELECT
    g.batch_id,
    g.population_concept,
    COALESCE(bs.count_cells, 0) AS count_cells,
    COALESCE(cs.clean_cells, 0) AS clean_cells,
    COALESCE(cs.null_population, 0) AS null_population,
    COALESCE(cs.zero_cells, 0) AS zero_cells,
    COALESCE(cs.mismatched, 0) AS mismatched,
    COALESCE(cs.misparsed, 0) AS misparsed,
    COALESCE(cs.unleveled_places, 0) AS unleveled_places,
    COALESCE(cs.places_country, 0) AS places_country,
    COALESCE(cs.places_region, 0) AS places_region,
    COALESCE(cs.places_province, 0) AS places_province,
    COALESCE(cs.places_city_municipality, 0) AS places_city_municipality,
    COALESCE(cs.footnote_places, 0) AS footnote_places,
    COALESCE(cs.old_name_places, 0) AS old_name_places,
    COALESCE(cs.capital_places, 0) AS capital_places,
    COALESCE(r.repeated_keys, 0) AS repeated_keys,
    t.unresolved_parents,
    t.unclosed,
    COALESCE(z.all_zero_places, 0) AS all_zero_places,
    COALESCE(cs.misflagged_places, 0) AS misflagged_places,
    COALESCE(x.sex_problems, 0) AS sex_problems,
    COALESCE(n.national_by_age, '') AS national_by_age,
    COALESCE(q.quarantined_cells, 0) AS quarantined_cells,
    COALESCE(q.reason_population_blank, 0) AS reason_population_blank,
    COALESCE(q.reason_population_negative, 0) AS reason_population_negative,
    COALESCE(q.reason_population_not_whole_number, 0) AS reason_population_not_whole_number,
    'country ' || CAST(p.country AS STRING) || ', ' || 'region ' || CAST(p.region AS STRING) || ', ' || 'province ' || CAST(p.province AS STRING) || ', ' || 'city_municipality ' || CAST(p.city_municipality AS STRING) AS expected_levels,
    'country ' || CAST(COALESCE(cs.places_country, 0) AS STRING) || ', ' || 'region ' || CAST(COALESCE(cs.places_region, 0) AS STRING) || ', ' || 'province ' || CAST(COALESCE(cs.places_province, 0) AS STRING) || ', ' || 'city_municipality ' || CAST(COALESCE(cs.places_city_municipality, 0) AS STRING) AS actual_levels,
    'special_geographic_area ' || CAST(p.special_geographic_area AS STRING) || ', ' || 'sga_cluster ' || CAST(p.sga_cluster AS STRING) AS expected_statuses,
    'special_geographic_area ' || CAST(COALESCE(cs.status_special_geographic_area, 0) AS STRING) || ', ' || 'sga_cluster ' || CAST(COALESCE(cs.status_sga_cluster, 0) AS STRING) AS actual_statuses
  FROM grid AS g
  JOIN batches AS bt ON bt.batch_id = g.batch_id
  LEFT JOIN pins AS p ON p.workbook_sha256 = bt.source_sha256
  LEFT JOIN bronze_sheets AS bs ON bs.batch_id = g.batch_id AND bs.population_concept = g.population_concept
  LEFT JOIN clean_sheets AS cs ON cs.batch_id = g.batch_id AND cs.population_concept = g.population_concept
  LEFT JOIN repeated AS r ON r.batch_id = g.batch_id AND r.population_concept = g.population_concept
  LEFT JOIN zero_places AS z ON z.batch_id = g.batch_id AND z.population_concept = g.population_concept
  LEFT JOIN tree AS t ON t.batch_id = g.batch_id AND t.population_concept = g.population_concept
  LEFT JOIN sex_sums AS x ON x.batch_id = g.batch_id AND x.population_concept = g.population_concept
  LEFT JOIN national AS n ON n.batch_id = g.batch_id AND n.population_concept = g.population_concept
  LEFT JOIN quarantine_sheets AS q ON q.batch_id = g.batch_id AND q.population_concept = g.population_concept
),
-- The two concepts of a census year, cell by cell: the same places, household never above total (O-5).
concept_cells AS (
  SELECT COALESCE(t.batch_id, h.batch_id) AS batch_id, t.place_name AS total_place, h.place_name AS household_place,
         t.parent_name, t.level, t.population AS total, h.population AS household
  FROM (SELECT * FROM clean WHERE population_concept = 'total') AS t
  FULL OUTER JOIN (SELECT * FROM clean WHERE population_concept = 'household') AS h ON t.batch_id = h.batch_id AND t.place_name = h.place_name AND t.level = h.level AND t.sex = h.sex AND t.age = h.age AND t.parent_name IS NOT DISTINCT FROM h.parent_name
),
equal_places AS (
  SELECT batch_id, COUNT(*) AS equal_places FROM (
    SELECT batch_id, total_place, parent_name, level
    FROM concept_cells WHERE total_place IS NOT NULL AND household_place IS NOT NULL
    GROUP BY batch_id, total_place, parent_name, level
    HAVING COUNT_IF(total IS DISTINCT FROM household) = 0
  ) AS e GROUP BY batch_id
),
pairs AS (
  SELECT cur.batch_id,
         COALESCE(SUM(CASE WHEN c.total_place IS NULL OR c.household_place IS NULL THEN 1 ELSE 0 END), 0) AS unpaired_cells,
         COALESCE(SUM(CASE WHEN c.household > c.total THEN 1 ELSE 0 END), 0) AS household_above_total,
         COALESCE(MAX(e.equal_places), 0) AS equal_places
  FROM cur
  LEFT JOIN concept_cells AS c ON c.batch_id = cur.batch_id
  LEFT JOIN equal_places AS e ON e.batch_id = cur.batch_id
  GROUP BY cur.batch_id
),
silver_rows AS (
  SELECT census_year, population_concept, sex, age, logical_dataset, batch_id, delivery_version, schema_version, source_sha256, source_sheet, source_row_number, place_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT census_year, population_concept, sex, age, logical_dataset, batch_id, delivery_version, schema_version, source_sha256, source_sheet, source_row_number, place_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(census_year IS NULL OR population_concept IS NULL OR sex IS NULL OR age IS NULL OR logical_dataset IS NULL OR batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_sheet IS NULL OR source_row_number IS NULL OR place_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
-- Silver rows whose Bronze row is not a count row of a current batch (an old version, a note, or gone).
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_sheet = bronze.source_sheet
    AND s.source_row_number = bronze.source_row_number AND s.batch_id = bronze.batch_id
    AND ((bronze.schema_version IN ('v1') AND bronze.source_row_kind = 'place') OR (bronze.schema_version IN ('v2') AND bronze.source_row_kind IN ('sex_total', 'sex_male', 'sex_female')))
  WHERE bronze.source_row_number IS NULL
),
checks AS (
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'one_current_batch_per_census_year' AS check_name,
         CASE WHEN repeated_years = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(repeated_years AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze_cells' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         '1' AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'bronze_rows_accounted' AS check_name,
         CASE WHEN other_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(bronze_rows - other_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'sheets_are_concepts' AS check_name,
         CASE WHEN unknown_sheet_rows = 0 AND concept_sheets = 2 THEN 'PASS' ELSE 'FAIL' END AS status,
         '2 sheets, 0 rows elsewhere' AS expected, CAST(concept_sheets AS STRING) || ' sheets, ' || CAST(unknown_sheet_rows AS STRING) || ' rows elsewhere' AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'household_not_above_total' AS check_name,
         CASE WHEN household_above_total = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(household_above_total AS STRING) AS actual FROM pairs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'concepts_pair_up' AS check_name,
         CASE WHEN unpaired_cells = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(unpaired_cells AS STRING) AS actual FROM pairs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'places_with_equal_concepts' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(equal_places AS STRING) AS actual FROM pairs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rule_structural_rows_not_counts' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(structural_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_place' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_place AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_sex_total' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_sex_total AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_sex_male' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_sex_male AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_sex_female' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_sex_female AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_title' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_title AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_header' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_header AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_note' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_note AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_source' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_source AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_kind_blank' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kind_blank AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rows_reconcile_' || population_concept AS check_name,
         CASE WHEN clean_cells + quarantined_cells = count_cells THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(count_cells AS STRING) AS expected, CAST(clean_cells + quarantined_cells AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'population_matches_bronze_' || population_concept AS check_name,
         CASE WHEN mismatched = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(mismatched AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'population_not_null_' || population_concept AS check_name,
         CASE WHEN null_population = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(null_population AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'place_label_parsed_' || population_concept AS check_name,
         CASE WHEN misparsed = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(misparsed AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'key_unique_' || population_concept AS check_name,
         CASE WHEN repeated_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(repeated_keys AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'place_levels_assigned_' || population_concept AS check_name,
         CASE WHEN unleveled_places = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(unleveled_places AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'one_country_' || population_concept AS check_name,
         CASE WHEN places_country = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         '1' AS expected, CAST(places_country AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'parents_resolve_' || population_concept AS check_name,
         CASE WHEN unresolved_parents = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(unresolved_parents AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'tree_closes_' || population_concept AS check_name,
         CASE WHEN unclosed = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(unclosed AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'no_all_zero_place_' || population_concept AS check_name,
         CASE WHEN all_zero_places = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(all_zero_places AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'levels_match_expected_' || population_concept AS check_name,
         CASE WHEN expected_levels IS NOT NULL AND expected_levels = actual_levels THEN 'PASS' ELSE 'FAIL' END AS status,
         COALESCE(expected_levels, 'not pinned: add this workbook to expected_levels in config/mappings/psa_school_age_population.json') AS expected, actual_levels AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'place_status_match_expected_' || population_concept AS check_name,
         CASE WHEN expected_statuses IS NOT NULL AND expected_statuses = actual_statuses AND misflagged_places = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         COALESCE(expected_statuses, 'not pinned: add this workbook to expected_levels in config/mappings/psa_school_age_population.json') AS expected, actual_statuses || CASE WHEN misflagged_places > 0 THEN ', misflagged ' || CAST(misflagged_places AS STRING) ELSE '' END AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'sexes_add_up_' || population_concept AS check_name,
         CASE WHEN sex_problems = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(sex_problems AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'quarantined_cells_' || population_concept AS check_name,
         CASE WHEN quarantined_cells = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(quarantined_cells AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'quarantine_reason_population_blank_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(reason_population_blank AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'quarantine_reason_population_negative_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(reason_population_negative AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'quarantine_reason_population_not_whole_number_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(reason_population_not_whole_number AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'zero_population_cells_' || population_concept AS check_name,
         CASE WHEN zero_cells = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(zero_cells AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'national_both_sexes_by_age_' || population_concept AS check_name,
         'PASS' AS status,
         'ages 5-24, comma-separated' AS expected, national_by_age AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rule_footnote_split_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(footnote_places AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rule_old_name_split_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(old_name_places AS STRING) AS actual FROM sheets
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_school_age_population_clean_candidate' AS table_name, 'rule_capital_flagged_' || population_concept AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(capital_places AS STRING) AS actual FROM sheets
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'psa_school_age_population' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for psa_school_age_population: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_school_age_population' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_school_age_population_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_school_age_population_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_school_age_population_clean_candidate;

ALTER TABLE edu_access.`03-silver`.psa_school_age_population_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
