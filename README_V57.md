# DG Deal Finder V57 — Restore Valuation Data Flow

Root cause confirmed against Autoza's current public API docs:
`/api/v1/vehicles` is the live paginated vehicle search and supports make/model/min_year/max_year.
`/api/public/market-stats` currently exposes whole-market summary plus pricesByMake, not model-specific Cayman pricing.

V57 fixes the retrieval path. It queries same make/model ±1 year first, then ±2, then ±4, then same make/model without year restriction if the market is still thin. Downstream valuation still prefers the tightest cohort. Broad rows only rescue thin markets.

The aggregate endpoint is now treated only as low-confidence make-level rescue, never as a model-specific valuation.

Preserved: V53 multi-signal valuation, no-£0 guard, saved appraisals, Cayman year rules, no paid provider.

Validation: compile PASS; AST PASS; mocked retrieval runtime PASS (empty ±1 automatically widens and returns vehicles); 100/100 targeted regression assertions PASS.
