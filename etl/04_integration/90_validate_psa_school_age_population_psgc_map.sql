-- Integration gate for psa_school_age_population. Generated from config/integration/psa_school_age_population_psgc.json by src/integration/psa_school_age_population_psgc.py:
--   python -m src.integration.psa_school_age_population_psgc gate > etl/04_integration/90_validate_psa_school_age_population_psgc_map.sql
-- Do not edit by hand; tests/test_integration_school_age.py fails if it differs.
--
-- The job task after the build. It checks psa_school_age_population_psgc_map_candidate, one row per check in
-- data_quality_results (layer 'integration'). On any FAIL it records the run 'failed' and stops
-- before publishing, so psa_school_age_population_psgc_map keeps the last map that passed. Otherwise it copies
-- the candidate to the map table and records the run 'succeeded'. WARN (pending reviews, unmatched,
-- ambiguous, an override whose place is not in the data, a census region the rules do not list, a
-- census province with no PSGC parent, PSGC cities and municipalities no place matched, counted per
-- census year) is recorded and the map is published. Results hold counts, never row values.

DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'psa_school_age_population', 'integration', 'edu_access.04-integration.psa_school_age_population_psgc_map_candidate', check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
-- Every place of either concept: a place only one concept lists still needs its map row.
WITH places AS (SELECT DISTINCT census_year, place_name, parent_name, region_name, province_name FROM edu_access.`03-silver`.psa_school_age_population_clean
                WHERE level = 'city_municipality'),
