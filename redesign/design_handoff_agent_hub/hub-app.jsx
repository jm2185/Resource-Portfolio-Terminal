// ============================================================================
// AGENT HUB — Mission Control (clickable), Forge-layer aligned.
// Three columns: TEAM (roster) → WORK (delegate composer + board) → FOCUS.
// The fleet runs uniformly on Opus 4.8; agents differ by ROLE + RUNTIME LANE.
// The autonomy boundary is concrete: alerts fire autonomously, while trims /
// exits / swaps land in PROPOSALS for you to approve.
// ============================================================================
const { useState, useEffect, useRef, useCallback } = React;
const HUB = window.HUB;
const { LaneChip, ActionChip, AgentRow, ProposalCard, TaskCard, Lane, agentById } = window;

let _tid = 100;
const ntid = () => "n" + (++_tid);

const AUT = [
  { id: "manual",  label: "manual",      note: <>you <b>drive</b> every run</> },
  { id: "propose", label: "propose",     note: <>agents <b>propose</b>, you approve</> },
  { id: "alerts",  label: "alerts",      note: <>alerts <b>fire</b> · trims & exits proposed</> },
];

// small dropdown field used in the composer
function Picker({ label, display, set, open, onToggle, children }) {
  return (
    <div className="field" onClick={e => e.stopPropagation()}>
      <span className="fl">{label}</span>
      <span className={"pick" + (set ? " set" : "")} onClick={onToggle}>
        {display}<span className="car">▾</span>
      </span>
      {open && <div className="menu">{children}</div>}
    </div>
  );
}

