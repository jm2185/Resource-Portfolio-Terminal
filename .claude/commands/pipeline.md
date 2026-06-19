---
description: Run the 3-agent research pipeline (scout → synthesis → verifier) on a theme or name
argument-hint: [theme | ticker]   e.g. "silver junior developers", "royalty companies", "AGA.V"
---
Orchestrate the embedded research team end-to-end on `$ARGUMENTS`. You are the conductor — invoke
the specialists, pass each one's output to the next, and keep the human's view grounded throughout.

**Decide the entry point from `$ARGUMENTS`:**
- A **theme** ("silver junior developers", "project generators", "royalties") → start at **@scout**.
- A **specific ticker** ("AGA.V", "GROY") → skip scouting; start at **@synthesis** on that name.
- Empty → ask what to scout, or offer to run on the current focus (`get_ui_context`).

**Post live status as you go** (so the cockpit's PIPELINE panel tracks the run while the user keeps
working): call `pipeline_event` at each transition — `pipeline_event(stage="scout", message="…",
theme="$ARGUMENTS")` when you start scouting, `stage="synthesis"` / `stage="verifier"` as you hand
off, and per name `pipeline_event(ticker=…, verdict="APPROVE|CONDITIONAL|REJECT", message="<one-line
finding: the thesis + the key risk>")`. The `message` becomes the seed of a research thread the user
can branch off, so make it substantive. End with `pipeline_event(status="done", stage="done",
result="<the full structured report>")` — the cockpit seeds a thread per surviving name and saves the
report to the Dossier.

**Mint a run tag first.** Subagents run in ISOLATED contexts — one stage's output never reaches the
next on its own. Before you invoke anyone, mint a short run tag from the theme + date (e.g.
`pl:silver-0619`) and pass it **verbatim into every stage's prompt** (and into `pipeline_event(theme=…)`).
Every stage tags its Living-Memory writes with it; every downstream stage can then recover the prior
stage's work from the store. The tag is the spine of the hand-off.

**Run the chain — hand off on TWO channels, never one:**
1. **@scout** — hunt and return a ranked shortlist (skip if a ticker was given). Show the names.
   Scout itself writes each survivor to the durable store (`memory_write type=scout_candidate` tagged
   with the run tag + `add_candidate` to the universe) — that persistence IS the hand-off.
2. **@synthesis** — **thread @scout's actual shortlist text into synthesis's prompt** (the fast path:
   it cannot see scout's report otherwise) AND give it the run tag (the durable path: it recovers the
   shortlist via `memory_query(type="scout_candidate", tag="<run-tag>")` if your prompt is thin). It
   builds the ranked comparison, runs live what-ifs (`apply_scenario`), scores conviction, names the
   top pick, and writes its ranking back to Memory under the run tag.
3. **@verifier** — pass synthesis's advanced set in the prompt AND the run tag; it recovers the
   ranking via `memory_query(tag="<run-tag>", type="note")` if needed. It forensically red-teams
   everything advanced; APPROVE / CONDITIONAL / REJECT each, leaving `pin_insight` (good) /
   `highlight_ticker` (warn|risk) traces and a durable `pipeline_event(ticker=…, verdict=…)` per name.

**The invariant: no stage starts blind.** If you ever invoke a downstream stage with only the theme —
no prior output threaded and no run tag to recover it — the chain breaks exactly there (the stage
re-scouts or invents). Always carry both the text and the tag.

**Then report the chain with attribution**, e.g.:
> **Pipeline · "royalty companies"** — Scout found 5 → Synthesis ranked → Verifier **approved 2**
> (GROY, URC.TO), 1 conditional (financing), 2 rejected. Top pick **GROY** — pinned, scenario loaded
> in What-If. One to watch: URC.TO pending the raise.

**Rules:** ground every step in tools/web (no fabricated names or catalysts); reflect outcomes
visually in the dashboard, not just chat (one badge per surviving name, the winner's scenario
pre-loaded); if the theme is ambiguous or scout finds nothing that clears the bar, say so rather
than padding. Remember the shortlist and verdicts so follow-ups ("now verify the second one",
"deep-dive the top pick") resolve without re-running.

**Conditional chains (H2):** a workflow stage may carry a `gate` checked against the prior stages'
output, so the chain aborts EARLY and cheaply instead of running every stage regardless — a decision
tree, not a fixed escalator. Gate vocabulary on `gate.require`: `any_approve` · `no_reject` ·
`jsf_at_least`/`jsf_below` (+`value`) · `contains`/`not_contains` (+`value`); a numeric gate whose
signal is absent passes by default (`on_missing:"halt"` flips it). A failed gate halts the chain and
writes a `WORKFLOW HALT` note to Living Memory (the Quest Log NOTE lane surfaces it). The cockpit's
**gated dossier** chain shows the pattern (scout → [any_approve] value → [JSF≥3.5] verifier →
[no_reject] synthesis); gated stages are marked `⟜` in the Pipeline view.
