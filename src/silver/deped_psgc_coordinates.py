"""Generate Silver for the public-only DepEd workbook (`deped_psgc_coordinates`, #217).

The workbook repeats `deped_enrollment` for its schools: the 58 enrollment counts are equal for all
47,818 schools, and its names, sector, management, annex and offering columns restate columns that
`deped_enrollment_clean` already cleans. What it adds is each school's location: PSGC codes and
coordinates. So Silver keeps one row per `school_id` with only those, under the same rules as the
all-sector crosswalk (`deped_enrollment_psgc`, D-049): codes padded to 10 digits, a reason wherever a code
is missing, Sulu's Q4 2024 codes recoded to PSGC 2Q 2026, and the coordinates typed and flagged. The
build and gate are that crosswalk's generator, given a scope: a row outside SY 2023-24 or not `Public` is
quarantined with its reason, never dropped. Only the data dictionary is written here.
"""

from src.silver.deped_enrollment_psgc import (  # noqa: F401  (the generator interface, shared)
    LEVELS, LINEAGE, build_sql, gate_checks, gate_sql, load_spec,
)

SOURCE_ID = "deped_psgc_coordinates"
DROPPED = [
    ("58 enrollment counts (`k_male` … `g12_arts_female`)",
     "Equal to `deped_enrollment` SY 2023-24 for all 47,818 schools (0 differences); enrollment comes only from `deped_enrollment_clean`"),
    ("`school_name`, `region`, `division`, `district`, `province`, `municipality`, `legislative_district`, `barangay`, `street_address`",
     "The same values as `deped_enrollment` for the same schools, apart from spacing, case, quote marks, and `-` or `n/a` where the CSV is blank; `deped_enrollment_clean` cleans them"),
    ("`sector`", "`Public` on every row; checked here by the scope rule, then not carried"),
    ("`school_subclassification`, `school_type`", "Relabels of `school_management` and `annex_status` in `deped_enrollment` (`DepED Managed` = `DepEd`, `School with no Annexes` = `Standalone School`, …)"),
    ("`modified_coc`, `curricular_offering_classification`",
     "`modified_coc` maps one to one to `offers_es`, `offers_jhs`, `offers_shs` in `deped_enrollment` for every school; each of the 14 `curricular_offering_classification` labels rolls up to one `modified_coc` (0 exceptions), and its finer detail (e.g. Kindergarten offered) stays in Bronze"),
    ("`psgc_region_name`, `psgc_province_name`, `psgc_city_municipality_name`, `psgc_barangay_name`", "Names come from `psa_psgc` through the code"),
    ("`urban_rural`, `income_class`, `income_class_long`", "PSA and DOF classifications, carried by `psa_psgc` and Gold's geography dimensions through the code"),
    ("`urp`, `implementing_unit`", "Undocumented or unused by AP1 to AP4, and in no other source; kept in Bronze if they are ever needed"),
]


