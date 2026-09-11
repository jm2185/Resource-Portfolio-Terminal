# Branch policy — 2026-09-11 audit

`main` is at `370a392` plus later handoff/research commits. There are **no open PRs**.

There are ~50 `claude/*` session branches plus `UI-Redesign`. These are **not** unmerged features waiting to land. They are leftover Claude Code session heads. Mass-merging them into `main` would replay stale engine, config, and thesis state on top of the current book.

## Do not merge

| Branch class | Why |
|---|---|
| `claude/*` (most) | Session forks from Jun–Sep 2026. Many predate CEG handoff, garage book, dual-lane, and the 2026-09-11 AGA death. |
| `UI-Redesign` (May 31) | Four months behind `main`. Educational/engine experiments, not a clean UI delta. |
| `claude/gamify-savings-spending-9sio6o` | Points at the **old** main tip (`69963e4`) from before today's handoff. |

## Salvage, do not merge

`claude/bunker-hill-silver47-merger-oogzz0` (Sep 2) is the only branch with **research** we still want. It underwrote BNKR credit (~US$125M stack vs then ~US$166M cap), the silver loan (1.2 Moz due Aug 8 2027), Sprott stream equitized Jun 2025, and management tenure. That work **supports the AGA exit**; it does not resurrect the spear. Pull facts into research notes. Do not merge the branch — later operator notes on that tip still treated hold-through-close as live, which the 2026-09-11 plan closed.

## Rule
New work lands on `main` (or a short-lived PR). Session branches stay as archaeology. Delete them when you next clean the remote.
