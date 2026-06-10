# CommodityEx — Cockpit Nervous System (live interactivity roadmap)

Design backlog for making the cockpit more interactive and communicative with itself. Captured
2026-06-05 from a brainstorm session. Concept-level only — the goal is **live context of everything
else, plus the operator's own terminal actions**, flowing between every component. Implementation
detail is left for when each item is picked up.

## The diagnosis
You already have the two hard pieces — a central hub (`engine.terminal_state`) and an immutable log
(Living Memory). What's missing is a nervous system *on top* of them: **semantic events instead of a
polled blob, push instead of pull, and a channel for the operator's terminal actions, which right now
the cockpit is almost blind to.**

## What's actually live vs. siloed right now
- **Central hub works.** Everything funnels through `engine.terminal_state`, broadcast over WebSocket
  every ~1s.
- **But it's a blob, not events.** Consumers diff a giant JSON string to notice change. Nobody is
  *told* "posture flipped to DEFENSIVE" or "JSF tripped on AGA.V" — they re-derive it. That's the root
  of the "things don't know about each other" feeling.
- **Living Memory is pull-only.** Append-only JSONL, no notification. A new council verdict lands and
  nothing wakes up; the next reader finds it whenever it happens to query.
- **Agents are islands.** Each prompt is a fresh `claude -p` subprocess, thread-scoped context. A
  running Bull can't see what the Bear just found. The Council is sequential hand-off, not a room.
- **The operator's terminal actions are invisible.** The TUI reports only `focused_ticker` +
  `active_view` back to the engine. Everything else — shell commands, git, edits, what-ifs you abandon,
  how long you dwell on a name — never enters the cockpit's context. This is the biggest gap relative
  to the goal.

## The ideas, ranked by leverage

### 1. Promote Living Memory from "memory" to "event spine"
It's already append-only JSONL — that *is* an event log. Add lightweight typed events
(`posture.flipped`, `jsf.tripped`, `user.focused`, `user.whatif`, `council.verdict`, `agent.started`)
and let every component *tail* it instead of polling state. One log = the shared consciousness, still
local, still auditable, no Kafka. This is the spine everything else hangs off.

### 2. Capture the operator's terminal actions as first-class context — via Claude Code hooks
You work inside Claude Code in this repo. The harness already sees every Bash/Edit/git action you
take. A `PostToolUse` hook can POST each to the engine (`user.ran <cmd>`, `user.edited <file>`,
`user.git_commit`). Suddenly agents know what you're *doing*, not just what you're *looking at*. That's
the literal "live context of any actions I'm taking in the terminal" — and it's a config change, not a
rewrite.

### 3. One synthesized "world state" every agent inherits
Today each agent pulls 3 tools (`get_conviction_ratings`, `memory_query`, `get_ui_context`) and
stitches its own picture. Instead, the engine maintains a single *situational-awareness snapshot* —
regime, posture, what you're looking at, your last N actions, recent verdicts, who else is running —
and every agent prompt gets it prepended. No agent starts blind.

### 4. Make the Council a live room, not a relay
Give each council session a shared scratchpad (a thread in the event spine) so the Bear sees the Bull's
claims forming, the Arbiter sees both reasoning live. Right now it's three subprocesses passing notes
under the door.

### 5. Reactive triggers — the cockpit acts without being asked
A tiny rules layer on the event spine: `posture.flips → DEFENSIVE → pin a book-level alert`;
`jsf.tripped(ticker) → highlight risk + auto-spawn a quick verifier`; `user focuses a name with a stale
council verdict → surface it`. This is the difference between a dashboard you query and a desk that
talks back.

### 6. A unified "desk tape" — the nervous system made visible
One chronological feed merging *your* actions + agent actions + state changes ("14:02 you ran what-if
AGA.V silver+8 · 14:02 posture BALANCED · 14:03 Bear flagged dilution"). It's simultaneously the killer
UX feature *and* the debug view that proves the wiring works.

## The throughline
Items 1+2 are the foundation (event spine + your actions flowing in); 3–6 are what you can build
*because* of them. You don't need a message broker — the append-only JSONL is already the right
substrate; you're just adding semantics and a tail-and-react loop.

**Suggested first pull:** #2 (capture terminal actions via hooks) — smallest change, most "whoa, it
knows what I'm doing" payoff, and it forces the event vocabulary that #1 needs anyway. If the
architectural backbone is wanted first, start with #1.
