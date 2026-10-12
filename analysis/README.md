# Analysis

Reproducible research programs live here. They read checksum-verified source
files from `RAW_DATA_DIR` and write documentation or compact review artifacts;
they are not production pipeline tasks.

| Folder | Purpose |
|---|---|
| `profiling/` | Inspect one source and generate its profile or data dictionary |
| `cross_source/` | Compare sources, test joinability, and generate exception lists |
| `demo/` | Presentation walkthroughs that run the real pipeline code on made-up inputs; no raw data, no credentials |
| `verification/` | Local checks of a built layer on the real data, run on a fresh local database; they print counts and hashes for an evidence record and write only to `local_state/` |

Reusable code shared by more than one program belongs in `src/profiling/`.
Production ingestion belongs in `src/ingestion/`, and production transformations
belong in `etl/`.
