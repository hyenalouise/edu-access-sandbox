# Evidence: every PSA poverty estimate row maps to one PSGC unit by Correspondence Code, and the 44 uncovered cities and municipalities are counted

Issue #92 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8) · run by @Catweyine · local only, not yet run on Databricks

## The claim

At commit `0e927a4`, the map build and gate (`etl/04_integration/02_map_psa_poverty_psgc.sql`, `90_validate_psa_poverty_psgc_map.sql`) turn the real `psa_poverty_stat_clean` (PSA 2018, 2021 and 2023 small-area estimates, 1,612 units per year) and `psa_psgc_clean` (2Q 2026) into `psa_poverty_psgc_map` with one row per Silver row, none dropped. Every row matches exactly one PSGC city, municipality or sub-municipality by `Correspondence Code` (D-030), no PSGC code is taken twice in a year, every estimate equals its Silver value, and every FAIL check passes. The 2023 counts are D-046's: 1,597 `estimated` and 1 `no_estimate` cities and municipalities, Manila's 14 districts, and 44 PSGC cities and municipalities with no PSA row (D-054).

## What was run

On macOS, Python 3.12 and the project's DuckDB, with a landing folder holding only the two approved PSA workbooks (`PSGC-2Q-2026-Publication-Datafile.xlsx`, SHA-256 `31892bc2…`, and `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx`), twice on the same new database:

```bash
python -m src.job.local_run --landing <landing folder> --db <scratch database>
```

The job loaded PSGC (`psa_psgc__2026-Q2__31892bc2bdde`, 43,768 rows) and PSA Poverty Stat (`psa_poverty_stat__2018-2021-2023__303fb0e87bff`) into Bronze, built both Silver tables with every gate passing, then ran `02_map_psa_poverty_psgc` and `90_validate_psa_poverty_psgc_map` in the job's own order, right after those two Silver gates (D-051). The DepEd, HDX and school-age population files were not in the landing folder, so those lanes, the fan-in and the maps that read them failed. The poverty map still ran, because it reads only poverty and PSGC.

| | Run 1 | Run 2 |
|---|---|---|
| Integration run | `e88cef45-d2cb-4b3d-adae-62eec14bb181` | `c66210f1-3fd2-4c81-ae4e-83d37dae88a0` |
| Code revision | `0e927a4` | `0e927a4` |
| Map tasks | succeeded | succeeded |
| `pipeline_runs` (`integration_build`, `psa_poverty_stat`) | succeeded | succeeded |
| Checks: PASS / WARN / FAIL | 44 / 4 / 0 | 44 / 4 / 0 |

Every map column except `run_id` and `built_at_utc` was identical in the two runs, row for row.

## Results

| Check | Expected | Map |
|---|---|---|
| Silver rows / map rows / distinct (`psgc_id`, `estimate_year`) | equal | 4,836 / 4,836 / 4,836 |
| Matched / unmatched / ambiguous / pending | | 4,836 / 0 / 0 / 0 |
| Matched rows / distinct (`psgc_code`, `estimate_year`) | equal | 4,836 / 4,836 |
| `psgc_name` not the master name of `psgc_code` | 0 | 0 |
| Correspondence Code not `psgc_id` + `000`, or not the unit's | 0 | 0 |
| Estimate, flag or lineage value different from Silver | 0 | 0 |
| Name methods used | 0 | 0 |
| PSGC versions | 1 | 1 (2026-Q2) |
| Match rate | | 100.0% |

Per estimate year (the same in 2018, 2021 and 2023):

