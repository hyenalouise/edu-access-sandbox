# 04 Integration

Matching across sources: DepEd place names to PSGC codes, and other sources to the shared geography.

The first implemented map is `deped_annex_mother_map`, one row per annex school
and school year. The acquired DepEd releases identify annexes but do not include
their mother-school IDs, so every current row is retained as `unmatched` with
evidence and lineage. The validation gate records the unmatched count and fails
if an annex is dropped, duplicated, or represented inconsistently. No totals are
consolidated until a reliable crosswalk is reviewed (D-044).

The DepEd school geography spine is `01_map_deped_school_psgc.sql` and
`90_validate_deped_school_psgc_map.sql` (#91, D-049), generated from
`config/mappings/integration/deped_school_psgc.json`. It keeps one row per
enrollment school, school year, and level (`city_mun`, `bgy`), including
unmatched, ambiguous, excluded, and overseas schools. It matches cities once
per distinct (province, municipality) and barangays once per distinct place
before joining decisions back to schools, avoiding a school-by-PSGC cross
product on a small SQL warehouse. Its gate also fails a match rate below the
rules file's floor and warns when the reviewed counts change.

The HDX ADM3 to PSGC map is `03_map_hdx_adm3_psgc.sql` and
`90_validate_hdx_adm3_psgc_map.sql` (#93, D-052), generated from
`config/integration/hdx_adm3_psgc.json` by `python -m src.integration.hdx_adm3_psgc sql|gate`;
`tests/test_integration_hdx.py` fails if they differ.

The PSA poverty to PSGC map is `02_map_psa_poverty_psgc.sql` and
`90_validate_psa_poverty_psgc_map.sql` (#92, D-054), written by hand. One row per
`psa_poverty_stat_clean` row (`psgc_id`, `estimate_year`), matched by `Correspondence Code`
only, with the estimates copied unchanged. Names are compared, never matched; Manila's 14
districts keep their own sub-municipality codes. The gate counts the PSGC cities and
municipalities with no PSA row per estimate year (D-028) and publishes only if no check
fails. Tests: `tests/test_integration_poverty.py`.

The PSA school-age population to PSGC map is
`05_map_psa_school_age_population_psgc.sql` and `90_validate_psa_school_age_population_psgc_map.sql`
(#159, D-055), generated from `config/integration/psa_school_age_population_psgc.json` by
`python -m src.integration.psa_school_age_population_psgc sql|gate`; `tests/test_integration_school_age.py`
fails if they differ. It waits for the school-age population and PSGC Silver gates.

Each map starts from the Silver gates of the sources it reads, not from the
source-lane fan-in (D-051). The DepEd school map waits for the enrollment,
EMISD crosswalk, and PSGC Silver gates, the HDX map for the HDX and PSGC Silver
gates, the poverty map for the poverty and PSGC Silver gates, and the school-age
map for the school-age population and PSGC Silver gates.

The remaining candidate mapping names are documented as drafts in the
[ETL table registry](../../docs/standards/tables.md); they are not reserved until
keys, grains, and review rules are approved. Files follow
`NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see
[File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
