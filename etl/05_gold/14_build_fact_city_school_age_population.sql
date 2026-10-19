-- Gold build for fact_city_school_age_population (D-048, docs/architecture/data-model.md).
--
-- Grain: city or municipality x census year x single year of age x sex, for AP4 (D-042). Reads the
-- published psa_school_age_population_clean (D-053), its PSGC map (D-055), and dim_city_municipality
-- for each unit's region and province, so the task waits for that dimension's gate (D-051). Writes
-- fact_city_school_age_population_candidate; the gate (the next task) checks it and publishes the
-- fact only if no check fails. It rebuilds on every run.
--
-- Rules:
--   - Rows: the city and municipality places of Silver, population_concept 'total' (D-042), sex
--     'male' and 'female' only. The published 'both' row is not stored; the gate reconciles to it
--     (D-048). Every age Silver publishes is kept (5 to 24); Analytics selects 5 to 17. Nothing is
--     interpolated, and the broader 5 to 24 category is never substituted.
--   - city_mun_psgc_code is the place's matched PSGC code. A place that is not matched (today the 8
--     2020 Special Geographic Area clusters, which are not LGUs, D-055) goes to the UNKNOWN member
--     of dim_city_municipality, with its psgc_match_status. Places that share UNKNOWN in a year are
--     summed into one row per age and sex, so no population is dropped and the key stays unique; if
--     they differ in status, the row keeps the first in alphabetical order (today all are unmatched).
--   - is_2020_2024_geography_comparable follows the AP4 comparability rule of the metric
--     specification and the data model ("boundary or hierarchy changes"). It is TRUE only for a code
--     matched in both census years that is not in the reviewed list below: units whose territory
--     changed, and every unit of a province or region whose hierarchy changed between the censuses.
--     Units that exist in one year only (the 8 Special Geographic Area municipalities of 2024) and
--     UNKNOWN are FALSE.

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

-- The reviewed 2020-to-2024 geography changes (metric specification, AP4 comparability):
--   unit      the unit's own territory changed: the EMBO barangays moved from Makati to Taguig, and
--             the six Cotabato towns whose barangays formed the Special Geographic Area (D-031, D-054)
--   region    the region changed: the Negros Island Region (RA No. 12000) took Negros Occidental,
--             Negros Oriental and Siquijor, and Bacolod, from Regions VI and VII
--   province  the province or region changed: Sulu moved from BARMM to Region IX (EO No. 91, s. 2025),
--             and Maguindanao split into del Norte and del Sur (RA No. 11550)
-- A unit matches on its own code, or on its region_psgc_code or province_psgc_code in dim_city_municipality.
CREATE OR REPLACE TEMPORARY VIEW school_age_geography_changes AS
SELECT * FROM (VALUES
  ('unit', '1380300000', 'City of Makati: EMBO barangays moved to Taguig'),
  ('unit', '1381500000', 'City of Taguig: received the EMBO barangays from Makati'),
  ('unit', '1204702000', 'Carmen, Cotabato: barangays moved to the Special Geographic Area'),
  ('unit', '1204703000', 'Kabacan, Cotabato: barangays moved to the Special Geographic Area'),
  ('unit', '1204709000', 'Midsayap, Cotabato: barangays moved to the Special Geographic Area'),
  ('unit', '1204711000', 'Pigkawayan, Cotabato: barangays moved to the Special Geographic Area'),
  ('unit', '1204712000', 'Pikit, Cotabato: barangays moved to the Special Geographic Area'),
  ('unit', '1204717000', 'Aleosan, Cotabato: barangays moved to the Special Geographic Area'),
  ('region', '1800000000', 'Negros Island Region: re-established from Regions VI and VII'),
  ('province', '0906600000', 'Sulu: moved from BARMM to Region IX'),
  ('province', '1908700000', 'Maguindanao del Norte: split from Maguindanao'),
  ('province', '1908800000', 'Maguindanao del Sur: split from Maguindanao')
) AS v(change_kind, psgc_code, reason);

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population_candidate USING DELTA AS
WITH placed AS (
  SELECT
    s.census_year,
    s.age,
    s.sex,
    s.population,
    CASE WHEN m.match_status = 'matched' THEN m.psgc_code ELSE 'UNKNOWN' END AS city_mun_psgc_code,
    m.match_status AS psgc_match_status
  FROM edu_access.`03-silver`.psa_school_age_population_clean AS s
  JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map AS m
    ON m.census_year = s.census_year AND m.batch_id = s.batch_id AND m.place_row_number = s.place_row_number
  WHERE s.level = 'city_municipality' AND s.population_concept = 'total' AND s.sex IN ('male', 'female')
),
summed AS (
  SELECT
    city_mun_psgc_code,
    census_year AS reference_year,
    age,
    sex,
    CAST(SUM(population) AS BIGINT) AS population,
    MIN(psgc_match_status) AS psgc_match_status
  FROM placed
  GROUP BY city_mun_psgc_code, census_year, age, sex
),
both_years AS (
  SELECT city_mun_psgc_code
  FROM summed
  WHERE city_mun_psgc_code <> 'UNKNOWN'
  GROUP BY city_mun_psgc_code
  HAVING COUNT(DISTINCT reference_year) = 2
),
-- Each unit once, however many listed changes it falls under, so the join adds no rows.
changed AS (
  SELECT DISTINCT d.city_mun_psgc_code AS psgc_code
  FROM edu_access.`05-gold`.dim_city_municipality AS d
  JOIN school_age_geography_changes AS c
    ON (c.change_kind = 'unit' AND c.psgc_code = d.city_mun_psgc_code)
    OR (c.change_kind = 'region' AND c.psgc_code = d.region_psgc_code)
    OR (c.change_kind = 'province' AND c.psgc_code = d.province_psgc_code)
)
SELECT
  f.city_mun_psgc_code,
  CAST(f.reference_year AS INT) AS reference_year,
  CAST(f.age AS INT) AS age,
  f.sex,
  f.population,
  f.psgc_match_status,
  (y.city_mun_psgc_code IS NOT NULL AND c.psgc_code IS NULL) AS is_2020_2024_geography_comparable
FROM summed AS f
LEFT JOIN both_years AS y ON y.city_mun_psgc_code = f.city_mun_psgc_code
LEFT JOIN changed AS c ON c.psgc_code = f.city_mun_psgc_code;

COMMENT ON TABLE edu_access.`05-gold`.fact_city_school_age_population_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use fact_city_school_age_population.';
ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population_candidate OWNER TO `reached-hq`;
