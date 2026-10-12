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
| `freshness.yml` | How old each loaded source's latest succeeded batch may get before the job warns it may be stale, with the basis for each limit (D-043) |

Credentials, workspace tokens, raw source files, and user-specific paths do not
belong here. When executable configuration changes, update its tests and the
canonical documentation in the same pull request.