psgc AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference),
p0 AS (
  SELECT p.psgc_code, p.level_blank,
         CASE WHEN p.name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact,
         CASE WHEN p.old_names IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(p.old_names), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS ok_exact
  FROM psgc AS p WHERE p.geographic_level = 'Prov' OR (p.level_blank AND p.province_code = p.psgc_code)
),
parents AS (SELECT p0.*, TRIM(regexp_replace(translate(translate(translate(p0.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold, TRIM(regexp_replace(translate(translate(translate(p0.ok_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS ok_fold FROM p0),
units AS (
  SELECT u.psgc_code, u.name, u.province_code, substr(u.psgc_code, 1, 2) AS region2,
         u.province_code IS NULL OR bp.psgc_code IS NOT NULL AS no_province
  FROM psgc AS u LEFT JOIN parents AS bp ON bp.level_blank AND bp.psgc_code = u.province_code
  WHERE u.geographic_level IN ('City', 'Mun')
),
regions AS (SELECT * FROM (VALUES (2020, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '19'), (2020, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '09'), (2020, 'CORDILLERA ADMINISTRATIVE REGION', '14'), (2020, 'MIMAROPA REGION', '17'), (2020, 'NATIONAL CAPITAL REGION', '13'), (2020, 'REGION I', '01'), (2020, 'REGION II', '02'), (2020, 'REGION III', '03'), (2020, 'REGION IV-A', '04'), (2020, 'REGION V', '05'), (2020, 'REGION VI', '06'), (2020, 'REGION VI', '18'), (2020, 'REGION VII', '07'), (2020, 'REGION VII', '18'), (2020, 'REGION VIII', '08'), (2020, 'REGION IX', '09'), (2020, 'REGION X', '10'), (2020, 'REGION XI', '11'), (2020, 'REGION XII', '12'), (2020, 'REGION XIII', '16'), (2024, 'BANGSAMORO AUTONOMOUS REGION IN MUSLIM MINDANAO', '19'), (2024, 'CORDILLERA ADMINISTRATIVE REGION', '14'), (2024, 'MIMAROPA REGION', '17'), (2024, 'NATIONAL CAPITAL REGION', '13'), (2024, 'NEGROS ISLAND REGION', '18'), (2024, 'REGION I - ILOCOS REGION', '01'), (2024, 'REGION II - CAGAYAN VALLEY', '02'), (2024, 'REGION III - CENTRAL LUZON', '03'), (2024, 'REGION IVA - CALABARZON', '04'), (2024, 'REGION V - BICOL REGION', '05'), (2024, 'REGION VI - WESTERN VISAYAS', '06'), (2024, 'REGION VII - CENTRAL VISAYAS', '07'), (2024, 'REGION VIII - EASTERN VISAYAS', '08'), (2024, 'REGION IX - ZAMBOANGA PENINSULA', '09'), (2024, 'REGION X - NORTHERN MINDANAO', '10'), (2024, 'REGION XI - DAVAO REGION', '11'), (2024, 'REGION XII - SOCCSKSARGEN', '12'), (2024, 'REGION XIII - CARAGA', '16')) AS v(census_year, region_name, region2)),
region_codes AS (SELECT * FROM (VALUES ('0100000000'), ('0200000000'), ('0300000000'), ('0400000000'), ('0500000000'), ('0600000000'), ('0700000000'), ('0800000000'), ('0900000000'), ('1000000000'), ('1100000000'), ('1200000000'), ('1300000000'), ('1400000000'), ('1600000000'), ('1700000000'), ('1800000000'), ('1900000000')) AS v(psgc_code)),
aliases AS (SELECT * FROM (VALUES (2024, 'WESTERN SAMAR', '0806000000'), (2020, 'MAGUINDANAO', '1908700000'), (2020, 'MAGUINDANAO', '1908800000')) AS v(census_year, province_name, psgc_code)),
overrides AS (SELECT * FROM (VALUES (2020, 'BULACAN', 'BALIUAG', '0301403000', 'reviewed_alias', 'respelled LGU: PSA BALIUAG is PSGC City of Baliwag, Bulacan'), (2020, 'DAVAO DEL NORTE', 'SAN ISIDRO', '1102324000', 'reviewed_alias', 'renamed LGU: PSA SAN ISIDRO (Davao del Norte) is PSGC Sawata'), (2020, 'MISAMIS OCCIDENTAL', 'DON VICTORIANO CHIONGBIAN', '1004217000', 'reviewed_alias', 'PSGC shortens the name: PSA DON VICTORIANO CHIONGBIAN is PSGC Don Victoriano, Misamis Occidental'), (2024, 'BULACAN', 'BALIUAG', '0301403000', 'reviewed_alias', 'respelled LGU: PSA BALIUAG is PSGC City of Baliwag, Bulacan'), (2024, 'DAVAO DEL NORTE', 'SAN ISIDRO', '1102324000', 'reviewed_alias', 'renamed LGU: PSA SAN ISIDRO (Davao del Norte) is PSGC Sawata'), (2024, 'MISAMIS OCCIDENTAL', 'DON VICTORIANO CHIONGBIAN', '1004217000', 'reviewed_alias', 'PSGC shortens the name: PSA DON VICTORIANO CHIONGBIAN is PSGC Don Victoriano, Misamis Occidental'), (2020, 'PAMPANGA', 'SANTO TOMAS', '0305421000', 'reviewed_alias', 'abbreviation: PSA 2020 SANTO TOMAS (Pampanga) is PSGC Sto. Tomas, the only Santo Tomas in Pampanga'), (2024, 'MASBATE', 'PIO V. CORPUZ', '0504116000', 'reviewed_alias', 'respelled LGU: PSA PIO V. CORPUZ is PSGC Pio V. Corpus, Masbate'), (2024, 'PALAWAN', 'RIZAL', '1705323000', 'reviewed_alias', 'renamed LGU: PSA RIZAL (Palawan) is PSGC Dr. Jose P. Rizal'), (2020, 'INTERIM PROVINCE', 'CARMEN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'KABACAN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'MIDSAYAP CLUSTER I', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'MIDSAYAP CLUSTER II', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIGCAWAYAN CLUSTER', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER I', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER II', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)'), (2020, 'INTERIM PROVINCE', 'PIKIT CLUSTER III', CAST(NULL AS STRING), CAST(NULL AS STRING), '2020 Interim Province cluster: a PSA grouping of Special Geographic Area barangays by former Cotabato town, not an LGU, with no PSGC counterpart (D-031)')) AS v(census_year, parent_name, place_name, psgc_code, match_method, reason)),
-- #181 (D-052): every name-rule match lies inside the parent the rules give, recomputed here from the
-- place's region and province, not read from the build: a listed region of its census year, then the
-- province's reviewed alias, else a PSGC parent in that region whose name or old name is the province's;
-- a place directly under its region only among the units with no PSGC province.
named AS (
  SELECT m.source_row_ref, m.census_year, m.region_name, m.province_name, m.psgc_code,
         CASE WHEN m.province_name IS NULL THEN NULL ELSE (CASE WHEN regexp_replace(TRIM(regexp_replace(translate(upper(m.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') LIKE 'CITY OF %' THEN substr(regexp_replace(TRIM(regexp_replace(translate(upper(m.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', ''), 9) || ' CITY' ELSE regexp_replace(TRIM(regexp_replace(translate(upper(m.province_name), chr(9) || chr(160), '  '), ' +', ' ')), ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '') END) END AS k_exact
  FROM edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m WHERE m.match_method IN ('name_exact', 'name_normalized', 'name_old')
),
named_keys AS (SELECT named.*, TRIM(regexp_replace(translate(translate(translate(named.k_exact, chr(209) || chr(193) || chr(201) || chr(205) || chr(211) || chr(218) || chr(220) || chr(192) || chr(200) || chr(204) || chr(210) || chr(217) || chr(194) || chr(202) || chr(206) || chr(212) || chr(219), 'NAEIOUUAEIOUAEIOU'), '.-' || chr(39), '   '), chr(9) || chr(160), '  '), ' +', ' ')) AS k_fold FROM named),
in_scope AS (
  SELECT DISTINCT n.source_row_ref
  FROM named_keys AS n JOIN units AS u ON u.psgc_code = n.psgc_code
  JOIN regions AS r ON r.census_year = n.census_year AND r.region_name = n.region_name AND r.region2 = u.region2
  LEFT JOIN (SELECT DISTINCT census_year, province_name FROM aliases) AS aa
    ON aa.census_year = n.census_year AND aa.province_name = n.province_name
  LEFT JOIN aliases AS a ON a.census_year = n.census_year AND a.province_name = n.province_name AND a.psgc_code = u.province_code
  LEFT JOIN parents AS pa ON pa.psgc_code = u.province_code
  WHERE (n.province_name IS NULL AND u.no_province)
     OR (n.province_name IS NOT NULL AND aa.province_name IS NOT NULL AND a.psgc_code IS NOT NULL)
     OR (n.province_name IS NOT NULL AND aa.province_name IS NULL AND substr(pa.psgc_code, 1, 2) = r.region2
         AND (n.k_exact = pa.k_exact OR n.k_exact = pa.ok_exact OR n.k_fold = pa.k_fold OR n.k_fold = pa.ok_fold))
),
-- Each (census year, sex, age, concept) cell of the country against the sum over the mapped places.
national AS (
  SELECT census_year, population_concept, sex, age, population FROM edu_access.`03-silver`.psa_school_age_population_clean WHERE level = 'country'
),
mapped AS (
  SELECT c.census_year, c.population_concept, c.sex, c.age, SUM(c.population) AS population
  FROM edu_access.`03-silver`.psa_school_age_population_clean AS c JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m
    ON m.census_year = c.census_year AND m.place_name = c.place_name AND m.parent_name = c.parent_name
  WHERE c.level = 'city_municipality'
  GROUP BY c.census_year, c.population_concept, c.sex, c.age
),
totals AS (
  SELECT (SELECT COUNT(*) FROM places) AS source_places, (SELECT COUNT(*) FROM units) AS psgc_units,
         (SELECT COUNT(*) FROM overrides AS o JOIN places AS p ON p.census_year = o.census_year AND p.parent_name = o.parent_name AND p.place_name = o.place_name) AS overrides_present,
         (SELECT COUNT(*) FROM overrides AS o LEFT JOIN places AS p ON p.census_year = o.census_year AND p.parent_name = o.parent_name AND p.place_name = o.place_name
          WHERE p.place_name IS NULL) AS overrides_missing,
         (SELECT COUNT(*) FROM (SELECT DISTINCT census_year, region_name FROM places) AS pr
          LEFT JOIN (SELECT DISTINCT census_year, region_name FROM regions) AS r
            ON r.census_year = pr.census_year AND r.region_name = pr.region_name
          WHERE r.region_name IS NULL) AS regions_missing,
         -- A census province whose places all have no PSGC parent (no alias, no single name match).
         (SELECT COUNT(*) FROM (SELECT DISTINCT m.census_year, m.province_name FROM
            edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m WHERE m.province_name IS NOT NULL
            GROUP BY m.census_year, m.province_name HAVING COUNT(m.parent_match) = 0) AS x) AS provinces_unresolved,
         -- A region or alias code that is not a region or province row of the master quarter.
         (SELECT COUNT(*) FROM region_codes AS rc LEFT JOIN edu_access.`03-silver`.psa_psgc_clean AS p ON p.psgc_code = rc.psgc_code
            AND p.is_master_reference AND p.geographic_level = 'Reg' WHERE p.psgc_code IS NULL)
         + (SELECT COUNT(*) FROM aliases AS a LEFT JOIN edu_access.`03-silver`.psa_psgc_clean AS p ON p.psgc_code = a.psgc_code
            AND p.is_master_reference AND (p.geographic_level = 'Prov' OR (p.level_blank AND p.province_code = p.psgc_code))
            WHERE p.psgc_code IS NULL) AS bad_rule_codes,
         (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,
         (SELECT COUNT(*) FROM named) - (SELECT COUNT(*) FROM in_scope) AS name_scope_mismatch,
         -- Per census year: each (year, PSGC unit) pair with no matched place in that year.
         (SELECT COUNT(*) FROM (SELECT DISTINCT census_year FROM places) AS y CROSS JOIN units AS u
          LEFT JOIN (SELECT DISTINCT census_year, psgc_code FROM edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate WHERE match_status = 'matched') AS mm
            ON mm.psgc_code = u.psgc_code AND mm.census_year = y.census_year
          WHERE mm.psgc_code IS NULL) AS units_without_place,
         (SELECT COALESCE(SUM(c.population), 0) FROM edu_access.`03-silver`.psa_school_age_population_clean AS c WHERE c.level = 'country' AND c.census_year = 2020 AND c.population_concept = 'total' AND c.sex = 'both' AND c.age BETWEEN 5 AND 17) AS ap4_total_2020,
         (SELECT COALESCE(SUM(c.population), 0) FROM edu_access.`03-silver`.psa_school_age_population_clean AS c JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m
            ON m.census_year = c.census_year AND m.place_name = c.place_name AND m.parent_name = c.parent_name
          WHERE c.level = 'city_municipality' AND m.match_status = 'matched' AND c.census_year = 2020 AND c.population_concept = 'total' AND c.sex = 'both' AND c.age BETWEEN 5 AND 17) AS ap4_matched_2020,
         (SELECT COALESCE(SUM(c.population), 0) FROM edu_access.`03-silver`.psa_school_age_population_clean AS c WHERE c.level = 'country' AND c.census_year = 2024 AND c.population_concept = 'total' AND c.sex = 'both' AND c.age BETWEEN 5 AND 17) AS ap4_total_2024,
         (SELECT COALESCE(SUM(c.population), 0) FROM edu_access.`03-silver`.psa_school_age_population_clean AS c JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m
            ON m.census_year = c.census_year AND m.place_name = c.place_name AND m.parent_name = c.parent_name
          WHERE c.level = 'city_municipality' AND m.match_status = 'matched' AND c.census_year = 2024 AND c.population_concept = 'total' AND c.sex = 'both' AND c.age BETWEEN 5 AND 17) AS ap4_matched_2024,
         (SELECT COUNT(*) FROM national AS n LEFT JOIN mapped AS s ON s.census_year = n.census_year
            AND s.population_concept = n.population_concept AND s.sex = n.sex AND s.age = n.age
          WHERE s.population IS NULL OR s.population <> n.population) AS population_cells_off
),
agg AS (
  SELECT
    COUNT(*) AS map_rows,
    COUNT(DISTINCT m.source_row_ref) AS map_places,
    COUNT_IF(m.match_status = 'matched') AS matched_rows,
    COUNT(DISTINCT CASE WHEN m.match_status = 'matched' THEN CAST(m.census_year AS STRING) || '/' || m.psgc_code END) AS matched_codes,
    COUNT_IF(m.match_status = 'matched' AND (m.psgc_code IS NULL OR u.psgc_code IS NULL)) AS matched_without_unit,
    COUNT_IF(m.match_status <> 'matched' AND m.psgc_code IS NOT NULL) AS unmatched_with_code,
    COUNT_IF(m.match_status IS NULL OR m.match_status NOT IN ('matched', 'unmatched', 'ambiguous')) AS bad_status,
    COUNT_IF((m.match_status = 'matched' AND (m.match_method IS NULL OR m.match_method NOT IN ('name_exact', 'name_normalized', 'name_old', 'reviewed_alias'))) OR (m.match_status <> 'matched' AND m.match_method IS NOT NULL)) AS bad_method,
    COUNT_IF(m.review_status IS NULL OR m.review_status NOT IN ('rule', 'reviewed', 'pending')) AS bad_review,
    COUNT_IF(NOT COALESCE((m.match_status = 'matched' AND m.review_status IN ('rule', 'reviewed') AND m.match_method IS NOT NULL AND m.psgc_code IS NOT NULL) OR (m.match_status = 'ambiguous' AND m.review_status = 'pending' AND m.match_method IS NULL AND m.psgc_code IS NULL) OR (m.match_status = 'unmatched' AND m.review_status IN ('pending', 'reviewed') AND m.match_method IS NULL AND m.psgc_code IS NULL), FALSE)) AS bad_combination,
    COUNT_IF(m.match_status = 'matched' AND (m.psgc_name IS NULL OR u.name IS NULL OR m.psgc_name <> u.name)) AS psgc_name_mismatch,
    COUNT_IF((m.parent_match IS NOT NULL AND m.parent_match NOT IN ('province_name', 'province_old_name', 'province_alias', 'region')) OR (m.review_status = 'rule' AND m.parent_match IS NULL)) AS bad_parent_match,
    COUNT_IF(m.review_status = 'reviewed') AS overrides_used,
    COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_sheet IS NULL OR m.place_row_number IS NULL OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL OR (m.psgc_code IS NOT NULL AND (m.psgc_batch_id IS NULL OR m.psgc_source_row_number IS NULL))) AS missing_lineage,
    COUNT_IF(m.run_id IS NULL OR m.run_id <> :run_id) AS other_run_rows,
    COUNT_IF(m.review_status = 'pending') AS pending_rows,
    COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows,
    COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows,
    COUNT_IF(m.census_year = 2020 AND TRUE) AS rows_2020,
    COUNT_IF(m.census_year = 2020 AND m.match_status = 'matched') AS matched_2020,
    COUNT_IF(m.census_year = 2020 AND m.match_status = 'matched' AND m.match_method = 'name_exact') AS method_name_exact_2020,
    COUNT_IF(m.census_year = 2020 AND m.match_status = 'matched' AND m.match_method = 'name_normalized') AS method_name_normalized_2020,
    COUNT_IF(m.census_year = 2020 AND m.match_status = 'matched' AND m.match_method = 'name_old') AS method_name_old_2020,
    COUNT_IF(m.census_year = 2020 AND m.match_status = 'matched' AND m.match_method = 'reviewed_alias') AS method_reviewed_alias_2020,
    COUNT_IF(m.census_year = 2024 AND TRUE) AS rows_2024,
    COUNT_IF(m.census_year = 2024 AND m.match_status = 'matched') AS matched_2024,
    COUNT_IF(m.census_year = 2024 AND m.match_status = 'matched' AND m.match_method = 'name_exact') AS method_name_exact_2024,
    COUNT_IF(m.census_year = 2024 AND m.match_status = 'matched' AND m.match_method = 'name_normalized') AS method_name_normalized_2024,
    COUNT_IF(m.census_year = 2024 AND m.match_status = 'matched' AND m.match_method = 'name_old') AS method_name_old_2024,
    COUNT_IF(m.census_year = 2024 AND m.match_status = 'matched' AND m.match_method = 'reviewed_alias') AS method_reviewed_alias_2024
  FROM edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate AS m
  LEFT JOIN units AS u ON u.psgc_code = m.psgc_code
),
stats AS (SELECT * FROM agg CROSS JOIN totals),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN source_places > 0 AND psgc_units > 0 THEN 'PASS' ELSE 'FAIL' END AS status, 'census places and PSGC units' AS expected, CAST(CAST(source_places AS STRING) || ' / ' || CAST(psgc_units AS STRING) AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_reconcile' AS check_name, CASE WHEN map_rows = source_places THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_places AS STRING) AS expected, CAST(map_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'one_row_per_place' AS check_name, CASE WHEN map_places = map_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(map_rows AS STRING) AS expected, CAST(map_places AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_code_taken_once' AS check_name, CASE WHEN matched_codes = matched_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(matched_rows AS STRING) AS expected, CAST(matched_codes AS STRING) AS actual FROM stats
  UNION ALL SELECT 'matched_has_psgc_unit' AS check_name, CASE WHEN matched_without_unit = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(matched_without_unit AS STRING) AS actual FROM stats
  UNION ALL SELECT 'unmatched_has_no_psgc' AS check_name, CASE WHEN unmatched_with_code = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(unmatched_with_code AS STRING) AS actual FROM stats
  UNION ALL SELECT 'status_valid' AS check_name, CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_status AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_valid' AS check_name, CASE WHEN bad_method = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_method AS STRING) AS actual FROM stats
  UNION ALL SELECT 'review_status_valid' AS check_name, CASE WHEN bad_review = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_review AS STRING) AS actual FROM stats
  UNION ALL SELECT 'status_combination_valid' AS check_name, CASE WHEN bad_combination = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_combination AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_name_matches_unit' AS check_name, CASE WHEN psgc_name_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(psgc_name_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'name_match_inside_province' AS check_name, CASE WHEN name_scope_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(name_scope_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'parent_match_valid' AS check_name, CASE WHEN bad_parent_match = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_parent_match AS STRING) AS actual FROM stats
  UNION ALL SELECT 'overrides_applied' AS check_name, CASE WHEN overrides_used = overrides_present THEN 'PASS' ELSE 'FAIL' END AS status, CAST(overrides_present AS STRING) AS expected, CAST(overrides_used AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rule_codes_in_psgc' AS check_name, CASE WHEN bad_rule_codes = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_rule_codes AS STRING) AS actual FROM stats
  UNION ALL SELECT 'one_psgc_version' AS check_name, CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END AS status, CAST(1 AS STRING) AS expected, CAST(master_periods AS STRING) AS actual FROM stats
  UNION ALL SELECT 'lineage_complete' AS check_name, CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(missing_lineage AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_built_by_this_run' AS check_name, CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(other_run_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'population_reconciles' AS check_name, CASE WHEN population_cells_off = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(population_cells_off AS STRING) AS actual FROM stats
  UNION ALL SELECT 'review_pending' AS check_name, CASE WHEN pending_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(pending_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'unmatched' AS check_name, CASE WHEN unmatched_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(unmatched_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'ambiguous' AS check_name, CASE WHEN ambiguous_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(ambiguous_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'override_place_missing' AS check_name, CASE WHEN overrides_missing = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(overrides_missing AS STRING) AS actual FROM stats
  UNION ALL SELECT 'region_not_listed' AS check_name, CASE WHEN regions_missing = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(regions_missing AS STRING) AS actual FROM stats
  UNION ALL SELECT 'province_without_psgc_parent' AS check_name, CASE WHEN provinces_unresolved = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(provinces_unresolved AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_units_without_place' AS check_name, CASE WHEN units_without_place = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(units_without_place AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_exact_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_exact_2020 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_normalized_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_normalized_2020 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_old_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_old_2020 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_reviewed_alias_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_reviewed_alias_2020 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_exact_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_exact_2024 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_normalized_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_normalized_2024 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_old_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_old_2024 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_reviewed_alias_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_reviewed_alias_2024 AS STRING) AS actual FROM stats
  UNION ALL SELECT 'match_rate_percent_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(CASE WHEN rows_2020 = 0 THEN 0 ELSE ROUND(100.0 * matched_2020 / rows_2020, 2) END AS STRING) AS actual FROM stats
  UNION ALL SELECT 'ap4_population_matched_percent_2020' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(CASE WHEN ap4_total_2020 = 0 THEN 0 ELSE ROUND(100.0 * ap4_matched_2020 / ap4_total_2020, 2) END AS STRING) AS actual FROM stats
  UNION ALL SELECT 'match_rate_percent_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(CASE WHEN rows_2024 = 0 THEN 0 ELSE ROUND(100.0 * matched_2024 / rows_2024, 2) END AS STRING) AS actual FROM stats
  UNION ALL SELECT 'ap4_population_matched_percent_2024' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(CASE WHEN ap4_total_2024 = 0 THEN 0 ELSE ROUND(100.0 * ap4_matched_2024 / ap4_total_2024, 2) END AS STRING) AS actual FROM stats
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The map table is not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'psa_school_age_population' AND layer = 'integration'
    AND checked_at_utc >= session.integration_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Integration gate failed for psa_school_age_population: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_school_age_population' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

-- Every check passed: publish, then record the run 'succeeded'.
CREATE OR REPLACE TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map USING DELTA AS
SELECT * FROM edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate;

ALTER TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_school_age_population'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
