# DG Deal Finder V51 — Free Valuation Rescue

Built from the stable V47 base.

Changes:
- Keeps existing Autoza comparable-advert valuation.
- Adds Autoza's free/no-key aggregate market-stats endpoint as a second valuation layer.
- If individual comparable adverts fail, DG attempts the aggregate asking-price guide.
- If all free market evidence fails, DG no longer treats £0 as a valuation.
- A manual retail estimate becomes available so the deal maths (max buy, contribution, ROI, prep/stress logic) can still be used.
- Manual estimates are explicitly labelled as manual, not market-derived.
- No paid valuation provider has been added.
- MarketCheck has NOT been hard-wired because it requires an API key and its current pricing is not purely free after trial/quota. The app's existing optional MarketCheck support remains untouched.

Validation:
- Python compile passed.
- AST parse passed.
- 100/100 targeted regression assertions passed.
- External live network calls were not executed in this build environment.
