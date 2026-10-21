# Raw files the job needs

Every file the pipeline loads, in one list. The job reads 15 files from 9 sources; nothing else in `raw-data/` is loaded. Each file is identified by its SHA-256, so a file with the right name but other bytes is refused (`checksum_mismatch`).

The list is copied from the approved deliveries in [`config/ingestion/`](../../config/ingestion/README.md), which decide what loads; `tests/test_documentation_structure.py` fails if a file or checksum here differs from them. Where each file came from, and its licence, is on its [source card](../data/source-inventory/README.md).

## Get the files

**Team members: copy the team volume.** The `dev` job reads `` edu_access.`00-source`.raw ``, so copying it gives you the same bytes. With the CLI profile from [terminal setup, Part 12](terminal-setup.md#part-12-logging-in-to-databricks) and `RAW_DATA_DIR` set ([Part 8](terminal-setup.md#part-8-raw-data-and-raw_data_dir)):

```bash
databricks fs cp -r dbfs:/Volumes/edu_access/00-source/raw/deped "$RAW_DATA_DIR/deped" --profile reached-hq
databricks fs cp -r dbfs:/Volumes/edu_access/00-source/raw/psa "$RAW_DATA_DIR/psa" --profile reached-hq
databricks fs cp -r dbfs:/Volumes/edu_access/00-source/raw/admin_boundaries "$RAW_DATA_DIR/admin_boundaries" --profile reached-hq
```

The volume also holds files the job does not load (other DepEd sources, `phl_admin4.geojson`); the copy brings them too. `phl_admin3.geojson` alone is 555,585,099 bytes.

**Without workspace access: download them.** 11 files are public downloads. 4 were sent by email and are not published (see below); ask the team, or the publisher, for them.

## Where the job looks

The loader looks for each source in its publisher folder under `RAW_DATA_DIR`, in any subfolder, so `raw-data/deped/original/` and the volume's dated subfolders both work:

```
raw-data/
├── deped/               10 files: enrollment, facilities, personnel, two EMISD workbooks
├── psa/                 4 files: PSGC, poverty, two census workbooks
└── admin_boundaries/    1 file: phl_admin3.geojson
```

Keep the original file names, and never open and save a file in Excel ([Part 8](terminal-setup.md#part-8-raw-data-and-raw_data_dir)).

## The files

| Source | File | Folder | How to get it | SHA-256 |
|---|---|---|---|---|
| `deped_enrollment` | `Enrollment-in-SY-2020-2021.zip` | `deped/` | [DepEd Machine-Ready Files](https://www.deped.gov.ph/machine-ready-files/), School Characteristics | `65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241` |
| `deped_enrollment` | `Enrollment-in-SY-2021-2022.zip` | `deped/` | DepEd Machine-Ready Files | `62f412466435db6feba57684643f5af99ca901c6ea88accb420efe9a9bfb0acd` |
| `deped_enrollment` | `Enrollment-in-SY-2022-2023.zip` | `deped/` | DepEd Machine-Ready Files | `6d567d801a8d4eb6c9dec3c032ba208e4cd929c226b6326bc7c687c83efbf9bf` |
| `deped_enrollment` | `Enrollment-in-SY-2023-2024.zip` | `deped/` | DepEd Machine-Ready Files | `a10f4d0f9082919c13b3a091774c8231c99c95b1b1872310714107013b77dbbb` |
| `deped_enrollment` | `Enrollment-in-SY-2024-2025.zip` | `deped/` | DepEd Machine-Ready Files | `fd5dd74a62b828608c62335b7c324ddf05be58e3f05465fee68854795f5b1a92` |
| `deped_enrollment` | `Enrollment-in-SY-2025-2026.zip` | `deped/` | DepEd Machine-Ready Files | `ab4d7e24b3a46a99db2c76dee5279a976e4c3a76062e79f7217e70dc6dd1b450` |
| `deped_facilities` | `School-Facilities-in-SY-2023-2024.zip` | `deped/` | DepEd Machine-Ready Files | `9317af02b595d3a8d7381715780ef183a92da35354bbe0f3796045490e546609` |
| `deped_personnel` | `School-Personnel-in-SY-2023-2024.zip` | `deped/` | DepEd Machine-Ready Files | `9d1e5adfc33d67244f0d1a796f1b8b1930f5704eadf9f901008da68d7764a817` |
| `deped_enrollment_psgc` | `SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx` | `deped/` | Email from DepEd EMISD; not published | `746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5` |
| `deped_psgc_coordinates` | `SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx` | `deped/` | Email from `phcd.staff@psa.gov.ph`; not published | `edf7ba68cb768d658226a316754d636bec1d792b290692b14dd0cdd6e62fc8a1` |
| `psa_psgc` | `PSGC-2Q-2026-Publication-Datafile.xlsx` | `psa/` | [PSA PSGC](https://psa.gov.ph/classification/psgc); PSA replaces this file each quarter | `31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d` |
| `psa_poverty_stat` | `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx` | `psa/` | [PSA small area estimates](https://psa.gov.ph/statistics/poverty-sae/stat-tables) | `303fb0e87bff046acaa21e3ac586f6def6b737b9082eb1f51451a887fd93a026` |
| `psa_school_age_population` | `2020 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx` | `psa/` | Email from PSA; not published | `e40d71839b951926cd3c9515c1edafbb6a2121f734670716e3b21bd3f9dcd35f` |
| `psa_school_age_population` | `2024 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx` | `psa/` | Email from PSA; not published | `49d15bb0cdd191cd6aef4a14f4b063da247ba791b32caa653c37c464dff15954` |
| `hdx_boundaries` | `phl_admin3.geojson` | `admin_boundaries/` | [HDX COD-AB Philippines](https://data.humdata.org/dataset/cod-ab-phl) | `f682747fbb26ba773131049ef61603f4b872ba93739f6e2c3320f55dd21eec41` |

The four emailed workbooks have no stated licence (UNVERIFIED on their source cards), so check the card before publishing anything derived from them.

## Check

Compare checksums before running the job:

| macOS or Linux | Windows PowerShell |
|---|---|
| `shasum -a 256 "$RAW_DATA_DIR"/deped/*.zip` | `Get-FileHash "$env:RAW_DATA_DIR\deped\*.zip" -Algorithm SHA256` |

Then run the job ([README, Run it](../../README.md#run-it)). If a file is missing, its Bronze load warns `approved_deliveries_present`. A source with nothing loaded fails its Silver gate, but a source with several files (enrollment, school-age population) can pass with one missing (#220), so read the warnings, not only the exit code.
