-- Gold build for dim_barangay (D-048, docs/architecture/data-model.md).
--
-- One row per PSGC barangay of the master quarter (D-012, today 2026-Q2), plus technical members, so a
-- fact never needs a NULL barangay key:
--   <city_mun_psgc_code>-UNKNOWN  member_type 'unknown', one per PSGC city or municipality: a school
--                                 placed in that city or municipality but in no unique barangay
--   UNKNOWN                       member_type 'unknown', under the UNKNOWN city member
--   EXCLUDED                      member_type 'excluded', under the EXCLUDED city member
-- Text codes, as in dim_city_municipality, so none can collide with or pass as a PSGC code.
--
-- Reads psa_psgc_clean only (D-035), so it waits only for the PSGC Silver gate (D-051). Writes
-- dim_barangay_candidate; the gate (the next task) checks it and publishes dim_barangay only if no
-- check fails. It rebuilds on every run.
--
-- Rules:
--   - city_mun_psgc_code is the barangay's city or municipality in dim_city_municipality. Silver's
--     city_municipality_code is the City or Mun row, except for the City of Manila, whose barangays sit
--     under its 14 SubMun districts: those roll up to the City row at the district's province position
--     (1380601000 -> 1380600000), because Gold has no sub-municipality grain (D-046).
--   - urban_rural is Silver's U or R; NULL where PSGC publishes '-' (urban_rural_null_reason
--     'unknown'), never folded into rural (D-035).

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_barangay_candidate USING DELTA AS
WITH psgc AS (
  SELECT *
  FROM edu_access.`03-silver`.psa_psgc_clean
  WHERE is_master_reference
),
regular AS (
  SELECT
    b.psgc_code AS barangay_psgc_code,
    b.name AS barangay_name,
    CASE WHEN parent.geographic_level = 'SubMun' THEN substr(parent.psgc_code, 1, 5) || '00000'
         ELSE b.city_municipality_code END AS city_mun_psgc_code,
    b.urban_rural,
    'regular' AS member_type
  FROM psgc AS b
  LEFT JOIN psgc AS parent ON parent.psgc_code = b.city_municipality_code
  WHERE b.geographic_level = 'Bgy'
),
city_unknown AS (
  SELECT
    c.psgc_code || '-UNKNOWN' AS barangay_psgc_code,
    'Unknown barangay in ' || c.name AS barangay_name,
    c.psgc_code AS city_mun_psgc_code,
    CAST(NULL AS STRING) AS urban_rural,
    'unknown' AS member_type
  FROM psgc AS c
  WHERE c.geographic_level IN ('City', 'Mun')
),
technical AS (
  SELECT code AS barangay_psgc_code, label AS barangay_name, code AS city_mun_psgc_code,
         CAST(NULL AS STRING) AS urban_rural, member_type
  FROM (VALUES
    ('UNKNOWN', 'Unknown barangay', 'unknown'),
    ('EXCLUDED', 'Excluded from barangay analysis', 'excluded')
  ) AS v(code, label, member_type)
)
SELECT * FROM regular
UNION ALL SELECT * FROM city_unknown
UNION ALL SELECT * FROM technical;

COMMENT ON TABLE edu_access.`05-gold`.dim_barangay_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use dim_barangay.';
ALTER TABLE edu_access.`05-gold`.dim_barangay_candidate OWNER TO `reached-hq`;
