# DG Deal Finder V56 — Valuation Retrieval Fix

This release fixes the data-retrieval side rather than adding another pricing formula.

Autoza currently documents its free, no-auth public aggregate JSON endpoint at:
`/api/public/market-stats`

V56:
- calls that documented endpoint directly;
- tries make+model, then make, then whole-market only as a final aggregate retrieval attempt;
- parses several common JSON field shapes defensively (typical/median/average, low/high, count/sample size);
- retains the existing live comparable-advert route;
- retains V55 progressive comparable cohorts;
- retains V53 median + mileage + market-position triangulation;
- retains the no-£0 guard and manual fallback;
- adds no paid provider.

Validation: Python compile PASS; AST PASS; parser runtime tests PASS for multiple JSON shapes; 100/100 targeted regression assertions PASS.

External note: the endpoint's existence and no-auth status were verified from Autoza's current public documentation. The build environment itself does not have reliable external HTTP access, so the Streamlit deployment remains the live network test.
