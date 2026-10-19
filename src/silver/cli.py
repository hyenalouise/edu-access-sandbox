"""Command line for Silver: print the generated SQL and data dictionary. Run from the repository root.

    python -m src.silver.cli sql        --source deped_enrollment > etl/03_silver/01_clean_deped_enrollment.sql
    python -m src.silver.cli gate       --source deped_enrollment > etl/03_silver/90_validate_deped_enrollment_clean.sql
    python -m src.silver.cli dictionary --source deped_enrollment > docs/data/silver/deped-enrollment-clean.md
    python -m src.silver.cli sql        --source deped_personnel > etl/03_silver/03_clean_deped_personnel.sql
    python -m src.silver.cli gate       --source deped_personnel > etl/03_silver/90_validate_deped_personnel_clean.sql
    python -m src.silver.cli dictionary --source deped_personnel > docs/data/silver/deped-personnel-clean.md
    python -m src.silver.cli sql        --source psa_poverty_stat > etl/03_silver/05_clean_psa_poverty_stat.sql
    python -m src.silver.cli gate       --source psa_poverty_stat > etl/03_silver/90_validate_psa_poverty_stat_clean.sql
    python -m src.silver.cli dictionary --source psa_poverty_stat > docs/data/silver/psa-poverty-stat-clean.md
    python -m src.silver.cli sql        --source deped_facilities > etl/03_silver/02_clean_deped_facilities.sql
    python -m src.silver.cli gate       --source deped_facilities > etl/03_silver/90_validate_deped_facilities_clean.sql
    python -m src.silver.cli dictionary --source deped_facilities > docs/data/silver/deped-facilities-clean.md
    python -m src.silver.cli sql        --source deped_enrollment_psgc > etl/03_silver/07_clean_deped_enrollment_psgc.sql
    python -m src.silver.cli gate       --source deped_enrollment_psgc > etl/03_silver/90_validate_deped_enrollment_psgc_clean.sql
    python -m src.silver.cli dictionary --source deped_enrollment_psgc > docs/data/silver/deped-enrollment-psgc-clean.md

The build and the gate are SQL tasks of the job (databricks.yml); run the job
locally with python -m src.job.local_run. Exit codes: 0 printed; 2 the
contract or the mapping is invalid.
"""

import argparse
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.errors import EXIT_CONFIG_ERROR, EXIT_OK, IngestionError
from src.silver.generators import generator


def cmd_print(kind):
    def run(args):
        g = generator(args.source)
        sys.stdout.write(getattr(g, kind)(g.load_spec(REPO_ROOT, args.source)))
        return EXIT_OK
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m src.silver.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, kind, text in (("sql", "build_sql", "the Silver build SQL"), ("gate", "gate_sql", "the Silver gate SQL"),
                             ("dictionary", "dictionary_markdown", "the Silver data dictionary (Markdown)")):
        p = sub.add_parser(name, help=f"print {text} generated from the contract and the mapping")
        p.add_argument("--source", required=True)
        p.set_defaults(func=cmd_print(kind))
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except IngestionError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    exit_code = main()
    if exit_code != EXIT_OK:
        sys.exit(exit_code)
