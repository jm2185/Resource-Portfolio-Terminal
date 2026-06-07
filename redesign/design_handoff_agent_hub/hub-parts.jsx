// ============================================================================
// AGENT HUB — presentational parts (runtime chips, agent rows, task / proposal
// cards, lanes). Forge-layer aligned: the fleet is uniformly Opus 4.8, so the
// chip carries the agent's RUNTIME LANE, not its model.
// ============================================================================
const HUB = window.HUB;
const agentById = id => HUB.roster.find(a => a.id === id);
const runtimeOf = id => { const a = agentById(id); return a ? HUB.runtimes[a.runtime] : null; };

// the runtime-lane badge (pane / headless / sweep / rules)
function LaneChip({ runtime, className = "" }) {
  const r = HUB.runtimes[runtime];
  if (!r) return null;
  return (
    <span className={"rchip r-" + runtime + " " + className}>
      <span className="d" />{r.label}
    </span>
  );
}

// one agent in the roster
function AgentRow({ a, sel, onClick }) {
  return (
    <div className={"agent" + (sel ? " sel" : "")} onClick={onClick}>
      <span className={"sd " + a.status} title={a.status} />
      <div style={{ minWidth: 0 }}>
        <span className="nm">{a.name}</span>
        <div className="rl">{a.role}</div>
      </div>
      <div className="right">
        <LaneChip runtime={a.runtime} />
        <span className="deleg">› delegate</span>
      </div>
    </div>
  );
}

// the proposed ACTION verb chip (trim / swap / exit / recalibrate / alert)
function ActionChip({ action }) {
  return <span className={"pact a-" + action}>{action}</span>;
}

// one PROPOSAL card — the autonomy boundary; needs your approve / reject
function ProposalCard({ p, sel, onClick, onApprove, onReject }) {
  const a = agentById(p.agent);
  return (
    <div className={"prop " + p.action + (sel ? " sel" : "")} onClick={onClick}>
      <div className="accent" />
      <div className="pbody">
        <div className="prow1">
          <ActionChip action={p.action} />
          <span className="psubj">{p.subject}</span>
          <span className="pby">{a ? a.name : p.agent}</span>
          {a && <LaneChip runtime={a.runtime} />}
          <span className="pfrom">{p.from}</span>
        </div>
        <div className="pwhat">{p.what}</div>
        <div className="pacts" onClick={e => e.stopPropagation()}>
          <button className="btn-approve" onClick={onApprove}>Approve ↵</button>
          <button className="btn-reject" onClick={onReject}>Dismiss</button>
        </div>
      </div>
    </div>
  );
}

// one task card on the board
function TaskCard({ t, sel, onClick, onCancel }) {
  const a = agentById(t.agent);
  return (
    <div className={"task " + t.state + (t.result === "flagged" ? " flagged" : "") + (sel ? " sel" : "")} onClick={onClick}>
      <div className="accent" />
      <div className="tbody">
        <div className="trow1">
          <span className="tagent">{a ? a.name : t.agent}</span>
          {a && <LaneChip runtime={a.runtime} />}
          <span className="tarrow">→</span>
          <span className="tsubj">{t.subject}</span>
          <span className="tkind">{t.kind}</span>
          <span className="tmeta">
            {t.state === "scheduled"
              ? <span className="tcadence">⏲ {t.cadence}</span>
              : t.state === "done"
                ? <span className={t.result === "flagged" ? "tflag" : "tok"}>{t.result === "flagged" ? "⚑ flagged" : "✓ ok"}</span>
                : <span>{t.elapsed}</span>}
            {t.state === "working" && <span className="x" title="cancel" onClick={e => { e.stopPropagation(); onCancel && onCancel(); }}>✕</span>}
          </span>
        </div>
        <div className="twhat">{t.what}</div>
        {t.state === "working" && (
          <div className="tprog">
            <span className="pbar"><i style={{ width: t.pct + "%" }} /></span>
            <span className="ptxt">{t.stage != null ? `${t.stage + 1}/${t.stages.length} · ${t.pct}%` : t.pct + "%"}</span>
          </div>
        )}
        {t.state === "scheduled" && (
          <div className="tprog"><span className="ptxt" style={{ color: "var(--amber)" }}>next run {t.next}</span></div>
        )}
      </div>
    </div>
  );
}

// a labeled lane wrapping a set of cards
function Lane({ glyph, title, count, note, state, children }) {
  return (
    <div className="lane">
      <div className={"lane-h " + state}>
        <span className="g">{glyph}</span>
        <span className="lt">{title}</span>
        <span className="lc">{count}</span>
        {note && <span className="ln">{note}</span>}
      </div>
      <div className="lane-body">{children}</div>
    </div>
  );
}

Object.assign(window, { LaneChip, ActionChip, AgentRow, ProposalCard, TaskCard, Lane, agentById, runtimeOf });
