-- Integration build for psa_school_age_population. Generated from config/integration/psa_school_age_population_psgc.json by src/integration/psa_school_age_population_psgc.py:
--   python -m src.integration.psa_school_age_population_psgc sql > etl/04_integration/05_map_psa_school_age_population_psgc.sql
-- Do not edit by hand; tests/test_integration_school_age.py fails if it differs.
--
-- Rebuilds psa_school_age_population_psgc_map_candidate: one row per city or municipality of each census year in the published
-- psa_school_age_population_clean, matched by name to the cities and municipalities of the master PSGC quarter in
-- psa_psgc_clean, only inside the PSGC parent found for the place. No place is dropped: a place no rule
-- matches is kept as unmatched or ambiguous. The map table (psa_school_age_population_psgc_map) is never written here: the
-- gate checks the candidate and publishes it only if no check fails (as D-025 does for Silver).
-- Rules, regions, aliases and overrides: the rules file above.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'integration_build', 'psa_school_age_population', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TEMPORARY VIEW psa_school_age_population_psgc_matched AS
-- The master PSGC quarter.
WITH psgc AS (
  SELECT psgc_code, name, old_names, geographic_level, level_blank, province_code, publication_period,
         batch_id, source_row_number
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
-- Parents: provinces, and the blank-level containers that stand for one (the Special Geographic Area,
-- City of Isabela), each with the keys of its name and old name.
p0 AS (
  SELECT p.psgc_code, p.level_blank,
         CASE WHEN p.name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact,
         CASE WHEN p.old_names IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS ok_exact
  FROM psgc AS p WHERE p.geographic_level = 'Prov' OR (p.level_blank AND p.province_code = p.psgc_code)
),
parents AS (SELECT p0.*, TRIM(regexp_replace(translate(translate(translate(p0.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold, TRIM(regexp_replace(translate(translate(translate(p0.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_fold FROM p0),
-- The cities and municipalities, with the keys of their name and old name. no_province: not inside a
-- PSGC province (the highly urbanized cities, Pateros, and the units of a blank-level container).
u0 AS (
  SELECT u.psgc_code, u.province_code, substr(u.psgc_code, 1, 2) AS region2,
         u.province_code IS NULL OR bp.psgc_code IS NOT NULL AS no_province,
         CASE WHEN u.name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(u.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(u.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(u.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact,
         CASE WHEN u.old_names IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(u.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(u.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(u.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS ok_exact
  FROM psgc AS u LEFT JOIN parents AS bp ON bp.level_blank AND bp.psgc_code = u.province_code
  WHERE u.geographic_level IN ('City', 'Mun')
),
u1 AS (SELECT u0.*, TRIM(regexp_replace(translate(translate(translate(u0.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold, TRIM(regexp_replace(translate(translate(translate(u0.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_fold FROM u0),
units AS (SELECT u1.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || u1.k_fold || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city FROM u1),
-- The census places: one per (census year, place, parent), with the lineage of its row on the
-- total sheet (the other concept lists the same places; the gate checks it).
s0 AS (
  SELECT census_year, place_name, parent_name,
         MIN(place_label) AS place_label, MIN(old_name) AS old_name, MIN(province_name) AS province_name,
         MIN(region_name) AS region_name, MIN(place_status) AS place_status,
         MIN(batch_id) AS batch_id, MIN(source_sha256) AS source_sha256, MIN(source_sheet) AS source_sheet,
         MIN(place_row_number) AS place_row_number
  FROM edu_access.`03-silver`.psa_school_age_population_clean
  WHERE level = 'city_municipality' AND population_concept = 'total'
  GROUP BY census_year, place_name, parent_name
),
s1 AS (
  SELECT s0.*,
         CASE WHEN s0.place_name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(s0.place_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(s0.place_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(s0.place_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact,
         CASE WHEN s0.old_name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(s0.old_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(s0.old_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(s0.old_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS ok_exact
  FROM s0
),
s2 AS (SELECT s1.*, TRIM(regexp_replace(translate(translate(translate(s1.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold, TRIM(regexp_replace(translate(translate(translate(s1.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_fold FROM s1),
s AS (SELECT s2.*, TRIM(regexp_replace(translate(regexp_replace(regexp_replace(' ' || s2.k_fold || ' ', ' (CITY|OF) ', ' '), ' (CITY|OF) ', ' '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_city FROM s2),
regions AS (SELECT * FROM (VALUES (2020, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '19'), (2020, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '09'), (2020, 'CORDILLERA ADMINISTRATIVE REGION', '14'), (2020, 'MIMAROPA REGION', '17'), (2020, 'NATIONAL CAPITAL REGION', '13'), (2020, 'REGION I', '01'), (2020, 'REGION II', '02'), (2020, 'REGION III', '03'), (2020, 'REGION IV-A', '04'), (2020, 'REGION V', '05'), (2020, 'REGION VI', '06'), (2020, 'REGION VI', '18'), (2020, 'REGION VII', '07'), (2020, 'REGION VII', '18'), (2020, 'REGION VIII', '08'), (2020, 'REGION IX', '09'), (2020, 'REGION X', '10'), (2020, 'REGION XI', '11'), (2020, 'REGION XII', '12'), (2020, 'REGION XIII', '16'), (2024, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '19'), (2024, 'CORDILLERA ADMINISTRATIVE REGION', '14'), (2024, 'MIMAROPA REGION', '17'), (2024, 'NATIONAL CAPITAL REGION', '13'), (2024, 'NEGROS ISLAND REGION', '18'), (2024, 'REGION I - ILOCOS REGION', '01'), (2024, 'REGION II - CAGAYAN VALLEY', '02'), (2024, 'REGION III - CENTRAL LUZON', '03'), (2024, 'REGION IVA - CALABARZON', '04'), (2024, 'REGION V - BICOL REGION', '05'), (2024, 'REGION VI - WESTERN VISAYAS', '06'), (2024, 'REGION VII - CENTRAL VISAYAS', '07'), (2024, 'REGION VIII - EASTERN VISAYAS', '08'), (2024, 'REGION IX - ZAMBOANGA PENINSULA', '09'), (2024, 'REGION X - NORTHERN MINDANAO', '10'), (2024, 'REGION XI - DAVAO REGION', '11'), (2024, 'REGION XII - SOCCSKSARGEN', '12'), (2024, 'REGION XIII - CARAGA', '16')) AS v(census_year, region_name, region2)),
aliases AS (SELECT * FROM (VALUES (2024, 'WESTERN SAMAR', '0806000000'), (2020, 'MAGUINDANAO', '1908700000'), (2020, 'MAGUINDANAO', '1908800000')) AS v(census_year, province_name, psgc_code)),
overrides AS (SELECT * FROM (VALUES (2020, 'BULACAN', 'BALIUAG', '0301403000', 'reviewed_alias', 'respelled LGU: PSA BALIUAG is PSGC City of Baliwag, Bulacan'), (2020, 'DAVAO DEL NORTE', 'SAN ISIDRO', '1102324000', 'reviewed_alias', 'renamed LGU: PSA SAN ISIDRO (Davao del Norte) is PSGC Sawata'), (2020, 'MISAMIS OCCIDENTAL', 'DON VICTORIANO CHIONGBIAN', '1004217000', 'reviewed_alias', 'PSGC shortens the name: PSA DON VICTORIANO CHIONGBIAN is PSGC Don Victoriano, Misamis Occidental'), (2024, 'BULACAN', 'BALIUAG', '0301403000', 'reviewed_alias', 'respelled LGU: PSA BALIUAG is PSGC City of Baliwag, Bulacan'), (2024, 'DAVAO DEL NORTE', 'SAN ISIDRO', '1102324000', 'reviewed_alias', 'renamed LGU: PSA SAN ISIDRO (Davao del Norte) is PSGC Sawata'), (2024, 'MISAMIS OCCIDENTAL', 'DON VICTORIANO CHIONGBIAN', '1004217000', 'reviewed_alias', 'PSGC shortens the name: PSA DON VICTORIANO CHIONGBIAN is PSGC Don Victoriano, Misamis Occidental'), (2020, 'PAMPANGA', 'SANTO TOMAS', '0305421000', 'reviewed_alias', 'abbreviation: PSA 2020 SANTO TOMAS (Pampanga) is PSGC Sto. Tomas, the only Santo Tomas in Pampanga'), (2024, 'MASBATE', 'PIO V. CORPUZ', '0504116000', 'reviewed_alias', 'respelled LGU: PSA PIO V. CORPUZ is PSGC Pio V. Corpus, Masbate'), (2024, 'PALAWAN', 'RIZAL', '1705323000', 'reviewed_alias', 'renamed LGU: PSA RIZAL (Palawan) is PSGC Dr. Jose P. Rizal'), (2020, 'INTERIM PROVINCE', 'CARMEN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'KABACAN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'MIDSAYAP CLUSTER I', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'MIDSAYAP CLUSTER II', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIGCAWAYAN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER I', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER II', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER III', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)')) AS v(census_year, parent_name, place_name, psgc_code, match_method, reason)),
-- Each census province: its keys, then the PSGC parent(s) found for it. A reviewed alias first;
-- else the one parent inside the listed regions whose name (1) or old name (2) matches, exact or folded.
pp0 AS (
  SELECT DISTINCT census_year, region_name, province_name FROM s0 WHERE province_name IS NOT NULL
),
pp1 AS (SELECT pp0.*, CASE WHEN pp0.province_name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(pp0.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(pp0.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(pp0.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact FROM pp0),
pp AS (SELECT pp1.*, TRIM(regexp_replace(translate(translate(translate(pp1.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold FROM pp1),
by_province_name AS (
  SELECT pp.census_year, pp.province_name, pa.psgc_code,
         CASE WHEN pp.k_exact = pa.k_exact OR pp.k_fold = pa.k_fold THEN 1
              WHEN pp.k_exact = pa.ok_exact OR pp.k_fold = pa.ok_fold THEN 2 END AS tier
  FROM pp
  JOIN regions AS r ON r.census_year = pp.census_year AND r.region_name = pp.region_name
  JOIN parents AS pa ON substr(pa.psgc_code, 1, 2) = r.region2
),
province_best AS (
  SELECT census_year, province_name, MIN(tier) AS tier FROM by_province_name WHERE tier IS NOT NULL
  GROUP BY census_year, province_name
),
province_hit AS (
  SELECT b.census_year, b.province_name, b.tier, COUNT(DISTINCT n.psgc_code) AS hits, MIN(n.psgc_code) AS psgc_code
  FROM province_best AS b JOIN by_province_name AS n
    ON n.census_year = b.census_year AND n.province_name = b.province_name AND n.tier = b.tier
  GROUP BY b.census_year, b.province_name, b.tier
),
province_scope AS (
  SELECT census_year, province_name, psgc_code AS province_code, 'province_alias' AS parent_match FROM aliases
  UNION ALL
  SELECT h.census_year, h.province_name, h.psgc_code,
         CASE WHEN h.tier = 1 THEN 'province_name' ELSE 'province_old_name' END
  FROM province_hit AS h
  LEFT JOIN aliases AS a ON a.census_year = h.census_year AND a.province_name = h.province_name
  WHERE h.hits = 1 AND a.province_name IS NULL
),
-- Each place's parent: its province's scope, or, directly under its region, the region's units with no
-- province. A place with neither gets no name match (names are matched only inside a matched parent).
scope AS (
  SELECT s.census_year, s.place_name, s.parent_name, MIN(ps.parent_match) AS parent_match
  FROM s JOIN province_scope AS ps ON ps.census_year = s.census_year AND ps.province_name = s.province_name
  GROUP BY s.census_year, s.place_name, s.parent_name
  UNION ALL
  SELECT DISTINCT s.census_year, s.place_name, s.parent_name, 'region'
  FROM s JOIN regions AS r ON r.census_year = s.census_year AND r.region_name = s.region_name
  WHERE s.province_name IS NULL
),
by_name AS (
  SELECT s.census_year, s.place_name, s.parent_name, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_fold = u.k_fold THEN 2 WHEN s.k_city = u.k_city THEN 3 WHEN s.k_fold = u.ok_fold OR s.ok_fold = u.k_fold OR s.ok_fold = u.ok_fold THEN 4 END AS tier
  FROM s JOIN province_scope AS ps ON ps.census_year = s.census_year AND ps.province_name = s.province_name
  JOIN units AS u ON u.province_code = ps.province_code
  UNION ALL
  SELECT s.census_year, s.place_name, s.parent_name, u.psgc_code, CASE WHEN s.k_exact = u.k_exact THEN 1 WHEN s.k_fold = u.k_fold THEN 2 WHEN s.k_city = u.k_city THEN 3 WHEN s.k_fold = u.ok_fold OR s.ok_fold = u.k_fold OR s.ok_fold = u.ok_fold THEN 4 END
  FROM s JOIN regions AS r ON r.census_year = s.census_year AND r.region_name = s.region_name
  JOIN units AS u ON s.province_name IS NULL AND u.no_province AND u.region2 = r.region2
),
best AS (
  SELECT census_year, place_name, parent_name, MIN(tier) AS tier FROM by_name WHERE tier IS NOT NULL
  GROUP BY census_year, place_name, parent_name
),
name_hit AS (
  SELECT b.census_year, b.place_name, b.parent_name, b.tier, COUNT(DISTINCT n.psgc_code) AS hits,
         MIN(n.psgc_code) AS psgc_code
  FROM best AS b JOIN by_name AS n ON n.census_year = b.census_year AND n.place_name = b.place_name
    AND n.parent_name = b.parent_name AND n.tier = b.tier
  GROUP BY b.census_year, b.place_name, b.parent_name, b.tier
),
-- One decision per place, in the rules' order.
decided AS (
  SELECT s.*, sc.parent_match,
    CASE WHEN o.place_name IS NOT NULL THEN o.psgc_code
         WHEN nh.hits = 1 THEN nh.psgc_code
         ELSE NULL END AS psgc_code,
    CASE WHEN o.place_name IS NOT NULL THEN CASE WHEN o.psgc_code IS NULL THEN 'unmatched' ELSE 'matched' END
         WHEN nh.hits = 1 THEN 'matched'
         WHEN nh.hits > 1 THEN 'ambiguous'
         ELSE 'unmatched' END AS match_status,
    CASE WHEN o.place_name IS NOT NULL THEN o.match_method
         WHEN nh.hits = 1 THEN CASE WHEN nh.tier = 1 THEN 'name_exact' WHEN nh.tier = 2 THEN 'name_normalized' WHEN nh.tier = 3 THEN 'name_normalized' WHEN nh.tier = 4 THEN 'name_old' END
         END AS match_method,
    CASE WHEN o.place_name IS NOT NULL THEN 'reviewed'
         WHEN nh.hits = 1 THEN 'rule'
         ELSE 'pending' END AS review_status,
    CASE WHEN o.place_name IS NOT NULL THEN o.reason
         WHEN nh.hits = 1 THEN 'name in parent, ' || CASE WHEN nh.tier = 1 THEN 'exact' WHEN nh.tier = 2 THEN 'folded' WHEN nh.tier = 3 THEN 'word City ignored' WHEN nh.tier = 4 THEN 'old name' END
         WHEN nh.hits > 1 THEN CAST(nh.hits AS STRING) || ' units match at tier ' || CASE WHEN nh.tier = 1 THEN 'exact' WHEN nh.tier = 2 THEN 'folded' WHEN nh.tier = 3 THEN 'word City ignored' WHEN nh.tier = 4 THEN 'old name' END
         WHEN sc.parent_match IS NULL AND s.province_name IS NULL THEN 'region not listed in the rules, so no name match was tried'
         WHEN sc.parent_match IS NULL THEN 'no PSGC province found for the province name, so no name match was tried'
         ELSE 'no name match in the parent' END AS reason
  FROM s
  LEFT JOIN overrides AS o ON o.census_year = s.census_year AND o.parent_name = s.parent_name AND o.place_name = s.place_name
  LEFT JOIN scope AS sc ON sc.census_year = s.census_year AND sc.place_name = s.place_name AND sc.parent_name = s.parent_name
  LEFT JOIN name_hit AS nh ON nh.census_year = s.census_year AND nh.place_name = s.place_name
    AND nh.parent_name = s.parent_name
)
SELECT
  'psa_school_age_population' AS source_id,
  CAST(d.census_year AS STRING) || '/' || d.parent_name || '/' || d.place_name AS source_row_ref,
  d.census_year,
  d.place_label,
  d.place_name,
  d.old_name,
  d.parent_name,
  d.province_name,
  d.region_name,
  d.place_status,
  (SELECT MIN(publication_period) FROM psgc) AS psgc_version,
  d.psgc_code,
  p.name AS psgc_name,
  'city_mun' AS geographic_level,
  d.match_status,
  d.match_method,
  d.review_status,
  d.parent_match,
  d.reason,
  d.batch_id,
  d.source_sha256,
  d.source_sheet,
  d.place_row_number,
  p.batch_id AS psgc_batch_id,
  p.source_row_number AS psgc_source_row_number,
  session.integration_run_id AS run_id,
  session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decided AS d
LEFT JOIN psgc AS p ON p.psgc_code = d.psgc_code;

CREATE OR REPLACE TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate USING DELTA AS
SELECT
  source_id,
  source_row_ref,
  census_year,
  place_label,
  place_name,
  old_name,
  parent_name,
  province_name,
  region_name,
  place_status,
  psgc_version,
  psgc_code,
  psgc_name,
  geographic_level,
  match_status,
  match_method,
  review_status,
  parent_match,
  reason,
  batch_id,
  source_sha256,
  source_sheet,
  place_row_number,
  psgc_batch_id,
  psgc_source_row_number,
  run_id,
  built_at_utc,
  code_revision
FROM psa_school_age_population_psgc_matched;

COMMENT ON TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate IS 'Unpublished build for the Integration gate, which may have failed. Do not read: use psa_school_age_population_psgc_map.';
ALTER TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate OWNER TO `reached-hq`;
