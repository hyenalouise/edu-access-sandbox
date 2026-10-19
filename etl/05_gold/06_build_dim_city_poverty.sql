-- Gold build for dim_city_poverty (D-046, D-048, docs/architecture/data-model.md).
--
-- One row per regular member of dim_city_municipality (the 1,642 PSGC 2Q 2026 cities and
-- municipalities), key city_mun_psgc_code, with PSA's 2023 small-area poverty estimate for it. The
-- UNKNOWN and EXCLUDED technical members get no row. Context only: no ranking, flag or score reads it.
--
-- Reads published tables only: dim_city_municipality and psa_poverty_psgc_map (D-054), which carries
-- each Silver estimate unchanged. Writes dim_city_poverty_candidate; the gate (the next task) checks it
-- and publishes dim_city_poverty only if no check fails, so a FAIL keeps the last good build. It
-- rebuilds on every run.
--
-- Rules (D-046):
--   - estimate_year is 2023 on every row, the selected estimate year (D-027).
--   - A member takes the 2023 map row matched to it at city or municipality level. Its measures are
--     Silver's, as published and still DOUBLE: a lower limit below 0 stays below 0.
--   - poverty_status is Silver's estimate_status for that row ('estimated' or 'no_estimate'), or
--     'not_in_source' when the PSA file has no row for the member (D-028). Silver's fourth value,
--     'partial_estimate', is carried as it is so the gate fails it; it is never shown as no_estimate.
--   - cv_over_20 is poverty_cv > 20 (D-034), so it is NULL, not FALSE, when there is no estimate.
--   - status_reason is NULL when estimated, otherwise one of D-046's three reasons. The City of Manila
--     reason goes to the member whose sub-municipality districts have 2023 rows in the map: Manila's
--     14 district estimates are kept in the map and never combined into a city value here. The gate
--     checks that this member is the City of Manila (HUC, 14 district rows). The reason's semicolon
--     is written chr(59): the local runner splits statements on ';'.

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_poverty_candidate USING DELTA AS
WITH regular AS (
  SELECT city_mun_psgc_code
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
),
estimates AS (
  SELECT *
  FROM edu_access.`04-integration`.psa_poverty_psgc_map
  WHERE estimate_year = 2023 AND match_status = 'matched' AND geographic_level = 'city_mun'
),
-- The city a matched district belongs to: its province-position code (1380601000 -> 1380600000), the
-- same roll-up dim_barangay uses.
district_parents AS (
  SELECT DISTINCT substr(psgc_code, 1, 5) || '00000' AS city_mun_psgc_code
  FROM edu_access.`04-integration`.psa_poverty_psgc_map
  WHERE estimate_year = 2023 AND match_status = 'matched' AND geographic_level = 'sub_mun'
),
joined AS (
  SELECT
    r.city_mun_psgc_code,
    COALESCE(e.estimate_status, 'not_in_source') AS poverty_status,
    d.city_mun_psgc_code IS NOT NULL AS has_districts,
    e.poverty_incidence,
    e.ci90_lower_limit,
    e.ci90_upper_limit,
    e.coefficient_of_variation
  FROM regular AS r
  LEFT JOIN estimates AS e ON e.psgc_code = r.city_mun_psgc_code
  LEFT JOIN district_parents AS d ON d.city_mun_psgc_code = r.city_mun_psgc_code
)
SELECT
  city_mun_psgc_code,
  CAST(2023 AS INT) AS estimate_year,
  CAST(poverty_incidence AS DOUBLE) AS poverty_incidence,
  CAST(ci90_lower_limit AS DOUBLE) AS poverty_ci90_lower,
  CAST(ci90_upper_limit AS DOUBLE) AS poverty_ci90_upper,
  CAST(coefficient_of_variation AS DOUBLE) AS poverty_cv,
  coefficient_of_variation > 20 AS cv_over_20,
  poverty_status,
  CASE
    WHEN poverty_status = 'no_estimate' THEN 'PSA published no 2023 estimate'
    WHEN poverty_status = 'not_in_source' AND has_districts
      THEN 'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined'
    WHEN poverty_status = 'not_in_source' THEN 'not in the PSA city and municipal estimates'
  END AS status_reason
FROM joined;

COMMENT ON TABLE edu_access.`05-gold`.dim_city_poverty_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use dim_city_poverty.';
ALTER TABLE edu_access.`05-gold`.dim_city_poverty_candidate OWNER TO `reached-hq`;
