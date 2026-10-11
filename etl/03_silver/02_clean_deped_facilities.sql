-- Silver build for deped_facilities. Generated from config/ingestion/deped_facilities.json
-- and config/mappings/deped_facilities.json:
--   python -m src.silver.cli sql --source deped_facilities > etl/03_silver/02_clean_deped_facilities.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each school year). Bronze is read, never changed.
-- Every current Bronze row ends in exactly one of the two tables:
--   deped_facilities_clean_candidate       one row per school per school year, typed and standardized;
--   deped_facilities_quarantine_candidate  rows that cannot be trusted, with their reasons.
-- Every school is kept, public or not: facility measures exist for public schools only (O-3), and
-- Gold scopes to them. Location is not in this file; it comes from enrollment through school_id, so
-- a school missing from the published deped_enrollment_clean for its school year is quarantined
-- (O-2, D-037). This task therefore runs after the enrollment Silver gate.
-- The Silver tables (deped_facilities_clean, deped_facilities_quarantine) are never written here:
-- the gate (the next task) checks the candidates and publishes them only if every check passes,
-- so a failed build never replaces the last good one. It rebuilds on every run (D-025).
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
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_facilities'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'deped_facilities', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every current Bronze row once, cleaned, with the reasons it would be quarantined.
-- A reason is decided with explicit NULL handling, and concat_ws never returns NULL, so
-- quarantine_reasons = '' and <> '' split the rows without losing any.
CREATE OR REPLACE TEMPORARY VIEW deped_facilities_classified AS
WITH enrollment AS (
  SELECT DISTINCT school_year, school_id FROM edu_access.`03-silver`.deped_enrollment_clean
),
bronze AS (
  SELECT r.*, e.school_id IS NOT NULL AS in_enrollment
  FROM edu_access.`02-bronze`.deped_facilities_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  LEFT JOIN enrollment AS e ON e.school_year = r.school_year AND e.school_id = r.school_id
  WHERE c.source_id = 'deped_facilities'
),
-- Labels: whitespace normalized, blank to NULL. Counts stay as published here.
normalized AS (
  SELECT
    r.school_year,
    r.`school_id`,
    COUNT(*) OVER (PARTITION BY r.school_year, r.`school_id`) AS school_id_rows,
    r.in_enrollment,
    NULLIF(TRIM(regexp_replace(translate(r.`sector`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS sector,
    NULLIF(TRIM(regexp_replace(translate(r.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS school_management,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_es,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_jhs,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_shs,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_covered_court,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_covered_court,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_gymnasium,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_gymnasium,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_gate_entrance,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_gate_entrance,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_gate_exit,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_gate_exit,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_perimeter_fence_permanent,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_perimeter_fence_permanent,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_flood_marker,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_flood_marker,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_perimeter_fence_temporary,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_perimeter_fence_temporary,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_playground,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_playground,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_garden,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_garden,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_solar_panel,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_solar_panel,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_bike_rack,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_bike_rack,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_paved_pathway,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_paved_pathway,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_pathway_roofing,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_pathway_roofing,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_road_paved,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_road_paved,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_road_unpaved,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_road_unpaved,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_road_levelled,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_road_levelled,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_road_rough,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_road_rough,
    NULLIF(TRIM(regexp_replace(translate(r.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_has_road_under_construction,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_has_road_under_construction,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_private_4wheel,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_private_4wheel,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_private_motorcycle,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_private_motorcycle,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_boat,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_boat,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_uv_express,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_uv_express,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_pedicab,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_pedicab,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_tricycle,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_tricycle,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_jeepney,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_jeepney,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_habalhabal,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_habalhabal,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_train,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_train,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_bus,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_bus,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_bicycle,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_bicycle,
    NULLIF(TRIM(regexp_replace(translate(r.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS es_accessible_walking_hiking,
    NULLIF(TRIM(regexp_replace(translate(r.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS hs_accessible_walking_hiking,
    r.`es_classrooms_instructional` AS es_classrooms_instructional,
    r.`jhs_classrooms_instructional` AS jhs_classrooms_instructional,
    r.`shs_classrooms_instructional` AS shs_classrooms_instructional,
    r.`es_classrooms_non_instructional` AS es_classrooms_non_instructional,
    r.`jhs_classrooms_non_instructional` AS jhs_classrooms_non_instructional,
    r.`shs_classrooms_non_instructional` AS shs_classrooms_non_instructional,
    r.`buildings_good_condition` AS buildings_good_condition,
    r.`buildings_needs_minor_repair` AS buildings_needs_minor_repair,
    r.`buildings_needs_major_repair` AS buildings_needs_major_repair,
    r.`buildings_for_completion` AS buildings_for_completion,
    r.`buildings_ongoing_construction` AS buildings_ongoing_construction,
    r.`buildings_for_condemnation` AS buildings_for_condemnation,
    r.`buildings_for_demolition` AS buildings_for_demolition,
    r.`es_temporary_learning_spaces` AS es_temporary_learning_spaces,
    r.`hs_temporary_learning_spaces` AS hs_temporary_learning_spaces,
    r.`es_classes_using_temporary_learning_spaces` AS es_classes_using_temporary_learning_spaces,
    r.`hs_classes_using_temporary_learning_spaces` AS hs_classes_using_temporary_learning_spaces,
    r.`es_makeshift_rooms` AS es_makeshift_rooms,
    r.`hs_makeshift_rooms` AS hs_makeshift_rooms,
    r.`es_classes_using_makeshift_rooms` AS es_classes_using_makeshift_rooms,
    r.`hs_classes_using_makeshift_rooms` AS hs_classes_using_makeshift_rooms,
    r.batch_id,
    r.delivery_version,
    r.schema_version,
    r.source_sha256,
    r.source_row_number
  FROM bronze AS r
),
-- Labels mapped to the standard set (unmapped: NULL, and the gate fails), booleans, and counts
-- typed only when they are whole numbers (TRY_CAST alone accepts '5.0' in DuckDB), each against
-- its group's plausible maximum.
typed AS (
  SELECT
    n.school_year,
    n.school_id,
    CASE n.sector
      WHEN 'Public' THEN 'Public'
      WHEN 'Private' THEN 'Private'
      WHEN 'SUC/LUC' THEN 'SUC/LUC'
      WHEN 'PSO' THEN 'PSO'
    END AS sector,
    CASE n.school_management
      WHEN 'DepEd' THEN 'DepEd'
      WHEN 'Non-Sectarian' THEN 'Non-Sectarian'
      WHEN 'Sectarian' THEN 'Sectarian'
      WHEN 'SUC' THEN 'SUC'
      WHEN 'LUC' THEN 'LUC'
      WHEN 'DOST' THEN 'DOST'
      WHEN 'Other GA' THEN 'Other GA'
      WHEN 'International School' THEN 'International School'
      WHEN 'PSO' THEN 'PSO'
    END AS school_management,
    CASE WHEN n.offers_es IN ('True') THEN TRUE WHEN n.offers_es IN ('False') THEN FALSE END AS offers_es,
    CASE WHEN n.offers_jhs IN ('True') THEN TRUE WHEN n.offers_jhs IN ('False') THEN FALSE END AS offers_jhs,
    CASE WHEN n.offers_shs IN ('True') THEN TRUE WHEN n.offers_shs IN ('False') THEN FALSE END AS offers_shs,
    CASE WHEN regexp_like(n.es_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classrooms_instructional AS INT) END AS es_classrooms_instructional,
    CASE WHEN regexp_like(n.jhs_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhs_classrooms_instructional AS INT) END AS jhs_classrooms_instructional,
    CASE WHEN regexp_like(n.shs_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.shs_classrooms_instructional AS INT) END AS shs_classrooms_instructional,
    CASE WHEN regexp_like(n.es_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classrooms_non_instructional AS INT) END AS es_classrooms_non_instructional,
    CASE WHEN regexp_like(n.jhs_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhs_classrooms_non_instructional AS INT) END AS jhs_classrooms_non_instructional,
    CASE WHEN regexp_like(n.shs_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.shs_classrooms_non_instructional AS INT) END AS shs_classrooms_non_instructional,
    CASE WHEN regexp_like(n.buildings_good_condition, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_good_condition AS INT) END AS buildings_good_condition,
    CASE WHEN regexp_like(n.buildings_needs_minor_repair, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_needs_minor_repair AS INT) END AS buildings_needs_minor_repair,
    CASE WHEN regexp_like(n.buildings_needs_major_repair, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_needs_major_repair AS INT) END AS buildings_needs_major_repair,
    CASE WHEN regexp_like(n.buildings_for_completion, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_completion AS INT) END AS buildings_for_completion,
    CASE WHEN regexp_like(n.buildings_ongoing_construction, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_ongoing_construction AS INT) END AS buildings_ongoing_construction,
    CASE WHEN regexp_like(n.buildings_for_condemnation, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_condemnation AS INT) END AS buildings_for_condemnation,
    CASE WHEN regexp_like(n.buildings_for_demolition, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_demolition AS INT) END AS buildings_for_demolition,
    CASE WHEN regexp_like(n.es_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_temporary_learning_spaces AS INT) END AS es_temporary_learning_spaces,
    CASE WHEN regexp_like(n.hs_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_temporary_learning_spaces AS INT) END AS hs_temporary_learning_spaces,
    CASE WHEN regexp_like(n.es_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classes_using_temporary_learning_spaces AS INT) END AS es_classes_using_temporary_learning_spaces,
    CASE WHEN regexp_like(n.hs_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_classes_using_temporary_learning_spaces AS INT) END AS hs_classes_using_temporary_learning_spaces,
    CASE WHEN regexp_like(n.es_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_makeshift_rooms AS INT) END AS es_makeshift_rooms,
    CASE WHEN regexp_like(n.hs_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_makeshift_rooms AS INT) END AS hs_makeshift_rooms,
    CASE WHEN regexp_like(n.es_classes_using_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classes_using_makeshift_rooms AS INT) END AS es_classes_using_makeshift_rooms,
    CASE WHEN regexp_like(n.hs_classes_using_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_classes_using_makeshift_rooms AS INT) END AS hs_classes_using_makeshift_rooms,
    CASE WHEN n.es_has_covered_court IN ('True') THEN TRUE WHEN n.es_has_covered_court IN ('False') THEN FALSE END AS es_has_covered_court,
    CASE WHEN n.hs_has_covered_court IN ('True') THEN TRUE WHEN n.hs_has_covered_court IN ('False') THEN FALSE END AS hs_has_covered_court,
    CASE WHEN n.es_has_gymnasium IN ('True') THEN TRUE WHEN n.es_has_gymnasium IN ('False') THEN FALSE END AS es_has_gymnasium,
    CASE WHEN n.hs_has_gymnasium IN ('True') THEN TRUE WHEN n.hs_has_gymnasium IN ('False') THEN FALSE END AS hs_has_gymnasium,
    CASE WHEN n.es_has_gate_entrance IN ('True') THEN TRUE WHEN n.es_has_gate_entrance IN ('False') THEN FALSE END AS es_has_gate_entrance,
    CASE WHEN n.hs_has_gate_entrance IN ('True') THEN TRUE WHEN n.hs_has_gate_entrance IN ('False') THEN FALSE END AS hs_has_gate_entrance,
    CASE WHEN n.es_has_gate_exit IN ('True') THEN TRUE WHEN n.es_has_gate_exit IN ('False') THEN FALSE END AS es_has_gate_exit,
    CASE WHEN n.hs_has_gate_exit IN ('True') THEN TRUE WHEN n.hs_has_gate_exit IN ('False') THEN FALSE END AS hs_has_gate_exit,
    CASE WHEN n.es_has_perimeter_fence_permanent IN ('True') THEN TRUE WHEN n.es_has_perimeter_fence_permanent IN ('False') THEN FALSE END AS es_has_perimeter_fence_permanent,
    CASE WHEN n.hs_has_perimeter_fence_permanent IN ('True') THEN TRUE WHEN n.hs_has_perimeter_fence_permanent IN ('False') THEN FALSE END AS hs_has_perimeter_fence_permanent,
    CASE WHEN n.es_has_flood_marker IN ('True') THEN TRUE WHEN n.es_has_flood_marker IN ('False') THEN FALSE END AS es_has_flood_marker,
    CASE WHEN n.hs_has_flood_marker IN ('True') THEN TRUE WHEN n.hs_has_flood_marker IN ('False') THEN FALSE END AS hs_has_flood_marker,
    CASE WHEN n.es_has_perimeter_fence_temporary IN ('True') THEN TRUE WHEN n.es_has_perimeter_fence_temporary IN ('False') THEN FALSE END AS es_has_perimeter_fence_temporary,
    CASE WHEN n.hs_has_perimeter_fence_temporary IN ('True') THEN TRUE WHEN n.hs_has_perimeter_fence_temporary IN ('False') THEN FALSE END AS hs_has_perimeter_fence_temporary,
    CASE WHEN n.es_has_playground IN ('True') THEN TRUE WHEN n.es_has_playground IN ('False') THEN FALSE END AS es_has_playground,
    CASE WHEN n.hs_has_playground IN ('True') THEN TRUE WHEN n.hs_has_playground IN ('False') THEN FALSE END AS hs_has_playground,
    CASE WHEN n.es_has_garden IN ('True') THEN TRUE WHEN n.es_has_garden IN ('False') THEN FALSE END AS es_has_garden,
    CASE WHEN n.hs_has_garden IN ('True') THEN TRUE WHEN n.hs_has_garden IN ('False') THEN FALSE END AS hs_has_garden,
    CASE WHEN n.es_has_solar_panel IN ('True') THEN TRUE WHEN n.es_has_solar_panel IN ('False') THEN FALSE END AS es_has_solar_panel,
    CASE WHEN n.hs_has_solar_panel IN ('True') THEN TRUE WHEN n.hs_has_solar_panel IN ('False') THEN FALSE END AS hs_has_solar_panel,
    CASE WHEN n.es_has_bike_rack IN ('True') THEN TRUE WHEN n.es_has_bike_rack IN ('False') THEN FALSE END AS es_has_bike_rack,
    CASE WHEN n.hs_has_bike_rack IN ('True') THEN TRUE WHEN n.hs_has_bike_rack IN ('False') THEN FALSE END AS hs_has_bike_rack,
    CASE WHEN n.es_has_paved_pathway IN ('True') THEN TRUE WHEN n.es_has_paved_pathway IN ('False') THEN FALSE END AS es_has_paved_pathway,
    CASE WHEN n.hs_has_paved_pathway IN ('True') THEN TRUE WHEN n.hs_has_paved_pathway IN ('False') THEN FALSE END AS hs_has_paved_pathway,
    CASE WHEN n.es_has_pathway_roofing IN ('True') THEN TRUE WHEN n.es_has_pathway_roofing IN ('False') THEN FALSE END AS es_has_pathway_roofing,
    CASE WHEN n.hs_has_pathway_roofing IN ('True') THEN TRUE WHEN n.hs_has_pathway_roofing IN ('False') THEN FALSE END AS hs_has_pathway_roofing,
    CASE WHEN n.es_has_road_paved IN ('True') THEN TRUE WHEN n.es_has_road_paved IN ('False') THEN FALSE END AS es_has_road_paved,
    CASE WHEN n.hs_has_road_paved IN ('True') THEN TRUE WHEN n.hs_has_road_paved IN ('False') THEN FALSE END AS hs_has_road_paved,
    CASE WHEN n.es_has_road_unpaved IN ('True') THEN TRUE WHEN n.es_has_road_unpaved IN ('False') THEN FALSE END AS es_has_road_unpaved,
    CASE WHEN n.hs_has_road_unpaved IN ('True') THEN TRUE WHEN n.hs_has_road_unpaved IN ('False') THEN FALSE END AS hs_has_road_unpaved,
    CASE WHEN n.es_has_road_levelled IN ('True') THEN TRUE WHEN n.es_has_road_levelled IN ('False') THEN FALSE END AS es_has_road_levelled,
    CASE WHEN n.hs_has_road_levelled IN ('True') THEN TRUE WHEN n.hs_has_road_levelled IN ('False') THEN FALSE END AS hs_has_road_levelled,
    CASE WHEN n.es_has_road_rough IN ('True') THEN TRUE WHEN n.es_has_road_rough IN ('False') THEN FALSE END AS es_has_road_rough,
    CASE WHEN n.hs_has_road_rough IN ('True') THEN TRUE WHEN n.hs_has_road_rough IN ('False') THEN FALSE END AS hs_has_road_rough,
    CASE WHEN n.es_has_road_under_construction IN ('True') THEN TRUE WHEN n.es_has_road_under_construction IN ('False') THEN FALSE END AS es_has_road_under_construction,
    CASE WHEN n.hs_has_road_under_construction IN ('True') THEN TRUE WHEN n.hs_has_road_under_construction IN ('False') THEN FALSE END AS hs_has_road_under_construction,
    CASE WHEN n.es_accessible_private_4wheel IN ('True') THEN TRUE WHEN n.es_accessible_private_4wheel IN ('False') THEN FALSE END AS es_accessible_private_4wheel,
    CASE WHEN n.hs_accessible_private_4wheel IN ('True') THEN TRUE WHEN n.hs_accessible_private_4wheel IN ('False') THEN FALSE END AS hs_accessible_private_4wheel,
    CASE WHEN n.es_accessible_private_motorcycle IN ('True') THEN TRUE WHEN n.es_accessible_private_motorcycle IN ('False') THEN FALSE END AS es_accessible_private_motorcycle,
    CASE WHEN n.hs_accessible_private_motorcycle IN ('True') THEN TRUE WHEN n.hs_accessible_private_motorcycle IN ('False') THEN FALSE END AS hs_accessible_private_motorcycle,
    CASE WHEN n.es_accessible_boat IN ('True') THEN TRUE WHEN n.es_accessible_boat IN ('False') THEN FALSE END AS es_accessible_boat,
    CASE WHEN n.hs_accessible_boat IN ('True') THEN TRUE WHEN n.hs_accessible_boat IN ('False') THEN FALSE END AS hs_accessible_boat,
    CASE WHEN n.es_accessible_uv_express IN ('True') THEN TRUE WHEN n.es_accessible_uv_express IN ('False') THEN FALSE END AS es_accessible_uv_express,
    CASE WHEN n.hs_accessible_uv_express IN ('True') THEN TRUE WHEN n.hs_accessible_uv_express IN ('False') THEN FALSE END AS hs_accessible_uv_express,
    CASE WHEN n.es_accessible_pedicab IN ('True') THEN TRUE WHEN n.es_accessible_pedicab IN ('False') THEN FALSE END AS es_accessible_pedicab,
    CASE WHEN n.hs_accessible_pedicab IN ('True') THEN TRUE WHEN n.hs_accessible_pedicab IN ('False') THEN FALSE END AS hs_accessible_pedicab,
    CASE WHEN n.es_accessible_tricycle IN ('True') THEN TRUE WHEN n.es_accessible_tricycle IN ('False') THEN FALSE END AS es_accessible_tricycle,
    CASE WHEN n.hs_accessible_tricycle IN ('True') THEN TRUE WHEN n.hs_accessible_tricycle IN ('False') THEN FALSE END AS hs_accessible_tricycle,
    CASE WHEN n.es_accessible_jeepney IN ('True') THEN TRUE WHEN n.es_accessible_jeepney IN ('False') THEN FALSE END AS es_accessible_jeepney,
    CASE WHEN n.hs_accessible_jeepney IN ('True') THEN TRUE WHEN n.hs_accessible_jeepney IN ('False') THEN FALSE END AS hs_accessible_jeepney,
    CASE WHEN n.es_accessible_habalhabal IN ('True') THEN TRUE WHEN n.es_accessible_habalhabal IN ('False') THEN FALSE END AS es_accessible_habalhabal,
    CASE WHEN n.hs_accessible_habalhabal IN ('True') THEN TRUE WHEN n.hs_accessible_habalhabal IN ('False') THEN FALSE END AS hs_accessible_habalhabal,
    CASE WHEN n.es_accessible_train IN ('True') THEN TRUE WHEN n.es_accessible_train IN ('False') THEN FALSE END AS es_accessible_train,
    CASE WHEN n.hs_accessible_train IN ('True') THEN TRUE WHEN n.hs_accessible_train IN ('False') THEN FALSE END AS hs_accessible_train,
    CASE WHEN n.es_accessible_bus IN ('True') THEN TRUE WHEN n.es_accessible_bus IN ('False') THEN FALSE END AS es_accessible_bus,
    CASE WHEN n.hs_accessible_bus IN ('True') THEN TRUE WHEN n.hs_accessible_bus IN ('False') THEN FALSE END AS hs_accessible_bus,
    CASE WHEN n.es_accessible_bicycle IN ('True') THEN TRUE WHEN n.es_accessible_bicycle IN ('False') THEN FALSE END AS es_accessible_bicycle,
    CASE WHEN n.hs_accessible_bicycle IN ('True') THEN TRUE WHEN n.hs_accessible_bicycle IN ('False') THEN FALSE END AS hs_accessible_bicycle,
    CASE WHEN n.es_accessible_walking_hiking IN ('True') THEN TRUE WHEN n.es_accessible_walking_hiking IN ('False') THEN FALSE END AS es_accessible_walking_hiking,
    CASE WHEN n.hs_accessible_walking_hiking IN ('True') THEN TRUE WHEN n.hs_accessible_walking_hiking IN ('False') THEN FALSE END AS hs_accessible_walking_hiking,
    concat_ws(',',
      CASE WHEN n.school_id IS NULL OR n.school_id = '' THEN 'school_id_blank'
           WHEN NOT regexp_like(n.school_id, '^[0-9]{6}$') THEN 'school_id_malformed' END,
      CASE WHEN n.school_id <> '' AND n.school_id_rows > 1 THEN 'school_id_duplicated' END,
      CASE WHEN regexp_like(n.es_classrooms_instructional, '^-[0-9]+$')
         OR regexp_like(n.jhs_classrooms_instructional, '^-[0-9]+$')
         OR regexp_like(n.shs_classrooms_instructional, '^-[0-9]+$')
         OR regexp_like(n.es_classrooms_non_instructional, '^-[0-9]+$')
         OR regexp_like(n.jhs_classrooms_non_instructional, '^-[0-9]+$')
         OR regexp_like(n.shs_classrooms_non_instructional, '^-[0-9]+$')
         OR regexp_like(n.buildings_good_condition, '^-[0-9]+$')
         OR regexp_like(n.buildings_needs_minor_repair, '^-[0-9]+$')
         OR regexp_like(n.buildings_needs_major_repair, '^-[0-9]+$')
         OR regexp_like(n.buildings_for_completion, '^-[0-9]+$')
         OR regexp_like(n.buildings_ongoing_construction, '^-[0-9]+$')
         OR regexp_like(n.buildings_for_condemnation, '^-[0-9]+$')
         OR regexp_like(n.buildings_for_demolition, '^-[0-9]+$')
         OR regexp_like(n.es_temporary_learning_spaces, '^-[0-9]+$')
         OR regexp_like(n.hs_temporary_learning_spaces, '^-[0-9]+$')
         OR regexp_like(n.es_classes_using_temporary_learning_spaces, '^-[0-9]+$')
         OR regexp_like(n.hs_classes_using_temporary_learning_spaces, '^-[0-9]+$')
         OR regexp_like(n.es_makeshift_rooms, '^-[0-9]+$')
         OR regexp_like(n.hs_makeshift_rooms, '^-[0-9]+$')
         OR regexp_like(n.es_classes_using_makeshift_rooms, '^-[0-9]+$')
         OR regexp_like(n.hs_classes_using_makeshift_rooms, '^-[0-9]+$')
      THEN 'count_negative' END,
      CASE WHEN (n.es_classrooms_instructional <> '' AND NOT regexp_like(n.es_classrooms_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_classrooms_instructional, '^-[0-9]+$'))
         OR (n.jhs_classrooms_instructional <> '' AND NOT regexp_like(n.jhs_classrooms_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.jhs_classrooms_instructional, '^-[0-9]+$'))
         OR (n.shs_classrooms_instructional <> '' AND NOT regexp_like(n.shs_classrooms_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.shs_classrooms_instructional, '^-[0-9]+$'))
         OR (n.es_classrooms_non_instructional <> '' AND NOT regexp_like(n.es_classrooms_non_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_classrooms_non_instructional, '^-[0-9]+$'))
         OR (n.jhs_classrooms_non_instructional <> '' AND NOT regexp_like(n.jhs_classrooms_non_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.jhs_classrooms_non_instructional, '^-[0-9]+$'))
         OR (n.shs_classrooms_non_instructional <> '' AND NOT regexp_like(n.shs_classrooms_non_instructional, '^[0-9]{1,9}$') AND NOT regexp_like(n.shs_classrooms_non_instructional, '^-[0-9]+$'))
         OR (n.buildings_good_condition <> '' AND NOT regexp_like(n.buildings_good_condition, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_good_condition, '^-[0-9]+$'))
         OR (n.buildings_needs_minor_repair <> '' AND NOT regexp_like(n.buildings_needs_minor_repair, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_needs_minor_repair, '^-[0-9]+$'))
         OR (n.buildings_needs_major_repair <> '' AND NOT regexp_like(n.buildings_needs_major_repair, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_needs_major_repair, '^-[0-9]+$'))
         OR (n.buildings_for_completion <> '' AND NOT regexp_like(n.buildings_for_completion, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_for_completion, '^-[0-9]+$'))
         OR (n.buildings_ongoing_construction <> '' AND NOT regexp_like(n.buildings_ongoing_construction, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_ongoing_construction, '^-[0-9]+$'))
         OR (n.buildings_for_condemnation <> '' AND NOT regexp_like(n.buildings_for_condemnation, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_for_condemnation, '^-[0-9]+$'))
         OR (n.buildings_for_demolition <> '' AND NOT regexp_like(n.buildings_for_demolition, '^[0-9]{1,9}$') AND NOT regexp_like(n.buildings_for_demolition, '^-[0-9]+$'))
         OR (n.es_temporary_learning_spaces <> '' AND NOT regexp_like(n.es_temporary_learning_spaces, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_temporary_learning_spaces, '^-[0-9]+$'))
         OR (n.hs_temporary_learning_spaces <> '' AND NOT regexp_like(n.hs_temporary_learning_spaces, '^[0-9]{1,9}$') AND NOT regexp_like(n.hs_temporary_learning_spaces, '^-[0-9]+$'))
         OR (n.es_classes_using_temporary_learning_spaces <> '' AND NOT regexp_like(n.es_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_classes_using_temporary_learning_spaces, '^-[0-9]+$'))
         OR (n.hs_classes_using_temporary_learning_spaces <> '' AND NOT regexp_like(n.hs_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') AND NOT regexp_like(n.hs_classes_using_temporary_learning_spaces, '^-[0-9]+$'))
         OR (n.es_makeshift_rooms <> '' AND NOT regexp_like(n.es_makeshift_rooms, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_makeshift_rooms, '^-[0-9]+$'))
         OR (n.hs_makeshift_rooms <> '' AND NOT regexp_like(n.hs_makeshift_rooms, '^[0-9]{1,9}$') AND NOT regexp_like(n.hs_makeshift_rooms, '^-[0-9]+$'))
         OR (n.es_classes_using_makeshift_rooms <> '' AND NOT regexp_like(n.es_classes_using_makeshift_rooms, '^[0-9]{1,9}$') AND NOT regexp_like(n.es_classes_using_makeshift_rooms, '^-[0-9]+$'))
         OR (n.hs_classes_using_makeshift_rooms <> '' AND NOT regexp_like(n.hs_classes_using_makeshift_rooms, '^[0-9]{1,9}$') AND NOT regexp_like(n.hs_classes_using_makeshift_rooms, '^-[0-9]+$'))
      THEN 'count_uncastable' END,
      CASE WHEN CASE WHEN regexp_like(n.es_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classrooms_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.jhs_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhs_classrooms_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.shs_classrooms_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.shs_classrooms_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.es_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classrooms_non_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.jhs_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhs_classrooms_non_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.shs_classrooms_non_instructional, '^[0-9]{1,9}$') THEN TRY_CAST(n.shs_classrooms_non_instructional AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.buildings_good_condition, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_good_condition AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_needs_minor_repair, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_needs_minor_repair AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_needs_major_repair, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_needs_major_repair AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_for_completion, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_completion AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_ongoing_construction, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_ongoing_construction AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_for_condemnation, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_condemnation AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.buildings_for_demolition, '^[0-9]{1,9}$') THEN TRY_CAST(n.buildings_for_demolition AS BIGINT) END > 200
         OR CASE WHEN regexp_like(n.es_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_temporary_learning_spaces AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.hs_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_temporary_learning_spaces AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.es_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classes_using_temporary_learning_spaces AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.hs_classes_using_temporary_learning_spaces, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_classes_using_temporary_learning_spaces AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.es_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_makeshift_rooms AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.hs_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_makeshift_rooms AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.es_classes_using_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.es_classes_using_makeshift_rooms AS BIGINT) END > 1000
         OR CASE WHEN regexp_like(n.hs_classes_using_makeshift_rooms, '^[0-9]{1,9}$') THEN TRY_CAST(n.hs_classes_using_makeshift_rooms AS BIGINT) END > 1000
      THEN 'count_above_plausible_max' END,
      CASE WHEN NOT n.in_enrollment THEN 'school_id_not_in_enrollment' END
    ) AS quarantine_reasons,
    n.batch_id,
    n.delivery_version,
    n.schema_version,
    n.source_sha256,
    n.source_row_number
  FROM normalized AS n
)
SELECT
  t.school_year,
  t.school_id,
  t.sector,
  t.school_management,
  t.offers_es,
  t.offers_jhs,
  t.offers_shs,
  t.es_classrooms_instructional,
  t.jhs_classrooms_instructional,
  t.shs_classrooms_instructional,
  t.es_classrooms_non_instructional,
  t.jhs_classrooms_non_instructional,
  t.shs_classrooms_non_instructional,
  t.buildings_good_condition,
  t.buildings_needs_minor_repair,
  t.buildings_needs_major_repair,
  t.buildings_for_completion,
  t.buildings_ongoing_construction,
  t.buildings_for_condemnation,
  t.buildings_for_demolition,
  t.es_temporary_learning_spaces,
  t.hs_temporary_learning_spaces,
  t.es_classes_using_temporary_learning_spaces,
  t.hs_classes_using_temporary_learning_spaces,
  t.es_makeshift_rooms,
  t.hs_makeshift_rooms,
  t.es_classes_using_makeshift_rooms,
  t.hs_classes_using_makeshift_rooms,
  t.es_has_covered_court,
  t.hs_has_covered_court,
  t.es_has_gymnasium,
  t.hs_has_gymnasium,
  t.es_has_gate_entrance,
  t.hs_has_gate_entrance,
  t.es_has_gate_exit,
  t.hs_has_gate_exit,
  t.es_has_perimeter_fence_permanent,
  t.hs_has_perimeter_fence_permanent,
  t.es_has_flood_marker,
  t.hs_has_flood_marker,
  t.es_has_perimeter_fence_temporary,
  t.hs_has_perimeter_fence_temporary,
  t.es_has_playground,
  t.hs_has_playground,
  t.es_has_garden,
  t.hs_has_garden,
  t.es_has_solar_panel,
  t.hs_has_solar_panel,
  t.es_has_bike_rack,
  t.hs_has_bike_rack,
  t.es_has_paved_pathway,
  t.hs_has_paved_pathway,
  t.es_has_pathway_roofing,
  t.hs_has_pathway_roofing,
  t.es_has_road_paved,
  t.hs_has_road_paved,
  t.es_has_road_unpaved,
  t.hs_has_road_unpaved,
  t.es_has_road_levelled,
  t.hs_has_road_levelled,
  t.es_has_road_rough,
  t.hs_has_road_rough,
  t.es_has_road_under_construction,
  t.hs_has_road_under_construction,
  t.es_accessible_private_4wheel,
  t.hs_accessible_private_4wheel,
  t.es_accessible_private_motorcycle,
  t.hs_accessible_private_motorcycle,
  t.es_accessible_boat,
  t.hs_accessible_boat,
  t.es_accessible_uv_express,
  t.hs_accessible_uv_express,
  t.es_accessible_pedicab,
  t.hs_accessible_pedicab,
  t.es_accessible_tricycle,
  t.hs_accessible_tricycle,
  t.es_accessible_jeepney,
  t.hs_accessible_jeepney,
  t.es_accessible_habalhabal,
  t.hs_accessible_habalhabal,
  t.es_accessible_train,
  t.hs_accessible_train,
  t.es_accessible_bus,
  t.hs_accessible_bus,
  t.es_accessible_bicycle,
  t.hs_accessible_bicycle,
  t.es_accessible_walking_hiking,
  t.hs_accessible_walking_hiking,
  COALESCE(t.sector = 'PSO' OR t.school_management = 'PSO', FALSE) AS is_overseas,
  (
        t.es_classrooms_instructional IS NOT NULL OR
        t.jhs_classrooms_instructional IS NOT NULL OR
        t.shs_classrooms_instructional IS NOT NULL OR
        t.es_classrooms_non_instructional IS NOT NULL OR
        t.jhs_classrooms_non_instructional IS NOT NULL OR
        t.shs_classrooms_non_instructional IS NOT NULL OR
        t.buildings_good_condition IS NOT NULL OR
        t.buildings_needs_minor_repair IS NOT NULL OR
        t.buildings_needs_major_repair IS NOT NULL OR
        t.buildings_for_completion IS NOT NULL OR
        t.buildings_ongoing_construction IS NOT NULL OR
        t.buildings_for_condemnation IS NOT NULL OR
        t.buildings_for_demolition IS NOT NULL OR
        t.es_temporary_learning_spaces IS NOT NULL OR
        t.hs_temporary_learning_spaces IS NOT NULL OR
        t.es_classes_using_temporary_learning_spaces IS NOT NULL OR
        t.hs_classes_using_temporary_learning_spaces IS NOT NULL OR
        t.es_makeshift_rooms IS NOT NULL OR
        t.hs_makeshift_rooms IS NOT NULL OR
        t.es_classes_using_makeshift_rooms IS NOT NULL OR
        t.hs_classes_using_makeshift_rooms IS NOT NULL OR
        t.es_has_covered_court IS NOT NULL OR
        t.hs_has_covered_court IS NOT NULL OR
        t.es_has_gymnasium IS NOT NULL OR
        t.hs_has_gymnasium IS NOT NULL OR
        t.es_has_gate_entrance IS NOT NULL OR
        t.hs_has_gate_entrance IS NOT NULL OR
        t.es_has_gate_exit IS NOT NULL OR
        t.hs_has_gate_exit IS NOT NULL OR
        t.es_has_perimeter_fence_permanent IS NOT NULL OR
        t.hs_has_perimeter_fence_permanent IS NOT NULL OR
        t.es_has_flood_marker IS NOT NULL OR
        t.hs_has_flood_marker IS NOT NULL OR
        t.es_has_perimeter_fence_temporary IS NOT NULL OR
        t.hs_has_perimeter_fence_temporary IS NOT NULL OR
        t.es_has_playground IS NOT NULL OR
        t.hs_has_playground IS NOT NULL OR
        t.es_has_garden IS NOT NULL OR
        t.hs_has_garden IS NOT NULL OR
        t.es_has_solar_panel IS NOT NULL OR
        t.hs_has_solar_panel IS NOT NULL OR
        t.es_has_bike_rack IS NOT NULL OR
        t.hs_has_bike_rack IS NOT NULL OR
        t.es_has_paved_pathway IS NOT NULL OR
        t.hs_has_paved_pathway IS NOT NULL OR
        t.es_has_pathway_roofing IS NOT NULL OR
        t.hs_has_pathway_roofing IS NOT NULL OR
        t.es_has_road_paved IS NOT NULL OR
        t.hs_has_road_paved IS NOT NULL OR
        t.es_has_road_unpaved IS NOT NULL OR
        t.hs_has_road_unpaved IS NOT NULL OR
        t.es_has_road_levelled IS NOT NULL OR
        t.hs_has_road_levelled IS NOT NULL OR
        t.es_has_road_rough IS NOT NULL OR
        t.hs_has_road_rough IS NOT NULL OR
        t.es_has_road_under_construction IS NOT NULL OR
        t.hs_has_road_under_construction IS NOT NULL OR
        t.es_accessible_private_4wheel IS NOT NULL OR
        t.hs_accessible_private_4wheel IS NOT NULL OR
        t.es_accessible_private_motorcycle IS NOT NULL OR
        t.hs_accessible_private_motorcycle IS NOT NULL OR
        t.es_accessible_boat IS NOT NULL OR
        t.hs_accessible_boat IS NOT NULL OR
        t.es_accessible_uv_express IS NOT NULL OR
        t.hs_accessible_uv_express IS NOT NULL OR
        t.es_accessible_pedicab IS NOT NULL OR
        t.hs_accessible_pedicab IS NOT NULL OR
        t.es_accessible_tricycle IS NOT NULL OR
        t.hs_accessible_tricycle IS NOT NULL OR
        t.es_accessible_jeepney IS NOT NULL OR
        t.hs_accessible_jeepney IS NOT NULL OR
        t.es_accessible_habalhabal IS NOT NULL OR
        t.hs_accessible_habalhabal IS NOT NULL OR
        t.es_accessible_train IS NOT NULL OR
        t.hs_accessible_train IS NOT NULL OR
        t.es_accessible_bus IS NOT NULL OR
        t.hs_accessible_bus IS NOT NULL OR
        t.es_accessible_bicycle IS NOT NULL OR
        t.hs_accessible_bicycle IS NOT NULL OR
        t.es_accessible_walking_hiking IS NOT NULL OR
        t.hs_accessible_walking_hiking IS NOT NULL
  ) AS has_facility_data,
  COALESCE(t.sector = 'Public' AND t.offers_es
    AND t.es_classrooms_instructional IS NULL, FALSE) AS es_classrooms_missing,
  t.quarantine_reasons,
  t.batch_id,
  t.delivery_version,
  t.schema_version,
  t.source_sha256,
  t.source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM typed AS t;

-- One row per school per school year, with the Bronze row it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_facilities_clean_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  sector,
  school_management,
  offers_es,
  offers_jhs,
  offers_shs,
  es_classrooms_instructional,
  jhs_classrooms_instructional,
  shs_classrooms_instructional,
  es_classrooms_non_instructional,
  jhs_classrooms_non_instructional,
  shs_classrooms_non_instructional,
  buildings_good_condition,
  buildings_needs_minor_repair,
  buildings_needs_major_repair,
  buildings_for_completion,
  buildings_ongoing_construction,
  buildings_for_condemnation,
  buildings_for_demolition,
  es_temporary_learning_spaces,
  hs_temporary_learning_spaces,
  es_classes_using_temporary_learning_spaces,
  hs_classes_using_temporary_learning_spaces,
  es_makeshift_rooms,
  hs_makeshift_rooms,
  es_classes_using_makeshift_rooms,
  hs_classes_using_makeshift_rooms,
  es_has_covered_court,
  hs_has_covered_court,
  es_has_gymnasium,
  hs_has_gymnasium,
  es_has_gate_entrance,
  hs_has_gate_entrance,
  es_has_gate_exit,
  hs_has_gate_exit,
  es_has_perimeter_fence_permanent,
  hs_has_perimeter_fence_permanent,
  es_has_flood_marker,
  hs_has_flood_marker,
  es_has_perimeter_fence_temporary,
  hs_has_perimeter_fence_temporary,
  es_has_playground,
  hs_has_playground,
  es_has_garden,
  hs_has_garden,
  es_has_solar_panel,
  hs_has_solar_panel,
  es_has_bike_rack,
  hs_has_bike_rack,
  es_has_paved_pathway,
  hs_has_paved_pathway,
  es_has_pathway_roofing,
  hs_has_pathway_roofing,
  es_has_road_paved,
  hs_has_road_paved,
  es_has_road_unpaved,
  hs_has_road_unpaved,
  es_has_road_levelled,
  hs_has_road_levelled,
  es_has_road_rough,
  hs_has_road_rough,
  es_has_road_under_construction,
  hs_has_road_under_construction,
  es_accessible_private_4wheel,
  hs_accessible_private_4wheel,
  es_accessible_private_motorcycle,
  hs_accessible_private_motorcycle,
  es_accessible_boat,
  hs_accessible_boat,
  es_accessible_uv_express,
  hs_accessible_uv_express,
  es_accessible_pedicab,
  hs_accessible_pedicab,
  es_accessible_tricycle,
  hs_accessible_tricycle,
  es_accessible_jeepney,
  hs_accessible_jeepney,
  es_accessible_habalhabal,
  hs_accessible_habalhabal,
  es_accessible_train,
  hs_accessible_train,
  es_accessible_bus,
  hs_accessible_bus,
  es_accessible_bicycle,
  hs_accessible_bicycle,
  es_accessible_walking_hiking,
  hs_accessible_walking_hiking,
  is_overseas,
  has_facility_data,
  es_classrooms_missing,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM deped_facilities_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.deped_facilities_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_facilities_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_facilities_clean_candidate OWNER TO `reached-hq`;

-- Rows set aside, never deleted: the Bronze row, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_facilities_quarantine_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM deped_facilities_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.deped_facilities_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_facilities_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_facilities_quarantine_candidate OWNER TO `reached-hq`;
