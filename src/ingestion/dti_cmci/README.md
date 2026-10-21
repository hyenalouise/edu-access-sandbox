# DTI CMCI extraction

Two one-off scripts that extracted the CMCI Education and Capacity of School Services scores, 2023 and 2024, from the public [CMCI Data Portal](https://cmci.dti.gov.ph/data-portal.php), one request per LGU, year, and indicator.

| Script | Indicator |
|---|---|
| `cmci_education_2023_2024.py` | Education |
| `cmci_capacity_of_school_services_2023_2024.py` | Capacity of School Services |

**They are not part of the pipeline.** `dti_cmci` has no ingestion contract, no Bronze table, and no job task; it is a profiled context source only. The scripts need `requests`, `beautifulsoup4`, and `pandas`, which are not in `requirements-dev.txt`, and they call the live portal, so tests never run them.

The extraction rules, run dates, retry passes, and each row's `status` (`valid`, `cmci_missing`, `cmci_server_error`) are in the [`dti_cmci` source card](../../../docs/data/source-inventory/dti_cmci/README.md).
