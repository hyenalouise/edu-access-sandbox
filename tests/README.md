# Tests

Run the complete local suite from the repository root:

```bash
python -m pytest tests -q
```

| Location | Purpose |
|---|---|
| `factories/` | Python builders that create deterministic, made-up inputs in temporary directories |
| `data/` | Small static, made-up files when a factory is not practical |
| `test_repo_policy.py` | Data, secret, environment, and file-size rules |
| `test_documentation_structure.py` | Required indexes, retired paths, and local Markdown links |
| `test_naming.py` | Naming configuration and ETL path conventions |
| `test_analytics_priority.py` | AP1–AP4 outputs, D-057 priority tiers, and D-059 AP2/AP3 benchmark values and classifications |
| `test_ingestion_*.py` | Delivery validation, loading, rerun, and source-specific behavior |
| `test_silver.py` | DepEd enrollment Silver: cleaning rules, quarantine, the gate, the run record, revisions, and the generated SQL |
| `test_silver_facilities.py` | DepEd facilities Silver on made-up deliveries with matching enrollment: typed counts and yes/no columns, blanks kept NULL, enrollment's labels, overseas, public-scope and missing-classroom flags, per-group maximums, quarantine, the enrollment reference, scope warnings, every gate check, revisions, publishing, and the rules file |
| `test_silver_psa.py` | PSA Poverty Stat Silver on made-up workbooks: unpivot, ID padding, region banners, NULL and `no_estimate`, full-precision numbers, statistical flags, quarantine, every gate check, revisions and new years, repeated rebuilds, the run record, and the generated files |
| `test_silver_personnel.py` | Personnel Silver typing, blank-versus-zero retention, standardized labels, principal-total flag, quarantine, reconciliation, and every gate check |
| `test_fan_in.py` | The source-lane fan-in: the committed `90_validate_control.sql` equals what `src/job/fan_in.py` generates, it checks exactly the Silver lanes switched on, and the generator refuses a fan-in that misses or adds a lane |
| `test_integration_hdx.py` | HDX ADM3 → PSGC crosswalk: every rule of #74, overrides, the gate, and the generated files |
| `test_integration_poverty.py` | PSA poverty → PSGC map: the `Correspondence Code` rule, names compared but not matched, Manila's districts, estimates unchanged, coverage counts, a tampered candidate failing the gate and keeping the published map, and the job tasks |
| `test_integration_school_age.py` | PSA school-age population → PSGC map: parents, name tiers, overrides per census year, the gate (population adds up), and the generated files |
| `test_silver_hdx.py` | HDX ADM3 Silver: exact typing, geometry checks (DuckDB spatial), quarantine, flags, the gate, and the generated files |
| `test_integration_deped_school_psgc.py` | DepEd school/year → PSGC city and barangay map on made-up units, one school per branch of the reviewed rule (`test_deped_school_psgc_rule.py`): code versus name, the barangay check on a disagreement, `rollup`, `code_region_moved` only for a recoded code, Special Geographic Area schools by code and by every listed spelling, the inside-the-city check, aliases, old and truncated names, repeated names, Maguindanao, the NCR scope and the Isabela province (each with a namesake only the rule separates), a barangay code missing from the PSGC, overrides and their review status, overseas rows; and the gate: targeted FAIL mutations preserve the last published map, including exact source-key membership, the configured master PSGC version, and value or lineage changes that keep counts and formats (enrollment fields, crosswalk lineage, PSGC fields, review and override fields), plus the match-rate floor, profiled counts, override warnings, and refused rules |
| `test_deped_school_psgc_rule.py` | The proposed #91 DepEd school-to-PSGC rule on made-up units: code versus name, the barangay check on a disagreement, `rollup`, `code_region_moved`, Special Geographic Area schools, the inside-the-city check (overrides included), the Signal Village override, unknown name tiers, and every method listed in D-029 |
| `test_bundle.py`, `test_databricks_runtime.py` | The job's commit tracking and task order, and the Databricks runtime differences imitated locally |

Tests must never depend on real source rows or credentials.
