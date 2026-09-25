# DG Deal Finder V47 — Stable Rollback

V45/V46 introduced a global reliability policy that interfered with the normal selector path and made many/all cars unusable.

V47 rolls the catalogue/selector architecture back to V44, the last stable pre-global-policy build, while retaining the specific verified historical Cayman correction:
- 2006–2008 Cayman: 2.7L flat-six
- 2006–2008 Cayman S: 3.4L flat-six
- later 718 2.0L engines are not valid for a 2008 Cayman

No new all-manufacturer filtering experiment has been layered onto this release.

Validation:
- Python compile passed
- AST parse passed
- 100/100 targeted regression assertions passed

This does not claim every historical UK derivative is manufacturer-verified. The priority of V47 is restoring the working application before expanding catalogue coverage again.
