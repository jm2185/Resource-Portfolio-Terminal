#!/usr/bin/env python3
"""
Smoke test for the MCP server *logic* (core.py) — runs WITHOUT the MCP SDK.

It exercises the read-only and safety paths only (no engine launch, no commits),
so it is safe to run anywhere:  python mcp_server/selftest.py
A non-zero exit code means a core provider regressed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failures
    status = PASS if cond else FAIL
    if not cond:
        failures += 1
    print(f"  [{status}] {name}{(' — ' + detail) if detail and not cond else ''}")


print("== file operations ==")
ls = core.list_files(".", "*.py")
check("list_files finds engine.py", any(f == "engine.py" for f in ls["files"]))
rf = core.read_file("README.md")
check("read_file returns content", rf["bytes"] > 0 and "content" in rf)

print("== path & write safety ==")
for bad in ["../etc/passwd", "/etc/passwd"]:
    try:
        core.read_file(bad)
        check(f"reject traversal {bad!r}", False, "no SafetyError raised")
    except core.SafetyError:
        check(f"reject traversal {bad!r}", True)
try:
    core.read_file("FRED_API_KEY")
    check("block secret read", False, "no SafetyError")
except core.SafetyError:
    check("block secret read", True)
needs = core.edit_file("README.md", "A new", "A newer", confirm=False)
check("edit needs confirmation", needs["status"] == "needs_confirmation")
for prot in ["v5_config.json", "secret.env"]:
    try:
        core.edit_file(prot, "x", "y", confirm=True)
        check(f"block write to {prot}", False, "no SafetyError")
    except core.SafetyError:
        check(f"block write to {prot}", True)

print("== git helpers (read-only) ==")
gs = core.git_status()
check("git_status has branch", bool(gs.get("branch")))
gd = core.git_diff()
check("git_diff returns dict", "diff" in gd)
commit_guard = core.git_commit("test", confirm=False)
check("git_commit needs confirmation", commit_guard["status"] == "needs_confirmation")

print("== project-state providers ==")
ov = core.get_project_overview()
check("overview names the project", "CommodityEx" in ov["project"])
ing = core.get_ingestion_status()
check("ingestion_status handles missing/present", "cache_present" in ing)
conv = core.get_conviction_ratings()
check("conviction degrades when engine down", "engine_running" in conv)
cfg = core.get_config_values()
check("config exposes tickers", "AGA.V" in cfg.get("tickers", []))
sec = core.get_config_values(section="portfolio_metadata")
check("config section fetch works", sec.get("section") == "portfolio_metadata")
gl = core.get_glossary()
check("glossary loads or degrades", ("entries" in gl) or ("error" in gl))

print("== prompt helper ==")
pr = core.improve_prompt_for_claude(
    "Add a unit test for runway calculation", context="focus on edge cases",
    files="engine.py,test_v5_engine.py", mode="debug")
check("prompt names the repo", "CommodityEx" in pr["refined_prompt"])
check("prompt includes files", "test_v5_engine.py" in pr["refined_prompt"])
check("prompt mode respected", pr["mode"] == "debug")

print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
