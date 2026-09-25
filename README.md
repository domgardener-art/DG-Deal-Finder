# DG Deal Finder Mobile

A phone-first Streamlit/PWA-style prototype for quickly appraising Facebook Marketplace and other used-car listings.

## Run it
1. Install Python 3.10+.
2. In this folder:
   `pip install -r requirements.txt`
3. Run:
   `streamlit run app.py`
4. Open the shown local address in your phone browser if your phone and computer are on the same network, or deploy the app to a supported web host.
5. In Safari/Chrome use **Add to Home Screen** to make it feel like an app.

## Marketplace workflow
Facebook Marketplace → Share → Copy link → open DG Deal Finder → paste link → enter listing details → Analyse.

You can also attach a screenshot. V2 stores/displays it during appraisal, but does not OCR it automatically.

## What it calculates
- all-in cost
- prep contingency
- potential contribution
- ROI
- maximum buy price
- DG deal score
- BUY CANDIDATE / INVESTIGATE / PASS
- saved deal pipeline

## Important
The app is decision support only. Verify MOT, provenance, finance/write-off status, vehicle identity, condition and live retail comparables before buying.

## Logical next upgrades
- DVLA vehicle lookup from registration
- DVSA MOT history lookup
- screenshot AI extraction
- permitted valuation/comparable feeds
- mobile share-target integration when deployed as a native/PWA wrapper
