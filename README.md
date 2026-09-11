# Resource-Portfolio-Terminal (CommodityEx)

A solo, AI-augmented research cockpit for a concentrated silver / junior-mining barbell.
The engine (`engine.py`) is the single source of truth; the Textual TUI (`commodityex_tui.py`,
launched via `./cockpit.sh`) and the MCP server (`mcp_server/`) are thin consumers.

- **System tour & doc index:** `docs/WALKTHROUGH.md`
- **Agent operating manual (the NL router):** `CLAUDE.md`
- **Cockpit launch & layout:** `COCKPIT.md`
- **Engine math reference:** `ENGINE_DESIGN.md` · metric glossary: `METRIC_COMPASS.md`
- **Spear status (2026-09-11):** `docs/SPEAR_STATUS.md`
- **Latest session handoff:** `docs/HANDOFF_2026-09-11_AGA_SPEAR_TLT.md`

Ingest the 2026-09-11 tape into Living Memory (idempotent):

```
python scripts/bootstrap/ingest_handoff_2026_09_11.py --dry-run
python scripts/bootstrap/ingest_handoff_2026_09_11.py
```
