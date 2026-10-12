"""Personnel Silver typing, flags, quarantine, reconciliation, and publishing."""

import uuid

import pytest

from factories.deped_deliveries import approve, columns, empty_config, fake_repo, make_delivery, make_rows
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import deped_personnel
from src.silver.generators import REPO_ROOT

REVISION = "c" * 40
CONTROL = "edu_access.`01-control`"
CLEAN = "edu_access.`03-silver`.deped_personnel_clean"
QUARANTINE = "edu_access.`03-silver`.deped_personnel_quarantine"


def blank_measures(source, rows):
    header = columns("v1", source)
    dimensions = {"school_id", "school_name", "region", "division", "province", "school_district", "legislative_district",
                  "municipality", "barangay", "street_address", "sector", "school_management", "annex_status",
                  "Modified Curricular Offering Classification", "offers_es", "offers_jhs", "offers_shs"}
    for row in rows:
        for i, column in enumerate(header):
            if column not in dimensions:
                row[i] = ""
    return header, rows


def set_values(header, row, values):
    for column, value in values.items():
        row[header.index(column)] = value


def test_personnel_silver_preserves_values_flags_findings_and_reconciles(tmp_path):
    landing = tmp_path / "landing"
    personnel_config = empty_config("deped_personnel")
    personnel_header, personnel_rows = blank_measures("deped_personnel", make_rows(columns("v1", "deped_personnel")))
    set_values(personnel_header, personnel_rows[0], {"es_master_teacher_i": "0", "kinder_teachers_lgu_funding": "2.0",
                                                     "kinder_teachers_other_funding": "0.0"})
    set_values(personnel_header, personnel_rows[1], {"offers_shs": "True", "shs_school_principal_i": "1",
                                                     "shs_total_school_principal": "2"})
    set_values(personnel_header, personnel_rows[2], {"es_master_teacher_i": "5"})
    personnel_zip = make_delivery(landing / "deped" / "original", "2023-24", source_id="deped_personnel",
                                  header=personnel_header, rows=personnel_rows)
    approve(personnel_config, personnel_zip, "2023-24")

    repo = fake_repo(tmp_path / "repo", personnel_config)
    store = DuckDBStore()
    summary = IngestionRun(store, repo, "deped_personnel", landing, "local", REVISION).execute()
    assert summary.status == "succeeded"

    params = {"run_id": str(uuid.uuid4()), "code_revision": REVISION, "environment": "local"}
    silver = repo / "etl" / "03_silver"
    store.run_file(silver / "03_clean_deped_personnel.sql", params)
    store.run_file(silver / "90_validate_deped_personnel_clean.sql", params)

    assert store.query(f"SELECT COUNT(*) FROM {CLEAN}") == [(3,)]
    assert store.query(f"SELECT COUNT(*) FROM {QUARANTINE}") == [(0,)]
    assert store.query(f"SELECT es_master_teacher_i FROM {CLEAN} WHERE school_id = '900001'") == [(0,)]
    assert store.query(f"SELECT kinder_teachers_lgu_funding FROM {CLEAN} WHERE school_id = '900001'") == [(2,)]
    assert store.query(f"SELECT kinder_teachers_other_funding FROM {CLEAN} WHERE school_id = '900001'") == [(0,)]
    assert store.query(f"SELECT shs_master_teacher_iv, shs_master_teacher_iv_unavailable FROM {CLEAN} ORDER BY school_id") == [(None, True), (None, True), (None, True)]
    assert store.query(f"SELECT shs_total_school_principal, shs_school_principal_calculated, shs_principal_total_discrepancy FROM {CLEAN} WHERE school_id = '900002'") == [(2, 1, True)]
    assert store.query(f"SELECT actual FROM {CONTROL}.data_quality_results WHERE run_id = '{params['run_id']}' AND check_name = 'principal_total_discrepancies'") == [("1",)]
    assert store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE run_id = '{params['run_id']}' "
                       "AND check_name LIKE 'quarantine_reason_%' AND status = 'PASS'") == [(len(deped_personnel.REASONS),)]

    store.sql("UPDATE edu_access.`02-bronze`.deped_personnel_raw SET offers_es = 'Maybe' WHERE school_id = '900001'")
    params["run_id"] = str(uuid.uuid4())
    store.run_file(silver / "03_clean_deped_personnel.sql", params)
    with pytest.raises(Exception, match="1 FAIL result"):
        store.run_file(silver / "90_validate_deped_personnel_clean.sql", params)
    assert store.query(f"SELECT check_name, actual FROM {CONTROL}.data_quality_results WHERE run_id = '{params['run_id']}' AND status = 'FAIL'") == [("labels_mapped_offers_es", "1")]

    store.sql("UPDATE edu_access.`02-bronze`.deped_personnel_raw SET offers_es = 'True', es_master_teacher_i = '-1' WHERE school_id = '900001'")
    params["run_id"] = str(uuid.uuid4())
    store.run_file(silver / "03_clean_deped_personnel.sql", params)
    with pytest.raises(Exception, match="1 FAIL result"):
        store.run_file(silver / "90_validate_deped_personnel_clean.sql", params)
    assert store.query(f"SELECT check_name, actual FROM {CONTROL}.data_quality_results WHERE run_id = '{params['run_id']}' AND status = 'FAIL'") == [("quarantine_rate", "1")]


def test_personnel_runs_independently_and_gates_labels_and_quarantine_rate():
    spec = deped_personnel.load_spec(REPO_ROOT)
    build = deped_personnel.build_sql(spec)
    gate = deped_personnel.gate_sql(spec)
    assert "deped_enrollment_clean" not in build
    summary = "edu_access.`03-silver`.deped_personnel_gate_summary_candidate"
    assert f"CREATE OR REPLACE TABLE {summary} USING DELTA AS" in gate
    assert gate.index(f"CREATE OR REPLACE TABLE {summary}") < gate.index(f"INSERT INTO {CONTROL}.data_quality_results")
    assert f"DROP TABLE IF EXISTS {summary};" in gate
    assert set(deped_personnel.gate_checks(spec)) == set(["current_batch_present", "rows_reconcile", "school_id_unique",
        "lineage_complete", "rows_built_by_this_run", "blank_measures_stay_null", "recorded_zero_preserved",
        "all_blank_measure_retained", "all_blank_measure_flagged", "principal_total_discrepancies",
        "labels_mapped_sector", "labels_mapped_school_management", "labels_mapped_offers_es",
        "labels_mapped_offers_jhs", "labels_mapped_offers_shs", "quarantine_rate",
        *[f"quarantine_reason_{reason}" for reason in deped_personnel.REASONS]])
    assert "WHEN quarantine_rows * 100 > bronze_rows THEN 'FAIL'" in gate
