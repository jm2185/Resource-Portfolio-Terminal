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

**Run the chain:**
1. **@scout** — hunt and return a ranked shortlist (skip if a ticker was given). Show the names.
2. **@synthesis** — take the shortlist (or the given name), build the ranked comparison, run live
   what-ifs (`apply_scenario` so they show in the cockpit), score conviction, name the top pick.
3. **@verifier** — forensically red-team everything advanced; APPROVE / CONDITIONAL / REJECT each,
   leaving `pin_insight` (good) / `highlight_ticker` (warn|risk) traces on the relevant names.

**Then report the chain with attribution**, e.g.:
> **Pipeline · "royalty companies"** — Scout found 5 → Synthesis ranked → Verifier **approved 2**
> (GROY, URC.TO), 1 conditional (financing), 2 rejected. Top pick **GROY** — pinned, scenario loaded
> in What-If. One to watch: URC.TO pending the raise.

**Rules:** ground every step in tools/web (no fabricated names or catalysts); reflect outcomes
visually in the dashboard, not just chat (one badge per surviving name, the winner's scenario
pre-loaded); if the theme is ambiguous or scout finds nothing that clears the bar, say so rather
than padding. Remember the shortlist and verdicts so follow-ups ("now verify the second one",
"deep-dive the top pick") resolve without re-running.