function HubApp() {
  const [tasks, setTasks] = useState(HUB.tasks);
  const [proposals, setProposals] = useState(HUB.proposals);
  const [autonomy, setAutonomy] = useState("alerts");
  const [selAgent, setSelAgent] = useState("sentinel");
  const [selTask, setSelTask] = useState(null);
  const [toast, setToast] = useState(null);

  // composer
  const [nl, setNl] = useState("");
  const [cAgent, setCAgent] = useState("sentinel");
  const [cKind, setCKind] = useState("sweep");
  const [cSubject, setCSubject] = useState("book");
  const [cWhen, setCWhen] = useState("now");
  const [menu, setMenu] = useState(null);

  // live tick — advance in-flight work
  useEffect(() => {
    const iv = setInterval(() => {
      setTasks(ts => ts.map(t => {
        if (t.state !== "working") return t;
        let pct = t.pct + 3 + Math.round(Math.random() * 3);
        let stage = t.stage;
        if (pct >= 100) { pct = 18; stage = (t.stage + 1) % t.stages.length; }
        return { ...t, pct, stage };
      }));
    }, 1500);
    return () => clearInterval(iv);
  }, []);

  const flash = (node) => { setToast(node); clearTimeout(flash._t); flash._t = setTimeout(() => setToast(null), 4600); };

  const pickAgent = (id) => {
    setSelAgent(id); setSelTask(null);
    setCAgent(id);
    const a = agentById(id);
    if (a && a.can && a.can.length) setCKind(a.can.includes(cKind) ? cKind : a.can[0]);
  };

  const fillFromCommand = (cmd) => {
    setCAgent(cmd.agent); setCKind(cmd.kind);
    setSelAgent(cmd.agent); setSelTask(null);
    if (cmd.kind === "sweep" || cmd.kind === "calibrate") setCSubject("book");
    else setCSubject(s => s && s.includes(".") ? s : "AGA.V");
    setNl(cmd.desc.replace("{ticker}", cSubject && cSubject.includes(".") ? cSubject : "AGA.V").replace("{a}→{b}", "URC.TO→MAG"));
  };

  const delegate = () => {
    const a = agentById(cAgent);
    if (!a || !cSubject) return;

    // M4 thesis-ledger writes — claims & Ulysses rules file to the Ledger
    if (cKind === "claim" || cKind === "rule") {
      const t = { id: ntid(), agent: cAgent, subject: cSubject, kind: cKind,
        what: (nl || (cKind === "rule" ? `armed: if … then alert/trim ${cSubject}` : `claim recorded for ${cSubject}`)),
        state: "done", result: "ok", elapsed: "just now" };
      setTasks(ts => [t, ...ts]);
      flash(<>{cKind === "rule" ? <>Armed a <b className="val">Ulysses rule</b></> : <>Filed a <b className="val">thesis claim</b></>} on <b className="val">{cSubject}</b> <span className="dim">— written to the Thesis Ledger, validated at save</span></>);
      setNl(""); return;
    }

    if (cWhen === "schedule") {
      const t = { id: ntid(), agent: cAgent, subject: cSubject, kind: cKind,
        what: nl || `${cKind} ${cSubject} on a schedule`, state: "scheduled",
        cadence: cKind === "sweep" ? "every 6h" : "daily · 09:00", next: cKind === "sweep" ? "in 6h" : "tomorrow" };
      setTasks(ts => [t, ...ts]);
      flash(<>Scheduled <b className="val">{a.name}</b> → {cSubject} <span className="dim">· runs respect autonomy: <b style={{ color: "var(--amber)" }}>{autonomy}</b></span></>);
    } else {
      const t = { id: ntid(), agent: cAgent, subject: cSubject, kind: cKind,
        what: nl || `${cKind} ${cSubject} — grounding now`, state: "working",
        stage: 0, stages: ["grounding context", "working", "writing result"], pct: 10, elapsed: "0:01" };
      setTasks(ts => [t, ...ts]);
      setSelTask(t.id); setSelAgent(cAgent);
      flash(<>Delegated <b className="val">{cKind}</b> to <b className="val">{a.name}</b> on <b className="val">{cSubject}</b> <span className="dim">— {HUB.runtimes[a.runtime].sub} on opus 4.8, you'll be notified</span></>);
    }
    setNl("");
  };

  const cancelTask = (id) => {
    setTasks(ts => ts.filter(t => t.id !== id));
    if (selTask === id) setSelTask(null);
    flash(<><span className="dim">Cancelled run</span></>);
  };

  const approveProposal = (p) => {
    setProposals(ps => ps.filter(x => x.id !== p.id));
    const verb = { trim: "trimming", swap: "executing swap", exit: "exiting", recalibrate: "recalibrating" }[p.action] || p.action;
    if (p.action === "recalibrate") {
      const t = { id: ntid(), agent: p.agent, subject: p.subject, kind: "calibrate",
        what: `${verb} — applying proposed bias correction`, state: "working",
        stage: 0, stages: ["recomputing priors", "regrading book", "writing scorecard"], pct: 14, elapsed: "0:01" };
      setTasks(ts => [t, ...ts]);
    } else {
      const t = { id: ntid(), agent: p.agent, subject: p.subject, kind: p.action,
        what: `${verb} ${p.subject} — ${p.what}`, state: "working",
        stage: 0, stages: ["staging order", "routing to runner", "confirming"], pct: 20, elapsed: "0:01" };
      setTasks(ts => [t, ...ts]);
    }
    flash(<>Approved <b className="val">{p.action.toUpperCase()}</b> on <b className="val">{p.subject}</b> <span className="dim">— routed to the runner</span></>);
  };
  const rejectProposal = (p) => {
    setProposals(ps => ps.filter(x => x.id !== p.id));
    flash(<><span className="dim">Dismissed</span> {p.action} on <b className="val">{p.subject}</b> <span className="dim">· logged to the Ledger</span></>);
  };

  const byState = s => tasks.filter(t => t.state === s);
  const working = byState("working"), queued = byState("queued"), scheduled = byState("scheduled"), done = byState("done");

  const selA = agentById(selAgent);
  const selT = selTask ? tasks.find(t => t.id === selTask) : null;
  const canDelegate = !!(cAgent && cSubject);
  const isLedgerKind = cKind === "claim" || cKind === "rule";

  return (
    <div className="hub" onClick={() => setMenu(null)}>

      {/* ───────── TOP CHROME ───────── */}
      <div className="hub-top">
        <div className="hub-brand">
          <span className="mark">◆</span>
          <span className="ttl">Agent Hub</span>
          <span className="sub">mission control</span>
        </div>
        <span className="fleet"><span className="k">fleet</span> <b>opus 4.8</b></span>
        <div className="hub-sep" />
        <div className="cal">
          <span className="ck">catalysts</span>
          {HUB.calendar.map((c, i) => (
            <span key={i} className={"ce " + (c.kind === "macro" ? "macro" : "")}>
              <b>{c.tk}</b> {c.ev} <span className="in">{c.in}</span>
            </span>
          ))}
        </div>
        <div className="spacer" />
        <div className="hub-stat"><span className="pip" style={{ background: "var(--amber)" }} /> <b>{proposals.length}</b> awaiting you</div>
        <div className="hub-stat"><span className="pip live" /> <b>{working.length}</b> working</div>
        <div className="hub-stat"><span className="pip" style={{ background: "var(--amber)" }} /> <b>{scheduled.length}</b> scheduled</div>
        <div className="hub-sep" />
        <div className="aut">
          <span className="k">Autonomy</span>
          <div className="dial">{AUT.map(o => (
            <button key={o.id} className={autonomy === o.id ? "on" : ""} onClick={e => { e.stopPropagation(); setAutonomy(o.id); }}>{o.label}</button>
          ))}</div>
          <span className="note">{AUT.find(o => o.id === autonomy).note}</span>
        </div>
        <div className="hub-sep" />
        <div className="esc"><span className="kbd">esc</span> close</div>
      </div>

      {/* ───────── BODY ───────── */}
      <div className="hub-body">

        {/* ===== LEFT — ROSTER ===== */}
        <div className="col col-team">
          <div className="col-h"><span className="t">Roster</span><span className="m">{HUB.roster.length} agents · opus 4.8</span></div>
          <div className="col-scroll">
            {HUB.groups.map(g => {
              const members = HUB.roster.filter(a => a.group === g.id);
              return (
                <div key={g.id}>
                  <div className="group-h">
                    <span className="gt">{g.title}</span>
                    <span className="gn">— {g.note}</span>
                    <span className="gc">{members.length}</span>
                  </div>
                  {members.map(a => <AgentRow key={a.id} a={a} sel={selAgent === a.id && !selTask} onClick={() => pickAgent(a.id)} />)}
                </div>
              );
            })}
            <div className="add-agent"><span className="p">+</span><span>New agent — name it, give it a brief & a runtime lane…</span></div>
          </div>
        </div>

        {/* ===== CENTER — DELEGATE + BOARD ===== */}
        <div className="col col-work">
          <div className="compose-wrap">
            <div className="compose-lab"><span className="t">Delegate a task</span><span className="h">describe it, or build it below · ⏎ to send</span></div>
            <div className={"composer" + (nl ? " hot" : "")}>
              <div className="nl" onClick={() => { setMenu(null); }}>
                <span className="c">›</span>
                <input value={nl} onChange={e => setNl(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && canDelegate) delegate(); }}
                  placeholder='e.g. "rule AGA.V if runway<5d then alert"  ·  "swap URC.TO→MAG"  ·  "sentinel sweep"' />
                <span className="kbd">⏎</span>
              </div>
              <div className="fields">
                <Picker label="agent" set={!!cAgent} open={menu === "agent"} onToggle={() => setMenu(menu === "agent" ? null : "agent")}
                  display={cAgent ? <><span style={{ color: "var(--text-hi)" }}>{agentById(cAgent).name}</span> <LaneChip runtime={agentById(cAgent).runtime} /></> : "pick agent"}>
                  {HUB.groups.map(g => (
                    <div key={g.id}>
                      <div className="mh">{g.title}</div>
                      {HUB.roster.filter(a => a.group === g.id).map(a => (
                        <div key={a.id} className="mi" onClick={() => { pickAgent(a.id); setMenu(null); }}>
                          {a.name}<LaneChip runtime={a.runtime} /><span className="sub" />
                        </div>
                      ))}
                    </div>
                  ))}
                </Picker>
                <span className="arrow" style={{ color: "var(--faint)", alignSelf: "flex-end", paddingBottom: 7 }}>·</span>
                <Picker label="do what" set={!!cKind} open={menu === "kind"} onToggle={() => setMenu(menu === "kind" ? null : "kind")}
                  display={cKind || "kind"}>
                  {(cAgent ? agentById(cAgent).can : HUB.kinds).map(k => (
                    <div key={k} className="mi" onClick={() => { setCKind(k); setMenu(null); }}>{k}</div>
                  ))}
                </Picker>
                <span className="arrow" style={{ color: "var(--faint)", alignSelf: "flex-end", paddingBottom: 7 }}>·</span>
                <div className="field" onClick={e => e.stopPropagation()}>
                  <span className="fl">subject</span>
                  <span className={"pick" + (cSubject ? " set" : "")}>
                    <input value={cSubject} onChange={e => setCSubject(e.target.value)} placeholder="ticker / theme"
                      onKeyDown={e => { if (e.key === "Enter" && canDelegate) delegate(); }} />
                  </span>
                </div>
                {!isLedgerKind && <>
                  <span className="arrow" style={{ color: "var(--faint)", alignSelf: "flex-end", paddingBottom: 7 }}>·</span>
                  <Picker label="when" set open={menu === "when"} onToggle={() => setMenu(menu === "when" ? null : "when")}
                    display={cWhen === "now" ? "now" : "schedule"}>
                    <div className="mi" onClick={() => { setCWhen("now"); setMenu(null); }}>now <span className="sub">one-shot</span></div>
                    <div className="mi" onClick={() => { setCWhen("schedule"); setMenu(null); }}>schedule <span className="sub">recurring</span></div>
                  </Picker>
                </>}
                <div className="compose-go">
                  <span className="go-note">{isLedgerKind ? <>files to <b>Thesis Ledger</b></> : cWhen === "schedule" ? <>respects <b>{autonomy}</b></> : <>runs on <b>opus 4.8</b></>}</span>
                  <button className={"btn-go" + (cWhen === "schedule" || isLedgerKind ? " propose" : "")} disabled={!canDelegate} onClick={delegate}>
                    {isLedgerKind ? (cKind === "rule" ? "Arm rule ⏎" : "File claim ⏎") : cWhen === "schedule" ? "Schedule ⏲" : "Delegate ⏎"}
                  </button>
                </div>
              </div>
            </div>
            <div className="cmds">
              <span className="lbl">saved commands</span>
              {HUB.commands.map(c => (
                <span key={c.id} className="cmd" onClick={() => fillFromCommand(c)} title={c.desc}>
                  <span className="g">›</span>{c.label}
                </span>
              ))}
            </div>
          </div>

          {/* THE BOARD */}
          <div className="col-scroll">
            <div className="board">
              {proposals.length > 0 && (
                <Lane glyph="⚑" title="Proposals" count={proposals.length} state="proposed" note="awaiting your approval">
                  {proposals.map(p => (
                    <ProposalCard key={p.id} p={p}
                      sel={false}
                      onClick={() => { setSelAgent(p.agent); setSelTask(null); }}
                      onApprove={() => approveProposal(p)} onReject={() => rejectProposal(p)} />
                  ))}
                </Lane>
              )}
              <Lane glyph="⟳" title="Working" count={working.length} state="working" note="live now">
                {working.length ? working.map(t => <TaskCard key={t.id} t={t} sel={selTask === t.id} onClick={() => { setSelTask(t.id); setSelAgent(t.agent); }} onCancel={() => cancelTask(t.id)} />)
                  : <div className="empty">no agents working — delegate above</div>}
              </Lane>
              <Lane glyph="◷" title="Queued" count={queued.length} state="queued" note="next up">
                {queued.map(t => <TaskCard key={t.id} t={t} sel={selTask === t.id} onClick={() => { setSelTask(t.id); setSelAgent(t.agent); }} />)}
              </Lane>
              <Lane glyph="⏲" title="Scheduled" count={scheduled.length} state="scheduled" note="recurring">
                {scheduled.map(t => <TaskCard key={t.id} t={t} sel={selTask === t.id} onClick={() => { setSelTask(t.id); setSelAgent(t.agent); }} />)}
              </Lane>
              <Lane glyph="✓" title="Done today" count={done.length} state="done">
                {done.map(t => <TaskCard key={t.id} t={t} sel={selTask === t.id} onClick={() => { setSelTask(t.id); setSelAgent(t.agent); }} />)}
              </Lane>
            </div>
          </div>
        </div>

        {/* ===== RIGHT — INSPECTOR ===== */}
        <div className="col col-focus">
          {selT ? <TaskInspector t={selT} onClose={() => setSelTask(null)} onCancel={() => cancelTask(selT.id)} />
                : selA ? <AgentInspector a={selA}
                    schedules={tasks.filter(t => t.state === "scheduled" && t.agent === selA.id)}
                    onDelegate={() => { setCAgent(selA.id); setCWhen("now"); delegate(); }}
                    onKind={(k) => { setCAgent(selA.id); setCKind(k); }}
                    onSchedule={() => { setCAgent(selA.id); setCWhen("schedule"); }} />
                : <div className="empty"><div className="big">Nothing focused</div>Pick an agent or a task to see its detail here.</div>}
        </div>
      </div>

      {/* ───────── FOOTER ───────── */}
      <div className="hub-foot">
        <span><span className="k">↵</span> delegate</span>
        <span><span className="k">⚑</span> approve proposals</span>
        <span><span className="k">⏲</span> schedule</span>
        <span><span className="k">click</span> an agent to delegate · a task to inspect</span>
        <span className="r"><span className="hub-stat"><span className="pip live" /> sentinel is watching the book</span> · autonomy: <b style={{ color: "var(--amber)" }}>{AUT.find(o => o.id === autonomy).label}</b></span>
      </div>

      {toast && <div className="hub-toast">{toast}</div>}
    </div>
  );
}

