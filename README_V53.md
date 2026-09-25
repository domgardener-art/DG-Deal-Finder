# DG Deal Finder V53 — Multi-Signal Valuation

Built from V52.

DG now triangulates market-derived retail from three signals:
- median asking price of comparable adverts;
- mileage-adjusted linear regression when at least five useful mileage observations exist;
- market-position median from the closest-mileage half of the cohort.

Comparable adverts remain restricted to target year ±1. With enough adverts, IQR trimming removes extreme asking-price outliers. Mileage regression is bounded to prevent noisy samples implying that extra mileage increases value or pushing the result far outside the observed market. The final estimate is the median of available signals.

Confidence uses sample size and central price spread. Autoza's free/no-key aggregate asking-price guide remains the next fallback. Manual retail remains the final fallback rather than £0. No paid valuation source is included.

Important: these are asking-price estimates, not achieved transaction prices.

Validation: compile PASS; AST PASS; synthetic runtime valuation tests PASS (±1-year exclusion, outlier resistance, mileage regression); 100/100 targeted regression assertions PASS.
