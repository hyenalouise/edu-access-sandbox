"""What differs between delivery formats, so pipeline.py has one flow for every source.

| | `zip_csv` (DepEd) | `xlsx_sheet` (PSA Poverty Stat) | `xlsx_table` (PSA PSGC) | `xlsx_report` (DepEd EMISD) | `xlsx_census` (PSA school-age population) | `geojson_features` (COD-AB boundaries) |
|---|---|---|---|---|---|---|
| Discovered files | `*.zip` named like `archive_pattern` | `*.xlsx` named like `workbook_pattern` | `*.xlsx` named like `workbook_pattern` | `*.xlsx` named like `workbook_pattern` | `*.xlsx` named like `workbook_pattern` | `*.geojson` named like `archive_pattern` |
| Period | one school year, from two file names | several estimate years, from the header | one publication quarter, from the file name and the `Metadata` sheet | one school year, from the file name and a title cell | one census year, from the file name and the sheet names | one reference date, from the approved delivery (`valid_on`) |
| Versions counted per | school year | logical dataset | quarter (held in `school_year`, D-019) | school year | logical dataset (the census year held in `estimate_years_covered`) | reference date (held in `school_year`, D-026) |
| Load type | by school year (batch.load_type) | by year set (batch.load_type_for_years) | by quarter (batch.load_type) | by school year (batch.load_type) | by census year (batch.load_type_for_years) | by reference date (batch.load_type) |
| Checks | validate.prepare_delivery | workbook.prepare_workbook | xlsx_table.prepare_delivery | xlsx_report.prepare_delivery | xlsx_census.prepare_delivery | geojson_features.prepare_geojson_delivery |

Anything not in this table is shared: identity by SHA-256, the control tables,
the insert-only MERGE, reconciliation, the Bronze gate.
"""

import re
from pathlib import Path

from src.ingestion import control
from src.ingestion.batch import load_type, load_type_for_years
from src.ingestion.contract import source_format, years_label
from src.ingestion.validate import identify_delivery, prepare_delivery
from src.ingestion import geojson_features, workbook, xlsx_census, xlsx_report, xlsx_table


class ZipCsv:
    glob = "*.zip"
    pattern_key = "archive_pattern"

    def __init__(self, config):
        self.config = config

    def period_from_name(self, name):
        """School year read from an archive name, for a file that is not approved (a label only)."""
        match = re.match(self.config["archive_pattern"], name)
        if not match:
            return None
        start = int(match["start"])
        return f"{start}-{str(start + 1)[-2:]}" if int(match["end"]) == start + 1 else None

    def describe(self, delivery, path):
        """Columns of ingestion_batches that say which period a file is."""
        year = delivery["school_year"] if delivery else self.period_from_name(Path(path).name)
        return {"school_year": year, "logical_dataset": None, "estimate_years_covered": None,
                "source_sheet": None, "period": year}

    def expected_rows(self, delivery):
        return delivery["row_count"]

    def load_type(self, store, source_id, delivery):
        return load_type(delivery, control.succeeded_years(store, source_id))

    def blocked_is_revision(self, store, source_id, batch, path):
        return batch["school_year"] in control.succeeded_years(store, source_id)

    def identify(self, path):
        return identify_delivery(self.config, path)

    def prepare(self, registry_entry, path):
        return prepare_delivery(self.config, registry_entry, path)


class XlsxSheet:
    glob = "*.xlsx"
    pattern_key = "workbook_pattern"

    def __init__(self, config):
        self.config = config

    def period_from_name(self, name):
        return None  # a workbook's years come from its header, never its name

    def describe(self, delivery, path):
        if delivery:
            years = years_label(delivery["estimate_years"])
            return {"school_year": None, "logical_dataset": delivery["logical_dataset"],
                    "estimate_years_covered": years, "source_sheet": delivery["sheet"], "period": years}
        # Not approved: label it by the years its header names (read-only; never used to load).
        years = workbook.peek_estimate_years(self.config, path)
        label = years_label(years) if years else None
        return {"school_year": None, "logical_dataset": None, "estimate_years_covered": label,
                "source_sheet": None, "period": label}

    def expected_rows(self, delivery):
        return workbook.used_range_last_row(delivery)  # every row of the sheet is loaded

    def load_type(self, store, source_id, delivery):
        return load_type_for_years(delivery, control.succeeded_estimate_years(store, source_id))

    def blocked_is_revision(self, store, source_id, batch, path):
        """A changed workbook whose header names years already loaded is likely a revision."""
        label = batch.get("estimate_years_covered")
        return bool(label and set(label.split(",")) & control.succeeded_estimate_years(store, source_id))

    def identify(self, path):
        return workbook.identify_workbook(self.config, path)

    def prepare(self, registry_entry, path):
        return workbook.prepare_workbook(self.config, registry_entry, path)


