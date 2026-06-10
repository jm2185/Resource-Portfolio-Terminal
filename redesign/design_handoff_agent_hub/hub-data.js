// ============================================================================
// AGENT HUB — fake-but-authentic delegation state, Forge-layer aligned.
//
// The fleet now runs UNIFORMLY on Opus 4.8 — so the differentiator is no longer
// "which model" but the agent's ROLE and its RUNTIME LANE:
//    pane     — interactive (a live Claude pane)
//    headless — background red-team / scout
//    sweep    — scheduled watcher (the Sentinel)
//    rules    — deterministic local audit
//
// The Forge layer adds: the SENTINEL (the book that watches itself, 6h sweep),
// the Thesis Ledger (claims + Ulysses rules), Council SWAPS (challenger vs
// incumbent), and calibration with seeded priors. The autonomy boundary is now
// concrete: alerts fire autonomously; trims / exits / swaps surface as PROPOSALS.
// ============================================================================
window.HUB = {
  fleet: { model: "opus 4.8", note: "every agent runs on Opus 4.8" },

  // the runtime lanes (the new visual differentiator)
  runtimes: {
    pane:     { label: "pane",     sub: "interactive pane" },
    headless: { label: "headless", sub: "background run" },
    sweep:    { label: "sweep",    sub: "scheduled watcher" },
    rules:    { label: "rules",    sub: "deterministic local" },
  },

  groups: [
    { id: "sentinel", title: "The Sentinel",        note: "the book that watches itself" },
    { id: "council",  title: "Dialectic Council",   note: "verdict & swaps" },
    { id: "research", title: "Research Pipeline",    note: "scout → synthesize → gate" },
    { id: "audit",    title: "Calibration & Audit",  note: "keep the book honest" },
  ],

  // the team
  roster: [
    { id: "sentinel", name: "sentinel", group: "sentinel", runtime: "sweep", status: "watching",
      role: "The watching brain — liquidity-runway, financing-window / death-spiral, thesis-integrity and fired Ulysses rules. Sweeps the book every 6h; alerts fire on its own, trims & exits it only proposes.",
      can: ["sweep", "liquidity", "death-spiral", "thesis-integrity"],
      watches: [
        { k: "liquidity-runway",            v: "5d ADV cap",      status: "warn", note: "AGA.V 4.2d — below floor" },
        { k: "financing-window",            v: "dilution ≤2% QoQ", status: "ok",   note: "no name in window" },
        { k: "thesis-integrity",            v: "claims vs tape",   status: "warn", note: "URC.TO — 1 claim drifting" },
        { k: "Ulysses rules",               v: "12 armed",         status: "ok",   note: "0 fired this sweep" },
      ] },

    { id: "arbiter",   name: "arbiter",   group: "council",  runtime: "pane",     status: "idle",
      role: "The Council's judge — reconciles Bull & Bear into one verdict, and arbitrates swaps (challenger vs incumbent) on a friction-adjusted hurdle + catalyst lock.",
      can: ["council", "swap", "explain", "ask"] },
    { id: "bull",      name: "bull",      group: "council",  runtime: "pane",     status: "idle",
      role: "The Council's long advocate — argues the upside case.",
      can: ["thesis", "ask"] },
    { id: "bear",      name: "bear",      group: "council",  runtime: "headless", status: "working",
      role: "The Council's Bear + Liquidity Sentinel — argues the downside, feeds the Sentinel's death-spiral read.",
      can: ["red-team", "liquidity", "ask"] },

    { id: "scout",     name: "scout",     group: "research", runtime: "headless", status: "scheduled",
      role: "Opportunity finder across the silver / junior-mining universe; seeds the catalyst calendar grounded-or-silent.",
      can: ["scout", "screen", "compare"] },
    { id: "synthesis", name: "synthesis", group: "research", runtime: "pane",     status: "working",
      role: "Aggregator / analyst for the research pipeline.",
      can: ["synthesize", "compare", "ask"] },
    { id: "verifier",  name: "verifier",  group: "research", runtime: "headless", status: "idle",
      role: "Forensic red-team and final gate of the research pipeline.",
      can: ["verify", "red-team", "gate"] },

    { id: "calibration",            name: "calibration",            group: "audit", runtime: "rules",    status: "idle",
      role: "Grades the book against seeded priors (MinEx / Schodde, S&P Global). Reports a credible interval — never a bare %. Proposes bias corrections; never applies them.",
      can: ["calibrate", "grade", "bias-scan"] },
    { id: "catalyst-verifier",      name: "catalyst-verifier",      group: "audit", runtime: "headless", status: "idle",
      role: "Verifies calendar catalysts straight-to-source — grounded-or-silent, never invents a date.",
      can: ["catalyst", "verify", "audit"] },
    { id: "data-integrity-auditor", name: "data-integrity-auditor", group: "audit", runtime: "rules",    status: "idle",
      role: "Audits the book for ticker → company → archetype drift.",
      can: ["audit", "grade"] },
    { id: "conviction-analyst",     name: "conviction-analyst",     group: "audit", runtime: "pane",     status: "working",
      role: "Explains a holding's Conviction-Mode rating, pillar by pillar, against the seeded priors.",
      can: ["explain", "ask"] },
  ],

  // ── PROPOSALS — the autonomy boundary. Agents surface these; you approve. ──
  proposals: [
    { id: "p1", agent: "sentinel", subject: "AGA.V", kind: "liquidity", action: "trim",
      what: "liquidity-runway 4.2d < 5d floor — trim 0.6% of book to fit ADV", from: "6m ago · sweep" },
    { id: "p2", agent: "arbiter", subject: "URC.TO → MAG", kind: "swap", action: "swap",
      what: "MAG clears the friction-adjusted hurdle (+0.41 > 0.35) · catalyst lock open", from: "22m ago · council" },
    { id: "p3", agent: "calibration", subject: "spears", kind: "bias-scan", action: "recalibrate",
      what: "conviction inflation +0.4 detected on spears (n=18) — propose recalibrate, never auto-applied", from: "1h ago" },
  ],

  // the live board
  tasks: [
    { id: "t1", agent: "conviction-analyst", subject: "AGA.V", kind: "explain",
      what: "reading forensics · verifying catalysts", state: "working",
      stage: 2, stages: ["grounding context", "reading forensics", "verifying catalysts", "writing rationale"],
      pct: 52, elapsed: "0:08" },
    { id: "t2", agent: "synthesis", subject: "book", kind: "council",
      what: "council 2 of 3 · GMX approve · URC conditional", state: "working",
      stage: 1, stages: ["bull filing", "bear filing", "arbiter reconciling"],
      pct: 64, elapsed: "1:12" },

    { id: "q1", agent: "verifier", subject: "MAG", kind: "verify",
      what: "forensic gate — dilution, liquidity, permit risk", state: "queued", elapsed: "queued · 2nd" },
    { id: "q2", agent: "scout", subject: "DSV.V", kind: "scout",
      what: "screening silver developer vs book peers", state: "queued", elapsed: "queued · 3rd" },

    { id: "s0", agent: "sentinel", subject: "book", kind: "sweep",
      what: "liquidity · death-spiral · thesis-integrity · armed rules", state: "scheduled",
      cadence: "every 6h", next: "in 2h" },
    { id: "s1", agent: "scout", subject: "silver universe", kind: "scout",
      what: "scan for new names clearing the forensic gate", state: "scheduled",
      cadence: "daily · 14:40", next: "in 6h" },
    { id: "s2", agent: "bear", subject: "AGA.V", kind: "red-team",
      what: "red-team the spear — fresh dilution & liquidity read", state: "scheduled",
      cadence: "weekly · Mon 08:00", next: "in 3d" },
    { id: "s3", agent: "calibration", subject: "book", kind: "calibrate",
      what: "grade last week's closed decisions vs seeded priors", state: "scheduled",
      cadence: "weekly · Fri 16:30", next: "in 4d" },

    { id: "d0", agent: "sentinel", subject: "book", kind: "sweep",
      what: "swept 23 names · 0 Ulysses rules fired · 1 alert raised", state: "done", result: "ok", elapsed: "today 06:00" },
    { id: "d1", agent: "catalyst-verifier", subject: "AGA.V", kind: "catalyst",
      what: "PEA confirmed Q1-27 straight-to-source", state: "done", result: "ok", elapsed: "2h ago" },
    { id: "d2", agent: "bear", subject: "URC.TO", kind: "red-team",
      what: "methodology audit — flagged 1 stale catalyst", state: "done", result: "flagged", elapsed: "40m ago" },
  ],

  // saved prompt templates — Forge entry points (M4 catalyst:/claim:/rule:)
  commands: [
    { id: "sweep",     label: "sentinel sweep",      kind: "sweep",    agent: "sentinel",
      desc: "Run the watch now — liquidity, death-spiral, thesis-integrity, rules" },
    { id: "swap",      label: "swap {a}→{b}",         kind: "swap",     agent: "arbiter",
      desc: "Arbitrate a swap: challenger vs incumbent on the friction hurdle" },
    { id: "catalyst",  label: "catalyst {ticker}",    kind: "catalyst", agent: "catalyst-verifier",
      desc: "Verify {ticker}'s catalysts straight-to-source, grounded-or-silent" },
    { id: "rule",      label: "rule {ticker} if …",   kind: "rule",     agent: "sentinel",
      desc: "Arm a Ulysses rule on the Thesis Ledger — fires when its trigger is true" },
    { id: "claim",     label: "claim {ticker} …",     kind: "claim",    agent: "arbiter",
      desc: "Record a thesis claim on the Thesis Ledger" },
    { id: "calibrate", label: "calibrate book",       kind: "calibrate", agent: "calibration",
      desc: "Grade the book against seeded priors; report credible intervals" },
  ],

  // catalyst calendar — surfaced as ambient context (next windows)
  calendar: [
    { tk: "AGA.V",  ev: "PEA",        in: "38d", kind: "name" },
    { tk: "MAG",    ev: "drill assays", in: "11d", kind: "name" },
    { tk: "macro",  ev: "FOMC",       in: "6d",  kind: "macro" },
  ],

  // recent agent outputs / alerts, keyed by agent id (for the inspector)
  outputs: {
    sentinel: [
      { level: "warn", text: "AGA.V — liquidity-runway 4.2d, below 5d floor · trim proposed", meta: "6m ago · this sweep" },
      { level: "good", text: "death-spiral scan clean — no name inside financing window", meta: "today 06:00" },
      { level: "info", text: "12 Ulysses rules armed · 0 fired", meta: "today 06:00" },
    ],
    arbiter: [
      { level: "good", text: "AGA.V — RE-AFFIRM · below-floor accumulate (0.75× cap)", meta: "8m ago · council verdict" },
      { level: "info", text: "URC.TO → MAG — swap proposed, challenger clears hurdle", meta: "22m ago" },
    ],
    calibration: [
      { level: "warn", text: "spears — conviction inflation +0.4 (n=18) · recalibrate proposed", meta: "1h ago" },
      { level: "info", text: "discovery→mine prior 0.50 [0.34–0.67] · MinEx/Schodde", meta: "seeded" },
    ],
    bear: [
      { level: "warn", text: "URC.TO — stale catalyst flagged · methodology audit", meta: "40m ago" },
      { level: "warn", text: "AGA.V — junior G&A burn → dilution risk", meta: "12m ago · injected" },
    ],
    "catalyst-verifier": [
      { level: "good", text: "AGA.V PEA confirmed Q1-27 straight-to-source", meta: "2h ago" },
    ],
    "conviction-analyst": [
      { level: "good", text: "AGA.V — V pillar 8.8: payoff 27x, +17% catalyst-adjusted", meta: "12m ago · injected to memory" },
      { level: "info", text: "GMX.TO — rating 6.3, below fair value, accumulate", meta: "2h ago" },
    ],
  },

  subjects: ["AGA.V", "URC.TO", "GROY", "GMX.TO", "DSV.V", "MAG", "book", "silver universe"],
  kinds: ["ask", "explain", "sweep", "swap", "catalyst", "rule", "claim", "red-team", "verify", "compare", "scout", "audit", "council", "calibrate", "bias-scan"],
};
