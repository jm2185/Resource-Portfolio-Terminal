# Phase 8 — Activate the MCP server + stabilization verification

A short, ordered runbook to (A) get the MCP server running on your MacBook,
(B) connect your subscribed models, and (C) verify the recent fixes against **live**
data outside the sandbox. Full reference: `mcp_server/README.md`.

---

## A. Run it on your MacBook (~3 min)

From the repo root (`resource-portfolio-terminal/`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                 # engine/dashboard/ingestion runtime
pip install streamlit                            # for run_dashboard
pip install -r mcp_server/requirements-mcp.txt   # the MCP SDK (no API keys)

python mcp_server/selftest.py                    # expect: ALL PASSED
```

Leave the venv active. Note the **absolute** path to its python — you'll point each
client at it so the `mcp` package is importable:

```bash
echo "$(pwd)/.venv/bin/python"
```

---

## B. Connect your subscribed models

The server speaks MCP over **stdio**; the model comes from the client's own
subscription — no raw API keys anywhere.

**Claude Code (your Claude subscription).** A project `.mcp.json` is already committed —
open Claude Code in this folder and approve `commodity-ex`. Pin it to your venv by
setting `"command"` in `.mcp.json` to the path from step A, or:
```bash
claude mcp add commodity-ex -- /ABS/.venv/bin/python /ABS/mcp_server/server.py
```

**Cursor + Gemini.** Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):
```json
{ "mcpServers": { "commodity-ex": {
  "command": "/ABS/.venv/bin/python",
  "args": ["/ABS/resource-portfolio-terminal/mcp_server/server.py"] } } }
```
Then pick **Gemini** as Cursor's model — it will see the 16 tools.

**Grok.** MCP support is consumed through an **MCP-capable client/IDE**. Use Grok from a
client that hosts MCP stdio servers (the same `mcpServers` block as above). If the Grok
client you use does not yet host MCP servers, drive Grok through `improve_prompt_for_claude`
instead (it drafts; Claude Code executes — see section D). _Be aware: native MCP hosting
varies by client and changes often; confirm in your client's docs._

**Claude Desktop (bonus).** Same `mcpServers` block in
`~/Library/Application Support/Claude/claude_desktop_config.json`; Desktop also surfaces
the five `cex://…` resources.

Quick check from any client: ask it to call **`get_project_overview`** — you should get
the architecture summary and current branch back.

---

## C. Stabilization verification pass (run once connected)

**Already verified at the code/unit level in CI/sandbox** (no network needed):
`run_tests('test_catalyst_engine.py')` → 41/41 · `run_tests('test_archetypes.py')` →
42/42 (incl. the GROY asset-light-yield path + FX) · `run_tests('test_conviction_health.py')`
→ 8/8 (Phase 8 health colours). The bits that **need your Mac's network** — live catalyst
feeds and GROY's live fundamentals — are below.

1. **Refresh data live.** Call `run_ingestion(force=true, catalysts=true, verbose=true)`.
   In the output, each provider should report a real fetch — watch for `degraded`/empty
   fallbacks (those mean a source failed and you're on stale/neutral data).
2. **Confirm freshness.** Call `get_ingestion_status()` → `stale: false`, `GROY` present in
   `tickers`, `has_macro: true`, and per-source `status` healthy.
3. **Boot the engine on fresh data.** `run_engine(action='start', force_refresh=true)`,
   then `get_conviction_ratings()` → the **GROY** basket should appear with a rating +
   band, and its recent catalysts attached.
4. **Spot-check GROY (data accuracy).** Royalty / asset-light-yield archetype, USD→CAD FX
   ≈ 1.38 applied, share price and cash-flow sane (not zero/placeholder).
5. **Spot-check catalysts (no hallucination).** Each event traces to a **real PR title**
   (exact-title attribution), the manual CSV acts as a true high-trust override, dedup is
   clean, and ages look fresh.
6. **Eyeball Conviction Mode.** `run_dashboard(action='start')` → open
   `http://127.0.0.1:8501` → pillar **numbers** are colour-coded (green good · amber mid ·
   red weak), the data-quality token is coloured, the bars keep their T-blue / Q-purple /
   V-green identity, and the view still feels **calm**.

---

## D. The multi-model loop (how to actually use it)

> Gemini / Grok drafts an idea → call **`improve_prompt_for_claude`** to turn it into a
> grounded Claude Code task → Claude Code edits with `read_file` / `edit_file` →
> **`run_tests`** → **`git_commit`** (you push). Each model stays on its subscription;
> the MCP server is the shared hands.
