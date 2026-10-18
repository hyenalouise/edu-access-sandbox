# Integration

Integration builds governed crosswalks from published Silver tables. A build
writes a candidate table; its following gate records `integration` results in
`data_quality_results` and publishes only when every structural check passes.
The last good published map therefore survives a failed build.

## DepEd school geography

`deped_school_psgc_map` has one row per (`school_year`, `school_id`,
`geographic_level`), where the level is `city_mun` or `bgy`. Every enrollment
row receives both levels. Overseas, unmatched, ambiguous, and excluded rows
remain in the map with a null `psgc_code`; they are never silently removed.

The map reads `deped_enrollment_clean`, `deped_enrollment_psgc_clean`, and the
master quarter of `psa_psgc_clean`. Matching follows D-049 and the reviewed
rules in `config/mappings/integration/deped_school_psgc.json`: EMISD code,
reviewed name matching, reviewed override, then an explicit unresolved status.
Source and matched geography, method, status, reason (the wording of the
reviewed rule, PR #153), PSGC version, `source_reference_date` (the school
year), and lineage are retained.

The EMISD crosswalk is keyed on SY 2023-24 school IDs and is applied to every
school year by `school_id` (D-049). Special Geographic Area schools (D-031) are
found by the province spellings listed in the rules file and by an EMISD code
in a Special Geographic Area municipality (`19999`), because SY 2020-21 files
them under Region XII and SY 2024-25 adds `(SGA - North Cotabato)`. An override
that finds no unit, like every row that is not matched, stays `pending`. Only
barangay overrides are applied; the generator refuses a `city_mun` override.

To keep the SQL practical on a small serverless warehouse, it matches cities
once per distinct (`province`, `municipality`) pair (1,653 on the real
deliveries) and barangays once per distinct place inside the named city, then
joins the decisions back to school-year rows. It does not form a school-by-PSGC
cross product. The generator and committed SQL must agree:

```bash
python -m src.integration.deped_school_psgc sql > etl/04_integration/01_map_deped_school_psgc.sql
python -m src.integration.deped_school_psgc gate > etl/04_integration/90_validate_deped_school_psgc_map.sql
```

The gate fails on row loss or multiplication, repeated keys, missing levels,
invalid status/method combinations, a matched code absent from the master PSGC
quarter, a wrong PSGC level, a barangay outside the accepted city, mixed PSGC
versions, incomplete lineage, rows from another run, or a match rate (matched
over rows not excluded) below the rules file's `gate.min_match_rate_pct`
(99.0) for any school year and level. It compares matched / ambiguous /
unmatched / excluded per school year and level with `gate.profiled_counts`:
PASS at those counts, WARN when they change, so a new delivery or rule change
is reviewed and the counts updated in its pull request. Unmatched, ambiguous,
excluded, pending-review, overrides that find no unit, and overrides that match
no school are WARN.

Local made-up validation is in `tests/test_integration_deped_school_psgc.py`:
one school per branch of the reviewed rule, and a negative test for each FAIL
check. The real-data reconciliation is
[evidence/reconciliation/2026-10-19-deped-school-psgc-integration.md](../../evidence/reconciliation/2026-10-19-deped-school-psgc-integration.md).
Two Databricks `dev` runs are still required before this draft is ready to
merge.
