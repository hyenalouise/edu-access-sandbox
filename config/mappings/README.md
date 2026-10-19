# Reviewed mappings

Store reviewed category mappings and manual cross-source overrides here when
Silver or Integration needs them. Every override must name its source value,
target value, evidence, rationale, and reviewer. Do not hide matching rules in
SQL case expressions or silently force ambiguous records to a target.

| File | Used by | What it maps |
|---|---|---|
| `deped_enrollment.json` | Silver (`src/silver/`) | Column classification and renames, every accepted label of the category and boolean columns with its standard value and evidence, character repairs, placeholders, and the overseas markers (D-022, D-023) |
| `deped_personnel.json` | Silver (`src/silver/deped_personnel.py`, named by its `generator` key) | Nullable integer measures, standard category labels, public-school scope, principal-total comparison, and the all-blank field (D-041) |
| `psa_psgc.json` | Silver (`src/silver/psa_psgc.py`, named by its `generator` key) | Identifier and correspondence code, text columns and the column J rename, population and its `#N/A` marker, the income class split, every accepted label of the four category columns, the derived parent codes, the quarantine threshold, evidence for each, and the open decisions (D-035) |
| `deped_facilities.json` | Silver (`src/silver/deped_facilities.py`, named by its `generator` key) | Column classification: count groups with a plausible maximum each, the facility yes/no column pattern, every accepted label of `sector` and `school_management` (enrollment's standard sets), overseas markers, public scope, the missing-classroom flag, level prefixes, and where location comes from (D-038) |
| `deped_enrollment_psgc.json` | Silver (`src/silver/deped_enrollment_psgc.py`, named by its `generator` key) | The school-to-PSGC crosswalk: which Bronze row kind is read, the code columns and their padding, the null markers and their reasons, the Sulu recode, the coordinate pattern and box, the published text kept, the quarantine threshold, and the profiled counts the gate records (D-049) |
| `psa_school_age_population.json` | Silver (`src/silver/psa_school_age_population.py`, named by its `generator` key) | Grain, the sex of each wide band and long row, structural row kinds, the place-label rules (footnote marker, `(Capital)`, old names), how levels and parents come from the sums, the level counts pinned for each approved workbook, and the count pattern (D-053) |
| `psa_poverty_stat.json` | Silver (`src/silver/psa_poverty_stat.py`, named by its `generator` key) | Grain and unpivot, identifier padding and Correspondence Code, text columns, region banner context, the five measures and their numeric pattern, bounds, statistical flag thresholds, and the quarantine threshold (D-034) |
| `integration/deped_school_psgc.json` | Integration (`etl/04_integration/01_map_deped_school_psgc.sql`, reading `deped_enrollment_psgc_clean` (#169), not written yet); written now in `analysis/cross_source/cross_source_deped_school_psgc_rule.py` and applied by `cross_source_deped_enrollment_psgc.py`; the file's `rule_order` describes that code and changes with it | The order in which a DepEd school's EMISD PSGC code and its name match are accepted, how name tiers map to D-029 `match_method` values, and reviewed place overrides with their evidence (#91, #137 Option B). Approved in PR #153; the Integration SQL is not written yet |

The source owner named in the file approves a change in a pull request; the
Silver SQL is then regenerated ([Silver, Changing a rule](../../docs/operations/silver.md#changing-a-rule-or-approving-a-label)).
A label that is not listed fails the Silver gate.

Integration rules and overrides live in `integration/`, so the Silver tests, which treat every top-level file here as a Silver mapping, do not read them.
