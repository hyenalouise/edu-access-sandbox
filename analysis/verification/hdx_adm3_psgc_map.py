"""Run the HDX ADM3 to PSGC crosswalk (#93) on a local DuckDB that already holds both Silver tables.

First build Silver locally with the job (it writes local_state/edu_access.duckdb by default):

    python -m src.job.local_run

then:

    python analysis/verification/hdx_adm3_psgc_map.py [--db local_state/edu_access.duckdb]

It runs the committed build and gate SQL (etl/04_integration/) as the job would, prints counts for an
evidence record, and writes every feature a person decided or still has to decide (review_status
reviewed or pending) to local_state/hdx_adm3_psgc_review.md, git-ignored, so overrides can be written into
config/integration/hdx_adm3_psgc.json. COD-AB and PSGC names are public reference data.
"""

import argparse
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.store import DuckDBStore  # noqa: E402
from src.job.local_run import DEFAULT_DB  # noqa: E402

MAP = "edu_access.`04-integration`.hdx_adm3_psgc_map"
CONTROL = "edu_access.`01-control`"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    store = DuckDBStore(args.db)
    run_id = f"local-map-{uuid.uuid4().hex[:8]}"
    params = {"run_id": run_id, "code_revision": "local", "environment": "local"}
    folder = REPO_ROOT / "etl" / "04_integration"
    store.run_file(folder / "03_map_hdx_adm3_psgc.sql", params)
    gate_failed = False
    try:
        store.run_file(folder / "90_validate_hdx_adm3_psgc_map.sql", params)
        print("gate: passed, map published")
    except Exception as e:  # the gate stops on any FAIL; its results are still recorded and printed below
        gate_failed = True
        print(f"gate: FAILED, map not published: {e}")
    for r in store.records(f"SELECT check_name, status, expected, actual FROM {CONTROL}.data_quality_results "
                           f"WHERE run_id = '{run_id}' ORDER BY check_name"):
        print(f"  {r['status']:<4} {r['check_name']:<32} expected {r['expected']}, actual {r['actual']}")
    # After a failed gate the published map is the last one that passed, not this build: report the candidate.
    table = MAP + "_candidate" if gate_failed else MAP
    print("by status and method:")
    for r in store.records(f"SELECT match_status, match_method, review_status, COUNT(*) AS n FROM {table} "
                           "GROUP BY ALL ORDER BY n DESC"):
        print(f"  {r['match_status']:<10} {str(r['match_method']):<20} {r['review_status']:<9} {r['n']:>5}")
    review = store.records(f"SELECT adm3_pcode, adm3_name, adm2_name, code_candidate, psgc_code, psgc_name, "
                           f"match_status, match_method, review_status, reason FROM {table} "
                           "WHERE review_status <> 'rule' ORDER BY review_status, adm3_pcode")
    out = REPO_ROOT / "local_state" / "hdx_adm3_psgc_review.md"
    out.parent.mkdir(exist_ok=True)
    lines = ["# HDX ADM3 to PSGC: features decided by a person (reviewed) or waiting for one (pending)", "",
             "| P-code | COD-AB name | Province | Code as PSGC | PSGC code | PSGC name | Status | Method | Review | Reason |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(r[k] or "") for k in ("adm3_pcode", "adm3_name", "adm2_name", "code_candidate",
                                                          "psgc_code", "psgc_name", "match_status", "match_method",
                                                          "review_status", "reason")) + " |" for r in review]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pending = sum(r["review_status"] == "pending" for r in review)
    print(f"{len(review) - pending} reviewed, {pending} still pending: {out.relative_to(REPO_ROOT)}")
    store.close()
    return 1 if gate_failed else 0  # a failed gate must not look like success to a shell or CI step


if __name__ == "__main__":
    sys.exit(main())
