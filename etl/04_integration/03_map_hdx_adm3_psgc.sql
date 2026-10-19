-- Integration build for hdx_boundaries. Generated from config/integration/hdx_adm3_psgc.json by src/integration/hdx_adm3_psgc.py:
--   python -m src.integration.hdx_adm3_psgc sql > etl/04_integration/03_map_hdx_adm3_psgc.sql
-- Do not edit by hand; tests/test_integration_hdx.py fails if it differs.
--
-- Rebuilds hdx_adm3_psgc_map_candidate: one row per HDX ADM3 feature of the published hdx_adm3_clean,
-- matched to the cities and municipalities of the master PSGC quarter in psa_psgc_clean.
-- No feature is dropped: a feature no rule matches is kept as unmatched or ambiguous. The map table
-- (hdx_adm3_psgc_map) is never written here: the gate checks the candidate and publishes it
-- only if no check fails (as D-025 does for Silver). Rules and overrides: the rules file above.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'integration_build', 'hdx_boundaries', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TEMPORARY VIEW hdx_adm3_psgc_matched AS
-- The master PSGC quarter: every row (for provinces), and its cities and municipalities (the candidates).
WITH psgc AS (
  SELECT psgc_code, name, old_names, correspondence_code, geographic_level, publication_period,
         batch_id, source_row_number
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
u0 AS (
  SELECT p.*,
         CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS k_exact,
         CASE WHEN p.old_names IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS ok_exact
  FROM psgc AS p WHERE p.geographic_level IN ('City', 'Mun')
),
u1 AS (SELECT u0.*, TRIM(regexp_replace(translate(translate(translate(u0.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold, TRIM(regexp_replace(translate(translate(translate(u0.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_fold FROM u0),
u2 AS (SELECT u1.*, TRIM(regexp_replace(translate(regexp_replace(u1.k_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_brackets, TRIM(regexp_replace(translate(regexp_replace(u1.ok_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_brackets FROM u1),
units AS (SELECT u2.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || u2.k_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || u2.ok_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_city FROM u2),
-- HDX features: the P-code's digits padded to ten (code10), its old 9-digit form (old9), the province's.
s0 AS (
  SELECT h.adm3_pcode, h.adm3_name, h.adm2_pcode, h.adm2_name, h.adm1_pcode, h.valid_on,
         h.batch_id, h.source_sha256, h.source_row_number,
         rpad(substr(h.adm3_pcode, 3), 10, '0') AS code10,
         rpad(substr(h.adm2_pcode, 3), 10, '0') AS prov10,
         CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(h.adm3_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(h.adm3_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(h.adm3_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END AS k_exact
  FROM edu_access.`03-silver`.hdx_adm3_clean AS h
),
s1 AS (SELECT s0.*, TRIM(regexp_replace(translate(translate(translate(s0.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold,
              substr(code10, 1, 2) || substr(code10, 4, 2) || substr(code10, 6, 2) || substr(code10, 8, 3) AS old9,
              substr(prov10, 1, 2) || substr(prov10, 4, 2) || substr(prov10, 6, 2) || substr(prov10, 8, 3) AS prov_old9
       FROM s0),
s2 AS (SELECT s1.*, TRIM(regexp_replace(translate(regexp_replace(s1.k_fold, '[(][^)]*[)]?', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_brackets FROM s1),
s AS (SELECT s2.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || s2.k_brackets || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city FROM s2),
-- Code rules, in order (1 code, 2 Correspondence Code, 3 Sulu), each with the name tier at which
-- the names agree (NULL: they do not).
by_code AS (
  SELECT s.adm3_pcode, s.valid_on, 1 AS rule, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_exact = u.ok_exact THEN 2 WHEN s.k_fold = u.k_fold THEN 3 WHEN s.k_fold = u.ok_fold THEN 4 WHEN s.k_brackets = u.k_brackets THEN 5 WHEN s.k_city = u.k_city THEN 6 END AS tier
  FROM s JOIN units AS u ON u.psgc_code = s.code10
  UNION ALL SELECT s.adm3_pcode, s.valid_on, 2, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_exact = u.ok_exact THEN 2 WHEN s.k_fold = u.k_fold THEN 3 WHEN s.k_fold = u.ok_fold THEN 4 WHEN s.k_brackets = u.k_brackets THEN 5 WHEN s.k_city = u.k_city THEN 6 END
  FROM s JOIN units AS u ON substr(s.code10, 3, 1) = '0' AND u.correspondence_code = s.old9
  UNION ALL SELECT s.adm3_pcode, s.valid_on, 3, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_exact = u.ok_exact THEN 2 WHEN s.k_fold = u.k_fold THEN 3 WHEN s.k_fold = u.ok_fold THEN 4 WHEN s.k_brackets = u.k_brackets THEN 5 WHEN s.k_city = u.k_city THEN 6 END
  FROM s JOIN units AS u ON s.code10 LIKE '19%' AND u.psgc_code = '09' || substr(s.code10, 3)
),
-- The first code rule whose names agree, and how many units it names: more than one (two units
-- sharing a Correspondence Code) is not one-to-one (D-030), so the feature stays ambiguous.
code_hits AS (
  SELECT adm3_pcode, valid_on, rule, COUNT(DISTINCT psgc_code) AS hits, MIN(psgc_code) AS psgc_code
  FROM by_code WHERE tier IS NOT NULL GROUP BY adm3_pcode, valid_on, rule
),
code_agreed AS (
  SELECT adm3_pcode, valid_on, MIN_BY(psgc_code, rule) AS psgc_code, MIN(rule) AS rule, MIN_BY(hits, rule) AS hits
  FROM code_hits GROUP BY adm3_pcode, valid_on
),
code_any AS (
  SELECT adm3_pcode, valid_on, MIN_BY(psgc_code, rule) AS psgc_code FROM by_code GROUP BY adm3_pcode, valid_on
),
-- The PSGC province for adm2_pcode: by code, else by Correspondence Code. Its first five digits
-- scope the name search. A feature whose province is not found, or has no city or municipality,
-- gets no name match: names are matched only inside a matched parent (D-029); a reviewed
-- override is the way to match it.
province AS (
  SELECT s.adm3_pcode, s.valid_on,
         substr(COALESCE(MIN(p1.psgc_code), MIN(p2.psgc_code)), 1, 5) AS prov5
  FROM s
  LEFT JOIN psgc AS p1 ON p1.psgc_code = s.prov10
  LEFT JOIN psgc AS p2 ON substr(s.prov10, 3, 1) = '0' AND p2.correspondence_code = s.prov_old9
  GROUP BY s.adm3_pcode, s.valid_on
),
scope AS (
  SELECT pr.adm3_pcode, pr.valid_on, pr.prov5, pc.n IS NOT NULL AS has_units
  FROM province AS pr
  LEFT JOIN (SELECT substr(psgc_code, 1, 5) AS prov5, COUNT(*) AS n FROM units GROUP BY 1) AS pc ON pc.prov5 = pr.prov5
),
by_name AS (
  SELECT s.adm3_pcode, s.valid_on, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_exact = u.ok_exact THEN 2 WHEN s.k_fold = u.k_fold THEN 3 WHEN s.k_fold = u.ok_fold THEN 4 WHEN s.k_brackets = u.k_brackets THEN 5 WHEN s.k_city = u.k_city THEN 6 END AS tier
  FROM s JOIN scope AS sc ON sc.adm3_pcode = s.adm3_pcode AND sc.valid_on = s.valid_on
  JOIN units AS u ON sc.has_units AND substr(u.psgc_code, 1, 5) = sc.prov5
),
best AS (
  SELECT adm3_pcode, valid_on, MIN(tier) AS tier FROM by_name WHERE tier IS NOT NULL GROUP BY adm3_pcode, valid_on
),
name_hit AS (
  SELECT b.adm3_pcode, b.valid_on, b.tier, COUNT(*) AS hits, MIN(n.psgc_code) AS psgc_code
  FROM best AS b JOIN by_name AS n ON n.adm3_pcode = b.adm3_pcode AND n.valid_on = b.valid_on AND n.tier = b.tier
  GROUP BY b.adm3_pcode, b.valid_on, b.tier
),
overrides AS (SELECT * FROM (VALUES ('PH0907226', DATE '2025-02-13', '0907226000', 'code_renamed', 'renamed LGU: COD-AB Bacungan (Leon T. Postigo) is PSGC Leon T. Postigo, Zamboanga del Norte'), ('PH1004217', DATE '2025-02-13', '1004217000', 'code_renamed', 'renamed LGU: COD-AB Don Victoriano Chiongbian (Don Mariano Marcos) is PSGC Don Victoriano, Misamis Occidental'), ('PH1102324', DATE '2025-02-13', '1102324000', 'code_renamed', 'renamed LGU: COD-AB San Isidro is PSGC Sawata, Davao del Norte'), ('PH1705323', DATE '2025-02-13', '1705323000', 'code_renamed', 'renamed LGU: COD-AB Rizal (Marcos) is PSGC Dr. Jose P. Rizal, Palawan'), ('PH1909901', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Carmen): no PSGC equivalent until a spatial check (D-031)'), ('PH1909902', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Kabacan): no PSGC equivalent until a spatial check (D-031)'), ('PH1909903', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Midsayap I): no PSGC equivalent until a spatial check (D-031)'), ('PH1909904', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Midsayap II): no PSGC equivalent until a spatial check (D-031)'), ('PH1909905', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pigkawayan): no PSGC equivalent until a spatial check (D-031)'), ('PH1909906', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit I): no PSGC equivalent until a spatial check (D-031)'), ('PH1909907', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit II): no PSGC equivalent until a spatial check (D-031)'), ('PH1909908', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit III): no PSGC equivalent until a spatial check (D-031)')) AS v(adm3_pcode, source_reference_date, psgc_code, match_method, reason)),
-- One decision per feature, in the rules' order.
decided AS (
  SELECT s.*,
    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.psgc_code
         WHEN ca.hits = 1 THEN ca.psgc_code
         WHEN ca.hits > 1 THEN NULL
         WHEN nh.hits = 1 THEN nh.psgc_code
         ELSE NULL END AS psgc_code,
    CASE WHEN o.adm3_pcode IS NOT NULL THEN CASE WHEN o.psgc_code IS NULL THEN 'unmatched' ELSE 'matched' END
         WHEN ca.hits = 1 THEN 'matched'
         WHEN ca.hits > 1 THEN 'ambiguous'
         WHEN nh.hits = 1 THEN 'matched'
         WHEN nh.hits > 1 OR cy.psgc_code IS NOT NULL THEN 'ambiguous'
         ELSE 'unmatched' END AS match_status,
    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.match_method
         WHEN ca.hits > 1 THEN NULL
         WHEN ca.rule = 1 THEN 'code' WHEN ca.rule = 2 THEN 'correspondence_code' WHEN ca.rule = 3 THEN 'code_region_moved'
         WHEN nh.hits = 1 THEN CASE WHEN nh.tier = 1 THEN 'name_exact' WHEN nh.tier = 2 THEN 'name_old' WHEN nh.tier = 3 THEN 'name_normalized' WHEN nh.tier = 4 THEN 'name_old' WHEN nh.tier = 5 THEN 'name_normalized' WHEN nh.tier = 6 THEN 'name_normalized' END
         END AS match_method,
    CASE WHEN o.adm3_pcode IS NOT NULL THEN 'reviewed'
         WHEN ca.hits = 1 OR (ca.hits IS NULL AND nh.hits = 1) THEN 'rule'
         ELSE 'pending' END AS review_status,
    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.reason
         WHEN ca.hits = 1 THEN NULL
         WHEN ca.hits > 1 THEN CAST(ca.hits AS STRING) || ' units share this code under the ' || CASE ca.rule WHEN 1 THEN 'code' WHEN 2 THEN 'Correspondence Code' ELSE 'Sulu' END || ' rule: not one-to-one (D-030), review'
         WHEN nh.hits = 1 THEN 'name in province, ' || CASE WHEN nh.tier = 1 THEN 'exact' WHEN nh.tier = 2 THEN 'old name' WHEN nh.tier = 3 THEN 'folded' WHEN nh.tier = 4 THEN 'folded old name' WHEN nh.tier = 5 THEN 'brackets dropped' WHEN nh.tier = 6 THEN 'word City ignored' END
              || CASE WHEN cy.psgc_code IS NOT NULL THEN ', the code names another unit' ELSE '' END
         WHEN nh.hits > 1 THEN CAST(nh.hits AS STRING) || ' units match at tier ' || CASE WHEN nh.tier = 1 THEN 'exact' WHEN nh.tier = 2 THEN 'old name' WHEN nh.tier = 3 THEN 'folded' WHEN nh.tier = 4 THEN 'folded old name' WHEN nh.tier = 5 THEN 'brackets dropped' WHEN nh.tier = 6 THEN 'word City ignored' END
         WHEN cy.psgc_code IS NOT NULL THEN 'the code points to ' || cy.psgc_code || ' but the names differ: review, then confirm by override'
         WHEN NOT COALESCE(sc.has_units, FALSE) THEN 'no PSGC province found for adm2_pcode, so no name match was tried'
         ELSE 'no code or name match' END AS reason
  FROM s
  LEFT JOIN overrides AS o ON o.adm3_pcode = s.adm3_pcode AND o.source_reference_date = s.valid_on
  LEFT JOIN code_agreed AS ca ON ca.adm3_pcode = s.adm3_pcode AND ca.valid_on = s.valid_on
  LEFT JOIN code_any AS cy ON cy.adm3_pcode = s.adm3_pcode AND cy.valid_on = s.valid_on
  LEFT JOIN name_hit AS nh ON nh.adm3_pcode = s.adm3_pcode AND nh.valid_on = s.valid_on
  LEFT JOIN scope AS sc ON sc.adm3_pcode = s.adm3_pcode AND sc.valid_on = s.valid_on
)
SELECT
  'hdx_boundaries' AS source_id,
  d.adm3_pcode || '/' || CAST(d.valid_on AS STRING) AS source_row_ref,
  d.adm3_pcode,
  d.adm3_name,
  d.adm2_pcode,
  d.adm2_name,
  d.adm1_pcode,
  d.valid_on AS source_reference_date,
  d.code10 AS code_candidate,
  (SELECT MIN(publication_period) FROM psgc) AS psgc_version,
  d.psgc_code,
  p.name AS psgc_name,
  'city_mun' AS geographic_level,
  d.match_status,
  d.match_method,
  d.review_status,
  d.reason,
  d.batch_id,
  d.source_sha256,
  d.source_row_number,
  p.batch_id AS psgc_batch_id,
  p.source_row_number AS psgc_source_row_number,
  session.integration_run_id AS run_id,
  session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decided AS d
LEFT JOIN psgc AS p ON p.psgc_code = d.psgc_code;

CREATE OR REPLACE TABLE edu_access.`04-integration`.hdx_adm3_psgc_map_candidate USING DELTA AS
SELECT
  source_id,
  source_row_ref,
  adm3_pcode,
  adm3_name,
  adm2_pcode,
  adm2_name,
  adm1_pcode,
  source_reference_date,
  code_candidate,
  psgc_version,
  psgc_code,
  psgc_name,
  geographic_level,
  match_status,
  match_method,
  review_status,
  reason,
  batch_id,
  source_sha256,
  source_row_number,
  psgc_batch_id,
  psgc_source_row_number,
  run_id,
  built_at_utc,
  code_revision
FROM hdx_adm3_psgc_matched;

COMMENT ON TABLE edu_access.`04-integration`.hdx_adm3_psgc_map_candidate IS 'Unpublished build for the Integration gate, which may have failed. Do not read: use hdx_adm3_psgc_map.';
ALTER TABLE edu_access.`04-integration`.hdx_adm3_psgc_map_candidate OWNER TO `reached-hq`;
