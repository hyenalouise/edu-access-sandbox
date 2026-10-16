CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_classroom_capacity USING DELTA AS
SELECT
  school_id,
  school_year,
  CASE
    WHEN es_classrooms_instructional IS NULL AND jhs_classrooms_instructional IS NULL AND shs_classrooms_instructional IS NULL THEN NULL
    ELSE COALESCE(es_classrooms_instructional, 0) + COALESCE(jhs_classrooms_instructional, 0) + COALESCE(shs_classrooms_instructional, 0)
  END AS instructional_classrooms_total,
  CASE
    WHEN es_temporary_learning_spaces IS NULL AND hs_temporary_learning_spaces IS NULL THEN NULL
    ELSE COALESCE(es_temporary_learning_spaces, 0) + COALESCE(hs_temporary_learning_spaces, 0)
  END AS temporary_learning_spaces,
  CASE
    WHEN es_classes_using_temporary_learning_spaces IS NULL AND hs_classes_using_temporary_learning_spaces IS NULL THEN NULL
    ELSE COALESCE(es_classes_using_temporary_learning_spaces, 0) + COALESCE(hs_classes_using_temporary_learning_spaces, 0)
  END AS classes_using_temporary_learning_spaces,
  CASE
    WHEN es_makeshift_rooms IS NULL AND hs_makeshift_rooms IS NULL THEN NULL
    ELSE COALESCE(es_makeshift_rooms, 0) + COALESCE(hs_makeshift_rooms, 0)
  END AS makeshift_rooms,
  CASE
    WHEN es_classes_using_makeshift_rooms IS NULL AND hs_classes_using_makeshift_rooms IS NULL THEN NULL
    ELSE COALESCE(es_classes_using_makeshift_rooms, 0) + COALESCE(hs_classes_using_makeshift_rooms, 0)
  END AS classes_using_makeshift_rooms
FROM edu_access.`03-silver`.deped_facilities_clean
WHERE sector = 'Public';

ALTER TABLE edu_access.`05-gold`.fact_school_classroom_capacity OWNER TO `reached-hq`;
