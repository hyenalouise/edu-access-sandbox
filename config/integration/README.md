# Integration rules

One reviewed file per mapping table: the order of its rules, what it matches against, and every manual override with its reason, its evidence and the source release it was reviewed for (it applies to that release only). Change a file only by a reviewed pull request, then regenerate the SQL (see `src/integration/README.md`).

| File | Map table |
|---|---|
| `hdx_adm3_psgc.json` | `hdx_adm3_psgc_map` (#93, D-052) |
| `psa_school_age_population_psgc.json` | `psa_school_age_population_psgc_map` (#159, D-055): also the PSGC regions each census region covers today, and the reviewed province aliases; overrides apply to one census year |
