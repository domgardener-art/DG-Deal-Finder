# DG Deal Finder V65 — Public Market Fallback

This build stops relying solely on the failing MCP price-guide call.

Valuation order:
1. Existing live API comparables
2. Autoza MCP live comparables
3. Autoza public CC-BY market/model pages
4. DG remembered Market Bank
5. Model guide only for <=6-year-old cars
6. Safe no-value state

The public-page route extracts actual visible listing year, mileage, fuel, gearbox clues and asking price,
then passes those rows through DG's existing year/mileage comparable estimator and saves them into the Market Bank.

Safety: a whole-model average is NOT used directly for older cars because it can badly overvalue an old generation
when the live model page contains mainly newer generations.

Also retains the V64 hard stop preventing £0 commercial cards.

Validation: compile PASS; AST PASS; 100/100 targeted regression checks PASS.
Current Autoza public pages and MCP documentation were web-verified. Container DNS prevented a live urllib fetch,
so the deployed Streamlit HTTP execution remains the external runtime test.
