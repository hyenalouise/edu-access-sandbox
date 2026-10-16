# DepEd annex-to-mother school link

## Finding

**Observed:** none of the three checksum-verified DepEd enrollment releases acquired by the project publishes a mother-school ID. Their only annex field is `annex_status`. The releases identify 843 annexes in SY 2023-24, 758 in SY 2024-25, and 730 in SY 2025-26 (AN-1), or 2,331 annex-school years in total. Of these, 2,091 are public-school annex years in scope for AP2 and AP3. The remaining 240 private or SUC/LUC records stay in the source-complete map but are excluded from those public-school measures.

DepEd's [2014 Government Elementary School Profile form](https://www.deped.gov.ph/wp-content/uploads/2014/08/DO_s2014_036.pdf) asks an annex to provide its six-digit mother-school ID. This shows that DepEd collects the relationship, but the form is not a published school-year crosswalk and cannot supply the missing links. The public [EBEIS school masterlist](https://ebeis.deped.gov.ph/beis/reports_info/masterlist) exposes school lookup fields but no complete annex-to-mother mapping. A school-name rule was rejected because names do not provide a unique, reviewed identifier and can describe former relationships.

## Decision for issue #102

`deped_annex_mother_map` lists one row for every annex school and school year. Until a reliable source is supplied, every row has `match_status = unmatched`, a NULL `mother_school_id`, a NULL `match_method`, and evidence `deped_enrollment_annex_status_only`. The generated [unmatched list](generated/deped_annexes_without_mother.md) records every affected school-year key.

No learner, classroom, or personnel value is consolidated. Their totals therefore remain exactly as published, but AP2 and AP3 must stay provisional because they do not yet follow DepEd's annex-consolidated method. The public-school scope is applied when those measures are built, while this mapping retains every annex record so the Integration total reconciles to Silver. When a reliable crosswalk becomes available, it must be checked for year, uniqueness, and source evidence before any mother-school ID is populated; the validation gate must then add explicit before-and-after total checks.

## Reproduce

Run locally against the checksum-approved public releases:

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/cross_source/cross_source_deped_annex.py
```

The script verifies each archive SHA-256, reports AN-1, and regenerates the unmatched list as AN-2. It reads raw files without modifying them and uses no Databricks compute.
