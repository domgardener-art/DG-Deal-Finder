# DG Deal Finder V59 — MCP Schema Fix
V59 asks Autoza `tools/list` for the live `get_uk_price_guide` input schema instead of guessing its arguments, then calls the model-aware price guide with only accepted fields. Existing comparable search and multi-signal valuation remain first. Failure diagnostics now show whether the deployed app can detect the Autoza price-guide tool.

Validation: compile PASS; AST PASS; mocked MCP schema/tool-call runtime PASS; 100/100 targeted regression checks PASS. External HTTP could not be live-tested in this build sandbox because outbound DNS is unavailable.
