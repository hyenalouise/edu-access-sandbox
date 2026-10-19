DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW fact_school_teacher_capacity_gate_summary AS
WITH source AS (
  SELECT * FROM edu_access.`03-silver`.deped_personnel_clean WHERE sector = 'Public'
), expected AS (
  SELECT
    'ES' AS education_level_code,
    SUM(COALESCE(es_teacher_i, 0) + COALESCE(es_teacher_ii, 0) + COALESCE(es_teacher_iii, 0)
      + COALESCE(es_master_teacher_i, 0) + COALESCE(es_master_teacher_ii, 0) + COALESCE(es_master_teacher_iii, 0) + COALESCE(es_master_teacher_iv, 0)
      + COALESCE(es_head_teacher_i, 0) + COALESCE(es_head_teacher_ii, 0) + COALESCE(es_head_teacher_iii, 0) + COALESCE(es_head_teacher_iv, 0) + COALESCE(es_head_teacher_v, 0) + COALESCE(es_head_teacher_vi, 0)
      + COALESCE(es_sped_sned_teacher_i, 0) + COALESCE(es_sped_sned_teacher_ii, 0) + COALESCE(es_sped_sned_teacher_iii, 0) + COALESCE(es_sped_sned_teacher_iv, 0) + COALESCE(es_sped_sned_teacher_v, 0)
      + COALESCE(kinder_teachers_sef_province, 0) + COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(kinder_teachers_other_funding, 0)
      + COALESCE(es_teachers_sef_province, 0) + COALESCE(es_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_lgu_funding, 0) + COALESCE(es_teachers_other_funding, 0)) AS teacher_total,
    SUM(COALESCE(kinder_teachers_sef_province, 0) + COALESCE(es_teachers_sef_province, 0)) AS provincial_total,
    SUM(COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_sef_municipality_city, 0)) AS city_municipal_total,
    SUM(COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(es_teachers_lgu_funding, 0)) AS lgu_total,
    SUM(COALESCE(kinder_teachers_other_funding, 0) + COALESCE(es_teachers_other_funding, 0)) AS other_total,
    COUNT_IF(es_teacher_i IS NULL AND es_teacher_ii IS NULL AND es_teacher_iii IS NULL
      AND es_master_teacher_i IS NULL AND es_master_teacher_ii IS NULL AND es_master_teacher_iii IS NULL AND es_master_teacher_iv IS NULL
      AND es_head_teacher_i IS NULL AND es_head_teacher_ii IS NULL AND es_head_teacher_iii IS NULL AND es_head_teacher_iv IS NULL AND es_head_teacher_v IS NULL AND es_head_teacher_vi IS NULL
      AND es_sped_sned_teacher_i IS NULL AND es_sped_sned_teacher_ii IS NULL AND es_sped_sned_teacher_iii IS NULL AND es_sped_sned_teacher_iv IS NULL AND es_sped_sned_teacher_v IS NULL
      AND kinder_teachers_sef_province IS NULL AND kinder_teachers_sef_municipality_city IS NULL AND kinder_teachers_lgu_funding IS NULL AND kinder_teachers_other_funding IS NULL
      AND es_teachers_sef_province IS NULL AND es_teachers_sef_municipality_city IS NULL AND es_teachers_lgu_funding IS NULL AND es_teachers_other_funding IS NULL) AS all_null_rows,
    COUNT_IF(NOT (es_teacher_i IS NULL AND es_teacher_ii IS NULL AND es_teacher_iii IS NULL
      AND es_master_teacher_i IS NULL AND es_master_teacher_ii IS NULL AND es_master_teacher_iii IS NULL AND es_master_teacher_iv IS NULL
      AND es_head_teacher_i IS NULL AND es_head_teacher_ii IS NULL AND es_head_teacher_iii IS NULL AND es_head_teacher_iv IS NULL AND es_head_teacher_v IS NULL AND es_head_teacher_vi IS NULL
      AND es_sped_sned_teacher_i IS NULL AND es_sped_sned_teacher_ii IS NULL AND es_sped_sned_teacher_iii IS NULL AND es_sped_sned_teacher_iv IS NULL AND es_sped_sned_teacher_v IS NULL
      AND kinder_teachers_sef_province IS NULL AND kinder_teachers_sef_municipality_city IS NULL AND kinder_teachers_lgu_funding IS NULL AND kinder_teachers_other_funding IS NULL
      AND es_teachers_sef_province IS NULL AND es_teachers_sef_municipality_city IS NULL AND es_teachers_lgu_funding IS NULL AND es_teachers_other_funding IS NULL)
      AND (es_teacher_i IS NULL OR es_teacher_ii IS NULL OR es_teacher_iii IS NULL OR es_master_teacher_i IS NULL OR es_master_teacher_ii IS NULL OR es_master_teacher_iii IS NULL OR es_master_teacher_iv IS NULL
      OR es_head_teacher_i IS NULL OR es_head_teacher_ii IS NULL OR es_head_teacher_iii IS NULL OR es_head_teacher_iv IS NULL OR es_head_teacher_v IS NULL OR es_head_teacher_vi IS NULL
      OR es_sped_sned_teacher_i IS NULL OR es_sped_sned_teacher_ii IS NULL OR es_sped_sned_teacher_iii IS NULL OR es_sped_sned_teacher_iv IS NULL OR es_sped_sned_teacher_v IS NULL
      OR kinder_teachers_sef_province IS NULL OR kinder_teachers_sef_municipality_city IS NULL OR kinder_teachers_lgu_funding IS NULL OR kinder_teachers_other_funding IS NULL
      OR es_teachers_sef_province IS NULL OR es_teachers_sef_municipality_city IS NULL OR es_teachers_lgu_funding IS NULL OR es_teachers_other_funding IS NULL)) AS partial_rows
  FROM source

  UNION ALL

  SELECT
    'JHS',
    SUM(COALESCE(jhs_teacher_i, 0) + COALESCE(jhs_teacher_ii, 0) + COALESCE(jhs_teacher_iii, 0)
      + COALESCE(jhs_master_teacher_i, 0) + COALESCE(jhs_master_teacher_ii, 0) + COALESCE(jhs_master_teacher_iii, 0) + COALESCE(jhs_master_teacher_iv, 0)
      + COALESCE(jhs_head_teacher_i, 0) + COALESCE(jhs_head_teacher_ii, 0) + COALESCE(jhs_head_teacher_iii, 0) + COALESCE(jhs_head_teacher_iv, 0) + COALESCE(jhs_head_teacher_v, 0) + COALESCE(jhs_head_teacher_vi, 0)
      + COALESCE(jhs_sped_teacher_i, 0) + COALESCE(jhs_sped_teacher_ii, 0) + COALESCE(jhs_sped_teacher_iii, 0) + COALESCE(jhs_sped_teacher_iv, 0) + COALESCE(jhs_sped_teacher_v, 0)
      + COALESCE(jhs_special_science_teacher_i, 0) + COALESCE(jhs_instructor_i, 0) + COALESCE(jhs_instructor_ii, 0) + COALESCE(jhs_instructor_iii, 0)
      + COALESCE(jhs_teachers_sef_province, 0) + COALESCE(jhs_teachers_sef_municipality_city, 0) + COALESCE(jhs_teachers_lgu_funding, 0) + COALESCE(jhs_teachers_other_funding, 0)),
    SUM(COALESCE(jhs_teachers_sef_province, 0)), SUM(COALESCE(jhs_teachers_sef_municipality_city, 0)), SUM(COALESCE(jhs_teachers_lgu_funding, 0)), SUM(COALESCE(jhs_teachers_other_funding, 0)),
    COUNT_IF(jhs_teacher_i IS NULL AND jhs_teacher_ii IS NULL AND jhs_teacher_iii IS NULL
      AND jhs_master_teacher_i IS NULL AND jhs_master_teacher_ii IS NULL AND jhs_master_teacher_iii IS NULL AND jhs_master_teacher_iv IS NULL
      AND jhs_head_teacher_i IS NULL AND jhs_head_teacher_ii IS NULL AND jhs_head_teacher_iii IS NULL AND jhs_head_teacher_iv IS NULL AND jhs_head_teacher_v IS NULL AND jhs_head_teacher_vi IS NULL
      AND jhs_sped_teacher_i IS NULL AND jhs_sped_teacher_ii IS NULL AND jhs_sped_teacher_iii IS NULL AND jhs_sped_teacher_iv IS NULL AND jhs_sped_teacher_v IS NULL
      AND jhs_special_science_teacher_i IS NULL AND jhs_instructor_i IS NULL AND jhs_instructor_ii IS NULL AND jhs_instructor_iii IS NULL
      AND jhs_teachers_sef_province IS NULL AND jhs_teachers_sef_municipality_city IS NULL AND jhs_teachers_lgu_funding IS NULL AND jhs_teachers_other_funding IS NULL),
    COUNT_IF(NOT (jhs_teacher_i IS NULL AND jhs_teacher_ii IS NULL AND jhs_teacher_iii IS NULL
      AND jhs_master_teacher_i IS NULL AND jhs_master_teacher_ii IS NULL AND jhs_master_teacher_iii IS NULL AND jhs_master_teacher_iv IS NULL
      AND jhs_head_teacher_i IS NULL AND jhs_head_teacher_ii IS NULL AND jhs_head_teacher_iii IS NULL AND jhs_head_teacher_iv IS NULL AND jhs_head_teacher_v IS NULL AND jhs_head_teacher_vi IS NULL
      AND jhs_sped_teacher_i IS NULL AND jhs_sped_teacher_ii IS NULL AND jhs_sped_teacher_iii IS NULL AND jhs_sped_teacher_iv IS NULL AND jhs_sped_teacher_v IS NULL
      AND jhs_special_science_teacher_i IS NULL AND jhs_instructor_i IS NULL AND jhs_instructor_ii IS NULL AND jhs_instructor_iii IS NULL
      AND jhs_teachers_sef_province IS NULL AND jhs_teachers_sef_municipality_city IS NULL AND jhs_teachers_lgu_funding IS NULL AND jhs_teachers_other_funding IS NULL)
      AND (jhs_teacher_i IS NULL OR jhs_teacher_ii IS NULL OR jhs_teacher_iii IS NULL OR jhs_master_teacher_i IS NULL OR jhs_master_teacher_ii IS NULL OR jhs_master_teacher_iii IS NULL OR jhs_master_teacher_iv IS NULL
      OR jhs_head_teacher_i IS NULL OR jhs_head_teacher_ii IS NULL OR jhs_head_teacher_iii IS NULL OR jhs_head_teacher_iv IS NULL OR jhs_head_teacher_v IS NULL OR jhs_head_teacher_vi IS NULL
      OR jhs_sped_teacher_i IS NULL OR jhs_sped_teacher_ii IS NULL OR jhs_sped_teacher_iii IS NULL OR jhs_sped_teacher_iv IS NULL OR jhs_sped_teacher_v IS NULL
      OR jhs_special_science_teacher_i IS NULL OR jhs_instructor_i IS NULL OR jhs_instructor_ii IS NULL OR jhs_instructor_iii IS NULL
      OR jhs_teachers_sef_province IS NULL OR jhs_teachers_sef_municipality_city IS NULL OR jhs_teachers_lgu_funding IS NULL OR jhs_teachers_other_funding IS NULL))
  FROM source

  UNION ALL

  SELECT
    'SHS',
    SUM(COALESCE(shs_teacher_i, 0) + COALESCE(shs_teacher_ii, 0) + COALESCE(shs_teacher_iii, 0)
      + COALESCE(shs_master_teacher_i, 0) + COALESCE(shs_master_teacher_ii, 0) + COALESCE(shs_master_teacher_iii, 0) + COALESCE(shs_master_teacher_iv, 0)
      + COALESCE(shs_head_teacher_i, 0) + COALESCE(shs_head_teacher_ii, 0) + COALESCE(shs_head_teacher_iii, 0) + COALESCE(shs_head_teacher_iv, 0) + COALESCE(shs_head_teacher_v, 0) + COALESCE(shs_head_teacher_vi, 0)
      + COALESCE(shs_special_science_teacher_i, 0)
      + COALESCE(shs_teachers_sef_province, 0) + COALESCE(shs_teachers_sef_municipality_city, 0) + COALESCE(shs_teachers_lgu_funding, 0) + COALESCE(shs_teachers_other_funding, 0)),
    SUM(COALESCE(shs_teachers_sef_province, 0)), SUM(COALESCE(shs_teachers_sef_municipality_city, 0)), SUM(COALESCE(shs_teachers_lgu_funding, 0)), SUM(COALESCE(shs_teachers_other_funding, 0)),
    COUNT_IF(shs_teacher_i IS NULL AND shs_teacher_ii IS NULL AND shs_teacher_iii IS NULL
      AND shs_master_teacher_i IS NULL AND shs_master_teacher_ii IS NULL AND shs_master_teacher_iii IS NULL AND shs_master_teacher_iv IS NULL
      AND shs_head_teacher_i IS NULL AND shs_head_teacher_ii IS NULL AND shs_head_teacher_iii IS NULL AND shs_head_teacher_iv IS NULL AND shs_head_teacher_v IS NULL AND shs_head_teacher_vi IS NULL
      AND shs_special_science_teacher_i IS NULL
      AND shs_teachers_sef_province IS NULL AND shs_teachers_sef_municipality_city IS NULL AND shs_teachers_lgu_funding IS NULL AND shs_teachers_other_funding IS NULL),
    COUNT_IF(NOT (shs_teacher_i IS NULL AND shs_teacher_ii IS NULL AND shs_teacher_iii IS NULL
      AND shs_master_teacher_i IS NULL AND shs_master_teacher_ii IS NULL AND shs_master_teacher_iii IS NULL AND shs_master_teacher_iv IS NULL
      AND shs_head_teacher_i IS NULL AND shs_head_teacher_ii IS NULL AND shs_head_teacher_iii IS NULL AND shs_head_teacher_iv IS NULL AND shs_head_teacher_v IS NULL AND shs_head_teacher_vi IS NULL
      AND shs_special_science_teacher_i IS NULL
      AND shs_teachers_sef_province IS NULL AND shs_teachers_sef_municipality_city IS NULL AND shs_teachers_lgu_funding IS NULL AND shs_teachers_other_funding IS NULL)
      AND (shs_teacher_i IS NULL OR shs_teacher_ii IS NULL OR shs_teacher_iii IS NULL OR shs_master_teacher_i IS NULL OR shs_master_teacher_ii IS NULL OR shs_master_teacher_iii IS NULL OR shs_master_teacher_iv IS NULL
      OR shs_head_teacher_i IS NULL OR shs_head_teacher_ii IS NULL OR shs_head_teacher_iii IS NULL OR shs_head_teacher_iv IS NULL OR shs_head_teacher_v IS NULL OR shs_head_teacher_vi IS NULL
      OR shs_special_science_teacher_i IS NULL OR shs_teachers_sef_province IS NULL OR shs_teachers_sef_municipality_city IS NULL OR shs_teachers_lgu_funding IS NULL OR shs_teachers_other_funding IS NULL))
  FROM source
), row_expected AS (
  SELECT
    s.school_id,
    s.school_year,
    l.education_level_code,
    CASE l.education_level_code
      WHEN 'ES' THEN COALESCE(es_teacher_i, 0) + COALESCE(es_teacher_ii, 0) + COALESCE(es_teacher_iii, 0)
        + COALESCE(es_master_teacher_i, 0) + COALESCE(es_master_teacher_ii, 0) + COALESCE(es_master_teacher_iii, 0) + COALESCE(es_master_teacher_iv, 0)
        + COALESCE(es_head_teacher_i, 0) + COALESCE(es_head_teacher_ii, 0) + COALESCE(es_head_teacher_iii, 0) + COALESCE(es_head_teacher_iv, 0) + COALESCE(es_head_teacher_v, 0) + COALESCE(es_head_teacher_vi, 0)
        + COALESCE(es_sped_sned_teacher_i, 0) + COALESCE(es_sped_sned_teacher_ii, 0) + COALESCE(es_sped_sned_teacher_iii, 0) + COALESCE(es_sped_sned_teacher_iv, 0) + COALESCE(es_sped_sned_teacher_v, 0)
        + COALESCE(kinder_teachers_sef_province, 0) + COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(kinder_teachers_other_funding, 0)
        + COALESCE(es_teachers_sef_province, 0) + COALESCE(es_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_lgu_funding, 0) + COALESCE(es_teachers_other_funding, 0)
      WHEN 'JHS' THEN COALESCE(jhs_teacher_i, 0) + COALESCE(jhs_teacher_ii, 0) + COALESCE(jhs_teacher_iii, 0)
        + COALESCE(jhs_master_teacher_i, 0) + COALESCE(jhs_master_teacher_ii, 0) + COALESCE(jhs_master_teacher_iii, 0) + COALESCE(jhs_master_teacher_iv, 0)
        + COALESCE(jhs_head_teacher_i, 0) + COALESCE(jhs_head_teacher_ii, 0) + COALESCE(jhs_head_teacher_iii, 0) + COALESCE(jhs_head_teacher_iv, 0) + COALESCE(jhs_head_teacher_v, 0) + COALESCE(jhs_head_teacher_vi, 0)
        + COALESCE(jhs_sped_teacher_i, 0) + COALESCE(jhs_sped_teacher_ii, 0) + COALESCE(jhs_sped_teacher_iii, 0) + COALESCE(jhs_sped_teacher_iv, 0) + COALESCE(jhs_sped_teacher_v, 0)
        + COALESCE(jhs_special_science_teacher_i, 0) + COALESCE(jhs_instructor_i, 0) + COALESCE(jhs_instructor_ii, 0) + COALESCE(jhs_instructor_iii, 0)
        + COALESCE(jhs_teachers_sef_province, 0) + COALESCE(jhs_teachers_sef_municipality_city, 0) + COALESCE(jhs_teachers_lgu_funding, 0) + COALESCE(jhs_teachers_other_funding, 0)
      WHEN 'SHS' THEN COALESCE(shs_teacher_i, 0) + COALESCE(shs_teacher_ii, 0) + COALESCE(shs_teacher_iii, 0)
        + COALESCE(shs_master_teacher_i, 0) + COALESCE(shs_master_teacher_ii, 0) + COALESCE(shs_master_teacher_iii, 0) + COALESCE(shs_master_teacher_iv, 0)
        + COALESCE(shs_head_teacher_i, 0) + COALESCE(shs_head_teacher_ii, 0) + COALESCE(shs_head_teacher_iii, 0) + COALESCE(shs_head_teacher_iv, 0) + COALESCE(shs_head_teacher_v, 0) + COALESCE(shs_head_teacher_vi, 0)
        + COALESCE(shs_special_science_teacher_i, 0) + COALESCE(shs_teachers_sef_province, 0) + COALESCE(shs_teachers_sef_municipality_city, 0) + COALESCE(shs_teachers_lgu_funding, 0) + COALESCE(shs_teachers_other_funding, 0)
    END AS teacher_count,
    CASE l.education_level_code WHEN 'ES' THEN CASE WHEN kinder_teachers_sef_province IS NULL AND es_teachers_sef_province IS NULL THEN NULL ELSE COALESCE(kinder_teachers_sef_province, 0) + COALESCE(es_teachers_sef_province, 0) END WHEN 'JHS' THEN jhs_teachers_sef_province WHEN 'SHS' THEN shs_teachers_sef_province END AS sef_provincial_teacher_count,
    CASE l.education_level_code WHEN 'ES' THEN CASE WHEN kinder_teachers_sef_municipality_city IS NULL AND es_teachers_sef_municipality_city IS NULL THEN NULL ELSE COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_sef_municipality_city, 0) END WHEN 'JHS' THEN jhs_teachers_sef_municipality_city WHEN 'SHS' THEN shs_teachers_sef_municipality_city END AS sef_city_municipal_teacher_count,
    CASE l.education_level_code WHEN 'ES' THEN CASE WHEN kinder_teachers_lgu_funding IS NULL AND es_teachers_lgu_funding IS NULL THEN NULL ELSE COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(es_teachers_lgu_funding, 0) END WHEN 'JHS' THEN jhs_teachers_lgu_funding WHEN 'SHS' THEN shs_teachers_lgu_funding END AS lgu_funded_teacher_count,
    CASE l.education_level_code WHEN 'ES' THEN CASE WHEN kinder_teachers_other_funding IS NULL AND es_teachers_other_funding IS NULL THEN NULL ELSE COALESCE(kinder_teachers_other_funding, 0) + COALESCE(es_teachers_other_funding, 0) END WHEN 'JHS' THEN jhs_teachers_other_funding WHEN 'SHS' THEN shs_teachers_other_funding END AS other_funded_teacher_count,
    CASE l.education_level_code
      WHEN 'ES' THEN COALESCE(es_teacher_i, es_teacher_ii, es_teacher_iii, es_master_teacher_i, es_master_teacher_ii, es_master_teacher_iii, es_master_teacher_iv, es_head_teacher_i, es_head_teacher_ii, es_head_teacher_iii, es_head_teacher_iv, es_head_teacher_v, es_head_teacher_vi, es_sped_sned_teacher_i, es_sped_sned_teacher_ii, es_sped_sned_teacher_iii, es_sped_sned_teacher_iv, es_sped_sned_teacher_v, kinder_teachers_sef_province, kinder_teachers_sef_municipality_city, kinder_teachers_lgu_funding, kinder_teachers_other_funding, es_teachers_sef_province, es_teachers_sef_municipality_city, es_teachers_lgu_funding, es_teachers_other_funding) IS NOT NULL
      WHEN 'JHS' THEN COALESCE(jhs_teacher_i, jhs_teacher_ii, jhs_teacher_iii, jhs_master_teacher_i, jhs_master_teacher_ii, jhs_master_teacher_iii, jhs_master_teacher_iv, jhs_head_teacher_i, jhs_head_teacher_ii, jhs_head_teacher_iii, jhs_head_teacher_iv, jhs_head_teacher_v, jhs_head_teacher_vi, jhs_sped_teacher_i, jhs_sped_teacher_ii, jhs_sped_teacher_iii, jhs_sped_teacher_iv, jhs_sped_teacher_v, jhs_special_science_teacher_i, jhs_instructor_i, jhs_instructor_ii, jhs_instructor_iii, jhs_teachers_sef_province, jhs_teachers_sef_municipality_city, jhs_teachers_lgu_funding, jhs_teachers_other_funding) IS NOT NULL
      WHEN 'SHS' THEN COALESCE(shs_teacher_i, shs_teacher_ii, shs_teacher_iii, shs_master_teacher_i, shs_master_teacher_ii, shs_master_teacher_iii, shs_master_teacher_iv, shs_head_teacher_i, shs_head_teacher_ii, shs_head_teacher_iii, shs_head_teacher_iv, shs_head_teacher_v, shs_head_teacher_vi, shs_special_science_teacher_i, shs_teachers_sef_province, shs_teachers_sef_municipality_city, shs_teachers_lgu_funding, shs_teachers_other_funding) IS NOT NULL
    END AS teacher_data_present,
    CASE l.education_level_code WHEN 'ES' THEN s.offers_es WHEN 'JHS' THEN s.offers_jhs WHEN 'SHS' THEN s.offers_shs END AS is_offered
  FROM source AS s
  CROSS JOIN (SELECT * FROM VALUES ('ES'), ('JHS'), ('SHS') AS levels(education_level_code)) AS l
), row_reconciliation AS (
  SELECT
    COALESCE(COUNT_IF(f.school_id IS NULL OR e.school_id IS NULL
      OR f.teacher_count IS DISTINCT FROM CASE WHEN e.teacher_data_present THEN e.teacher_count END
      OR f.sef_provincial_teacher_count IS DISTINCT FROM e.sef_provincial_teacher_count
      OR f.sef_city_municipal_teacher_count IS DISTINCT FROM e.sef_city_municipal_teacher_count
      OR f.lgu_funded_teacher_count IS DISTINCT FROM e.lgu_funded_teacher_count
      OR f.other_funded_teacher_count IS DISTINCT FROM e.other_funded_teacher_count), 0) AS mismatched_rows,
    COALESCE(COUNT_IF(e.is_offered IS TRUE AND f.teacher_count IS NULL), 0) AS offered_levels_without_teachers
  FROM row_expected AS e
  FULL OUTER JOIN edu_access.`05-gold`.fact_school_teacher_capacity_candidate AS f USING (school_id, school_year, education_level_code)
), actual AS (
  SELECT
    education_level_code,
    SUM(COALESCE(teacher_count, 0)) AS teacher_total,
    SUM(COALESCE(sef_provincial_teacher_count, 0)) AS provincial_total,
    SUM(COALESCE(sef_city_municipal_teacher_count, 0)) AS city_municipal_total,
    SUM(COALESCE(lgu_funded_teacher_count, 0)) AS lgu_total,
    SUM(COALESCE(other_funded_teacher_count, 0)) AS other_total,
    COUNT_IF(teacher_count IS NULL) AS all_null_rows
  FROM edu_access.`05-gold`.fact_school_teacher_capacity_candidate
  GROUP BY education_level_code
), reconciliation AS (
  SELECT COALESCE(COUNT_IF(EXISTS (SELECT 1 FROM source) AND (a.education_level_code IS NULL OR e.teacher_total <> a.teacher_total OR e.provincial_total <> a.provincial_total OR e.city_municipal_total <> a.city_municipal_total OR e.lgu_total <> a.lgu_total OR e.other_total <> a.other_total OR e.all_null_rows <> a.all_null_rows)), 0) AS mismatched_level_totals,
    COALESCE(SUM(e.partial_rows), 0) AS partially_reported_rows
  FROM expected AS e
  LEFT JOIN actual AS a USING (education_level_code)
), fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_school_teacher_capacity_candidate
)
SELECT
  (SELECT COUNT(*) * 3 FROM source) AS expected_rows,
  (SELECT COUNT(*) FROM fact) AS fact_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT (school_id, school_year, education_level_code)) FROM fact) AS duplicate_keys,
  (SELECT COALESCE(COUNT_IF(school_id IS NULL OR school_year IS NULL OR education_level_code IS NULL), 0) FROM fact) AS null_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school AS d ON d.school_id = f.school_id WHERE d.school_id IS NULL) AS missing_school_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school_year AS d ON d.school_year = f.school_year WHERE d.school_year IS NULL) AS missing_school_year_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_education_level AS d ON d.education_level_code = f.education_level_code WHERE d.education_level_code IS NULL) AS missing_level_keys,
  (SELECT mismatched_level_totals FROM reconciliation) AS mismatched_level_totals,
  (SELECT mismatched_rows FROM row_reconciliation) AS mismatched_rows,
  (SELECT offered_levels_without_teachers FROM row_reconciliation) AS offered_levels_without_teachers,
  (SELECT partially_reported_rows FROM reconciliation) AS partially_reported_rows,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`03-silver`.deped_enrollment_clean AS e ON e.school_id = f.school_id AND e.school_year = f.school_year) AS enrollment_join_rows,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`03-silver`.deped_enrollment_clean AS e ON e.school_id = f.school_id AND e.school_year = f.school_year WHERE e.school_id IS NULL) AS missing_enrollment_rows,
  (SELECT COALESCE(COUNT_IF(teacher_count < 0 OR sef_provincial_teacher_count < 0 OR sef_city_municipal_teacher_count < 0 OR lgu_funded_teacher_count < 0 OR other_funded_teacher_count < 0), 0) FROM fact) AS negative_measures,
  (SELECT COALESCE(COUNT_IF(teacher_count = 0), 0) FROM fact) AS zero_denominators;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_school_teacher_capacity', 'gold', 'edu_access.05-gold.fact_school_teacher_capacity', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN fact_rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(expected_rows AS STRING) AS expected, CAST(fact_rows AS STRING) AS actual FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'grain_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'school_fk_resolves', CASE WHEN missing_school_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_school_keys AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'school_year_fk_resolves', CASE WHEN missing_school_year_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_school_year_keys AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'education_level_fk_resolves', CASE WHEN missing_level_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_level_keys AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'source_totals_and_nulls_reconcile', CASE WHEN mismatched_level_totals = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(mismatched_level_totals AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'source_rows_reconcile', CASE WHEN mismatched_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(mismatched_rows AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'enrollment_join_adds_no_rows', CASE WHEN enrollment_join_rows = fact_rows THEN 'PASS' ELSE 'FAIL' END, CAST(fact_rows AS STRING), CAST(enrollment_join_rows AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'every_capacity_school_has_enrollment', CASE WHEN missing_enrollment_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_enrollment_rows AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'measures_nonnegative', CASE WHEN negative_measures = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_measures AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'offered_levels_without_teacher_data', CASE WHEN offered_levels_without_teachers = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(offered_levels_without_teachers AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'partial_teacher_reporting', 'PASS', 'informational', CAST(partially_reported_rows AS STRING) FROM fact_school_teacher_capacity_gate_summary
  UNION ALL SELECT 'zero_teacher_denominators', CASE WHEN zero_denominators = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(zero_denominators AS STRING) FROM fact_school_teacher_capacity_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_teacher_capacity: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_teacher_capacity' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_teacher_capacity USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_school_teacher_capacity_candidate;

ALTER TABLE edu_access.`05-gold`.fact_school_teacher_capacity OWNER TO `reached-hq`;
