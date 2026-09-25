# V66 — Debugged Valuation Fix

Debug findings from V65:
1. Public-page parsing depended on a `Compare` delimiter that is not guaranteed in listing markup.
2. Public fallback only ran when MCP returned an empty list; non-empty but unusable MCP rows could block it.
3. Duplicate market explanation came from separate render paths.

Fixes:
- price-centred public listing parser;
- merge REST + MCP + public evidence every time, then deduplicate/filter;
- failure-only VALUATION DEBUG panel showing REST/MCP/public row counts and parsed guide;
- duplicate explanation neutralised;
- hard no-value stop retained.

Current Autoza docs were rechecked: endpoint /api/mcp is no-auth Streamable HTTP and tools include search_used_cars and get_uk_price_guide.

Validation: compile PASS, AST PASS, 100/100 targeted checks, hard-stop ordering PASS.
External POST remains untestable from this container; V66 intentionally exposes exact live route counts in Streamlit if it still fails.