| Count | Map | D-046 (2023) |
|---|---:|---:|
| Rows | 1,612 | 1,612 |
| `city_mun` rows | 1,598 | 1,598 |
| of which `estimate_status = estimated` | 1,597 | 1,597 |
| of which `no_estimate` (Kalayaan, Palawan) | 1 | 1 |
| `sub_mun` rows (Manila's districts) | 14 | 14 |
| `names_differ` (WARN) | 61 | |
| PSGC cities and municipalities with no PSA row (WARN) | 44 | 44 |
| of which `city_class = 'HUC'` | 33 | 33 |
| of which no `Correspondence Code` (Special Geographic Area) | 8 | 8 |
| of which other (Isabela City, Cotabato City, Pateros) | 3 | 3 |
| Uncovered cities whose districts have rows (the City of Manila) | 1 | 1 |

The four WARN results are `names_differ` (183, 61 per year) and `psgc_units_not_in_source_2018`, `_2021` and `_2023` (44 each).

## The 61 names that differ (2023, the same in every year)

Listed for review (D-030). By kind:

- **Spelling, abbreviation or punctuation** (18): for example `Sanchez-Mira` / `Sanchez Mira`, `Jetafe` / `Getafe`, `Gen Tinio` / `General Tinio`, `Santo Nino` / `Santo Niño`.
- **Former name in brackets after the current name** (36): for example `Rodriguez (Montalban)` / `Rodriguez`; `Bacungan (Leon T. Postigo)` puts the current name in brackets.
- **Renamed LGU** (6): `Rizal` / `Dr. Jose P. Rizal`, `San Isidro` / `Sawata`, `Don Victoriano Chiongbian` / `Don Victoriano` and `Bacungan (Leon T. Postigo)` / `Leon T. Postigo` are the same four renamed LGUs the HDX map confirmed by review (D-052); `Bumbaran` / `Amai Manabilang` is footnote 2 of the workbook; `Sultan Gumander` / `Picong` (Lanao del Sur): PSGC 2Q 2026 lists `Sultan Gumander` as the old name of `1903635000` Picong, Correspondence Code `153635000` (confirmed by @maeveylain on #188 and rechecked in `psa_psgc_clean`).
- **Manila district** (1): `Tondo` / `Tondo I/II`.

Observed: none of the 61 names a different place. Each is matched by its code, never by its name, and none needs an override (D-054, **Open**).

| psgc_id | PSA name | PSGC code | PSGC name |
|---|---|---|---|
| `021522` | Sanchez-Mira | `0201522000` | Sanchez Mira |
| `031403` | City of Baliuag | `0301403000` | City of Baliwag |
| `031419` | San Idelfonso | `0301419000` | San Ildefonso |
| `034909` | Gen Mamerto Natividad | `0304909000` | General Mamerto Natividad |
| `034910` | Gen Tinio | `0304910000` | General Tinio |
| `035421` | Santo Tomas | `0305421000` | Sto. Tomas |
| `041018` | Mataas Na Kahoy | `0401018000` | Mataasnakahoy |
| `041028` | City of Santo Tomas | `0401028000` | City of Sto. Tomas |
| `042114` | Mendez (Mendez-Nuñez) | `0402114000` | Mendez |
| `045642` | San Francisco (Aurora) | `0405642000` | San Francisco |
| `045808` | Rodriguez (Montalban) | `0405808000` | Rodriguez |
| `050503` | Daraga (Locsin) | `0500503000` | Daraga |
| `054116` | Pio V. Corpuz | `0504116000` | Pio V. Corpus |
| `063030` | Miag-ao | `0603030000` | Miagao |
| `071226` | Jetafe | `0701226000` | Getafe |
| `071235` | Pres. Carlos P. Garcia | `0701235000` | President Carlos P. Garcia |
| `072237` | Pinamungahan | `0702237000` | Pinamungajan |
| `083724` | Javier (Bugho) | `0803724000` | Javier |
| `083728` | Lapaz | `0803728000` | La Paz |
| `086018` | Santo Nino | `0806018000` | Santo Niño |
| `086022` | Paranas (Wright) | `0806022000` | Paranas |
| `086414` | San Juan (Cabalian) | `0806414000` | San Juan |
| `156606` | Hadji Panglima Tahil (Marunggas) | `0906606000` | Hadji Panglima Tahil |
| `156616` | Panglima Estino (New Panamao) | `0906616000` | Panglima Estino |
| `097222` | Jose Dalman (Ponot) | `0907222000` | Jose Dalman |
| `097226` | Bacungan (Leon T. Postigo) | `0907226000` | Leon T. Postigo |
| `104217` | Don Victoriano Chiongbian | `1004217000` | Don Victoriano |
| `112301` | Asuncion (Saug) | `1102301000` | Asuncion |
| `112324` | San Isidro | `1102324000` | Sawata |
| `118202` | Laak (San Vicente) | `1108202000` | Laak |
| `118203` | Mabini (Doña Alicia) | `1108203000` | Mabini |
| `118205` | Maragusan (San Mariano) | `1108205000` | Maragusan |
| `118602` | Jose Abad Santos (Trinidad) | `1108602000` | Jose Abad Santos |
| `126318` | Santo Nino | `1206318000` | Santo Niño |
| `133901` | Tondo | `1380601000` | Tondo I/II |
| `140113` | Licuan-Baay (Licuan) | `1400113000` | Licuan-Baay |
| `142707` | Alfonso Lista (Potia) | `1402707000` | Alfonso Lista |
| `143211` | Rizal (Liwan) | `1403211000` | Rizal |
| `148101` | Calanasan (Bayag) | `1408101000` | Calanasan |
| `166719` | San Francisco (Anao-Aon) | `1606719000` | San Francisco |
| `166721` | Santa Monica (Sapao) | `1606721000` | Santa Monica |
| `168501` | Basilisa (Rizal) | `1608501000` | Basilisa |
| `168504` | Libjo (Albor) | `1608504000` | Libjo |
| `175323` | Rizal | `1705323000` | Dr. Jose P. Rizal |
| `064512` | Hinoba-An (Asia) | `1804512000` | Hinoba-an |
| `064519` | Moises Padilla (Magallon) | `1804519000` | Moises Padilla |
| `153603` | Balindong (Watu) | `1903603000` | Balindong |
| `153611` | Lumba-Bayabao (Maguing) | `1903611000` | Lumba-Bayabao |
| `153620` | Pagayawan (Tatarikan) | `1903620000` | Pagayawan |
| `153622` | Poona Bayabao (Gata) | `1903622000` | Poona Bayabao |
| `153635` | Sultan Gumander | `1903635000` | Picong |
| `153637` | Bumbaran | `1903637000` | Amai Manabilang |
| `157001` | Panglima Sugala (Balimbing) | `1907001000` | Panglima Sugala |
| `157003` | Mapun (Cagayan De Tawi-Tawi) | `1907003000` | Mapun |
| `153807` | Datu Odin Sinsuat (Dinaig) | `1908705000` | Datu Odin Sinsuat |
| `153814` | Kabuntalan (Tumbao) | `1908706000` | Kabuntalan |
| `153812` | Sultan Kudarat (Nuling) | `1908710000` | Sultan Kudarat |
| `153826` | Datu Saudi-Ampatuan | `1908809000` | Datu Saudi Ampatuan |
| `153819` | Gen. S. K. Pendatun | `1908811000` | Gen. S.K. Pendatun |
| `153808` | Shariff Aguak (Maganoy) | `1908820000` | Shariff Aguak |
| `153813` | Sultan Sa Barongis (Lambayong) | `1908823000` | Sultan Sa Barongis |

## The 44 PSGC cities and municipalities with no PSA row (2023)

The category comes from PSGC's own columns, as the gate counts it; no place is named in the SQL.

| PSGC code | Name | Level | city_class | Correspondence Code | Category |
|---|---|---|---|---|---|
| `0330100000` | City of Angeles | City | HUC | 035401000 | huc |
| `0331400000` | City of Olongapo | City | HUC | 037107000 | huc |
| `0431200000` | City of Lucena | City | HUC | 045624000 | huc |
| `0631000000` | City of Iloilo | City | HUC | 063022000 | huc |
| `0730600000` | City of Cebu | City | HUC | 072217000 | huc |
| `0731100000` | City of Lapu-Lapu | City | HUC | 072226000 | huc |
| `0731300000` | City of Mandaue | City | HUC | 072230000 | huc |
| `0831600000` | City of Tacloban | City | HUC | 083747000 | huc |
| `0931700000` | City of Zamboanga | City | HUC | 097332000 | huc |
| `1030500000` | City of Cagayan De Oro | City | HUC | 104305000 | huc |
| `1030900000` | City of Iligan | City | HUC | 103504000 | huc |
| `1130700000` | City of Davao | City | HUC | 112402000 | huc |
| `1230800000` | City of General Santos | City | HUC | 126303000 | huc |
| `1380100000` | City of Caloocan | City | HUC | 137501000 | huc |
| `1380200000` | City of Las Piñas | City | HUC | 137601000 | huc |
| `1380300000` | City of Makati | City | HUC | 137602000 | huc |
| `1380400000` | City of Malabon | City | HUC | 137502000 | huc |
| `1380500000` | City of Mandaluyong | City | HUC | 137401000 | huc |
| `1380600000` | City of Manila | City | HUC | 133900000 | huc |
| `1380700000` | City of Marikina | City | HUC | 137402000 | huc |
| `1380800000` | City of Muntinlupa | City | HUC | 137603000 | huc |
| `1380900000` | City of Navotas | City | HUC | 137503000 | huc |
| `1381000000` | City of Parañaque | City | HUC | 137604000 | huc |
| `1381100000` | Pasay City | City | HUC | 137605000 | huc |
| `1381200000` | City of Pasig | City | HUC | 137403000 | huc |
| `1381300000` | Quezon City | City | HUC | 137404000 | huc |
| `1381400000` | City of San Juan | City | HUC | 137405000 | huc |
| `1381500000` | City of Taguig | City | HUC | 137607000 | huc |
| `1381600000` | City of Valenzuela | City | HUC | 137504000 | huc |
| `1430300000` | City of Baguio | City | HUC | 141102000 | huc |
| `1630400000` | City of Butuan | City | HUC | 160202000 | huc |
| `1731500000` | City of Puerto Princesa | City | HUC | 175316000 | huc |
| `1830200000` | City of Bacolod | City | HUC | 064501000 | huc |
| `0990101000` | City of Isabela | City | CC | 099701000 | other |
| `1381701000` | Pateros | Mun |  | 137606000 | other |
| `1908703000` | City of Cotabato | City | ICC | 129804000 | other |
| `1999901000` | Kapalawan | Mun |  |  | without_correspondence_code |
| `1999902000` | Old Kaabakan | Mun |  |  | without_correspondence_code |
| `1999903000` | Kadayangan | Mun |  |  | without_correspondence_code |
| `1999904000` | Nabalawag | Mun |  |  | without_correspondence_code |
| `1999905000` | Pahamuddin | Mun |  |  | without_correspondence_code |
| `1999906000` | Malidegao | Mun |  |  | without_correspondence_code |
| `1999907000` | Ligawasan | Mun |  |  | without_correspondence_code |
| `1999908000` | Tugunan | Mun |  |  | without_correspondence_code |

## Not checked

- Databricks: not run. The SQL uses only constructs the HDX map already runs on Databricks, but D-017 still requires a `dev` run before this is trusted there.
- Whether the 61 differing names all name the same place was judged by reading them, PSGC's names and old names, and the sources named above.
- Boundary vintage: whether an estimate's territory equals today's PSGC unit is not checked (D-054, limitations).
