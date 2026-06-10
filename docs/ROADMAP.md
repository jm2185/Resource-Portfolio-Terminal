# CommodityEx — Feature Roadmap

Design backlog for new agents/features in the cockpit. Captured 2026-06-04 from a brainstorm
session. Concept-level only — ideas, sub-features, and guardrails. Implementation detail is left
for when each item is actually picked up.

**Guardrail — where this lives:** this is roadmap material. It does **not** belong in the cockpit's
"AGENT PROPOSALS" panel, which is a governance queue for confirmable config/param changes (one
key=value edit per row, awaiting `/confirm`, kept near-empty). A multi-idea backlog there would clog
the governance signal. The only roadmap item that legitimately surfaces in that panel is the
calibration loop's evidence-backed param proposal (Idea 2 ④).

## Style alignment (Druckenmiller — concentrated, risk-tolerant, high-research)
Every feature here is judged against the house style, not generic "good investing." The style is:
**concentrate into conviction, bet asymmetric, let the macro regime set the master risk dial, and
change your mind fast when the thesis breaks.** What matters is *how much you make when right vs. how
much you lose when wrong* — not how often you're right.

Concrete consequences for this roadmap:
- **Optimize for expectancy, not accuracy.** The calibration loop scores slugging and upside capture
  first, hit-rate second. A 30%-hit book that crushes its winners is *winning*; a tool that nudges you
  toward "be right more often" would quietly turn this into a diversified value book. Guard against
  that explicitly (Idea 2 ③).
- **The Bear sharpens the bet; it never vetoes it.** In an asymmetric book the Bear's job is to define
  the invalidation level and the downside leg, not to talk you out of a convex spear. A permanent
  bear-veto is a style violation (Idea 1).
- **Decision-support, never automation.** Nothing here sizes, presses, or cuts on its own. The system
  *surfaces* "press-it" and "thesis-broken" setups; the human pulls the trigger. This keeps
  Druck-style aggressive sizing compatible with the hard "nothing moves the book on its own" scope line.
- **Regime is the master risk dial.** Bottom-up name work (debate, calibration) is downstream of the
  top-down regime (liquidity, real yields, DXY, curve). When to press and when to get out of
  *everything* is a macro call — see the build-order note below.

## Signal coherence (the terminal must never argue with itself)
The book already carries several scoring layers — engine conviction (T/Q/V → band/directive), the JSF
forensic gate, catalysts — and this roadmap adds more (bull/bear verdict, expectancy scorecard, regime
posture). The failure mode is a cockpit that contradicts itself: regime flashing "risk-off, get out"
next to a name reading "BELOW FLOOR — ACCUMULATE," with no statement of which wins. A terminal that
argues with itself is worse than no signal — it destroys the operator's trust at the exact moment a
concentrated book needs a clear call. So every new signal is governed by three rules:

- **Altitude, not competition.** Signals sit at different levels and *compose*; they don't stack as
  equal-weight rivals. **Regime = book-level risk posture** (how hard you press, how much dry powder),
  **not** a name-level buy/sell score. "ACCUMULATE" under a risk-off regime composes to *"accumulate,
  smaller / slower,"* not a contradiction. **Calibration = a meta-layer** that adjusts confidence and
  priors, not a competing trade signal. **Engine conviction + JSF = the name-level source of truth**
  (the engine stays the single source of truth — new signals modulate or feed it, never shadow it).
