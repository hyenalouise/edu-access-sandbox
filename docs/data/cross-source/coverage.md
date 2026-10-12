# Coverage matrix

**Updated:** 2026-10-06 · Part of #8

One row per source: how it identifies places, its geographic level, years, time basis, grain, join keys, and how it reaches PSGC 2Q 2026, the master geography ([D-012](../../governance/decisions.md#d-012-which-psgc-version-to-use)). Sources still in open pull requests are included and marked.

Every number carries one evidence label:

- **Re-run:** computed from checksum-verified raw files by a script in this repository. Checks new to this matrix print under C-n from [`cross_source_coverage.py`](../../../analysis/cross_source/cross_source_coverage.py), and per source under BP-n ([barangay population](../../../analysis/cross_source/cross_source_psa_population_per_barangay.py)), AG-n ([age-group population](../../../analysis/cross_source/cross_source_psa_population_per_age_group.py)), CM-n ([CMCI](../../../analysis/cross_source/cross_source_dti_cmci.py)), and HB-n ([HDX boundaries](../../../analysis/cross_source/cross_source_hdx_boundaries.py)).
- **Card:** taken from the source's card, profile, or memo (merged or in an open pull request), not re-run here.
- **Not run:** nobody has computed it yet.

## Summary

1. **PSGC 2Q 2026 is the hub.** Every source reaches it at one of five levels: school (`school_id` through DepEd enrollment), barangay, city or municipality, province or HUC, and region. OSM reaches it only spatially, through the HDX boundaries.
2. **DepEd joins cleanly inside itself and mostly to PSGC.** All four DepEd school files join to enrollment on `school_id` with no loss, and 97.9% of SY 2023-24 schools reach a PSGC barangay by name (98.0% in SY 2024-25 and 2025-26, with the same rules; [year comparison](deped-year-comparison.md)).
3. **Poverty joins entirely, and 96 HDX ADM3 units partly, through PSGC's old 9-digit `Correspondence Code`.** The PSGC card still says not to join on that code, so the rule needs updating (see [Conflicts](#conflicts-between-documents)).
4. **Every acquired name-only or code-only source now has a match rate,** including the HDX boundaries: ADM3 1,634 of 1,642 and ADM4 99.7%, both one-to-one, but only when names are checked as well as codes, since COD-AB uses some PSGC code numbers for different units (Maguindanao, Manila). PSA barangay population: 99.87% by name, and every barangay accounted for. CMCI: 1,634 of 1,634, one-to-one. The age-group table's API codes are PSGC 2Q 2026 codes. Only FLEMMS cannot be tested, until the microdata is accessed.
5. **Two gaps change school-level results:** 6,119 located schools (10.2%) sit in the 44 cities and municipalities with no poverty estimate, and the 112 Special Geographic Area schools match Region XII municipalities, so any city- or municipality-level value attached to them is wrong (see [Limits](#what-limits-the-joins)).
6. **CHED is profiled but out of scope** ([D-003](../../governance/decisions.md#d-003-higher-education-is-out-of-scope)), so its rows are for the record only.

## What each source is

| Source | Owner | Status | Place identifier | Geographic level | Years | Time basis | Grain |
|---|---|---|---|---|---|---|---|
| **DepEd** | | | | | | | |
| [deped_enrollment](../source-inventory/deped_enrollment/) | @hyenalouise | profiled | Names only: region, division, province, city or municipality, barangay | School | SY 2023-24, 2024-25, 2025-26 acquired | School year (BOSY count) | One row per school per school year |
| [deped_facilities](../source-inventory/deped_facilities/) | @hyenalouise | profiled | None; location comes from enrollment | School | SY 2023-24 only | School year | One row per school; facility measures for public schools only |
| [deped_personnel](../source-inventory/deped_personnel/) | @mafelisilda | profiled | None; location comes from enrollment | School | SY 2023-24 only | School year | One row per school |
| [deped_ellna](../source-inventory/deped_ellna/) | @mafelisilda | profiled | Region and division labels | School (selected schools) | SY 2023-24 (given May 2024) | School year | One row per assessed school |
| [deped_nat_gr6](../source-inventory/deped_nat_gr6/) | @mafelisilda | profiled | Region and division labels | School (selected schools) | SY 2023-24 (given April 2024) | School year | One row per assessed school |
| **PSA** | | | | | | | |
| [psa_psgc](../source-inventory/psa_psgc/) | @maeveylain | profiled | 10-digit PSGC; old 9-digit `Correspondence Code` | Region to barangay | 2Q 2026 (`Q4_2023` for comparison only) | Reference date 30 June 2026; population from the 2024 census | One row per geographic unit |
| [psa_poverty_stat](../source-inventory/psa_poverty_stat/) | @maeveylain | profiled | 5- or 6-digit ID: the first 6 digits of the old 9-digit PSGC | City or municipality; no HUCs | 2018, 2021, 2023 | Estimate year; 2023 uses the 2023 FIES and January 2024 LFS | One row per city or municipality, wide by year |
| [psa_population_per_barangay](../source-inventory/psa_population_per_barangay/) | @mafelisilda | profiled | Names only | Barangay | 2024 census | Census reference date, 1 July 2024 | One row per barangay; total population |
| [psa_population_per_age_group](../source-inventory/psa_population_per_age_group/) | @mafelisilda | profiled | Names in the CSV; 10-digit codes only in the OpenSTAT API metadata | Country, region, and a mixed lower level (province, HUC, Pateros, Isabela City, Special Geographic Area) | 2024 census | Census; exact date not stated in the file | One row per age group and place; household population |
| psa_openstat_education ([#58](https://github.com/reached-hq/edu-access-intelligence/pull/58)) | @hyenalouise | profiled, open PR | Region names: 35 labels for 20 keys | Country and region | Varies by table; most end SY 2022-23; literacy 2013, 2019, 2024 | School year; survey year for literacy | One row per place and category, per table |
| [FLEMMS 2024 public-use file](https://psada.psa.gov.ph/catalog/334) | @hyenalouise | candidate, not acquired | Province or HUC code `prv`; region codes `reg` (without NIR) and `reg2` (with NIR) | Person and household, weighted to province or HUC | 2024; attendance asked for SY 2024-25 | Survey (fieldwork 30 September to 22 October 2024) | One row per person or household |
| **BPDA** | | | | | | | |
| [bpda_barmm_education](../source-inventory/bpda_barmm_education/) | @hyenalouise | profiled | Division labels | Historical school division (10) | SY 2018-19 to 2020-21 | School year | One row per division |
| [bpda_barmm_social_infrastructure](../source-inventory/bpda_barmm_social_infrastructure/) | @hyenalouise | profiled | Area labels | Province, city, or Special Geographic Area (9) | Mostly undated; some 2019-2022 headers | Mostly unstated | One row per area |
| [bpda_barmm_roads](../source-inventory/bpda_barmm_roads/) | @hyenalouise | profiled | Area labels | Province, city, or Special Geographic Area (9) | Undated | Unstated | One row per area |
| [bpda_mbhte_infrastructure_projects](../source-inventory/bpda_mbhte_infrastructure_projects/) | @hyenalouise | profiled | Province and municipality names; barangay blank | Project (Basilan only) | Funded 2020-2022; monitored April 2024 | Monitoring date | One row per project record (16) |
| **Other publishers** | | | | | | | |
| dti_cmci ([#35](https://github.com/reached-hq/edu-access-intelligence/pull/35)) | @saraevcldn | profiled, open PR | Names only; 361 carry a two- or three-letter province suffix such as `Alaminos (LA)` | City or municipality (1,634) | 2023, 2024 | CMCI reference year | One row per LGU per year, one file per indicator |
| hdx_boundaries ([#38](https://github.com/reached-hq/edu-access-intelligence/pull/38)) | @saraevcldn | profiled, open PR | `adm3_pcode`, `adm4_pcode`, and polygons | ADM3 city or municipality (1,642); ADM4 barangay (42,048) | `valid_on` 2025-02-13, version v03; 17 regions, before the Negros Island Region | Boundary validity date | One feature per unit |
| osm_philippines ([#39](https://github.com/reached-hq/edu-access-intelligence/pull/39)) | @saraevcldn | profiled, open PR | Coordinates only | Point, line, and area features | Snapshot of 2026-09-28T20:23:05Z | Extract time | One row per mapped feature |
| **CHED (out of scope, D-003)** | | | | | | | |
| [ched_enrollment](../source-inventory/ched_enrollment/) | @catweyine | profiled | Region labels | Region | AY 2020-21 to 2024-25 | Academic year, first semester | One row per region and sector |
| [ched_graduates](../source-inventory/ched_graduates/) | @catweyine | profiled | Region labels | Region | AY 2020-21 to 2024-25 | Academic year | One row per region and program level |
| [ched_school_count](../source-inventory/ched_school_count/) | @catweyine | profiled | Region labels | Region (17; no NIR row) | AY 2023-24 only | As of 10 October 2024 | One row per region |
| [ched_student_faculty_ratio](../source-inventory/ched_student_faculty_ratio/) | @catweyine | profiled | Region labels | Region | AY 2020-21 to 2024-25 | Academic year | One row per region |

## How each source joins

| Source | Join keys | Route to PSGC 2Q 2026 | Result | Not matched, and where it is listed | Evidence |
|---|---|---|---|---|---|
| **DepEd** | | | | | |
| deped_enrollment | `school_id` to the other DepEd files; place names to PSGC | Names inside their parent: province, then city or municipality, then barangay ([rules](deped-dataset-research.md#rules)) | SY 2023-24: 58,876 of 60,134 schools (97.9%) to barangay; 46,614 (77.5%) on the strict rule. SY 2024-25: 58,888 of 60,094 (98.0%). SY 2025-26: 58,972 of 60,168 (98.0%) | SY 2023-24: 1,258 schools, [listed](generated/deped_psgc_unmatched.md). Later years: 1,206 and 1,196; names not already unmatched in SY 2023-24 are [listed](generated/deped_year_changes.md). Overseas schools excluded by rule | Re-run (A-5, A-12; Y-6) |
| deped_facilities | `school_id` | Through enrollment | 60,167 of 60,167 enrollment schools, one-to-one | None | Re-run (B-2) |
| deped_personnel | `school_id` | Through enrollment | 60,167 of 60,167, one-to-one | None | Re-run (B-3) |
| deped_ellna | `school_id` | Through enrollment | 5,752 of 5,752 are in enrollment, same region | None, but only CAR and Regions I, III, VIII, IX, at 25.3% to 43.9% of their schools | Re-run (B-4, B-6) |
| deped_nat_gr6 | `school_id` | Through enrollment | 6,636 of 6,636 are in enrollment, same region | None, but the same five regions, at 27.7% to 45.4% of their schools | Re-run (B-5, B-6) |
| **PSA** | | | | | |
| psa_psgc | 10-digit PSGC | Is the reference | Not applicable | 50 rows have no `Correspondence Code`; 2 rows have no geographic level | Card (O-2, O-3) |
| psa_poverty_stat | `PSGC ID` padded to 6 digits plus `000` equals PSGC `Correspondence Code` | Code to `Correspondence Code`, then to the 10-digit PSGC | 1,612 of 1,612 rows (100%), one-to-one | 44 PSGC cities and municipalities have no estimate: 33 HUCs, Isabela City, Cotabato City, Pateros, and 8 Special Geographic Area municipalities. Kalayaan's row has no values. Named in profile X-1 and O-5 | Re-run (profile X-1, from the raw file); schools affected re-run (C-1) |
| psa_population_per_barangay | Names inside region, province or HUC, and city or municipality | PSGC's own `2024 Population` column holds the same counts, already coded (see [Population](#population-can-attach-by-code)); the name match is the check | By name: 41,958 of 42,011 (99.87%), one-to-one; 41,957 with the same population as PSGC. The other 52 pair one-to-one with PSGC barangays by equal population inside the same province or HUC | 1 left: San Rafael, Calaca (637). PSGC counts it inside Dacanlao. [Listed](generated/psa_population_psgc_unmatched.md) | Re-run (BP-2 to BP-5; C-3) |
| psa_population_per_age_group | 10-digit codes from the OpenSTAT API metadata of table `0201A6DPAG0` | Code is the 10-digit PSGC | 136 of 136 lower-level and region codes are PSGC 2Q 2026 codes with the same name (18 regions, 82 provinces, 33 HUCs, Pateros, Isabela City, Special Geographic Area); the 137th is the Philippines. Every CSV label ties to one code, including the two with `U+FFFD` | None. 38 `Both Sexes` cells and 19 all-age totals stay quarantined (Regions V, X, XI, ages 80 and over) | Re-run (AG-2, AG-3); quarantine: card (O-7, O-8) |
| psa_openstat_education | Region map from 35 labels to 20 keys | Region | All 35 labels map; the script stops on an unknown label. School tables use 17 regions | `Unknown` NAT rows have no region | Card (O-2, O-8) |
| FLEMMS 2024 public-use file | `prv`; `reg` or `reg2` | Unknown whether `prv` is a PSGC code or PSA's own numbering | **Cannot be tested** until the microdata is accessed | The Special Geographic Area is not a FLEMMS domain | Documentation only |
| **BPDA** | | | | | |
| bpda_barmm_education | Division labels | Names with documented aliases ([BARMM memo](barmm-dataset-research.md#bpda-label-matches-to-psgc-2q-2026)) | 6 of 10 labels (60.0%) | `Lanao del Sur I`, `Lanao del Sur II`, `Maguindanao I`, `Maguindanao II`: school divisions, not PSGC units | Card (BARMM memo; matched by hand, no script) |
| bpda_barmm_social_infrastructure | Area labels | Same | 8 of 9 labels (88.9%) | `Maguindanao` (not split) | Card (BARMM memo; by hand) |
| bpda_barmm_roads | Area labels | Same | 8 of 9 labels (88.9%) | `Maguindanao` (not split) | Card (BARMM memo; by hand) |
| bpda_mbhte_infrastructure_projects | Province and municipality names | Same | 4 of 4 place pairs (100%), covering all 16 records | None | Card (BARMM memo; by hand) |
| **Other publishers** | | | | | |
| dti_cmci | `lgu` plus `year` | Name after removing the suffix, inside the province the suffix stands for: 59 suffixes read from the data, 17 by review. Current names before old names; 16 reviewed aliases | 1,634 of 1,634, one-to-one: 1,440 exact, the rest by counted tiers. [Listed](generated/dti_cmci_psgc_match.md) | None. The 8 Special Geographic Area municipalities are the only PSGC cities and municipalities with no CMCI LGU | Re-run (CM-1 to CM-4) |
| hdx_boundaries | ADM3 `adm3_pcode`; ADM4 `adm4_pcode` | P-code converted to 10 digits; then the old 9-digit form against `Correspondence Code`; then Sulu's region `19` as `09`. A code counts only if the names agree; otherwise the name inside its parent decides | ADM3: 1,634 of 1,642, one-to-one: 1,480 by code with the same name, 4 by code with a renamed LGU, 96 through `Correspondence Code`, 19 Sulu, 35 by name (Maguindanao and Manila). ADM4: 41,918 of 42,048 (99.7%), one-to-one | ADM3: the 8 Special Geographic Area units (no PSGC equivalent; spatial check). ADM4: 130 (63 Special Geographic Area; 44 Bacoor barangays from before PSGC's renumbered set of 47; 21 polygons that are not barangays, such as forest land, Mount Apo park, a cemetery, and a mall; San Rafael in Calaca, which PSGC counts in Dacanlao; Barangay 176), plus 126 matched by code whose names differ, to review. [Listed](generated/hdx_boundaries_psgc_unmatched.md) | Re-run (HB-1 to HB-3) |
| osm_philippines | None; spatial only | Point or polygon inside an HDX polygon, then HDX to PSGC | **Not run** | 770 school features have blank names (124 points, 646 areas) | Card (O-3, O-4) |
| **CHED (out of scope)** | | | | | |
| ched_* (all four) | Region label | Region map | **Not run**; not needed while out of scope | BARMM has no values from AY 2023-24; the Negros Island Region has values only in AY 2024-25; school count has no NIR row | Card |

## Join paths

| Level | Sources | Key | Notes |
|---|---|---|---|
| School | DepEd enrollment, facilities, personnel, ELLNA, NAT Grade 6 | `school_id` | Enrollment is the anchor and the only DepEd file with place names |
| Barangay | DepEd (through the name match), barangay population, HDX ADM4 | 10-digit PSGC | Barangay is the level the sponsor tests ([D-013](../../governance/decisions.md#d-013-who-the-stakeholders-are)) |
| City or municipality | Poverty, CMCI, HDX ADM3, and DepEd aggregated | First 7 digits of the barangay PSGC, plus `000`; for Manila, first 5 digits plus `00000` | PSGC codes Manila's 14 districts as sub-municipalities, so the 7-digit rule gives the district; they roll up to the City of Manila (`1380600000`), which is how CMCI, poverty, and the boundaries count it: 324 SY 2023-24 schools (C-4). Poverty through `Correspondence Code`; HDX by code checked against the name; CMCI by name |
| Province or HUC | Age-group population, FLEMMS, and DepEd aggregated | First 5 digits of the PSGC | HUCs have province-level codes, so totals by PSGC province already keep them separate. DepEd files independent cities under their province; the name match sends them to their own codes |
| Region | OpenSTAT, CHED, BPDA context | Explicit region map | Use DepEd's own region for SY 2023-24 (D-012) |
| Spatial | OSM, HDX geometry | Point or polygon in polygon | Needs school coordinates, which no acquired source has |

The intended path for every area source is `school_id → PSGC barangay → aggregate by PSGC code → area source`. No area source is joined directly to DepEd names.

### Population can attach by code

PSGC 2Q 2026 has a `2024 Population` column keyed by the 10-digit code. It holds the same 2024 census counts as the barangay workbooks:

- **Total:** PSGC barangays sum to 112,727,776, the same as the workbooks' geographic total (C-3, profile O-7).
- **Zero-population barangays:** 12 in both, with the same regional split (C-3, profile O-10).
- **Barangay by barangay:** of the 41,958 workbook barangays matched to PSGC by name, 41,957 have exactly PSGC's population (BP-3). The other 52 workbook barangays each pair with one PSGC barangay of the same population in the same province or HUC: spelling differences, the barangays of two renamed municipalities (San Isidro, now Sawata; Don Victoriano Chiongbian, now Don Victoriano), and two renamed barangays (BP-4).
- **The one-barangay difference:** the workbooks list San Rafael (637) and Dacanlao (7,046) in the City of Calaca; PSGC 2Q 2026 has only Dacanlao, with 7,683, their sum (BP-5).

So barangay population attaches by PSGC code with no name crosswalk. The workbooks are a check on the PSGC column, not the join.

The workbooks mark footnotes with superscript runs, which text extraction reads as plain digits (`Barangay 176-A 1`); this confirms the barangay profile's S-1. The match drops them from the workbooks' own formatting (BP-1).

## What limits the joins

| Limit | Size | Handling |
|---|---|---|
| DepEd schools not matched to a PSGC barangay | 1,258 of 60,134 (SY 2023-24) | Listed, never forced. They still count at city, municipality, or province level where those matched |
| Schools in a city or municipality with no poverty estimate | 6,119 of 59,732 schools with a matched city or municipality (10.2%): HUCs 5,944 (324 of them in the City of Manila, C-4), Cotabato City 83, Isabela City 74, Pateros 18. Public schools: 2,801 of 47,818. Re-run (C-1) | Keep blank with reason `not_in_source`; never impute. HUC, Isabela, and Cotabato estimates exist in PSA's 2023 Official Poverty Statistics, a different method (direct estimation) |
| Special Geographic Area schools at city or municipality level | All 112 SY 2023-24 schools under `BARMM` / `NORTH COTABATO` match a Cotabato municipality in Region XII: Pikit 46, Midsayap 20, Pigkawayan 17, Kabacan 14, Carmen 12, Aleosan 3. Re-run (C-2) | A city- or municipality-level join (poverty, CMCI, ADM3) would give them those Region XII municipalities' values. Exclude them from such joins, or mark them, until their barangays are matched to the eight Special Geographic Area municipalities |
| Region changes since SY 2023-24 | 3,306 matched schools: Negros to NIR (2,725), Sulu to Region IX (469), and the 112 above. DepEd's own region also moves: NIR from SY 2024-25 (2,704 schools) and Sulu to Region IX from SY 2025-26 (477) | Take region from DepEd for SY 2023-24 (D-012). Trends across school years use PSGC 2Q 2026 region or province, never DepEd's region (Y-5) |
| Blank counts in SY 2025-26 | Senior High School columns blank for 47,352 schools and Kinder to Grade 10 for 1,403, where earlier years wrote 0. Separately, 120 schools that offer SHS have no SHS counts, and 46 schools have no counts at all | Blank is 0 only where the level is not offered; the rest are missing (Y-3) |
| Assessments are samples | ELLNA and NAT Grade 6 cover five regions only; none in BARMM | Report as selected schools, never as regional coverage |
| Population concepts differ | Barangay file: total population. Age-group file: household population, province or HUC and up | Never mix the two in one ratio. School-age measures stay at province or HUC level |
| Quarantined age-group cells | 38 `Both Sexes` cells and 19 all-age totals | Do not recalculate; keep out of joins |
| CMCI matches that rest on review | 17 suffix readings and 16 aliases (CM-2, CM-3) | A teammate checks the [list](generated/dti_cmci_psgc_match.md) once before Silver |
| No school coordinates | No acquired source has them | Spatial work (OSM, distance) waits for an official coordinate list |

## Time alignment with the SY 2023-24 anchor

| Source | Time | Relation to SY 2023-24 | Label to use |
|---|---|---|---|
| DepEd enrollment, facilities, personnel, ELLNA, NAT Grade 6 | SY 2023-24 | Same | SY 2023-24 |
| PSGC | 30 June 2026 | Later geography; names still match | "PSGC 2Q 2026" |
| Poverty | 2023 estimate | Same calendar year as the start of the school year; inputs are the 2023 FIES and January 2024 LFS | "Poverty 2023" next to "SY 2023-24"; not called the same period ([D-027](../../governance/decisions.md#d-027-poverty-2023-beside-sy-2023-24)) |
| Barangay and age-group population | 2024 census, 1 July 2024 | Just after SY 2023-24 ends | "2024 census" |
| FLEMMS | Fieldwork October 2024; attendance SY 2024-25 | One year later | Compare with DepEd SY 2024-25, or label the years apart |
| OpenSTAT | Most tables end SY 2022-23; school counts reach SY 2023-24 | Mostly earlier | Each table's own years |
| CMCI | 2023 and 2024 | Overlaps; meaning of the year not documented | "CMCI 2023" or "CMCI 2024"; never joined on `year` against school year |
| HDX boundaries | Valid 2025-02-13, before NIR | Geography between SY 2023-24 and PSGC 2Q 2026 | "COD-AB v03" |
| OSM | 2026-09-28 | Much later | "OSM 2026-09-28" |
| BPDA | SY 2018-19 to 2020-21, or undated | Earlier | Historical context only |

## Conflicts between documents

Statements that disagree across cards, memos, and the #8 thread, with the evidence that settles each one.

| # | Where | Says | Evidence | Fix |
|---|---|---|---|---|
| 1 | [psa_psgc profile](../source-inventory/psa_psgc/profile.md) O-3 | "Do not join on" `Correspondence Code` | The poverty join (X-1, 1,612 of 1,612) and 96 HDX ADM3 units depend on it. PSGC S-2 calls it "supported, not confirmed". D-012 says to revisit when a source arrives with codes from another PSGC version, which poverty and HDX both do | Done: [D-030](../../governance/decisions.md#d-030-joins-through-correspondence-code) allows these joins, one-to-one and name-checked, and O-3 points to it |
| 2 | [BARMM memo](barmm-dataset-research.md), summary 5 | OSM has 3,572 school points | OSM also stores schools as areas: 3,572 points and 47,068 areas, 50,640 school IDs with no overlap (#39 card O-3) | Corrected in this pull request |
| 3 | #8 thread (CMCI) | 1,634 of 1,634 CMCI LGUs match non-SGA PSGC units | The claim holds, but no card showed it: #35 records only 1,472 found after removing the suffix. Re-run here (CM-3): 1,634 of 1,634 match one-to-one, but only with a suffix lookup (17 suffixes by review) and 16 reviewed aliases. A plain name match also makes one false match: `San Pedro` takes Bulalacao through its old name instead of the City of San Pedro | Use the match in [dti_cmci_psgc_match.md](generated/dti_cmci_psgc_match.md); try current names before old names in any national name match |
| 4 | #8 thread (CMCI and OSM summary table) | CMCI columns `lgu_name`, `capacity_of_school`, `educational`; join to Gold on `psgc_code + year` | The files have `lgu`, `capacity_of_school_services`, `education` (#35 profile O-7). `year` is the CMCI reference year, not a school year | Use the real column names. Join on PSGC code and record the CMCI year as an attribute |
| 5 | #8 thread (OSM summary table) | 49,245 area features (`school`, `kindergarten`, `college`, `university`), "all have names" | 49,245 is right for areas only (47,068 + 217 + 1,273 + 687). 646 area schools have blank names (#39 O-4). The point layer adds 3,572 schools. Colleges and universities are higher education, out of scope under D-003 | Count both layers, `school` only (plus kindergarten if the team keeps it), and count blank names |
| 6 | #38 card and #8 thread (HDX) | 1,500 of 1,642 ADM3 codes match PSGC exactly (91.35%); the rest break down as 96 + 19 + 18 + 1 + 8 | Re-run (HB-2): the breakdown holds, and the 2 Maguindanao spellings resolve by the name rules, so only the 8 Special Geographic Area units are left, as the thread said. But 16 of the 1,500 code matches are Maguindanao codes that name a different municipality in PSGC (COD-AB `PH1908711` is Parang; PSGC `1908711000` is Sultan Mastura), and 4 are renamed LGUs. At barangay level, 184 codes name a different barangay (118 Maguindanao, 66 Manila) | Never join COD-AB to PSGC on the code alone; check the name too, as `cross_source_hdx_boundaries.py` does. #38's profile should state this |
| 7 | #8 thread (OSM comment) | The "DepEd EBEIS masterlist" lacks usable coordinates | No EBEIS masterlist is in the inventory. The DepEd files acquired have no coordinate columns at all | Name the file, or drop the reference |
| 8 | #8 thread (PSGC comment) | `Q4_2023` could bridge BPDA's pre-2024 geography | `Q4_2023` already has the Maguindanao split: the two provinces have no `Correspondence Code`, yet they are not among the 12 new codes without one (11 barangays and the NIR row, PSGC X-1), so their codes are in both files. It would not resolve BPDA's unsplit `Maguindanao`. It only keeps Sulu in BARMM, which the BARMM memo already handles by keeping the source region | No `Q4_2023` bridge needed; BPDA stays matched to 2Q 2026 as in the memo |
| 9 | [deped-dataset-research.md](deped-dataset-research.md) | Personnel and ELLNA come from open pull requests #40 and #49 | Both merged. Their card checksums equal the ones the script verifies, so the numbers stand | Point the memo at the merged cards (in #57) |
| 10 | #35 | Two folders, `cmci/` and `dti_cmci/`, with identical `profile.md` | One source should have one folder named after its `source_id` (D-006) | Remove `cmci/` in #35 |

## Open questions

None open. The eight raised here were settled on #74 on 2026-10-09, and seven are recorded in the decision log:

1. **Poverty year:** "Poverty 2023" beside "SY 2023-24", never one period ([D-027](../../governance/decisions.md#d-027-poverty-2023-beside-sy-2023-24)).
2. **Missing poverty areas:** the 44 stay blank as `not_in_source`, never imputed ([D-028](../../governance/decisions.md#d-028-cities-and-municipalities-without-a-poverty-estimate)).
3. **Shared match columns:** one set for every crosswalk to PSGC, with a fixed `match_method` list ([D-029](../../governance/decisions.md#d-029-one-set-of-match-columns-for-every-crosswalk)).
4. **`Correspondence Code`:** allowed for sources with old 9-digit codes, one-to-one and name-checked ([D-030](../../governance/decisions.md#d-030-joins-through-correspondence-code)).
5. **Special Geographic Area schools:** the 112 are `excluded` from city- and municipality-level joins until their barangays are matched ([D-031](../../governance/decisions.md#d-031-special-geographic-area-schools-at-city-or-municipality-level)).
6. **OSM scope:** `school` only; `kindergarten` only if #9 needs it ([D-032](../../governance/decisions.md#d-032-osm-scope)).
7. **Barangay population:** PSGC's `2024 Population` column, with the workbooks as a cross-check ([D-033](../../governance/decisions.md#d-033-barangay-population-source)); provisional until @mafelisilda confirms.
8. **CMCI reviewed readings:** checked by @saraevcldn on #74. All 17 suffix readings and 16 aliases hold. `Bantayan Island` means Bantayan town only, since CMCI lists Madridejos and Santa Fe (CU) separately.

## Status against #8

| Done when | Status |
|---|---|
| One row per source: codes or names, level, years, time basis | Done for every acquired source, plus FLEMMS as a candidate |
| Grain statement and join keys per source | Done |
| Names-only sources matched to PSGC, match rate recorded | Done for DepEd (three years), BPDA, barangay population, age-group population, and CMCI. HDX ADM3 and ADM4 re-run here. FLEMMS cannot be tested. CHED not needed (D-003) |
| Unmatched records counted and listed | Listed for DepEd, BPDA, barangay population, and CMCI; poverty gaps named. Listed for HDX too (ADM3 8, ADM4 130, and 126 to review) |
| Enrollment compared across SY 2023-24 to 2025-26 | Done in [deped-year-comparison.md](deped-year-comparison.md): label mappings (Y-2), blank counts (Y-3), school IDs (Y-4), place changes (Y-5), and the PSGC match per year (Y-6). Lists in [deped_year_changes.md](generated/deped_year_changes.md) |
