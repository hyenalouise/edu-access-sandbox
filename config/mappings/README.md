# Reviewed mappings

Store reviewed category mappings and manual cross-source overrides here when
Silver or Integration needs them. Every override must name its source value,
target value, evidence, rationale, and reviewer. Do not hide matching rules in
SQL case expressions or silently force ambiguous records to a target.

| File | Used by | What it maps |
|---|---|---|
| `deped_enrollment.json` | Silver (`src/silver/`) | Column classification and renames, every accepted label of the category and boolean columns with its standard value and evidence, character repairs, placeholders, and the overseas markers (D-022, D-023) |
| `deped_facilities.json` | Silver (`src/silver/deped_facilities.py`, named by its `generator` key) | Column classification: count groups with a plausible maximum each, the facility yes/no column pattern, every accepted label of `sector` and `school_management` (enrollment's standard sets), overseas markers, public scope, the missing-classroom flag, level prefixes, and the enrollment reference (D-038) |
| `psa_poverty_stat.json` | Silver (`src/silver/psa_poverty_stat.py`, named by its `generator` key) | Grain and unpivot, identifier padding and Correspondence Code, text columns, region banner context, the five measures and their numeric pattern, bounds, statistical flag thresholds, and the quarantine threshold (D-034) |

The source owner named in the file approves a change in a pull request; the
Silver SQL is then regenerated ([Silver, Changing a rule](../../docs/operations/silver.md#changing-a-rule-or-approving-a-label)).
A label that is not listed fails the Silver gate.