- **One reconciled verdict per name.** When layers disagree, the disagreement is resolved in *one*
  place and shown as *one* call, with the tension named ("strong long, but regime caps the size; bear's
  invalidation level is $X"). Never two contradictory numbers at equal weight on the same screen.
- **Show dissent as dissent, not as a second verdict.** A losing bear case or a stale signal surfaces
  as a flagged caveat on the one verdict — never as a rival headline number competing for the eye.

This is the connective tissue between the two open recommendations below: the Thesis Check multi-agent
is *where* per-name reconciliation happens, and the regime sentinel only earns its place if it plugs in
as a posture dial under these rules rather than as one more contradictory readout.

## Build order (so work compounds, not sprawls)
1. **Idea 1 ①** — surface the asymmetry metrics (ρ, φ, gate reason, confidence ribbon, price ladder)
   into the state the agents actually read. Smallest change, unblocks the most. The genuine first step.
2. **Bull/Bear adversarial layer** (rest of Idea 1).
3. **Calibration loop** — structured records → outcome capture → expectancy scorecard (Idea 2 ①②③).
4. **Regime posture dial** — the macro master dial, plugged in as a *composing book-level posture*
   (how hard to press / dry powder) under the Signal-coherence rules — never a rival name-level score.
5. **Thesis Check multi-agent** — per-name re-underwrite that reconciles bull/bear + regime fit +
   calibration prior + catalysts into one verdict. Sits last in the spine because it *consumes* every
   layer above it. (Skill + sentinel-triggered automation.)
6. **Quick wins** slotted as palate-cleansers between the heavier lifts.

*(Promoted 2026-06-04: steps 4 & 5 were the two open recommendations — now first-class, placed below
the initial features Ideas 1 & 2 as chosen.)*

Cross-links: Idea 1 ① also powers the PIPELINE verdict viz and `/expand`. Idea 2's records + outcomes
feed the catalyst decay sweep and are fed by it. Idea 2 ⑤ (per-archetype calibration) tells Idea 1's
Bear where to dig.

**Spine resolved (2026-06-04).** Both former recommendations are now promoted into the build order
above, placed below the initial features (Ideas 1 & 2) as chosen — the **regime posture dial** (step 4)
and the **Thesis Check multi-agent** (step 5), both governed by the Signal-coherence rules. The regime
dial is a composing book-level posture, never a rival name-level score; the Thesis Check sits last
because it consumes every layer above it.

---

## Idea 1 — Bull/Bear adversarial layer inside the pipeline

**What:** insert a structured debate between scout/synthesis and the verifier. A **Bull** builds the
strongest long case, a **Bear** the strongest short/pass case, each forced to ground every claim in
live engine numbers; a thin reconciler weighs the exchange before the verifier gates. Two advocates
beat one model "weighing both sides" — adversarial pressure surfaces the disconfirming evidence a
single pass rationalizes away.

**Why it fits the book:** the debate is scoped to the exact axes the engine already computes, so the
**engine can referee the argument**. Bull must clear the JSF forensic gate; Bear attacks floor
coverage (φ) and the payoff ratio (ρ); the directive is the scoreboard. In a 4-name concentrated book
the bear case is worth more *before* you size in than after — there's no diversification to wash out a
bad underwrite.

### Sub-features & guardrails
- **① Surface the asymmetry metrics to the agents** — *prerequisite.* The agent-facing ratings today
  are flattened to rating/band/directive; ρ, φ, payoff, upside, the gate reason and the confidence
  ribbon never reach the debaters. Until the Bear can read the number it's attacking, the debate is
  vapor. This is the keystone the rest leans on.
- **② Engine-refereed claims (the "fact gate")** — every claim is tagged engine-grounded (cites a live
  field) vs narrative (web/judgment). The reconciler weights grounded claims higher and flags any
  narrative claim that contradicts an engine field. *Guardrail: a long thesis that only works by
  ignoring the forensic cap is auto-killed, visibly, with the reason string. But the Bear's win
  condition is to define the **invalidation level and the downside leg**, not to kill a convex bet —
  no permanent bear-veto on the spear (style violation).*
- **③ Live debate in the PIPELINE panel** — post bull / bear / reconcile as visible stages so the desk
  watches rounds land. *Guardrail: the losing side's strongest point survives as a single warn-level
  badge — dissent doesn't evaporate when the bull wins.*
- **④ Convergence / confidence score** — don't just pick a winner, emit *how close* it was. A contested
  (≈51/49) split flows to the verifier flagged "contested" and gets a tighter pass. Calibrated
  disagreement is signal.
- **⑤ Asymmetric weighting by archetype** — for the spear (option-convexity) bias the debate toward
  asymmetry/upside; for royalties bias toward cash-flow durability and let the Bear attack accretion
  quality, not dilution (which the gate already exempts). Argue about what matters *for that name*.
- **⑥ Steelman handoff** — the winning side must restate the loser's best argument before synthesis
  proceeds (Rapoport rule). Cheap insurance against motivated reasoning.

**Guardrail (scope):** no auto-sizing or trade actions come out of the debate — it produces a verdict,
badges, and a scenario to load, nothing that moves the book on its own.

---

## Idea 2 — Calibration / decision-journal loop

**What:** an agent that, on a horizon, grades each past APPROVE / CONDITIONAL / REJECT and each engine
upside/floor estimate against what actually happened — *"your APPROVEs hit 7/10; your bull on AGA.V
projected 138%, realized 41%; your REP floors ran 12% conservative."* Realized outcomes then flow back
into the engine through the existing human-gated param path. Turns the dossier archive from write-only
into a learning system, and closes the engine's own named "no backtest / reconciliation" gap.

**Why concentration helps:** with four names you make few decisions, so each is trackable and
systematic bias (always too bullish on upside, floors always too conservative) is real money error,
not statistical noise. The base rate it produces becomes a prior every future scout/synthesis run
inherits.

**Two decisions that make it real (not hand-waving):**
- **Ground truth:** realized price from the data the cockpit already pulls.
- **Horizon:** decision-date → 30 / 90 / 180d, scored against *which leg* (floor / base / bull / bear).
  A bull call is "right" if price approached the bull leg in-window; a floor is "right" if it held.
  Multi-horizon because a discovery thesis and a royalty re-rate play out on different clocks.

### Sub-features & guardrails
- **① Structured decision records** — *prerequisite.* Dossiers are plain prose today; you can't grade
  what isn't machine-readable. Stamp each decision with the frozen legs, ρ, φ, JSF, verdict, and price
  at decision. Foundation for everything else; also makes the dossier library queryable.
- **② Outcome capture** — *prerequisite.* Stamp realized price at each horizon against the frozen legs.
  Can accrue on a schedule so outcomes build without you remembering.
- **③ Expectancy scorecard** — *centered on the Druckenmiller objective function, not accuracy.*
  Headline metrics: **slugging ratio** (avg win magnitude ÷ avg loss magnitude), **expectancy per
  decision**, **upside capture** on winners (realized ÷ projected bull leg — were you *under*-betting
  your good calls?), and **downside containment** (did you exit before the floor actually broke?).
  Hit-rate, conservatism bias and the reliability curve survive but are *secondary* — demoted on
  purpose, so the tool never optimizes you toward "be right more often." One screen, reviewed monthly.
  *Guardrail: if the scorecard's top line is hit-rate, it's mis-built — that's a diversified-value
  objective, not this book's.*
- **④ Evidence-backed param proposal** — *"floors ran 12% conservative across 8 closed decisions →
  propose loosening the conservatism scalar."* *Guardrail: the agent only proposes, with receipts, and
  it routes through the existing `/confirm` human gate — it never sets a tunable itself.* This is the
  one item that legitimately lands in the AGENT PROPOSALS panel.
- **⑤ Per-archetype calibration** — split the scorecard by archetype. You're probably well-calibrated
  on royalties and hot on explorers (or vice versa); this tells the Bull/Bear layer exactly where to
  apply extra skepticism. The two ideas compound.
- **⑥ Pre-mortem base rates fed forward** — before a new APPROVE, inject the relevant base rate ("your
  last 6 sub-$50M explorer APPROVEs hit 2/6 at the 90d bull leg"). History as a live prior at decision
  time, not a quarterly retrospective.
- **⑦ Decision-quality vs outcome-quality split** — grade the *process* separately from the *result*; a
  well-reasoned call that lost to a macro shock isn't a process failure. *Guardrail against the
  resulting fallacy — don't over-fit the engine to noise.*

---

## Quick wins

- **`/morning` desk brief** — one screen at session start: overnight regime delta (MRI move),
  floor-coverage crossings, fresh catalysts, what changed since yesterday. *Guardrails:* diff-only
  mode (silent when nothing moved — honors the low-noise mandate); tripwire-aware (lead with any name
  whose φ crossed 1.0 or whose directive flipped).
- **`/expand <ticker>`** — badges are one-way post-its today; let the user pop one open into the
  agent's original reasoning + linked thread. *Subs:* a provenance line (which agent / run / scenario
  produced it); a "re-underwrite" action that re-runs the name under current state and diffs against
  the pinned thesis (a natural on-ramp to the parked trip-wire).
- **Catalyst freshness sweep** — expand the existing catalyst agent from "find new events" to
  "re-verify every active catalyst on demand," proposing edits for stale / passed / realized ones.
  *Subs:* decay-aware (flag catalysts past their expected date that never resolved — feeds the
  calibration loop's outcome capture). *Guardrail: propose, don't write — you confirm each edit.*
- **PIPELINE-panel verdict viz** — render PASS / CONDITIONAL / REJECT as a mini bar aligned to the
  Book's conviction bars, so agreement is visible at a glance. *Subs:* bull/bear split coloring once
  Idea 1 ships; stale-verdict greying when live state has drifted from when the verdict was struck.

---

## Deliberately left off (guardrails on scope)
No auto position-sizing / rebalancing, no correlation regime-switching in the primary signal,
low-noise mandate (tripwires and badges, not feeds) — all things the engine demoted on purpose. Keep
new features on the right side of that line.

## Thesis Check multi-agent (Idea 3 — reframed 2026-06-04)
Formerly the standalone "thesis trip-wire." Reframed from a lone sentinel into a **multi-agent
re-underwrite of a name's thesis**, exposed two ways: as a **skill** (fire on demand — `/thesis-check
<ticker>`) and as an **automation** (a lightweight sentinel watches live state and *triggers* the
multi-agent when a leg moves materially). The sentinel is only the trigger; the substance is the
multi-agent review.

**What the multi-agent does:** pulls the *original* thesis from memory, then re-runs the name through
the relevant lenses — bull/bear (Idea 1), regime fit (the posture dial), the calibration prior for that
archetype (Idea 2 ⑤), catalyst freshness — and **reconciles them into one verdict** under the
Signal-coherence rules: *re-affirm · press · trim · exit*, with the tension named. This is the natural
home for per-name signal reconciliation — it's the coherence layer made concrete for one name.

**Guardrails:**
- *Symmetric by design (the Druck point):* it fires on the upside too — a confirming thesis with
  **improving** asymmetry surfaces a "press-it" prompt, not just a break-warning.
- *Decision-support only* — it outputs a reconciled call and a re-underwrite; the human sizes / cuts /
  presses. Nothing moves the book on its own.
- *One verdict, dissent as caveat* — never emits competing scores; the bear's invalidation level rides
  the single verdict as a flagged caveat.

Low–medium effort; `/expand`'s re-underwrite action is the natural on-ramp. Strong candidate to un-park
(see the spine recommendation above).
