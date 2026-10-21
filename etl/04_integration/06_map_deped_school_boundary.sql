-- Integration build for deped_psgc_coordinates (#217): the public-school boundary map.
--
-- Rebuilds deped_school_boundary_map_candidate: one row per row of the published deped_psgc_coordinates_clean
-- (school_year, school_id), never dropping one. It tests the boundary rule S-1 at city or municipality level:
-- is the school's published point inside the HDX ADM3 boundary of the city or municipality the reviewed school
-- map (deped_school_psgc_map, D-049) assigns it for that school year?
--   inside           inside a boundary of that city (adm3_pcode names the feature)
--   outside          the city has a boundary and the point is not inside it (a point on the edge is outside)
--   no_usable_point  coordinate_flag is set (missing, zero, outside_philippines): nothing to test
--   no_matched_city  the school map has no matched city or municipality for the school in that school year
--   no_boundary      the city is matched but has no matched, valid HDX boundary in the latest release
-- Boundaries are the latest HDX release's matched, valid features (as dim_city_municipality reads them); a city
-- may have more than one. The point, its flag and its Silver lineage are copied unchanged. Nothing is moved,
-- geocoded, or dropped: the status is a check. The map table (deped_school_boundary_map) is never written here:
-- the gate checks the candidate and publishes it only if no check fails (as D-025 does for Silver).
--
-- Cost: the scope (the location's school year, city level, matched, unflagged points) is applied before the
-- spatial join; each boundary is parsed once, not per school; one st_contains per school and boundary; the result
-- is reduced to one row per school before the final join, so nothing multiplies.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE integration_run_id STRING;
SET VARIABLE integration_run_id = :run_id;
DECLARE OR REPLACE VARIABLE integration_code_revision STRING;
SET VARIABLE integration_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_environment STRING;
SET VARIABLE integration_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_built_at_utc TIMESTAMP;
SET VARIABLE integration_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.integration_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_psgc_coordinates'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'integration_build', 'deped_psgc_coordinates', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_school_boundary_map_candidate USING DELTA AS
WITH location AS (
  SELECT school_year, school_id, longitude, latitude, coordinate_flag, batch_id, source_sha256, source_row_number
  FROM edu_access.`03-silver`.deped_psgc_coordinates_clean
),
city AS (
  -- Only the location's school years: the school map holds every enrollment year, and joining all of them to
  -- the boundary shapes would carry each shape through hundreds of thousands of rows (out of memory locally).
  SELECT school_year, school_id, psgc_code AS city_mun_psgc_code
  FROM edu_access.`04-integration`.deped_school_psgc_map
  WHERE geographic_level = 'city_mun' AND match_status = 'matched'
    AND school_year IN (SELECT DISTINCT school_year FROM location)
),
hdx_release AS (
  SELECT MAX(source_reference_date) AS source_reference_date
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map
),
boundary AS (
  -- One parsed shape per matched, valid ADM3 feature of the latest release.
  SELECT m.psgc_code AS city_mun_psgc_code, m.adm3_pcode, try_to_geometry(h.geometry) AS shape
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  JOIN hdx_release AS r ON r.source_reference_date = m.source_reference_date
  JOIN edu_access.`03-silver`.hdx_adm3_clean AS h
    ON h.adm3_pcode = m.adm3_pcode AND h.valid_on = m.source_reference_date
  WHERE m.match_status = 'matched' AND h.geometry_is_valid
),
located AS (
  -- Unflagged points with their matched city, before any shape is touched.
  SELECT l.school_year, l.school_id, l.longitude, l.latitude, c.city_mun_psgc_code
  FROM location AS l
  JOIN city AS c ON c.school_year = l.school_year AND c.school_id = l.school_id
  WHERE l.coordinate_flag IS NULL
),
tested AS (
  -- Points of a city that has a parsed boundary: one row per school, naming the feature that contains it.
  SELECT x.school_year, x.school_id,
         MIN(CASE WHEN st_contains(b.shape, try_to_geometry(concat('{"type": "Point", "coordinates": [',
                  CAST(x.longitude AS STRING), ', ', CAST(x.latitude AS STRING), ']}'))) THEN b.adm3_pcode END) AS adm3_pcode
  FROM located AS x
  JOIN boundary AS b ON b.city_mun_psgc_code = x.city_mun_psgc_code
  WHERE b.shape IS NOT NULL   -- an unparsed shape is no boundary, never 'outside'
  GROUP BY x.school_year, x.school_id
),
decided AS (
  SELECT l.*, c.city_mun_psgc_code, t.adm3_pcode,
         CASE
           WHEN l.coordinate_flag IS NOT NULL THEN 'no_usable_point'
           WHEN c.school_id IS NULL THEN 'no_matched_city'
           WHEN t.school_id IS NULL THEN 'no_boundary'
           WHEN t.adm3_pcode IS NOT NULL THEN 'inside'
           ELSE 'outside'
         END AS boundary_status
  FROM location AS l
  LEFT JOIN city AS c ON c.school_year = l.school_year AND c.school_id = l.school_id
  LEFT JOIN tested AS t ON t.school_year = l.school_year AND t.school_id = l.school_id
)
SELECT
  'deped_psgc_coordinates' AS source_id,
  d.school_year || '/' || d.school_id AS source_row_ref,
  d.school_year,
  d.school_id,
  d.longitude,
  d.latitude,
  d.coordinate_flag,
  d.city_mun_psgc_code,
  d.adm3_pcode,
  (SELECT source_reference_date FROM hdx_release) AS hdx_release,
  d.boundary_status,
  CASE d.boundary_status
    WHEN 'inside' THEN 'Point inside the HDX boundary of the assigned city or municipality'
    WHEN 'outside' THEN 'Point outside every HDX boundary of the assigned city or municipality'
    WHEN 'no_usable_point' THEN 'No point to test: coordinate_flag is ' || d.coordinate_flag
    WHEN 'no_matched_city' THEN 'The school PSGC map has no matched city or municipality for this school year'
    WHEN 'no_boundary' THEN 'The assigned city or municipality has no matched, valid HDX boundary'
  END AS reason,
  d.batch_id,
  d.source_sha256,
  d.source_row_number,
  session.integration_run_id AS run_id,
  session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decided AS d;

COMMENT ON TABLE edu_access.`04-integration`.deped_school_boundary_map_candidate IS 'Unpublished build for the Integration gate, which may have failed. Do not read: use deped_school_boundary_map.';
ALTER TABLE edu_access.`04-integration`.deped_school_boundary_map_candidate OWNER TO `reached-hq`;