// ---- inspector: an agent ----------------------------------------------------
function AgentInspector({ a, schedules, onDelegate, onKind, onSchedule }) {
  const r = HUB.runtimes[a.runtime];
  const outs = HUB.outputs[a.id] || [];
  return (
    <div className="insp">
      <div className="insp-scroll">
        <div className="insp-head">
          <div className="nm">{a.name}</div>
          <div className="modeline">
            <LaneChip runtime={a.runtime} />
            <span className="runs">opus 4.8 · {r.sub}</span>
          </div>
          <div className="role">{a.role}</div>
        </div>

        {a.watches && (
          <div className="insp-sec">
            <div className="sh">Watching <span className="c">every 6h sweep</span></div>
            {a.watches.map((w, i) => (
              <div className="watch-row" key={i}>
                <span className={"wd " + w.status} />
                <div className="body"><div className="wk">{w.k}</div><div className="wn">{w.note}</div></div>
                <span className="wv">{w.v}</span>
              </div>
            ))}
          </div>
        )}

        <div className="insp-sec">
          <div className="sh">Can do <span className="c">click to load the composer</span></div>
          <div className="can">{a.can.map(k => <span key={k} className="k" onClick={() => onKind(k)}>{k}</span>)}</div>
        </div>
        <div className="insp-sec">
          <div className="sh">Recurring <span className="c">{schedules.length || "none"}</span></div>
          {schedules.length ? schedules.map(s => (
            <div className="sched-row" key={s.id}>
              <span className="ic">⏲</span>
              <div className="body">
                <div className="l1"><span className="tk">{s.subject}</span> — {s.what}</div>
                <div className="l2">{s.cadence}</div>
              </div>
              <span className="when">{s.next}</span>
            </div>
          )) : <div style={{ fontSize: "var(--fs-2xs)", color: "var(--faint)" }}>No standing jobs. Use <b style={{ color: "var(--amber)", fontWeight: 400 }}>Schedule</b> below to add one.</div>}
        </div>
        <div className="insp-sec" style={{ borderBottom: 0 }}>
          <div className="sh">{a.watches ? "Recent alerts" : "Recent outputs"}</div>
          {outs.length ? outs.map((o, i) => (
            <div className="out-row" key={i}>
              <span className={"dot " + o.level} />
              <div className="body"><div className="ot">{o.text}</div><div className="om">{o.meta}</div></div>
            </div>
          )) : <div style={{ fontSize: "var(--fs-2xs)", color: "var(--faint)" }}>No runs yet.</div>}
        </div>
      </div>
      <div className="insp-foot">
        <button className="btn-deleg" onClick={onDelegate}>Delegate to {a.name}</button>
        <button className="btn-sched" onClick={onSchedule}>Schedule…</button>
      </div>
    </div>
  );
}

