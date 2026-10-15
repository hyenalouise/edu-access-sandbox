# 04 Integration

Matching across sources: DepEd place names to PSGC codes, and other sources to the shared geography.

The first implemented map is `deped_annex_mother_map`, one row per annex school
and school year. The acquired DepEd releases identify annexes but do not include
their mother-school IDs, so every current row is retained as `unmatched` with
evidence and lineage. The validation gate records the unmatched count and fails
if an annex is dropped, duplicated, or represented inconsistently. No totals are
consolidated until a reliable crosswalk is reviewed (D-044).

The remaining candidate mapping names are documented as drafts in the
[ETL table registry](../../docs/standards/tables.md); they are not reserved until
keys, grains, and review rules are approved. Files follow
`NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see
[File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
