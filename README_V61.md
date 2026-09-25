# DG Deal Finder V61 — DG Vehicle Bank

Bundled vehicle-spec bank: 3,526 seed rows across 35 makes.
It contains the app's existing UK model catalogue, curated powertrain combinations, and year-verified Porsche Cayman rules.

New market-memory bank:
- every genuine priced comparable returned by the live source is normalised and saved;
- future valuations check fresh adverts first, then DG's remembered market observations, then the model price guide;
- bank valuation prefers ±1 year and widens to ±3 only when fewer than 3 observations exist;
- median asking price is used rather than inventing a value.

Important V60 bug fixed: `estimate_market_from_comps()` returns `retail`, but V60's simplified `robust_market_value()` looked only for `value`. V61 accepts `retail/value/average`, so successful live comparable valuations are no longer silently discarded.

No synthetic prices are seeded into the market bank.

Validation:
- compile PASS
- AST PASS
- bundled bank integrity PASS
- Porsche 2008 Cayman year-rule presence PASS
- market-bank valuation runtime PASS
- 100/100 targeted checks PASS

Streamlit local files can be ephemeral across redeploy/restart; this version makes the bank functional immediately, but durable cloud persistence should be the next storage upgrade.
