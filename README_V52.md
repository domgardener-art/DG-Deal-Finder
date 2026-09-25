# DG Deal Finder V52 — ±1 Year Valuation Cohort

Built from V51.

Valuation logic:
- Market-derived comparable adverts are restricted to the selected vehicle's year, one year older, or one year newer.
- Example: a 2018 car can use 2017, 2018 and 2019 listings; 2016/2020 are excluded.
- Existing mileage/proximity ranking inside the comparable estimator remains.
- Existing exact/engine/fuel/gearbox/model cohort logic remains.
- Free Autoza aggregate asking-price rescue remains if individual comparable evidence cannot produce a value.
- Manual retail override remains the final fallback and is explicitly labelled manual.
- No paid provider added.

Validation: compile passed, AST passed, 100/100 targeted regression assertions passed.
