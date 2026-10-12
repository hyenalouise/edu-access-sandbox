# Cross-source analysis

Work that compares or joins sources, with evidence: how each source reaches PSGC 2Q 2026, the master geography ([D-012](../../governance/decisions.md#d-012-which-psgc-version-to-use)), and what that means for joining them (#8). Findings about a single source stay in its own folder under [`docs/data/source-inventory/`](../source-inventory/). The scripts that produce these numbers live in [`analysis/cross_source/`](../../../analysis/cross_source/), named `cross_source_*.py`.

Start with the [coverage matrix](coverage.md). It has one row per source and points to everything else.

```
docs/data/cross-source/
├── README.md                   this guide
├── coverage.md                 the coverage matrix (start here)
├── deped-dataset-research.md   memo: DepEd SY 2023-24 to PSGC, school ID joins
├── deped-year-comparison.md    memo: DepEd enrollment across three school years
├── barmm-dataset-research.md   memo: BARMM sources
└── generated/                  lists written by the scripts; never edited by hand
```

## Contents

### Memos (written by hand, every number from a script)

| File | What it answers | Finding IDs | Script |
|---|---|---|---|
| [coverage.md](coverage.md) | For every source: how it names places, its level, years, grain, join keys, and PSGC match. Also join paths, limits, time alignment, conflicts between documents, and open questions with the decisions they led to | C, BP, AG, CM, HB | several, below |
| [deped-dataset-research.md](deped-dataset-research.md) | How DepEd SY 2023-24 place names match PSGC, and how the DepEd school files join on `school_id` | A, B | [`cross_source_deped.py`](../../../analysis/cross_source/cross_source_deped.py) |
| [deped-year-comparison.md](deped-year-comparison.md) | What changes across DepEd enrollment SY 2023-24, 2024-25, and 2025-26: labels, blank counts, school IDs, places, and the PSGC match per year | Y | [`cross_source_deped_years.py`](../../../analysis/cross_source/cross_source_deped_years.py) |
| [barmm-dataset-research.md](barmm-dataset-research.md) | What the BPDA, PSA, and other sources can say about BARMM, and how they join | none (BPDA label matches were done by hand) | none |

### Generated lists, in [`generated/`](generated/) (never edit by hand; rerun the script)

| File | Lists | Script |
|---|---|---|
| [deped_psgc_unmatched.md](generated/deped_psgc_unmatched.md) | DepEd SY 2023-24 place names not matched to PSGC, with school counts | [`cross_source_deped.py`](../../../analysis/cross_source/cross_source_deped.py) |
| [deped_year_changes.md](generated/deped_year_changes.md) | School IDs dropped or added between years, place names that change for the same school, and names newly unmatched in later years | [`cross_source_deped_years.py`](../../../analysis/cross_source/cross_source_deped_years.py) |
| [psa_population_psgc_unmatched.md](generated/psa_population_psgc_unmatched.md) | Barangay population rows not matched to PSGC by their exact name, and how each was settled | [`cross_source_psa_population_per_barangay.py`](../../../analysis/cross_source/cross_source_psa_population_per_barangay.py) |
| [dti_cmci_psgc_match.md](generated/dti_cmci_psgc_match.md) | CMCI suffix readings, CMCI LGUs not matched by exact name, and PSGC units with no CMCI LGU | [`cross_source_dti_cmci.py`](../../../analysis/cross_source/cross_source_dti_cmci.py) |
| [hdx_boundaries_psgc_unmatched.md](generated/hdx_boundaries_psgc_unmatched.md) | COD-AB ADM3 and ADM4 units not matched to PSGC, and ADM4 code matches whose names differ (to review) | [`cross_source_hdx_boundaries.py`](../../../analysis/cross_source/cross_source_hdx_boundaries.py) |

## How to read the evidence

### Evidence labels

Every number in the coverage matrix carries one label:

| Label | Meaning | Can it be rerun? |
|---|---|---|
| **Re-run** | Computed from checksum-verified raw files by a script in this repository | Yes: run the script and find the finding ID in its output |
| **Card** | Taken from a source card, profile, or memo, not recomputed for the matrix. "By hand" means no script produced it | Only through that source's own profiling script, if it has one |
| **Not run** | Nobody has computed it yet | No |

### Finding IDs

A finding ID such as `A-5` or `Y-6` is printed by a script in front of the number it reports, as `[A-5] ...`. A number in a memo carries the same ID, so it can be traced to the exact check and reproduced. The letters say which script prints it:

| Prefix | Printed by | Covers |
|---|---|---|
| `A-n` | `cross_source_deped.py` | DepEd SY 2023-24 place names to PSGC 2Q 2026 |
| `B-n` | `cross_source_deped.py` | DepEd `school_id` joins between enrollment, facilities, personnel, ELLNA, and NAT Grade 6 |
| `Y-n` | `cross_source_deped_years.py` | DepEd enrollment across the three acquired school years |
| `C-n` | `cross_source_coverage.py` | Checks that span sources: schools without a poverty estimate (C-1), Special Geographic Area schools (C-2), PSGC population (C-3), Manila sub-municipalities rolled up to the City of Manila (C-4) |
| `BP-n` | `cross_source_psa_population_per_barangay.py` | PSA barangay population against PSGC |
| `AG-n` | `cross_source_psa_population_per_age_group.py` | PSA age-group population's OpenSTAT codes against PSGC |
| `CM-n` | `cross_source_dti_cmci.py` | CMCI LGUs against PSGC |
| `HB-n` | `cross_source_hdx_boundaries.py` | COD-AB (HDX) boundaries against PSGC |
| `O-n`, `X-n`, `S-n` | each source's own profiling script | That source's `profile.md`: observed findings, cross-checks, and suspected findings |

Example: the coverage matrix says enrollment matches PSGC at 98.0% in SY 2024-25, with evidence "Re-run (Y-6)". Run `cross_source_deped_years.py` and read the line that starts `[Y-6] SY 2024-25`.

## How the work was done

The coverage matrix for #8 was built in these steps. New cross-source work should follow the same order.

1. **Inventory every source's place key.** From each source card: does it carry PSGC codes, other codes, or names only; at what level; for which years; and what one row means.
2. **Read every claim against its evidence.** Each number posted in the #8 thread was checked against the source's card, profile, and pull request reviews. Disagreements are recorded in the matrix under "Conflicts between documents", with the evidence that settles each one.
3. **Re-run what can be re-run.** For every acquired source, a script reads the checksum-verified raw files and matches them to PSGC 2Q 2026, using the shared rules below. Numbers that could not be re-run keep the label **Card**.
4. **Count and list what does not match.** Nothing is forced. Every unmatched or ambiguous record is counted in the memo and listed in a generated file, with its reason.
5. **Look for joins that would be wrong, not just missing.** A match can succeed and still be wrong. Each script checks for codes claimed twice, and code matches are checked against names.
6. **Record what limits the joins, and what the team must decide.** Gaps that change results (for example, schools in areas without a poverty estimate) go under "What limits the joins"; choices that are not ours to make alone go under "Open questions", and once the team agrees, into the [decision log](../../governance/decisions.md).

## Shared matching rules

All `cross_source_*.py` scripts reuse the rules in `cross_source_deped.py`, so every source is matched the same way. Each rule beyond an exact match is a separate, counted tier, so a stricter reader can drop it.

- **Match inside the parent, never on a name alone.** Province, then city or municipality inside the province, then barangay inside the city or municipality. Region is never a match key (D-012).
- **Tiers, in order:** exact name; PSGC `Old names`; accents and punctuation ignored; bracketed text dropped; the words "City" and "of" ignored. The DepEd memo lists the DepEd-specific extensions ([rules](deped-dataset-research.md#rules)).
- **A match must be unique.** Two or more candidates is "ambiguous", never a pick.
- **Current names before old names** when there is no parent to scope the search: otherwise an old name can take another place's match (CMCI's `San Pedro` matched Bulalacao, whose old name is San Pedro, instead of the City of San Pedro).
- **A code is not enough on its own.** COD-AB uses some PSGC code numbers for different places (Maguindanao, Manila), so a code match counts only if the names agree.
- **`Correspondence Code`** (PSGC's old 9-digit code) links sources that carry old codes: poverty, and the COD-AB units still coded under Regions VI and VII. [D-030](../../governance/decisions.md#d-030-joins-through-correspondence-code) allows it when the join is one-to-one and the names are checked, recorded as `match_method = correspondence_code`.
- **Anything decided by review, not by the data,** such as a CMCI suffix reading or an alias, is written into the script, counted separately, and listed for a teammate to check.

## How to rerun

Every script runs locally, with no Databricks compute, from raw files in the folder named by `RAW_DATA_DIR` ([terminal setup, Part 8](../../getting-started/terminal-setup.md#part-8-raw-data-and-raw_data_dir)). Each script checks every file's SHA-256 against its source card and stops if one differs.

```bash
export RAW_DATA_DIR=~/Projects/reached-hq/raw-data
python analysis/cross_source/cross_source_deped.py
```

| Script | Needs under `RAW_DATA_DIR` |
|---|---|
| `cross_source_deped.py` | `deped/original/`: the SY 2023-24 enrollment, facilities, personnel, ELLNA, and NAT Grade 6 zips. `psa/original/`: the PSGC 2Q 2026 workbook |
| `cross_source_coverage.py` | Same as `cross_source_deped.py` |
| `cross_source_deped_years.py` | Same, plus the SY 2024-25 and 2025-26 enrollment zips |
| `cross_source_psa_population_per_barangay.py` | Same as `cross_source_deped.py`, plus the 18 regional barangay population workbooks in `psa/original/` |
| `cross_source_psa_population_per_age_group.py` | `psa/original/`: the age-group CSV, the PSGC 2Q 2026 workbook, and `0201A6DPAG0_metadata.json` (the OpenSTAT API metadata; the script header has the URL) |
| `cross_source_dti_cmci.py` | Same as `cross_source_deped.py`, plus `dti/original/cmci_lgu_list.csv` |
| `cross_source_hdx_boundaries.py` | Same as `cross_source_deped.py`, plus `admin_boundaries/original/phl_admin3.geojson` and `phl_admin4.geojson` (1.27 GB together) |

The raw files are on the team volume, `/Volumes/edu_access/00-source/raw/`, in folders named like the ones above (`deped`, `psa`, `cmci`, `admin_boundaries`). Copy them with the Databricks CLI and the `reached-hq` profile, for example:

```bash
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/cmci/cmci_lgu_list.csv "$RAW_DATA_DIR/dti/original/" --profile reached-hq
```

Running a script rewrites its generated list. If the list changes, the raw file or the rules changed: find out which before committing. The scripts that reuse `cross_source_deped.py` also rewrite `generated/deped_psgc_unmatched.md`, which should come out unchanged.

## Adding cross-source work

- **Script:** `analysis/cross_source/cross_source_<source_id>.py`, reading from `RAW_DATA_DIR`, checking checksums first, and reusing the matching rules above.
- **Finding IDs:** pick a new short prefix, add it to the table in this README, and print every number under its ID.
- **Lists:** write unmatched or ambiguous records to `docs/data/cross-source/generated/<source_id>_<what>.md`, with a first line saying which script generated it.
- **Coverage matrix:** update the source's row with the result, the list, and the evidence label and IDs; add any limit, conflict, or open question it raises.
- **This README:** add the memo or list to Contents.
