# Cross-source analysis

Scripts that test joins, geographic coverage, and year-to-year comparability across sources, named `cross_source_<subject>.py`. Most compare a source with PSGC 2Q 2026.

| Script | Checks | Writes |
|---|---|---|
| `cross_source_deped.py` | DepEd SY 2023-24 place names against PSGC | `generated/deped_psgc_unmatched.md` |
| `cross_source_deped_years.py` | DepEd enrollment across school years: dropped, added, and renamed schools | `generated/deped_year_changes.md` |
| `cross_source_deped_annex.py` | Whether the DepEd releases publish an annex-to-mother link (#102) | `generated/deped_annexes_without_mother.md` |
| `cross_source_deped_enrollment_psgc.py` | EMISD PSGC codes against enrollment place names (#137, #91) | Printed findings |
| `cross_source_deped_school_psgc_rule.py` | The DepEd school-to-PSGC rule as plain functions, run on the real data; tested on made-up units | Printed findings |
| `cross_source_hdx_boundaries.py` | COD-AB ADM3 and ADM4 against PSGC | `generated/hdx_boundaries_psgc_unmatched.md` |
| `cross_source_dti_cmci.py` | CMCI LGU names against PSGC | `generated/dti_cmci_psgc_match.md` |
| `cross_source_psa_population_per_barangay.py` | Barangay population names against PSGC | `generated/psa_population_psgc_unmatched.md` |
| `cross_source_psa_population_per_age_group.py` | Age-group population places against PSGC | Printed findings |
| `cross_source_coverage.py` | Which sources cover which places and years: the coverage matrix | Printed findings |

`generated/` is [`docs/data/cross-source/generated/`](../../docs/data/cross-source/generated/README.md). The memos that use these findings, and how to rerun everything, are in the [cross-source index](../../docs/data/cross-source/README.md).

```bash
export RAW_DATA_DIR=~/Projects/reached-hq/raw-data
python analysis/cross_source/cross_source_deped.py
```
