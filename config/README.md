# Configuration

This folder contains non-secret, reviewable project configuration.

| Location | Purpose |
|---|---|
| `project.json` | Workspace, catalog, schema, and storage settings already approved for the project |
| `sources.json` | Source registry and lifecycle status |
| `naming.yml` | Repository and lakehouse naming conventions |
| `tables.yml` | Final Bronze/Silver names and draft Integration candidates |
| `ingestion/` | Source-specific delivery contracts used by Bronze ingestion |
| `mappings/` | Reviewed category maps and manual cross-source overrides |
| `integration/` | Reviewed rules and manual overrides for each PSGC mapping table (D-052) |
| `quality_attributes.yml` | Which data-quality attribute (completeness, validity, ...) each check tests, for the data-quality dashboard only (#97) |
| `analytics_benchmarks.json` | Reviewed source metadata, values, derivations, and caveats for the AP2 and AP3 benchmark interpretations (D-059) |
| `freshness.yml` | How old each loaded source's latest succeeded batch may get before the job warns it may be stale, with the basis for each limit (D-043) |

Credentials, workspace tokens, raw source files, and user-specific paths do not
belong here. When executable configuration changes, update its tests and the
canonical documentation in the same pull request.
