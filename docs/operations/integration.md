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
An EMISD code with no unit in the master PSGC counts as no code at either
level, as in the reviewed rule, so the name decides; the raw code stays in
`code_candidate`.

Two DepEd naming facts are in the rules file with a reason and evidence:
`province_splits` (`MAGUINDANAO` is searched in Maguindanao del Norte and del
Sur) and `region_scopes` (a province naming `NCR` is searched in region
`1300000000`). The rest is read from PSGC Silver: a blank-level unit at the
province position (`level_blank`, the City of Isabela) can be a DepEd
province, and a barangay whose parent is a sub-municipality belongs to the city
sharing its first five digits, the same rollup used for Manila's districts,
which PSGC Silver gives no parent code.

To keep the SQL practical on a small serverless warehouse, it matches cities
once per distinct (`province`, `municipality`) pair (1,655 on the real
deliveries) and barangays once per distinct place inside the named city, then
joins the decisions back to school-year rows. It does not form a school-by-PSGC
cross product. The generator and committed SQL must agree:

```bash
python -m src.integration.deped_school_psgc sql > etl/04_integration/01_map_deped_school_psgc.sql
python -m src.integration.deped_school_psgc gate > etl/04_integration/90_validate_deped_school_psgc_map.sql
```

The gate fails on row loss or multiplication, any missing or extra source key,
repeated keys, missing levels,
invalid status/method combinations, a matched code absent from the master PSGC
quarter, a wrong PSGC level, a barangay outside the accepted city, mixed PSGC
versions, a master PSGC version different from the rules file, incomplete
lineage, rows from another run, any row whose carried values or lineage differ
from the current Silver rows (`enrollment_fields_reconcile`,
`crosswalk_lineage_reconciles`, `psgc_fields_reconcile`), a `review_status` or
override field that does not follow from the match and the rules file
(`review_fields_valid`), or a match rate (matched
over rows not excluded) below the rules file's `gate.min_match_rate_pct`
(99.0) for any school year and level. It compares matched / ambiguous /
unmatched / excluded per school year and level with `gate.profiled_counts`:
PASS at those counts and FAIL before publication when they change, so a new
delivery or rule change is reviewed and the counts updated in its pull request.
Unmatched, ambiguous,
excluded, pending-review, EMISD codes with no master PSGC unit, overrides that
find no unit, and overrides that match no school are WARN.

To review the unresolved schools, list every unmatched and ambiguous row with
the place DepEd gives, the EMISD code, and the reason (the evidence record
quotes the counts):

```sql
SELECT school_year, school_id, school_name, geographic_level, match_status,
       source_province, source_city_municipality, source_barangay, code_candidate, reason
FROM edu_access.`04-integration`.deped_school_psgc_map
WHERE match_status IN ('unmatched', 'ambiguous')
ORDER BY school_id, school_year, geographic_level;
```

Local made-up validation is in `tests/test_integration_deped_school_psgc.py`:
one school per branch of the reviewed rule, plus targeted negative mutations
for the publication-critical gate checks. The real-data reconciliation is
[evidence/reconciliation/2026-10-19-deped-school-psgc-integration.md](../../evidence/reconciliation/2026-10-19-deped-school-psgc-integration.md).
Two Databricks `dev` runs are still required before this draft is ready to
merge.
