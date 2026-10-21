# bpda_barmm_roads: BARMM road length by surface and administrative class

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | BARMM Roads |
| Publisher / agency | Bangsamoro Planning and Development Authority (BPDA), Bangsamoro Knowledge Portal |
| Source system (as stated by the publisher) | Bangsamoro Ecological Profile, Infrastructure open data |
| Source URL or acquisition method | Public XLSX download linked under **BARMM Roads** on the [Bangsamoro Knowledge Portal](https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/infrastructure); [direct export](https://docs.google.com/spreadsheets/d/1hYlFU4NuY3odhjDiOrwjiAXurgG8Oj6qFWKlKIcs7bE/export?format=xlsx) |
| Licensing or access restrictions | Public download. No license or reuse terms were found on the landing page or in the workbook; reuse terms remain **UNVERIFIED** |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-10-04 (Philippine time) |

## Files

Raw files are kept outside git. Row count refers to the data sheet and excludes its header row.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `BARMM_Roads.xlsx` | XLSX, two worksheets | n/a | 216,818 | 9 | `5e36f1c36db08617d511d900a9052bc58b73f521d00e9b1712a4ab841cf63cc9` | Databricks volume `/Volumes/edu_access/00-source/raw/bpda/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| Bangsamoro Knowledge Portal: BARMM Infrastructure (HTML snapshot `BPDA_Infrastructure_page_2026-10-04.html`, 214,951 bytes, saved 2026-10-04 Philippine time; stored in `/Volumes/edu_access/00-source/raw/bpda/`; shared with `bpda_barmm_social_infrastructure`) | https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/infrastructure | `24807e66d0c5f2a313fab4b06b795a6cc3843d49a7dee03764714abc260b1999` | Publisher, dataset title, placement in the Bangsamoro Ecological Profile, download link (the snapshot contains the same Google Sheet ID as the direct export). No license or reuse terms appear on the page |
| Workbook headers | Inside the inventoried file | File checksum above | Exact road classes, surface types, unit, and reporting-area labels |

No reference date, methodology, data-source note, geographic definition, or release note accompanies the workbook.

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Nine published reporting areas: Maguindanao, Lanao del Sur, Basilan, Sulu, Tawi-Tawi, Cotabato City, SGA, Lamitan City, and Marawi City |
| Geographic level | Mixed province, city, and Special Geographic Area labels |
| Time coverage | **UNVERIFIED**; no reference date or year appears in the data sheet or headers |
| Time basis | **UNVERIFIED** |
| Update frequency | **UNVERIFIED** |
| Population covered | Local-road lengths by surface type and by provincial, municipal, barangay, or city road class, as labelled by the publisher |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One wide row per published reporting-area label, with 20 road-length measures in kilometres |
| Candidate primary key | Raw `Province/City` label; 9 rows and 0 duplicates in this file |
| Candidate join keys | Raw reporting-area label only. A dated geographic bridge is required before joining; the source provides no time key or geographic code |
| PSGC available? Which version? | No. The file uses historical labels, including unsplit `Maguindanao`, `Sulu`, and `SGA` |
| Personally identifiable or sensitive fields | None. Public aggregate road-length measures only. Classification: **Public** |
| Provenance fields in the source | Worksheet name, row number, exact column header, and reporting-area label. No source agency, reference date, revision, or extraction timestamp appears inside the workbook |

Column-by-column descriptions, fill rates, and ranges: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column or structure | Expected type | Actual type | Notes |
|---|---|---|---|
| `Province/City` | Reporting-area identifier | Text | Unique in this file, but mixes provinces, cities, and SGA |
| 20 road-length columns | Non-negative decimal kilometres | 132 numeric values, 41 physical blanks, and 7 `-` markers across 180 measure cells | The publisher does not define blanks, `-`, or explicit zeroes |
| Geographic code | PSGC or another stable code | Absent | Name-only joins would be ambiguous and historically unstable |
| Spatial network fields | Geometry, endpoints, road segment ID, or routable links | Absent | The file cannot calculate distance or travel time |

## Lineage and dependencies

Unstated originating agency/system -> BPDA Bangsamoro Ecological Profile Google Sheet -> public XLSX export -> checksum-verified raw storage -> completeness and total/component reconciliation checks -> optional historical area bridge -> descriptive road-length context.

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** the workbook provides no reference date, source note, geographic code, collection method, missing-marker definition, or release history.
- **Observed:** 48 of 180 measure cells are not numeric: 41 are physically blank and 7 contain `-`. Their meanings are not documented, so neither form is converted to zero.
- **Observed:** 28 numeric cells contain explicit zeroes. The file does not say whether a zero means measured zero, not applicable, or no reported road length; zeroes remain distinct from blanks and `-`. 24 of the 28 zeroes are `City Roads` columns in province or SGA rows, which suggests not applicable rather than measured zero.
- **Observed:** only 20 total/component combinations have all five required numeric values. Sixteen reconcile within 0.02 km. Four have larger differences: Lanao del Sur concrete 70.56 km and earth 4.91 km; Basilan concrete 2.65 km and earth 1.10 km.
- **Observed:** the four larger differences numerically match the separately published Lamitan City or Marawi City road values exactly, except Lanao del Sur concrete differs from Marawi City's value by 0.02 km. The workbook does not explain whether province totals include those cities. The pattern does not hold for road opening: Marawi City has 0.08 km, but Lanao del Sur's road-opening total equals its components exactly.
- **Observed:** Cotabato City's city-road road-opening length (43.04 km) is larger than its overall road-opening total (42.04 km), exactly 1.00 km more. No reading of the `-` barangay cell can reconcile this.
- **Observed:** the geography is historical and mixed. It is not directly compatible with a current PSGC province table.

## Limitations for analysis

- The source can describe published aggregate road length by surface and road class, subject to an unknown reference date and unresolved area definitions.
- It cannot calculate school-to-community distance, shortest paths, travel time, seasonal access, ferry connections, or road-network connectivity because it contains no road geometry or endpoints.
- It cannot support trends because it contains one undated snapshot.
- Provincial and city rows must not be summed until BPDA confirms whether province totals include the separately listed cities.
- Missing values, `-`, and zeroes must remain separate until the publisher defines them.

## Recommended controls and monitoring

- Fail ingestion if the checksum, worksheet names, 21-column header, 9-row roster, or reporting-area key changes without re-inventory.
- Preserve the exact source label, source cell, raw value, and missing-marker type.
- Keep all values in kilometres as published; do not infer precision from the long binary-decimal strings stored in some cells.
- Do not aggregate province and city rows or use the table for distance calculations until BPDA supplies scope, dates, and geographic definitions.
- Request the reference date, source agency/system, road-class definitions, boundary vintage, missing-value rules, total/component logic, and reuse license.

