# DG Deal Finder V55 — Progressive Valuation Rescue

Goal: produce a usable valuation far more often without paid data.

The valuation cohort now widens only when the preferred evidence is insufficient:
A. target year ±1 — preferred;
B. target year ±2 — rescue, confidence capped;
C. same-model evidence within ±4 years — last comparable rescue, Low confidence;
D. existing free Autoza aggregate market guidance;
E. manual retail fallback if no free source has usable evidence.

The V53 median + mileage regression + market-position triangulation is retained inside each comparable cohort. The ±1-year rule remains the primary pricing comparison; broader years are rescue evidence only and are labelled accordingly.

The final result still cannot render £0 as a DG valuation. If every free source fails, the manual retail input defaults to the seller asking price so the user can edit it and continue immediately; it is clearly labelled manual rather than market-derived.

No paid provider added.

Validation: compile PASS; AST PASS; runtime progressive-ladder tests PASS (strict cohort wins; ±2 rescue works); 100/100 targeted regression assertions PASS.
