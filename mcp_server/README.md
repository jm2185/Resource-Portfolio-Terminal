# CommodityEx MCP Server — Phase 1 (local, subscription‑compatible)

A lightweight, **local‑first** [Model Context Protocol](https://modelcontextprotocol.io)
server that exposes high‑value tools and project state for the **CommodityEx Quant
Monitor v5.3** (`resource-portfolio-terminal`) repo.

Connect it from any subscription‑based MCP client — **Claude Code / Antigravity,
Cursor + Gemini, Grok, Claude Desktop** — and those models can read files, run the
test/engine/dashboard, inspect git, and pull live project state (conviction ratings,
glossary, ingestion status, config) **without you copy‑pasting** and **without any raw
API keys**. The model comes from your client's own subscription; this server only
brokers tools and runs locally on your machine.

```
   Claude Code / Cursor+Gemini / Grok / Claude Desktop      (your subscription)
                         │  MCP over stdio
                         ▼
            mcp_server/server.py  (FastMCP, local)
                         │  plain Python calls
                         ▼
      core.py  ──►  engine.py · dashboard.py · ingestion_pipeline.py · git · v5_config.json
```

---

## Setup (macOS)

From the repo root (`resource-portfolio-terminal/`):

```bash
# 1) One virtualenv for the whole project (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2) Project runtime deps (needed by run_engine / run_dashboard / run_tests / glossary)
pip install -r requirements.txt        # pandas, numpy, fastapi, uvicorn, requests, yfinance, …
pip install streamlit                  # only if you want run_dashboard

# 3) The MCP layer itself (one dependency, no API keys)
pip install -r mcp_server/requirements-mcp.txt   # mcp>=1.2.0
```

Verify the logic without a client (safe, read‑only):

```bash
python mcp_server/selftest.py     # prints PASS/FAIL for each provider
```

Sanity‑run the server (it will sit waiting on stdio — Ctrl‑C to exit):

```bash
python mcp_server/server.py
```

> The server prints diagnostics to **stderr** only; **stdout is the MCP protocol
> channel**, so never add `print()` to it.

---

## Connect from a client

The server speaks MCP over **stdio**. Point your client at
`python mcp_server/server.py`. If you used a virtualenv, use that interpreter's
absolute path (e.g. `/Users/you/resource-portfolio-terminal/.venv/bin/python`) so the
`mcp` package is importable.

### Claude Code (CLI / Antigravity)
A project‑scoped **`.mcp.json` is already committed at the repo root** — open Claude
Code in this folder and approve the `commodity-ex` server when prompted. To pin it to
your venv, edit `.mcp.json` and set `"command"` to your venv's python. Or add it by hand:

```bash
claude mcp add commodity-ex -- /ABS/PATH/.venv/bin/python /ABS/PATH/mcp_server/server.py
```

### Cursor (with Gemini) / Windsurf
Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

```json
{
  "mcpServers": {
    "commodity-ex": {
      "command": "/ABS/PATH/.venv/bin/python",
      "args": ["/ABS/PATH/resource-portfolio-terminal/mcp_server/server.py"]
    }
  }
}
```

### Claude Desktop
Edit `~/Library/Application Support/Claude/claude_desktop_config.json` with the same
`mcpServers` block as above, then restart Claude Desktop. (Desktop also surfaces the
five `cex://…` **resources**.)

### Grok / other MCP‑capable clients
Use the client's "add MCP server (stdio)" flow with command `python` and arg
`mcp_server/server.py` (absolute paths recommended). Any client that speaks MCP can
discover the tools automatically from their schemas.

---

## Tools exposed in Phase 1

| Tool | What it does |
|---|---|
| **`list_files`** | List repo files under a subdir/glob. Read‑only, repo‑scoped. |
| **`read_file`** | Read a UTF‑8 text file in the repo. Read‑only; secrets blocked. |
| **`edit_file`** | Exact‑string replace (needs `confirm=true`; backs up first). Create a file via `old_string=""`. |
| **`run_tests`** | Run the suite (pytest if present, else unittest); `target` narrows to one file. |
| **`run_ingestion`** | `ingestion_pipeline.py` wrapper — **this is where `--force` lives** (`force=true`). |
| **`run_engine`** | Manage the FastAPI engine on `:8000` (`start`/`stop`/`status`/`restart`); `force_refresh` re‑ingests first. |
| **`run_dashboard`** | Manage the Streamlit dashboard on `:8501` (`start`/`stop`/`status`/`restart`). |
| **`git_status`** | Branch + short working‑tree status. Read‑only. |
| **`git_diff`** | Unified diff of the working tree or index. Read‑only. |
| **`git_commit`** | Stage + commit (needs `confirm=true`). **Never pushes**; refuses protected/secret files. |
| **`get_conviction_ratings`** | Live Conviction‑Mode **T/Q/V** ratings + directives from the engine's `/state`. |
| **`get_ingestion_status`** | Freshness + per‑source status of `data/ingestion_cache.json`. |
| **`get_glossary`** | Rating glossary (`asymmetry_rating.ASYMMETRY_GLOSSARY`); pass a `key` for one term. |
| **`get_config_values`** | Key values from `v5_config.json`; pass a `section` for its full contents. |
| **`get_project_overview`** | One‑shot orientation: architecture, entrypoints, tickers, branch. |
| **`improve_prompt_for_claude`** | Refine a rough ask (from Gemini/Grok) into a high‑quality Claude Code prompt. Local, no API. |

### Resources (for resource‑aware clients)

The five project‑state providers are also exposed as readable resources, backed by the
same functions as the tools above:

`cex://overview` · `cex://conviction` · `cex://ingestion` · `cex://glossary` · `cex://config`

Tool‑only clients (Cursor, etc.) reach the exact same data through the `get_*` tools.

---

## Safety model

- **Repo‑scoped.** Every path is resolved and must stay inside the repository (defeats
  `..` traversal and symlink escapes).
- **Read‑only by default.** `list_files`, `read_file`, `git_status`, `git_diff` and all
  `get_*` providers never mutate anything.
- **Confirmation for destructive actions.** `edit_file` and `git_commit` return
  `needs_confirmation` until you call them again with `confirm=true`.
- **Secret & config protection.** Reads of `FRED_API_KEY` / `*.env` are blocked. Writes
  and commits refuse `v5_config.json`, `*_config.json`, secrets, and `.git/` `.cache/`.
- **No pushes.** `git_commit` commits locally only — you push when ready.
- **Backups.** `edit_file` snapshots the prior file into `.mcp_backups/` (git‑ignored).
- **Global kill‑switch.** Set `CEX_MCP_READONLY=1` to disable every mutating tool.

### Environment variables (all optional)

| Var | Default | Purpose |
|---|---|---|
| `CEX_MCP_READONLY` | _unset_ | `1` → disable all writes/commits/launches. |
| `CEX_REPO_ROOT` | parent of `mcp_server/` | Override the repo root. |
| `CEX_ENGINE_PORT` / `CEX_DASHBOARD_PORT` | `8000` / `8501` | Ports the run tools manage. |

> The optional `FRED_API_KEY` / `MARKETAUX_API_KEY` only improve the **data ingestion**
> (richer macro/news). The MCP layer never needs them.

---

## Next steps / Phase 2 ideas

- **Deeper rating tools:** `explain_rating(ticker)` (decompose a name's T/Q/V with the
  forensic JSF ledger), `rerun_valuation(ticker, overrides)` for what‑if scenarios.
- **Catalyst refresh:** a `refresh_catalysts` tool (`ingestion_pipeline.py --catalysts`)
  plus a `cex://catalysts` resource over `data/catalysts.json`.
- **Live metrics resource:** stream MRI / regime / forensic state via the engine `/ws`.
- **Niche‑tag & peer analysis:** EV/oz peer tables and archetype barbell weights as tools.
- **Multi‑model orchestration:** structured hand‑off prompts (Gemini drafts → Claude
  implements → Grok reviews) building on `improve_prompt_for_claude`.
- **Write‑safety upgrade:** optional dry‑run diffs for `edit_file` before applying.

These are intentionally **out of scope for Phase 1** (minimal, high‑ROI first).
