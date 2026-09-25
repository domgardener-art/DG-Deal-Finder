# V67 — Valuation scope bug fixed

The V66 live debug panel proved the immediate bug:
`name 'make' is not defined`.

The appraisal UI does not use local variables named `make`, `model`, `year`.
Its real robust_market_value call passes:
make = selected_make
model = selected_model
year = selected_year

V67 rewires the live MCP/public-page/guide diagnostics to those actual in-scope variables.
The core V66 merged valuation pipeline remains intact.

A visible `DG Deal Finder • V67 valuation scope fix` build tag is added so deployment can be verified.

Validation:
- py_compile PASS
- AST parse PASS
- explicit scope regression assertions PASS
- 100/100 targeted checks PASS
