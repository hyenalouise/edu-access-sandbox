-- Integration build for deped_enrollment. Generated from config/mappings/integration/deped_school_psgc.json by src/integration/deped_school_psgc.py:
--   python -m src.integration.deped_school_psgc sql > etl/04_integration/01_map_deped_school_psgc.sql
-- Do not edit by hand; tests/test_integration_deped_school_psgc.py fails if it differs.
--
-- Cities are matched once per distinct (province, municipality) and barangays once per distinct place, then
-- reused by every school-year row.
DECLARE OR REPLACE VARIABLE integration_run_id STRING;
SET VARIABLE integration_run_id = :run_id;
DECLARE OR REPLACE VARIABLE integration_code_revision STRING;
SET VARIABLE integration_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_environment STRING;
SET VARIABLE integration_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_built_at_utc TIMESTAMP;
SET VARIABLE integration_built_at_utc = current_timestamp();

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.integration_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED THEN UPDATE SET status = 'running', started_at_utc = session.integration_built_at_utc,
  finished_at_utc = NULL, failure_stage = NULL, error_message = NULL,
  code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'integration_build', 'deped_enrollment', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TEMPORARY VIEW deped_school_psgc_matched AS
WITH
psgc_input AS (
  SELECT psgc_code, name, old_names, geographic_level, region_code, province_code,
         city_municipality_code, publication_period, batch_id, source_row_number
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
p0 AS (SELECT x.*, CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(x.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(x.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(x.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS k_exact FROM psgc_input AS x),
p1 AS (SELECT x.*, TRIM(regexp_replace(translate(translate(translate(x.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold FROM p0 AS x),
p2 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(x.k_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_brackets FROM p1 AS x),
p3 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || x.k_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city FROM p2 AS x),
p4 AS (
  SELECT x.*,
    CASE WHEN x.old_names IS NULL THEN NULL ELSE CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(x.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(x.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(x.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END END AS ok_exact
  FROM p3 AS x
),
p5 AS (SELECT x.*, CASE WHEN x.ok_exact IS NULL THEN NULL ELSE TRIM(regexp_replace(translate(translate(translate(x.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) END AS ok_fold FROM p4 AS x),
units AS (SELECT * FROM p5),
-- Cities are matched once per DepEd (province, municipality) pair: the match never reads the barangay.
city_input AS (
  SELECT DISTINCT province, municipality FROM edu_access.`03-silver`.deped_enrollment_clean WHERE NOT is_overseas
),
city0 AS (SELECT x.*, CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(x.province), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(x.province), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(x.province), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS prov_exact, CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(x.municipality), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(x.municipality), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(x.municipality), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS k_exact FROM city_input AS x),
city1 AS (SELECT x.*, TRIM(regexp_replace(translate(translate(translate(x.prov_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS prov_fold, TRIM(regexp_replace(translate(translate(translate(x.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold FROM city0 AS x),
city2 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(x.k_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_brackets FROM city1 AS x),
city3 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || x.k_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city FROM city2 AS x),
aliases AS (SELECT * FROM (VALUES ('TONDO', '1380601000', 'Tondo I/II, a City of Manila sub-municipality'), ('KALOOKAN CITY', '1380100000', 'PSGC uses City of Caloocan'), ('OZAMIS CITY', '1004210000', 'PSGC uses City of Ozamiz'), ('BARAUEN', '0803710000', 'PSGC uses Burauen'), ('BALIUAG', '0301403000', 'PSGC uses City of Baliwag')) AS v(deped_name, psgc_code, reason)),
overrides AS (SELECT * FROM (VALUES ('bgy', 'NCR FOURTH DISTRICT', 'TAGUIG CITY', 'SIGNAL VILLAGE', 'code', 'DepEd names the barangay before it was split. PSGC 2Q 2026 lists Signal Village only as an old name of Central Signal Village, so the name match puts every Signal Village school there. The EMISD codes spread the same schools over North, Central and South Signal Village and Katuparan, all in Taguig. The code names the barangay each school is in. The name match cannot.', '@catweyine')) AS v(geographic_level, province, municipality, barangay, use_side, reason, reviewer)),
province_pairs AS (
  SELECT s.province, s.municipality, u.psgc_code,
    CASE WHEN s.prov_exact = u.k_exact THEN 1 WHEN s.prov_exact = u.ok_exact THEN 2
         WHEN s.prov_fold = u.k_fold THEN 3 WHEN s.prov_fold = u.ok_fold THEN 4 END AS tier
  FROM city3 AS s JOIN units AS u ON (u.geographic_level = 'Prov' OR u.psgc_code = '0990100000')
    AND (s.prov_exact = u.k_exact OR s.prov_exact = u.ok_exact OR s.prov_fold = u.k_fold OR s.prov_fold = u.ok_fold)
  UNION ALL
  SELECT s.province, s.municipality, u.psgc_code, 1
  FROM city3 AS s JOIN units AS u ON upper(s.province) = 'MAGUINDANAO'
    AND u.geographic_level = 'Prov' AND u.name IN ('Maguindanao del Norte', 'Maguindanao del Sur')
),
province_best AS (
  SELECT province, municipality, MIN(tier) AS tier
  FROM province_pairs WHERE tier IS NOT NULL GROUP BY 1,2
),
province_hits AS (
  SELECT b.province, b.municipality, COUNT(DISTINCT p.psgc_code) AS hits, MIN(p.psgc_code) AS psgc_code
  FROM province_best AS b JOIN province_pairs AS p USING (province, municipality, tier)
  GROUP BY 1,2
),
province_scope AS (
  SELECT DISTINCT b.province, b.municipality, substr(p.psgc_code, 1, 5) AS province_prefix
  FROM province_best AS b JOIN province_pairs AS p USING (province, municipality, tier)
),
city_pairs AS (
  SELECT s.province, s.municipality, u.psgc_code, u.geographic_level,
         CASE WHEN regexp_like(upper(s.province), 'NCR') AND u.psgc_code LIKE '13%' THEN 1
              WHEN ps.province_prefix IS NOT NULL THEN 1
              WHEN u.geographic_level = 'City' AND (ph.hits IS NULL OR substr(u.psgc_code, 6) = '00000') THEN 2 ELSE 9 END AS scope_rank,
         LEAST(COALESCE(CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_fold = u.k_fold THEN 3 WHEN s.k_brackets = u.k_brackets THEN 5 WHEN s.k_city = u.k_city THEN 6 END, 99), COALESCE(CASE WHEN s.k_exact = u.ok_exact THEN 2 WHEN s.k_fold = u.ok_fold THEN 4 END, 99)) AS tier
  FROM city3 AS s
  LEFT JOIN province_hits AS ph USING (province, municipality)
  JOIN units AS u ON u.geographic_level IN ('City', 'Mun', 'SubMun')
    AND (s.k_exact = u.k_exact OR s.k_exact = u.ok_exact OR s.k_fold = u.k_fold OR s.k_fold = u.ok_fold
         OR s.k_brackets = u.k_brackets OR s.k_city = u.k_city)
  LEFT JOIN province_scope AS ps ON ps.province IS NOT DISTINCT FROM s.province
    AND ps.municipality IS NOT DISTINCT FROM s.municipality AND ps.province_prefix = substr(u.psgc_code, 1, 5)
),
city_scope AS (
  SELECT province, municipality, MIN(scope_rank) AS scope_rank
  FROM city_pairs WHERE scope_rank < 9 AND tier < 99 GROUP BY 1,2
),
city_best AS (
  SELECT s.province, s.municipality, s.scope_rank, MIN(c.tier) AS tier
  FROM city_scope AS s JOIN city_pairs AS c USING (province, municipality, scope_rank)
  WHERE c.tier < 99 GROUP BY 1,2,3
),
city_hits AS (
  SELECT b.province, b.municipality, COUNT(DISTINCT c.psgc_code) AS hits, MIN(c.psgc_code) AS psgc_code,
         MIN(c.geographic_level) AS geographic_level, b.scope_rank, b.tier
  FROM city_best AS b JOIN city_pairs AS c USING (province, municipality, scope_rank, tier)
  GROUP BY 1,2,6,7
),
city_named AS (
  SELECT s.province, s.municipality, COALESCE(a.psgc_code, CASE WHEN c.hits = 1 THEN c.psgc_code END) AS name_city_code,
         COALESCE(au.geographic_level, c.geographic_level) AS name_city_level,
         CASE WHEN a.psgc_code IS NOT NULL THEN 'reviewed_alias'
              WHEN c.scope_rank = 2 THEN 'name_exact' ELSE CASE WHEN c.tier IN (1, 8, 9) THEN 'name_exact' WHEN c.tier IN (2, 4) THEN 'name_old' WHEN c.tier IN (3, 5, 6, 7) THEN 'name_normalized' WHEN c.tier = 10 THEN 'reviewed_alias' END END AS name_city_method,
         COALESCE(a.reason, CASE WHEN c.hits > 1 THEN CAST(c.hits AS STRING) || ' PSGC localities match the best name tier' END) AS name_city_reason
  FROM city3 AS s
  LEFT JOIN province_hits AS ph USING (province, municipality)
  LEFT JOIN aliases AS a ON a.deped_name = s.k_exact AND
    (regexp_like(upper(s.province), 'NCR') AND a.psgc_code LIKE '13%'
     OR ph.hits = 1 AND substr(a.psgc_code, 1, 5) = substr(ph.psgc_code, 1, 5)
     OR substr(a.psgc_code, 6) = '00000')
  LEFT JOIN units AS au ON au.psgc_code = a.psgc_code
  LEFT JOIN city_hits AS c USING (province, municipality)
),
-- Barangays are matched once per (province, municipality, barangay, truncation flag), inside the named city.
source_input AS (
  SELECT DISTINCT province, municipality, COALESCE(barangay, '') AS barangay, barangay_possibly_truncated
  FROM edu_access.`03-silver`.deped_enrollment_clean WHERE NOT is_overseas
),
source0 AS (SELECT x.*, CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(x.barangay), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(x.barangay), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(x.barangay), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS b_exact FROM source_input AS x),
source1 AS (SELECT x.*, TRIM(regexp_replace(translate(translate(translate(x.b_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS b_fold FROM source0 AS x),
source2 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(x.b_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS b_brackets FROM source1 AS x),
source3 AS (SELECT x.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || x.b_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS b_city FROM source2 AS x),
barangay_pairs AS (
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, u.psgc_code,
         LEAST(COALESCE(CASE WHEN s.b_exact = u.k_exact THEN 1 WHEN s.b_fold = u.k_fold THEN 3
                            WHEN s.b_brackets = u.k_brackets THEN 5 WHEN s.b_city = u.k_city THEN 6
                            WHEN s.barangay_possibly_truncated AND u.k_fold LIKE s.b_fold || '%' THEN 7 END, 99),
               COALESCE(CASE WHEN s.b_exact = u.ok_exact THEN 2 WHEN s.b_fold = u.ok_fold THEN 4 END, 99)) AS tier
  FROM source3 AS s JOIN city_named AS c USING (province, municipality)
  JOIN units AS u ON u.geographic_level = 'Bgy' AND u.city_municipality_code = c.name_city_code
),
barangay_best AS (
  SELECT province, municipality, barangay, barangay_possibly_truncated, MIN(tier) AS tier
  FROM barangay_pairs WHERE tier < 99 GROUP BY 1,2,3,4
),
barangay_hits AS (
  SELECT b.province, b.municipality, b.barangay, b.barangay_possibly_truncated,
         COUNT(DISTINCT p.psgc_code) AS hits, MIN(p.psgc_code) AS psgc_code, b.tier
  FROM barangay_best AS b JOIN barangay_pairs AS p USING (province, municipality, barangay, barangay_possibly_truncated, tier)
  GROUP BY 1,2,3,4,7
),
places AS (
  SELECT s.*, c.name_city_code, c.name_city_level, c.name_city_method, c.name_city_reason,
         CASE WHEN b.hits = 1 THEN b.psgc_code END AS name_bgy_code,
         CASE WHEN b.tier IN (1, 8, 9) THEN 'name_exact' WHEN b.tier IN (2, 4) THEN 'name_old' WHEN b.tier IN (3, 5, 6, 7) THEN 'name_normalized' WHEN b.tier = 10 THEN 'reviewed_alias' END AS name_bgy_method,
         CASE WHEN b.hits > 1 THEN CAST(b.hits AS STRING) || ' PSGC barangays match the best name tier' END AS name_bgy_reason
  FROM source3 AS s
  LEFT JOIN city_named AS c USING (province, municipality)
  LEFT JOIN barangay_hits AS b USING (province, municipality, barangay, barangay_possibly_truncated)
),
school_input AS (
  SELECT e.school_year, e.school_id, e.school_name, e.region, e.province, e.municipality, e.barangay,
         e.barangay_possibly_truncated, e.is_overseas,
         e.batch_id, e.source_sha256, e.source_row_number,
         x.psgc_city_municipality AS code_city, x.psgc_barangay AS code_bgy, x.psgc_recoded,
         x.batch_id AS crosswalk_batch_id, x.source_row_number AS crosswalk_source_row_number,
         pl.name_city_code, pl.name_city_level, pl.name_city_method, pl.name_city_reason,
         pl.name_bgy_code, pl.name_bgy_method, pl.name_bgy_reason,
         pl.b_exact, pl.b_fold, pl.b_brackets, pl.b_city
  FROM edu_access.`03-silver`.deped_enrollment_clean AS e
  LEFT JOIN edu_access.`03-silver`.deped_enrollment_psgc_clean AS x ON x.school_id = e.school_id
  LEFT JOIN places AS pl ON pl.province IS NOT DISTINCT FROM e.province
    AND pl.municipality IS NOT DISTINCT FROM e.municipality AND pl.barangay = COALESCE(e.barangay, '')
    AND pl.barangay_possibly_truncated = e.barangay_possibly_truncated
),
school_units AS (
  -- A code with no master PSGC unit counts as no code, as in the reviewed rule and at city level.
  SELECT s.*, cc.geographic_level AS code_city_level, cb.name AS code_bgy_name, cb.psgc_code AS code_bgy_unit,
         CASE WHEN cc.geographic_level = 'SubMun' THEN substr(cc.psgc_code, 1, 5) || '00000' ELSE cc.psgc_code END AS code_city_roll,
         CASE WHEN nc.geographic_level = 'SubMun' THEN substr(nc.psgc_code, 1, 5) || '00000' ELSE nc.psgc_code END AS name_city_roll,
         CASE WHEN s.barangay IS NOT NULL AND
              (s.b_exact = cb.k_exact OR s.b_exact = cb.ok_exact
               OR s.b_fold = cb.k_fold OR s.b_fold = cb.ok_fold
               OR s.b_brackets = cb.k_brackets OR s.b_city = cb.k_city
               OR (s.barangay_possibly_truncated AND cb.k_fold LIKE s.b_fold || '%'))
              THEN TRUE ELSE FALSE END AS code_bgy_name_agrees,
         cb.city_municipality_code AS code_bgy_parent,
         -- D-031: a school DepEd files under a Special Geographic Area place, or one whose EMISD code is
         -- in a Special Geographic Area municipality (SY 2020-21 still files these under Region XII).
         COALESCE(NOT s.is_overseas AND (s.code_city LIKE '19999%' OR s.code_bgy LIKE '19999%'
           OR (upper(s.region) = 'BARMM' AND upper(s.province) = 'NORTH COTABATO') OR (upper(s.region) = 'BARMM' AND upper(s.province) = '(SGA - NORTH COTABATO)')), FALSE) AS is_sga,
         o.use_side AS bgy_override_side, o.reason AS bgy_override_reason, o.reviewer AS bgy_override_reviewer
  FROM school_input AS s
  LEFT JOIN units AS cc ON cc.psgc_code = s.code_city AND cc.geographic_level IN ('City', 'Mun', 'SubMun')
  LEFT JOIN units AS cb ON cb.psgc_code = s.code_bgy AND cb.geographic_level = 'Bgy'
  LEFT JOIN units AS nc ON nc.psgc_code = s.name_city_code
  LEFT JOIN overrides AS o ON o.geographic_level = 'bgy' AND o.province = s.province
    AND o.municipality = s.municipality AND o.barangay = s.barangay
),
city_decided AS (
  SELECT s.*,
    CASE WHEN s.is_overseas THEN 'excluded'
         WHEN s.is_sga
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN 'matched' ELSE 'excluded' END
         WHEN s.code_city_roll IS NOT NULL AND s.code_city_roll = s.name_city_roll THEN 'matched'
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN 'matched' ELSE 'ambiguous' END
         WHEN COALESCE(s.code_city_roll, s.name_city_roll) IS NOT NULL THEN 'matched' ELSE 'unmatched' END AS city_status,
    CASE WHEN s.is_overseas THEN NULL
         WHEN s.is_sga
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN s.code_city_roll END
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL AND s.code_city_roll <> s.name_city_roll
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN s.code_city_roll END
         ELSE COALESCE(s.code_city_roll, s.name_city_roll) END AS city_code,
    CASE WHEN s.is_overseas THEN NULL
         WHEN s.code_city_level = 'SubMun' OR (s.code_city_roll IS NULL AND s.name_city_level = 'SubMun') THEN 'rollup'
         WHEN s.code_city_roll IS NOT NULL THEN CASE WHEN s.psgc_recoded AND s.code_city LIKE '09066%' THEN 'code_region_moved'
              WHEN s.name_city_roll = s.code_city_roll THEN 'code' ELSE 'code_name_differs' END
         ELSE s.name_city_method END AS city_method,
    -- The reasons repeat the match_detail wording of the reviewed analysis rule (PR #153).
    CASE WHEN s.is_overseas THEN 'Philippine Schools Overseas'
         WHEN s.is_sga
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city
                     THEN 'Special Geographic Area' || chr(59) || ' DepEd barangay name matches the code''s barangay' ELSE 'Special Geographic Area (D-031)' END
         WHEN s.code_city_roll IS NOT NULL AND s.code_city_roll = s.name_city_roll THEN 'code and name agree'
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city
                     THEN 'code' || chr(59) || ' DepEd barangay name matches the code''s barangay' ELSE 'code and name differ' END
         WHEN s.code_city_roll IS NOT NULL THEN 'code only'
         WHEN s.name_city_roll IS NOT NULL THEN 'name only'
         ELSE COALESCE(s.name_city_reason, 'no code, no name match') END AS city_reason
  FROM school_units AS s
),
bgy_pre AS (
  SELECT c.*,
    CASE WHEN c.city_status <> 'matched' THEN c.city_status
         WHEN c.bgy_override_side = 'code' THEN CASE WHEN c.code_bgy_unit IS NOT NULL THEN 'matched' ELSE 'unmatched' END
         WHEN c.bgy_override_side = 'name' THEN CASE WHEN c.name_bgy_code IS NOT NULL THEN 'matched' ELSE 'unmatched' END
         WHEN c.code_bgy_unit IS NOT NULL AND c.code_bgy_unit = c.name_bgy_code THEN 'matched'
         WHEN c.code_bgy_unit IS NOT NULL AND c.code_bgy_name_agrees THEN 'matched'
         WHEN c.code_bgy_unit IS NOT NULL AND c.name_bgy_code IS NOT NULL THEN 'ambiguous'
         WHEN COALESCE(c.code_bgy_unit, c.name_bgy_code) IS NOT NULL THEN 'matched' ELSE 'unmatched' END AS bgy_status0,
    CASE WHEN c.city_status <> 'matched' THEN NULL
         WHEN c.bgy_override_side = 'code' THEN c.code_bgy_unit
         WHEN c.bgy_override_side = 'name' THEN c.name_bgy_code
         WHEN c.code_bgy_unit IS NOT NULL AND (c.name_bgy_code IS NULL OR c.code_bgy_unit = c.name_bgy_code OR c.code_bgy_name_agrees) THEN c.code_bgy_unit
         WHEN c.code_bgy_unit IS NULL THEN c.name_bgy_code END AS bgy_code0,
    CASE WHEN c.city_status <> 'matched' THEN NULL
         WHEN (c.bgy_override_side = 'code' AND c.code_bgy_unit IS NOT NULL)
           OR (c.bgy_override_side IS NULL AND c.code_bgy_unit IS NOT NULL) THEN CASE WHEN c.psgc_recoded AND c.code_bgy_unit LIKE '09066%' THEN 'code_region_moved'
              WHEN c.name_bgy_code = c.code_bgy_unit OR c.code_bgy_name_agrees THEN 'code' ELSE 'code_name_differs' END
         WHEN (c.bgy_override_side = 'name' AND c.name_bgy_code IS NOT NULL)
           OR (c.bgy_override_side IS NULL AND c.code_bgy_unit IS NULL) THEN c.name_bgy_method END AS bgy_method0,
    CASE WHEN c.city_status <> 'matched' THEN 'city or municipality ' || c.city_status
         WHEN c.bgy_override_side IS NOT NULL AND COALESCE(CASE WHEN c.bgy_override_side = 'code' THEN c.code_bgy_unit ELSE c.name_bgy_code END, '') <> '' THEN 'reviewed override'
         WHEN c.bgy_override_side IS NOT NULL THEN 'reviewed override: no unit'
         WHEN c.code_bgy_unit IS NOT NULL AND c.code_bgy_unit = c.name_bgy_code THEN 'code and name agree'
         WHEN c.code_bgy_unit IS NOT NULL AND c.code_bgy_name_agrees THEN 'code' || chr(59) || ' DepEd barangay name matches'
         WHEN c.code_bgy_unit IS NOT NULL AND c.name_bgy_code IS NOT NULL THEN 'code and name differ'
         WHEN c.code_bgy_unit IS NOT NULL THEN 'code only'
         WHEN c.name_bgy_code IS NOT NULL THEN 'name only'
         ELSE COALESCE(c.name_bgy_reason, 'no code, no name match') END AS bgy_reason0
  FROM city_decided AS c
),
bgy_decided AS (
  SELECT b.*,
    CASE WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN 'ambiguous' ELSE b.bgy_status0 END AS bgy_status,
    CASE WHEN b.bgy_status0 <> 'matched' THEN NULL
         WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN NULL ELSE b.bgy_code0 END AS bgy_code,
    CASE WHEN b.bgy_status0 <> 'matched' THEN NULL
         WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN NULL ELSE b.bgy_method0 END AS bgy_method,
    CASE WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN 'barangay outside the accepted city or municipality' ELSE b.bgy_reason0 END AS bgy_reason
  FROM bgy_pre AS b LEFT JOIN units AS u ON u.psgc_code = b.bgy_code0
),
decisions AS (
  SELECT b.*, 'city_mun' AS geographic_level, b.code_city AS code_candidate, b.city_code AS psgc_code,
         b.city_status AS match_status, CASE WHEN b.city_code IS NULL THEN NULL ELSE b.city_method END AS match_method,
         b.city_reason || CASE WHEN b.city_code IS NOT NULL AND b.city_method = 'rollup' THEN '' || chr(59) || ' Manila sub-municipality rolled up' ELSE '' END AS reason,
         CAST(NULL AS STRING) AS override_reason, CAST(NULL AS STRING) AS override_reviewer
  FROM bgy_decided AS b
  UNION ALL
  SELECT b.*, 'bgy', b.code_bgy, b.bgy_code, b.bgy_status, b.bgy_method, b.bgy_reason,
         CASE WHEN b.city_status = 'matched' THEN b.bgy_override_reason END,
         CASE WHEN b.city_status = 'matched' THEN b.bgy_override_reviewer END
  FROM bgy_decided AS b
)
SELECT
  'deped_enrollment' AS source_id,
  d.school_year || '/' || d.school_id || '/' || d.geographic_level AS source_row_ref,
  d.school_year AS source_reference_date,  -- D-029; DepEd's reference period is the school year
  d.school_year, d.school_id, d.school_name,
  d.region AS source_region, d.province AS source_province,
  d.municipality AS source_city_municipality, d.barangay AS source_barangay,
  d.geographic_level, d.code_candidate,
  (SELECT MIN(publication_period) FROM psgc_input) AS psgc_version,
  d.psgc_code, p.name AS psgc_name,
  d.match_status, d.match_method,
  -- An override that finds no unit, or a barangay outside the city, still needs review.
  CASE WHEN d.match_status <> 'matched' THEN 'pending' WHEN d.override_reviewer IS NOT NULL THEN 'reviewed' ELSE 'rule' END AS review_status,
  d.reason, d.override_reason, d.override_reviewer,
  d.batch_id, d.source_sha256, d.source_row_number,
  d.crosswalk_batch_id, d.crosswalk_source_row_number,
  p.batch_id AS psgc_batch_id, p.source_row_number AS psgc_source_row_number,
  session.integration_run_id AS run_id, session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decisions AS d LEFT JOIN psgc_input AS p ON p.psgc_code = d.psgc_code;

CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_school_psgc_map_candidate USING DELTA AS
SELECT * FROM deped_school_psgc_matched;

COMMENT ON TABLE edu_access.`04-integration`.deped_school_psgc_map_candidate IS 'Unpublished build for the Integration gate. Do not read: use deped_school_psgc_map.';
ALTER TABLE edu_access.`04-integration`.deped_school_psgc_map_candidate OWNER TO `reached-hq`;
