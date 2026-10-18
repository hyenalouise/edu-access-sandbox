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
Source and matched geography, method, status, reason, PSGC version, and lineage
are retained.

To keep the SQL practical on a small serverless warehouse, it normalizes and
matches each distinct (`province`, `municipality`, `barangay`) tuple once, then
joins the decision back to school-year rows. It does not form a school-by-PSGC
cross product. The generator and committed SQL must agree:

```bash
python -m src.integration.deped_school_psgc sql > etl/04_integration/01_map_deped_school_psgc.sql
python -m src.integration.deped_school_psgc gate > etl/04_integration/90_validate_deped_school_psgc_map.sql
```

The gate fails on row loss or multiplication, repeated keys, missing levels,
invalid status/method combinations, a matched code absent from the master PSGC
quarter, a wrong PSGC level, a barangay outside the accepted city, mixed PSGC
versions, incomplete lineage, or rows from another run. Unmatched, ambiguous,
excluded, and pending-review counts are WARN; match rates are recorded per
school year and geographic level.

Local made-up validation is in
`tests/test_integration_deped_school_psgc.py`. A real-data reconciliation and
two Databricks `dev` runs are still required before this draft is ready to
merge.
