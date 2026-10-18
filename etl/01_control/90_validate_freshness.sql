-- Source freshness. Generated from databricks.yml and config/freshness.yml:
--   python -m src.job.freshness > etl/01_control/90_validate_freshness.sql
-- Do not edit by hand; tests/test_freshness.py fails if it differs.
--
-- Runs once the fan-in has finished, passed or not (run_if: ALL_DONE), after every Bronze load, so every run
-- records one result per loaded source in data_quality_results (layer 'control'): PASS when the
-- source's latest succeeded batch in current_batches succeeded within its limit, WARN when it is older
-- or the source has none. It never fails the task: stale data is still correct, only possibly out of
-- date. The stale-source alert in databricks.yml reports the WARN rows (D-043). Limits, with their basis:
--   deped_enrollment             400 days  Annual (source card); SY 2025-26 was added 2026-07-23
--   deped_facilities             400 days  Collected annually (Technical Notes p. 3); only one year published so far
--   deped_personnel              400 days  Annual BEIS collection (Technical Notes p. 3); publication timing unverified
--   psa_psgc                     120 days  Quarterly (Metadata sheet). The master reference stays 2Q 2026 (D-012); a WARN means a newer quarter is likely out and the owner decides whether to load it
--   psa_poverty_stat            1125 days  Small area estimates about every three years (2018, 2021, 2023); the 2023 estimates were released 6 Feb 2026, PSA press release 2026-43
--   hdx_boundaries               395 days  Every year (HDX expected update frequency); HDX lists the dataset past its 2025-04-01 due date, and the 2026-05 files keep the 2018 boundaries (version 03, reviewed 2024-04-01)
--   deped_enrollment_psgc        400 days  One school year (SY 2023-24), sent by DepEd EMISD on request (2026-10-14); no publication schedule is known, so the DepEd annual limit is used. A WARN means it is time to ask EMISD for a newer file
--   psa_school_age_population   1856 days  Census years only (2020 CPH, 2024 POPCEN), received from PSA on request (2026-10-15); PSA counts the population about every five years, so five years plus a month
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id           the job run
--   :code_revision    the commit that ran, from the job parameter; never a literal
--   :freshness_as_of  blank to check as of now; a UTC timestamp to check as of that time instead
--                     (how the stale-source alert is tested); text that is not a timestamp fails

DECLARE OR REPLACE VARIABLE freshness_as_of_utc TIMESTAMP;
SET VARIABLE freshness_as_of_utc = CASE WHEN TRIM(:freshness_as_of) = '' THEN current_timestamp()
                                        ELSE CAST(:freshness_as_of AS TIMESTAMP) END;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), l.source_id, 'control', 'edu_access.01-control.current_batches', 'source_fresh',
       CASE WHEN b.last_succeeded_at_utc >= session.freshness_as_of_utc - l.max_age THEN 'PASS' ELSE 'WARN' END,
       'succeeded within ' || CAST(l.max_age_days AS STRING) || ' days of '
         || CAST(CAST(session.freshness_as_of_utc AS DATE) AS STRING),
       CASE WHEN b.last_succeeded_at_utc IS NULL THEN 'no succeeded batch'
            ELSE 'last succeeded ' || CAST(CAST(b.last_succeeded_at_utc AS DATE) AS STRING) END,
       current_timestamp(), :code_revision
FROM (VALUES ('deped_enrollment', 400, INTERVAL '400' DAY),
       ('deped_facilities', 400, INTERVAL '400' DAY),
       ('deped_personnel', 400, INTERVAL '400' DAY),
       ('psa_psgc', 120, INTERVAL '120' DAY),
       ('psa_poverty_stat', 1125, INTERVAL '1125' DAY),
       ('hdx_boundaries', 395, INTERVAL '395' DAY),
       ('deped_enrollment_psgc', 400, INTERVAL '400' DAY),
       ('psa_school_age_population', 1856, INTERVAL '1856' DAY)) AS l(source_id, max_age_days, max_age)
LEFT JOIN (
  SELECT source_id, MAX(succeeded_at_utc) AS last_succeeded_at_utc
  FROM edu_access.`01-control`.current_batches
  GROUP BY source_id
) AS b ON b.source_id = l.source_id;
