-- Gold build for dim_city_municipality (D-048, docs/architecture/data-model.md).
--
-- One row per PSGC city or municipality of the master quarter (D-012, today 2026-Q2), plus the two
-- technical members every geography fact can point to instead of a NULL key:
--   UNKNOWN   member_type 'unknown'   a row whose city or municipality could not be matched
--   EXCLUDED  member_type 'excluded'  a row kept on purpose outside city-level analysis
-- Text codes, so a technical member can never collide with, or pass as, a ten-digit PSGC code.
--
-- Reads published tables only: psa_psgc_clean (D-035) and, for land area, hdx_adm3_psgc_map and
-- hdx_adm3_clean (D-042, D-052). Writes dim_city_municipality_candidate; the gate (the next task)
-- checks it and publishes dim_city_municipality only if no check fails. It rebuilds on every run.
--
-- Rules:
--   - Regular members are the master quarter's City and Mun rows. The two blank-level rows
--     (0990100000 City of Isabela (Not a Province), 1999900000 Special Geographic Area) are
--     province-position containers, not cities (D-035, profile O-2); the City of Isabela itself is
--     its own City row.
--   - Province is Silver's province_code as published: a Prov row, or one of the two containers.
--     NULL for the highly urbanized cities and Pateros.
--   - is_sga marks the municipalities under the Special Geographic Area container, 1999901000 to
--     1999908000 (D-031, D-049).
--   - Land area is the HDX area of the feature matched to the unit in the latest HDX release only,
--     so a unit matched in two releases is not counted twice (D-052). A unit with no matched feature
--     (today the 8 Special Geographic Area municipalities) keeps NULL; nothing is substituted.
--     DECIMAL(18,4) rounds the published 14 decimals to 4.

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_municipality_candidate USING DELTA AS
WITH psgc AS (
  SELECT *
  FROM edu_access.`03-silver`.psa_psgc_clean
  WHERE is_master_reference
),
hdx_release AS (
  SELECT MAX(source_reference_date) AS source_reference_date
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map
),
land_area AS (
  SELECT m.psgc_code, h.area_sqkm
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  JOIN hdx_release AS r ON r.source_reference_date = m.source_reference_date
  JOIN edu_access.`03-silver`.hdx_adm3_clean AS h
    ON h.adm3_pcode = m.adm3_pcode AND h.valid_on = m.source_reference_date
  WHERE m.match_status = 'matched'
),
regular AS (
  SELECT
    c.psgc_code AS city_mun_psgc_code,
    c.name AS city_mun_name,
    c.province_code AS province_psgc_code,
    p.name AS province_name,
    c.region_code AS region_psgc_code,
    g.name AS region_name,
    CASE c.geographic_level WHEN 'City' THEN 'city' WHEN 'Mun' THEN 'municipality' END AS lgu_type,
    c.city_class,
    c.income_class,
    c.income_class_retained_after_downgrade AS income_class_retained,
    CAST(a.area_sqkm AS DECIMAL(18,4)) AS land_area_sqkm,
    CASE WHEN a.area_sqkm IS NOT NULL THEN 'hdx_boundaries' END AS land_area_source,
    COALESCE(c.province_code = '1999900000', FALSE) AS is_sga,
    'regular' AS member_type,
    c.publication_period AS source_psgc_quarter
  FROM psgc AS c
  LEFT JOIN psgc AS p ON p.psgc_code = c.province_code
  LEFT JOIN psgc AS g ON g.psgc_code = c.region_code
  LEFT JOIN land_area AS a ON a.psgc_code = c.psgc_code
  WHERE c.geographic_level IN ('City', 'Mun')
),
technical AS (
  SELECT code, label, member_type
  FROM (VALUES
    ('UNKNOWN', 'Unknown city or municipality', 'unknown'),
    ('EXCLUDED', 'Excluded from city or municipality analysis', 'excluded')
  ) AS v(code, label, member_type)
)
SELECT * FROM regular
UNION ALL
SELECT
  t.code AS city_mun_psgc_code,
  t.label AS city_mun_name,
  CAST(NULL AS STRING) AS province_psgc_code,
  CAST(NULL AS STRING) AS province_name,
  CAST(NULL AS STRING) AS region_psgc_code,
  CAST(NULL AS STRING) AS region_name,
  CAST(NULL AS STRING) AS lgu_type,
  CAST(NULL AS STRING) AS city_class,
  CAST(NULL AS STRING) AS income_class,
  CAST(NULL AS BOOLEAN) AS income_class_retained,
  CAST(NULL AS DECIMAL(18,4)) AS land_area_sqkm,
  CAST(NULL AS STRING) AS land_area_source,
  FALSE AS is_sga,
  t.member_type,
  (SELECT MAX(publication_period) FROM psgc) AS source_psgc_quarter
FROM technical AS t;

COMMENT ON TABLE edu_access.`05-gold`.dim_city_municipality_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use dim_city_municipality.';
ALTER TABLE edu_access.`05-gold`.dim_city_municipality_candidate OWNER TO `reached-hq`;