class XlsxTable:
    """PSA PSGC: one workbook per publication quarter (D-019).

    The quarter goes where DepEd has its school year (`school_year` in the
    control tables): quarters sort the same way, so load types, backfills and
    current_batches work as for school years. logical_dataset and
    estimate_years_covered do not apply (NULL); source_sheet is the data sheet.
    """
    glob = "*.xlsx"
    pattern_key = "workbook_pattern"

    def __init__(self, config):
        self.config = config

    def period_from_name(self, name):
        return xlsx_table.period_from_name(self.config, name)

    def describe(self, delivery, path):
        quarter = delivery["publication_period"] if delivery else self.period_from_name(Path(path).name)
        return {"school_year": quarter, "logical_dataset": None, "estimate_years_covered": None,
                "source_sheet": delivery["sheet"] if delivery else None, "period": quarter}

    def expected_rows(self, delivery):
        return delivery["row_count"]

    def load_type(self, store, source_id, delivery):
        return load_type({**delivery, "school_year": delivery["publication_period"]},
                         control.succeeded_years(store, source_id))

    def blocked_is_revision(self, store, source_id, batch, path):
        return batch["school_year"] in control.succeeded_years(store, source_id)

    def identify(self, path):
        return xlsx_table.identify_delivery(self.config, path)

    def prepare(self, registry_entry, path):
        return xlsx_table.prepare_delivery(self.config, registry_entry, path)


class XlsxReport:
    """DepEd EMISD: one workbook per school year, laid out as a report (title rows, header lower down).

    The school year is in `school_year`, as for a DepEd zip, so versions, load
    types and current_batches work the same; source_sheet is the data sheet.
    """
    glob = "*.xlsx"
    pattern_key = "workbook_pattern"

    def __init__(self, config):
        self.config = config

    def period_from_name(self, name):
        return xlsx_report.period_from_name(self.config, name)

    def describe(self, delivery, path):
        year = delivery["school_year"] if delivery else self.period_from_name(Path(path).name)
        return {"school_year": year, "logical_dataset": None, "estimate_years_covered": None,
                "source_sheet": delivery["sheet"] if delivery else None, "period": year}

    def expected_rows(self, delivery):
        return delivery["row_count"]

    def load_type(self, store, source_id, delivery):
        return load_type(delivery, control.succeeded_years(store, source_id))

    def blocked_is_revision(self, store, source_id, batch, path):
        return batch["school_year"] in control.succeeded_years(store, source_id)

    def identify(self, path):
        return xlsx_report.identify_delivery(self.config, path)

    def prepare(self, registry_entry, path):
        return xlsx_report.prepare_delivery(self.config, registry_entry, path)


class XlsxCensus:
    """PSA school-age population: one workbook per census, every sheet loaded.

    A delivery is one census year, kept as a one-year set in
    estimate_years_covered so versions, load types and current_batches work as
    for psa_poverty_stat (per logical_dataset). source_sheet lists the sheets.
    """
    glob = "*.xlsx"
    pattern_key = "workbook_pattern"

    def __init__(self, config):
        self.config = config

    def period_from_name(self, name):
        return xlsx_census.period_from_name(self.config, name)

    def describe(self, delivery, path):
        if delivery:
            return {"school_year": None, "logical_dataset": delivery["logical_dataset"],
                    "estimate_years_covered": delivery["census_year"],
                    "source_sheet": ",".join(s["sheet"] for s in delivery["sheets"]), "period": delivery["census_year"]}
        year = self.period_from_name(Path(path).name)
        return {"school_year": None, "logical_dataset": None, "estimate_years_covered": year,
                "source_sheet": None, "period": year}

    def expected_rows(self, delivery):
        return xlsx_census.expected_rows(delivery)

    def load_type(self, store, source_id, delivery):
        return load_type_for_years({**delivery, "estimate_years": [delivery["census_year"]]},
                                   control.succeeded_estimate_years(store, source_id))

    def blocked_is_revision(self, store, source_id, batch, path):
        """A changed workbook named for a census already loaded is likely a revision."""
        return batch.get("estimate_years_covered") in control.succeeded_estimate_years(store, source_id)

    def identify(self, path):
        return xlsx_census.identify_delivery(self.config, path)

    def prepare(self, registry_entry, path):
        return xlsx_census.prepare_delivery(self.config, registry_entry, path)


class GeojsonFeatures(ZipCsv):
    """COD-AB boundaries: one GeoJSON file, not zipped (D-026).

    The reference date (valid_on) goes where DepEd has its school year, as the
    PSGC quarter does, so versions, load types and current_batches work as for
    school years. The date comes from the approved delivery, never the name.
    """
    glob = "*.geojson"
    pattern_key = "archive_pattern"

    def period_from_name(self, name):
        return None  # the reference date comes from the approved delivery, never the name

    def describe(self, delivery, path):
        period = delivery["school_year"] if delivery else None
        return {"school_year": period, "logical_dataset": None, "estimate_years_covered": None,
                "source_sheet": None, "period": period}

    def identify(self, path):
        return geojson_features.identify_geojson_delivery(self.config, path)

    def prepare(self, registry_entry, path):
        return geojson_features.prepare_geojson_delivery(self.config, registry_entry, path)


def for_config(config):
    """The format's class. An unknown format raises KeyError rather than being read as another format."""
    return {"zip_csv": ZipCsv, "xlsx_sheet": XlsxSheet, "xlsx_table": XlsxTable, "xlsx_report": XlsxReport,
            "xlsx_census": XlsxCensus, "geojson_features": GeojsonFeatures}[source_format(config)](config)