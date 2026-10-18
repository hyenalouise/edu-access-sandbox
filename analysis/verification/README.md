# Verification

Local checks of a built layer on the real, checksum-verified data. They print counts and hashes, never row values, for an evidence record under `evidence/`, and write only under `local_state/` (git-ignored). They are not job tasks. Most run the job's real tasks on a fresh DuckDB file; a source-totals program instead reads the published file on its own, without the pipeline, so a layer's totals can be checked against it.

| Program | What it checks |
|---|---|
| `psa_poverty_stat_silver.py` | The PSA Poverty Stat lane twice: Bronze rows by kind, candidates, clean and quarantined per estimate year, missing estimates, warning flags, the Silver gate, lineage, task timings, and the business-content hash of each rebuild ([Silver, PSA Poverty Stat](../../docs/operations/silver.md#running-locally-psa)) |
| `hdx_adm3_psgc_map.py` | The HDX ADM3 → PSGC crosswalk on a local DuckDB holding both Silver tables: the gate's results, counts by status and method, and the features that need review, written to `local_state/` for writing overrides (#93, D-052) |
| `deped_facilities_source_totals.py` | The four totals the facilities Silver gate reconciles (sum of all counts, `True` values, blank counts, blank yes/no), computed from the published CSV with the standard library only, after checking the zip's and CSV's SHA-256 against the contract; compared with the gate's values ([evidence](../../evidence/reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md)) |
