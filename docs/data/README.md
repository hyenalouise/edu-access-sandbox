# Data documentation

What each source holds and how the sources fit together.

| Folder | Holds | Written |
|---|---|---|
| [`source-inventory/`](source-inventory/README.md) | One folder per source: card, profile, and data dictionary | Cards and profiles by hand; dictionaries by `analysis/profiling/` |
| [`silver/`](silver/README.md) | One data dictionary per Silver table | By `python -m src.silver.cli dictionary` |
| [`cross-source/`](cross-source/README.md) | Joins, coverage, comparability, and exception lists across sources | Memos by hand; lists by `analysis/cross_source/` |
| [`analytics-outputs.md`](analytics-outputs.md) | Every column of the AP1 to AP4 outputs and `lgu_priority_matrix` | By hand; a test fails if a table's columns differ |

```mermaid
flowchart LR
    card[source-inventory/<br/>one source, as published] --> cross[cross-source/<br/>how sources join]
    card --> silver[silver/<br/>the cleaned table]
    cross --> integration[etl/04_integration]
    silver --> integration
```

The scripts that produce these findings live in [`analysis/`](../../analysis/README.md).
