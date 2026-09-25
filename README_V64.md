# V64 Valuation Pipeline Fix
Focused only on valuation.
- Tolerant MCP price-guide parsing.
- MCP search_used_cars fallback if REST gives no adverts.
- Order: live adverts -> DG Market Bank -> free model price guide.
- Fixed screenshot bug: no-value state now always st.stop()s before commercial cards.
Validation: compile, AST, 100/100 targeted checks, hard-stop ordering all PASS.
External Autoza POST could not run in this build container because DNS is blocked; current Autoza docs were web-verified.
