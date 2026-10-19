# 04 Integration

Matching across sources: DepEd place names to PSGC codes, and other sources to the shared geography.

The first implemented map is `deped_annex_mother_map`, one row per annex school
and school year. The acquired DepEd releases identify annexes but do not include
their mother-school IDs, so every current row is retained as `unmatched` with
evidence and lineage. The validation gate records the unmatched count and fails
if an annex is dropped, duplicated, or represented inconsistently. No totals are
consolidated until a reliable crosswalk is reviewed (D-044).

The second is the HDX ADM3 to PSGC map: `03_map_hdx_adm3_psgc.sql` and
`90_validate_hdx_adm3_psgc_map.sql` (#93, D-052), generated from
`config/integration/hdx_adm3_psgc.json` by `python -m src.integration.hdx_adm3_psgc sql|gate`;
`tests/test_integration_hdx.py` fails if they differ.

Each map starts from the Silver gates of the sources it reads, not from the
source-lane fan-in (D-051). The other maps are disabled placeholders:
`01_map_deped_school_psgc` (enrollment, the EMISD crosswalk, PSGC),
`02_map_psa_poverty_psgc` (poverty, PSGC), and
`05_map_psa_school_age_population_psgc` (school-age population, PSGC). The HDX
map waits for the HDX and PSGC Silver gates.

The remaining candidate mapping names are documented as drafts in the
[ETL table registry](../../docs/standards/tables.md); they are not reserved until
keys, grains, and review rules are approved. Files follow
`NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see
[File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