def dictionary_markdown(spec):
    p = spec.profiled
    scope = "; ".join(f"`{r['column']}` in {', '.join(f'`{v}`' for v in r['values'])} (else `{r['reason']}`)" for r in spec.scope)
    rows = ["| Column | Type | Meaning |", "|---|---|---|",
            "| `school_year` | `STRING` | School year of the approved Bronze batch; `2023-24` only (scope) |",
            "| `school_id` | `STRING` | Six-digit DepEd school ID, as published (leading zeros kept); one row per school and school year |"]
    rows += [f"| `psgc_{level}` | `STRING` | The workbook's {level.replace('_', ' or ')} PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |"
             for level in LEVELS]
    rows += ["| `psgc_recoded` | `BOOLEAN` | `TRUE` when the province is Sulu's Q4 2024 code (`19066…`): each code that starts with `19066` became `09066…`, and region `1900000000` became `0900000000`, so the code exists in the master PSGC 2Q 2026 (D-049, D-012) |",
             "| `psgc_null_reason` | `STRING` | Why a code in the row is `NULL`: `source_na` (`#N/A` in the workbook) or `not_in_workbook` (blank). `NULL` when every code is present. Region, province and city are `NULL` together; the barangay may also be `NULL` alone, for the same reason (the gate fails if the reasons ever differ) |",
             "| `barangay_outside_city` | `BOOLEAN` | The barangay code's first 7 digits (region, province, city or municipality) differ from the city or municipality code, which breaks the PSGC hierarchy. Flagged, not corrected: which code is wrong is unknown |",
             "| `longitude`, `latitude` | `DOUBLE` | The school's published point as a number (NSBI, as of 2025-07-07, workbook note above column AC). `NULL` for `#N/A` or blank, with `coordinate_flag` `missing`; the exact text stays in Bronze. Not corrected |",
             "| `coordinate_flag` | `STRING` | `missing`, `zero` (0, 0), `outside_philippines` (outside lon 116-127, lat 4-21.5), or `NULL`. A `NULL` flag is not proof of the right place: 260 schools are over 100 km from their own city or municipality (profile O-6, S-1) |"]
    rows += [f"| `{c}` | `{'INT' if c == 'delivery_version' else 'BIGINT' if c == 'source_row_number' else 'STRING'}` | Bronze lineage |" for c in LINEAGE]
    rows += ["| `run_id`, `cleaned_at_utc`, `code_revision` | `STRING`, `TIMESTAMP`, `STRING` | The Silver run that built the row |"]
    dropped = ["| Bronze columns | Why Silver does not carry them |", "|---|---|", *[f"| {c} | {why} |" for c, why in DROPPED]]
    profiled = [f"| `{name}` | {p[name]:,} |" for name in spec.profiled_names]
    return "\n".join([
        f"# `{spec.clean_table}`", "",
        f"Generated from the reviewed contract and mapping (`config/mappings/{spec.source_id}.json`):",
        f"`python -m src.silver.cli dictionary --source {spec.source_id}`. Do not edit by hand.", "",
        "Each public school's location from the public-only DepEd workbook (#217): its PSGC codes and its published coordinates, "
        "one row per school for SY 2023-24. It is not an enrollment table: the workbook's counts equal `deped_enrollment`, "
        "so enrollment comes only from `deped_enrollment_clean`. Only Bronze rows of kind `unit` are read. "
        f"Scope: {scope}. Licensing is unverified (source card).", "",
        "The coordinates are each school's own published point from the National School Building Inventory, not an "
        "administrative-area centre: of the 47,080 unflagged points, only 126 pairs are shared by more than one school "
        "(254 schools), and 40,046 lie within 10 km of the median point of their own city or municipality (profile O-6). "
        "They are kept and flagged, never corrected, geocoded, or inferred.", "",
        *rows, "",
        "## Not carried from Bronze", "",
        "Every Bronze column stays in `deped_psgc_coordinates_raw`. These are not carried, because another Silver table "
        "already holds them for the same schools, or nothing downstream uses them (checked 2026-10-21, school by school):", "",
        *dropped, "",
        "## Quarantine", "",
        f"`{spec.quarantine_table}` keeps each school row Silver does not carry, with its reasons and Bronze lineage:", "",
        "- `school_id_malformed`: not 6 digits.",
        "- `school_id_identical_copy`: a repeated `school_id` whose rows are identical in every published column; the first copy (lowest Excel row) stays in Silver.",
        "- `school_id_duplicated`: a repeated `school_id` whose rows differ; every copy is quarantined.",
        *[f"- `{r['reason']}`: `{r['column']}` is missing or not {', '.join(f'`{v}`' for v in r['values'])}." for r in spec.scope], "",
        f"Above {spec.quarantine_max_percent:g}% of the Bronze unit rows in quarantine fails the gate.", "",
        "## Profiled counts", "",
        "The gate records each count: PASS at the profiled value, WARN when it changes, never FAIL.", "",
        "| Check | Profiled |", "|---|---|", *profiled, ""])
