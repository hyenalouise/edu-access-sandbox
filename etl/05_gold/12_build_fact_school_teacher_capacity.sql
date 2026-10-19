CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_teacher_capacity_candidate USING DELTA AS
WITH public_personnel AS (
  SELECT * FROM edu_access.`03-silver`.deped_personnel_clean WHERE sector = 'Public'
), level_rows AS (
  SELECT
    school_id,
    school_year,
    'ES' AS education_level_code,
    CASE WHEN
      es_teacher_i IS NULL AND es_teacher_ii IS NULL AND es_teacher_iii IS NULL
      AND es_master_teacher_i IS NULL AND es_master_teacher_ii IS NULL AND es_master_teacher_iii IS NULL AND es_master_teacher_iv IS NULL
      AND es_head_teacher_i IS NULL AND es_head_teacher_ii IS NULL AND es_head_teacher_iii IS NULL AND es_head_teacher_iv IS NULL AND es_head_teacher_v IS NULL AND es_head_teacher_vi IS NULL
      AND es_sped_sned_teacher_i IS NULL AND es_sped_sned_teacher_ii IS NULL AND es_sped_sned_teacher_iii IS NULL AND es_sped_sned_teacher_iv IS NULL AND es_sped_sned_teacher_v IS NULL
      AND kinder_teachers_sef_province IS NULL AND kinder_teachers_sef_municipality_city IS NULL AND kinder_teachers_lgu_funding IS NULL AND kinder_teachers_other_funding IS NULL
      AND es_teachers_sef_province IS NULL AND es_teachers_sef_municipality_city IS NULL AND es_teachers_lgu_funding IS NULL AND es_teachers_other_funding IS NULL
    THEN NULL ELSE
      COALESCE(es_teacher_i, 0) + COALESCE(es_teacher_ii, 0) + COALESCE(es_teacher_iii, 0)
      + COALESCE(es_master_teacher_i, 0) + COALESCE(es_master_teacher_ii, 0) + COALESCE(es_master_teacher_iii, 0) + COALESCE(es_master_teacher_iv, 0)
      + COALESCE(es_head_teacher_i, 0) + COALESCE(es_head_teacher_ii, 0) + COALESCE(es_head_teacher_iii, 0) + COALESCE(es_head_teacher_iv, 0) + COALESCE(es_head_teacher_v, 0) + COALESCE(es_head_teacher_vi, 0)
      + COALESCE(es_sped_sned_teacher_i, 0) + COALESCE(es_sped_sned_teacher_ii, 0) + COALESCE(es_sped_sned_teacher_iii, 0) + COALESCE(es_sped_sned_teacher_iv, 0) + COALESCE(es_sped_sned_teacher_v, 0)
      + COALESCE(kinder_teachers_sef_province, 0) + COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(kinder_teachers_other_funding, 0)
      + COALESCE(es_teachers_sef_province, 0) + COALESCE(es_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_lgu_funding, 0) + COALESCE(es_teachers_other_funding, 0)
    END AS teacher_count,
    CASE WHEN kinder_teachers_sef_province IS NULL AND es_teachers_sef_province IS NULL THEN NULL ELSE COALESCE(kinder_teachers_sef_province, 0) + COALESCE(es_teachers_sef_province, 0) END AS sef_provincial_teacher_count,
    CASE WHEN kinder_teachers_sef_municipality_city IS NULL AND es_teachers_sef_municipality_city IS NULL THEN NULL ELSE COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_sef_municipality_city, 0) END AS sef_city_municipal_teacher_count,
    CASE WHEN kinder_teachers_lgu_funding IS NULL AND es_teachers_lgu_funding IS NULL THEN NULL ELSE COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(es_teachers_lgu_funding, 0) END AS lgu_funded_teacher_count,
    CASE WHEN kinder_teachers_other_funding IS NULL AND es_teachers_other_funding IS NULL THEN NULL ELSE COALESCE(kinder_teachers_other_funding, 0) + COALESCE(es_teachers_other_funding, 0) END AS other_funded_teacher_count
  FROM public_personnel

  UNION ALL

  SELECT
    school_id,
    school_year,
    'JHS' AS education_level_code,
    CASE WHEN
      jhs_teacher_i IS NULL AND jhs_teacher_ii IS NULL AND jhs_teacher_iii IS NULL
      AND jhs_master_teacher_i IS NULL AND jhs_master_teacher_ii IS NULL AND jhs_master_teacher_iii IS NULL AND jhs_master_teacher_iv IS NULL
      AND jhs_head_teacher_i IS NULL AND jhs_head_teacher_ii IS NULL AND jhs_head_teacher_iii IS NULL AND jhs_head_teacher_iv IS NULL AND jhs_head_teacher_v IS NULL AND jhs_head_teacher_vi IS NULL
      AND jhs_sped_teacher_i IS NULL AND jhs_sped_teacher_ii IS NULL AND jhs_sped_teacher_iii IS NULL AND jhs_sped_teacher_iv IS NULL AND jhs_sped_teacher_v IS NULL
      AND jhs_special_science_teacher_i IS NULL
      AND jhs_instructor_i IS NULL AND jhs_instructor_ii IS NULL AND jhs_instructor_iii IS NULL
      AND jhs_teachers_sef_province IS NULL AND jhs_teachers_sef_municipality_city IS NULL AND jhs_teachers_lgu_funding IS NULL AND jhs_teachers_other_funding IS NULL
    THEN NULL ELSE
      COALESCE(jhs_teacher_i, 0) + COALESCE(jhs_teacher_ii, 0) + COALESCE(jhs_teacher_iii, 0)
      + COALESCE(jhs_master_teacher_i, 0) + COALESCE(jhs_master_teacher_ii, 0) + COALESCE(jhs_master_teacher_iii, 0) + COALESCE(jhs_master_teacher_iv, 0)
      + COALESCE(jhs_head_teacher_i, 0) + COALESCE(jhs_head_teacher_ii, 0) + COALESCE(jhs_head_teacher_iii, 0) + COALESCE(jhs_head_teacher_iv, 0) + COALESCE(jhs_head_teacher_v, 0) + COALESCE(jhs_head_teacher_vi, 0)
      + COALESCE(jhs_sped_teacher_i, 0) + COALESCE(jhs_sped_teacher_ii, 0) + COALESCE(jhs_sped_teacher_iii, 0) + COALESCE(jhs_sped_teacher_iv, 0) + COALESCE(jhs_sped_teacher_v, 0)
      + COALESCE(jhs_special_science_teacher_i, 0)
      + COALESCE(jhs_instructor_i, 0) + COALESCE(jhs_instructor_ii, 0) + COALESCE(jhs_instructor_iii, 0)
      + COALESCE(jhs_teachers_sef_province, 0) + COALESCE(jhs_teachers_sef_municipality_city, 0) + COALESCE(jhs_teachers_lgu_funding, 0) + COALESCE(jhs_teachers_other_funding, 0)
    END AS teacher_count,
    jhs_teachers_sef_province AS sef_provincial_teacher_count,
    jhs_teachers_sef_municipality_city AS sef_city_municipal_teacher_count,
    jhs_teachers_lgu_funding AS lgu_funded_teacher_count,
    jhs_teachers_other_funding AS other_funded_teacher_count
  FROM public_personnel

  UNION ALL

  SELECT
    school_id,
    school_year,
    'SHS' AS education_level_code,
    CASE WHEN
      shs_teacher_i IS NULL AND shs_teacher_ii IS NULL AND shs_teacher_iii IS NULL
      AND shs_master_teacher_i IS NULL AND shs_master_teacher_ii IS NULL AND shs_master_teacher_iii IS NULL AND shs_master_teacher_iv IS NULL
      AND shs_head_teacher_i IS NULL AND shs_head_teacher_ii IS NULL AND shs_head_teacher_iii IS NULL AND shs_head_teacher_iv IS NULL AND shs_head_teacher_v IS NULL AND shs_head_teacher_vi IS NULL
      AND shs_special_science_teacher_i IS NULL
      AND shs_teachers_sef_province IS NULL AND shs_teachers_sef_municipality_city IS NULL AND shs_teachers_lgu_funding IS NULL AND shs_teachers_other_funding IS NULL
    THEN NULL ELSE
      COALESCE(shs_teacher_i, 0) + COALESCE(shs_teacher_ii, 0) + COALESCE(shs_teacher_iii, 0)
      + COALESCE(shs_master_teacher_i, 0) + COALESCE(shs_master_teacher_ii, 0) + COALESCE(shs_master_teacher_iii, 0) + COALESCE(shs_master_teacher_iv, 0)
      + COALESCE(shs_head_teacher_i, 0) + COALESCE(shs_head_teacher_ii, 0) + COALESCE(shs_head_teacher_iii, 0) + COALESCE(shs_head_teacher_iv, 0) + COALESCE(shs_head_teacher_v, 0) + COALESCE(shs_head_teacher_vi, 0)
      + COALESCE(shs_special_science_teacher_i, 0)
      + COALESCE(shs_teachers_sef_province, 0) + COALESCE(shs_teachers_sef_municipality_city, 0) + COALESCE(shs_teachers_lgu_funding, 0) + COALESCE(shs_teachers_other_funding, 0)
    END AS teacher_count,
    shs_teachers_sef_province AS sef_provincial_teacher_count,
    shs_teachers_sef_municipality_city AS sef_city_municipal_teacher_count,
    shs_teachers_lgu_funding AS lgu_funded_teacher_count,
    shs_teachers_other_funding AS other_funded_teacher_count
  FROM public_personnel
)
SELECT * FROM level_rows;

ALTER TABLE edu_access.`05-gold`.fact_school_teacher_capacity_candidate OWNER TO `reached-hq`;
