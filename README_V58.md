# DG Deal Finder V58 — Model Price Guide Fix

The repeated no-valuation problem came from relying on live-stock retrieval for thin cars.

Autoza currently documents a separate no-key MCP tool named `get_uk_price_guide`, which returns typical, lowest and highest current asking prices and can be narrowed to a make/model. V58 calls that model-aware price-guide tool directly.

Valuation order:
1. live comparable adverts and DG multi-signal valuation;
2. Autoza model-aware UK price guide via MCP;
3. broad make-level aggregate rescue;
4. manual retail only if all free sources fail.

The live-stock progressive search remains in place. The ±1-year cohort remains preferred for individual comparables. No paid provider is added.

Also fixes the final manual fallback so it defaults to the seller asking price when available rather than displaying 0.

Validation: compile PASS; AST PASS; 100/100 targeted regression assertions PASS.
External MCP network response could not be executed from the build sandbox; Autoza's current public documentation was verified before implementation.
