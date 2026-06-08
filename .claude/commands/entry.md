---
description: Entry timing check — am I top-blasting? Returns LOAD / SCALE-IN / WAIT / AVOID-EXTENDED with specific price zones and the biggest timing risk.
argument-hint: [ticker]   e.g. "AGA.V", "GROY"   (empty = current focus)
---

Run an **entry timing assessment** on `$ARGUMENTS` via **@entry-sentinel**.

**Resolve the name:** use the ticker in `$ARGUMENTS`; if empty, call `get_ui_context` for the
current focus. If neither is set, ask which name.

**Stream progress** so the pipeline panel tracks it:
```
pipeline_event(stage="entry-check", ticker=…, message="reading price ladder + 52-wk range…")
```

**Invoke @entry-sentinel** with a brief that includes the resolved ticker and asks for the full
Entry Risk verdict — φ/ρ at current price, price ladder, 52-wk proximity, recent catalyst check,
and the entry zone table. Ask it to leave the cockpit trace (pin or highlight) when done.

**Report the chain concisely**, e.g.:
> **Entry Sentinel · AGA.V** — STRETCHED — WAIT FOR PULLBACK. φ 0.91 (above REP floor), ρ 1.6
> (compressed), 6% from 52-wk high, catalyst spike 3 weeks ago. Ideal entry $0.68–$0.74 (below
> floor). Biggest risk: post-drill fade not yet complete. Pinned on cockpit.

Then emit `pipeline_event(status="done", result="[one-line verdict]")`.