// ---- inspector: a task ------------------------------------------------------
function TaskInspector({ t, onClose, onCancel }) {
  const a = agentById(t.agent);
  const log = {
    working: [["gln", "$ "], ["tl", "agent " + t.agent + " · opus 4.8"], ["gln", "\n› grounding "], ["ok", t.subject], ["gln", " context…\n› "], ["am", t.what]],
    done: [["gln", "$ "], ["tl", "agent " + t.agent], ["gln", "\n› complete — "], [t.result === "flagged" ? "am" : "ok", t.result === "flagged" ? "⚑ 1 issue flagged" : "✓ clean"], ["gln", "\n› written to Living Memory"]],
    queued: [["gln", "queued — waiting on a free slot…\nposition: " + (t.elapsed || "")]],
    scheduled: [["gln", "standing job — "], ["am", t.cadence], ["gln", "\nnext run " + t.next]],
  }[t.state] || [];
  return (
    <div className="insp">
      <div className="insp-scroll">
        <div className="insp-head">
          <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
            <span className="nm" style={{ fontSize: "var(--fs-lg)" }}>{t.agent}</span>
            {a && <LaneChip runtime={a.runtime} />}
            <span style={{ color: "var(--faint)" }}>→</span>
            <span className="nm" style={{ fontSize: "var(--fs-lg)", color: "var(--gold)" }}>{t.subject}</span>
          </div>
          <div className="modeline"><span className="tkind" style={{ fontSize: 9, color: "var(--dim)", textTransform: "uppercase", letterSpacing: ".06em", border: "1px solid var(--line)", borderRadius: 3, padding: "1px 6px" }}>{t.kind}</span><span className="runs">{t.state}{t.elapsed ? " · " + t.elapsed : ""}</span></div>
          <div className="role">{t.what}</div>
        </div>
        {t.state === "working" && t.stages && (
          <div className="insp-sec">
            <div className="sh">Stages <span className="c">{t.stage + 1} of {t.stages.length}</span></div>
            <div className="stage-list">
              {t.stages.map((s, i) => (
                <div key={i} className={"stage-item " + (i < t.stage ? "done" : i === t.stage ? "now" : "todo")}>
                  <span className="sg">{i < t.stage ? "✓" : i === t.stage ? "▸" : "·"}</span>
                  <span className="lab">{s}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="insp-sec" style={{ borderBottom: 0 }}>
          <div className="sh">Live log</div>
          <div className="logtail">{log.map(([c, txt], i) => <span key={i} className={c}>{txt}</span>)}</div>
        </div>
      </div>
      <div className="insp-foot">
        {t.state === "working"
          ? <><button className="btn-deleg" onClick={() => {}}>Open in pane ↗</button><button className="btn-sched" onClick={onCancel}>Cancel run</button></>
          : <button className="btn-sched" style={{ flex: 1 }} onClick={onClose}>Close detail</button>}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<HubApp />);
