# DG Deal Finder V62 — Full UK Vehicle Bank Builder

Adds an in-app importer for the current official DfT/DVLA UK vehicle datasets:
df_VEH0124_AM, df_VEH0124_NZ and df_VEH0220.

It builds `dg_full_uk_vehicle_bank.csv` from licensed cars, retaining make, generic model,
detailed model/spec, year, fuel and official engine-size band. It does not invent gearbox
or exact manufacturer engine codes.

The V61 3,526-row curated bank remains bundled as fallback and the DG Market Bank remains.

Use the sidebar `DG UK Vehicle Bank` > `BUILD / REFRESH UK VEHICLE BANK` once after deployment.

Validation: compile PASS, AST PASS, 100/100 targeted checks PASS.
The large government CSV payloads could not be live-downloaded from this build environment,
so the deployed download itself has not been externally runtime-tested here.
