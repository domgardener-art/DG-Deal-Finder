# DG Deal Finder V60 — Simplified Valuation Core

Valuation now uses only two real routes: live comparable adverts first, then Autoza's model-aware UK price guide. The accumulated progressive rescue chain is bypassed by the core valuation function.

The result-flow bug visible in V59 is also fixed: if no real valuation is obtained, Streamlit stops before max-buy / advertise cards, so a no-valuation warning can never be followed by £0 commercial recommendations.

Validation: compile PASS; AST PASS; 100/100 runtime-focused checks covering live-comparable valuation, model-price-guide rescue, genuine no-data handling, and hard-stop ordering. External HTTP is not claimed as live-tested from this build environment.
