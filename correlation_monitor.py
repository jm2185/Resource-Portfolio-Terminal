"""
correlation_monitor.py — is this a SECOND THESIS, or one bet with extra commissions?

The conventional-equity core exists for one reason: to win and lose for DIFFERENT REASONS than the
silver spear, so it can compound in the AI-upside (C) and benign (E) scenarios the resource book
leaves red — and thereby *fund* the concentrated silver bet instead of diluting it (the Druckenmiller
multi-thesis point). The whole justification collapses if the new sleeve just rides the same factor:
two positions at ρ 0.8 are one bet wearing two tickers. This module is the gauge that SETTLES that
with a number instead of a narrative. (Phase 1 of docs/DUAL_SIDED_TIV_BUILD_SPEC.md.)

Two jobs ``book_factor`` cannot do (it only sees HELD names, and only the cached level):
  • **Pre-add verdict** — score a CANDIDATE's return correlation to the spear / the book BEFORE a
    position exists (``assess_candidate``), so a redundant leveraged-steepener bet (the banks) or a
    junior-mining-beta-in-disguise (URNJ) is screened OUT at the gate — INDEPENDENT / PARTIAL /
    REDUNDANT, the test being "different reasons", not "different sector".
  • **Drift, not just level** — a ballast that *was* ρ 0.4 and is *now* ρ 0.7 and climbing has quietly
    stopped being ballast LONG before it crosses ``book_factor``'s static 0.85 line. ``drift`` is the
    slope (short-window ρ vs long-window ρ); ``assess_book_independence`` fires it per name, lane-aware
    (a CONVENTIONAL sleeve correlating to the spear is the alarm that matters most).

Signed correlation is read honestly: a strongly NEGATIVE ρ is not redundancy, it is a hedge (the best
kind of "different reason"), so the redundancy test is on POSITIVE ρ only; negative reads as
INDEPENDENT.

It MEASURES; it never sizes, allocates, or recommends a trade — the conviction dial stays the
operator's (the ``book_factor`` discipline). Pure + dependency-free (plain math, no numpy/pandas) so
the whole loop is unit-testable off the engine; the engine leg only marshals already-cached return
frames into these — NO new network in the pure layer. Thresholds tunable via /confirm
(``correlation_monitor.*``); graceful on thin inputs; never raises; no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_CORRELATION_CONFIG", "CORRELATION_GLOSSARY", "correlation_tooltip",
           "returns_from_closes", "align_returns", "pearson", "independence_verdict",
           "assess_candidate", "drift", "assess_book_independence", "select_fresh",
           "book_macro_summary", "screen_uncorrelated", "RESOURCE_FACTORS"]

DEFAULT_CORRELATION_CONFIG: dict[str, Any] = {
    "window_short": 60,        # the live read (matches the engine's cached 60d correlation matrix)
    "window_long": 120,        # the slow read, for the drift trend
    "independent_max": 0.30,   # ρ ≤ this vs the spear/book ⇒ INDEPENDENT (a real 2nd thesis; <0 = a hedge)
    "redundant_min": 0.60,     # ρ ≥ this ⇒ REDUNDANT (one bet, extra commissions); strictly between = PARTIAL
    "drift_warn": 0.10,        # ρ_short − ρ_long ≥ this (heading INTO correlation) ⇒ a sleeve creeping to the spear
    "min_n": 30,               # fewer date-aligned points ⇒ INSUFFICIENT, never a guess
}

CORRELATION_GLOSSARY: dict[str, dict[str, str]] = {
    "independence_verdict": {
        "what": "ρ of a name's returns to the SPEAR (and the book) — the test of whether it is a real second thesis or a redundant bet.",
        "scale": "ρ ≤ 0.30 INDEPENDENT (wins/loses for different reasons; negative = a hedge) · 0.30–0.60 PARTIAL (diversifies but shares a beta) · ≥ 0.60 REDUNDANT (one bet, extra commissions).",
        "influence": "A pre-add screen + a held-book monitor; gates a candidate, never sizes it. The Druckenmiller test is 'different REASONS', not 'different sector' — URNJ and the banks fail it despite different exposures.",
        "edge": "Correlation, not story: a name can look diversifying on the surface and still ride the spear's risk-appetite/real-rates beta. The number catches what the narrative hides.",
    },
    "correlation_drift": {
        "what": "Short-window ρ to the spear rising above the long-window ρ — a sleeve heading INTO correlation.",
        "scale": "FLAG when ρ_short − ρ_long ≥ ~0.10 AND ρ_short is in correlated territory (not a hedge tightening). Warn for ballast; risk for a conventional sleeve that is SUPPOSED to be independent.",
        "influence": "A SENTINEL event (pin + Living-Memory note), never a trade trigger — the trend companion to book_factor's static 0.85 level alarm. It fires BEFORE the level does.",
        "edge": "A ballast quietly stops being ballast on the way up, not at the threshold — the slope is the early warning the level can't give.",
    },
    "redundant_thesis": {
        "what": "A candidate whose returns correlate to the spear at/above the redundancy bar.",
        "scale": "ρ ≥ 0.60 to the spear ⇒ REDUNDANT — adding it concentrates the existing bet rather than adding a thesis.",
        "influence": "Screens the candidate OUT at the gate (the conventional core's first filter, in place of the resource slot-fit gate). Decision-support; the operator still decides.",
        "edge": "It is what would have screened the banks out as a leveraged-steepener duplicate of the gold the book already holds — the capability working.",
    },
    "diversifier_screen": {
        "what": "The book's macro-correlation read + a candidate universe ranked by INDEPENDENCE from the book — the search for a genuine second thesis.",
        "scale": "MEASURED ρ when a candidate has return history (INDEPENDENT/PARTIAL/REDUNDANT); a FACTOR-class PROXY otherwise (distinct-factor = likely uncorrelated; same-factor = likely correlated, measure to confirm).",
        "influence": "Surfaces names that win/lose for DIFFERENT reasons than the spear; the proxy says 'backfill prices to measure'. Decision-support; never sizes.",
        "edge": "If the whole universe loads the book's single factor, the honest result is 'no structural diversifier here' — which is itself the finding (the conventional core is where diversification lives).",
    },
}

#: the resource-metal factor family the book (the silver/junior-mining barbell) loads — used by the
#: factor-class PROXY when a candidate has no return history to measure. A candidate whose dominant
#: factor is NOT in this set (a conventional business) is a likely structural diversifier.
RESOURCE_FACTORS: frozenset = frozenset({"silver", "gold", "uranium", "copper", "cobalt", "nickel",
                                         "lithium", "ag", "au", "u", "cu", "co", "ni", "li"})


def correlation_tooltip(key: str) -> str:
    e = CORRELATION_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_CORRELATION_CONFIG)
    block = (config or {}).get("correlation_monitor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def _corr(corr_matrix: Optional[dict], a: str, b: str) -> Optional[float]:
    """Symmetric correlation lookup that tolerates either key order and casing. None if absent.
    (Same contract as ``book_factor._corr`` — the two read the SAME cached matrix.)"""
    m = corr_matrix or {}
    for x, y in ((a, b), (b, a)):
        row = m.get(x)
        if not isinstance(row, dict):
            row = m.get(x.upper()) if isinstance(m.get(x.upper()), dict) else None
        if isinstance(row, dict):
            v = _num(row.get(y))
            if v is None:
                v = _num(row.get(y.upper()))
            if v is not None:
                return v
    return None


# ---------------------------------------------------------------------------------------------------
# Input prep — turn a cached daily-close store (price_history.py) into the date-aligned return frames
# the correlations consume. Pure: the MCP/engine consumer just marshals the store into these; the math
# (returns, alignment) is tested here, off the engine.
# ---------------------------------------------------------------------------------------------------

def returns_from_closes(closes: Any) -> list:
    """Daily simple returns from a close series — ``[(date, close)]`` (any order) or ``{date: close}``.
    Returns ``[(date, ret)]`` oldest-first, one per consecutive pair, skipping non-positive/garbled
    prints. Pure; the date on each return is the LATER day (so two series align on the same axis)."""
    items = sorted((closes or {}).items()) if isinstance(closes, dict) \
        else sorted((d, c) for d, c in (closes or []))
    out = []
    for i in range(1, len(items)):
        c0, c1 = _num(items[i - 1][1]), _num(items[i][1])
        if c0 is not None and c1 is not None and c0 > 0:
            out.append((items[i][0], c1 / c0 - 1.0))
    return out


def align_returns(returns_by_ticker: Any) -> tuple:
    """Date-align per-ticker return series onto their COMMON dates (intersection), so a correlation is
    computed only over sessions every name traded. Input ``{ticker: [(date, ret)]}``; returns
    ``({ticker: [ret]}, [common_dates])`` ordered oldest-first. Pure — the alignment the engine's
    pandas frame does for free, done in stdlib for the candidate path."""
    series = {tk: dict(v or []) for tk, v in (returns_by_ticker or {}).items() if v}
    series = {tk: s for tk, s in series.items() if s}
    if not series:
        return {}, []
    common = set.intersection(*[set(s.keys()) for s in series.values()])
    dates = sorted(common)
    return {tk: [s[d] for d in dates] for tk, s in series.items()}, dates


def pearson(a_returns: Any, b_returns: Any, *, min_n: int = 2) -> Optional[float]:
    """Pearson correlation of two return series, r = cov / (σa·σb), clamped to [−1, 1]. The series
    must be DATE-ALIGNED by the caller (the engine pulls both from the same comps-worker frame); they
    are tail-aligned to the shorter length here, mirroring ``divergence_monitor.baseline_from_returns``.
    None on too few aligned points or a zero-variance leg — never a fabricated number. Plain math."""
    a = [v for v in (_num(x) for x in (a_returns or [])) if v is not None]
    b = [v for v in (_num(x) for x in (b_returns or [])) if v is not None]
    n = min(len(a), len(b))
    if n < max(2, int(min_n)):
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    r = cov / ((va * vb) ** 0.5)
    return max(-1.0, min(1.0, r))


def independence_verdict(rho: Any, *, config: Optional[dict] = None) -> dict:
    """Classify a (signed) correlation as INDEPENDENT / PARTIAL / REDUNDANT / INSUFFICIENT. Negative ρ
    reads as INDEPENDENT (a hedge — the best 'different reason'); only POSITIVE co-movement counts as
    redundancy. Returns the verdict, a short label, and a plain read. Pure."""
    cfg = _cfg(config)
    r = _num(rho)
    ind, red = float(cfg["independent_max"]), float(cfg["redundant_min"])
    if r is None:
        return {"verdict": "INSUFFICIENT", "rho": None,
                "label": "ρ n/a", "read": "not enough aligned return history to judge independence"}
    if r <= ind:
        v, lab = "INDEPENDENT", ("hedge (ρ<0)" if r < 0 else "genuinely independent")
        read = f"ρ {r:+.2f} — {lab}; wins and loses for different reasons than the spear"
    elif r < red:
        v, lab = "PARTIAL", "partial — diversifies but shares a beta"
        read = f"ρ {r:+.2f} — partial overlap; it diversifies but rides some of the spear's beta"
    else:
        v, lab = "REDUNDANT", "redundant — one bet, extra commissions"
        read = f"ρ {r:+.2f} — REDUNDANT; this concentrates the existing bet, it is not a second thesis"
    return {"verdict": v, "rho": round(r, 3), "label": lab, "read": read}


def _weighted_book_series(book_returns_by_ticker: Any, weights: Optional[dict], *,
                          exclude: Optional[set] = None) -> list:
    """Build the book's PORTFOLIO return series Σ wᵢ·rᵢ from per-name return lists (renormalized over
    the names actually present), tail-aligned to the shortest. The caller's lists must be date-aligned.
    Equal-weight when no weights given. Returns [] when nothing usable. Pure."""
    exclude = exclude or set()
    series = {}
    for t, rets in (book_returns_by_ticker or {}).items():
        if t in exclude:
            continue
        vals = [v for v in (_num(x) for x in (rets or [])) if v is not None]
        if vals:
            series[t] = vals
    if not series:
        return []
    n = min(len(v) for v in series.values())
    if n < 2:
        return []
    w = {t: (max(0.0, _num((weights or {}).get(t)) or 0.0)) for t in series}
    if sum(w.values()) <= 0:
        w = {t: 1.0 for t in series}                       # equal-weight fallback
    wsum = sum(w.values())
    aligned = {t: v[-n:] for t, v in series.items()}
    return [sum(w[t] * aligned[t][i] for t in series) / wsum for i in range(n)]


def assess_candidate(cand_returns: Any, book_returns_by_ticker: Any, *, spear: str = "AGA.V",
                     weights: Optional[dict] = None, name: str = "", config: Optional[dict] = None) -> dict:
    """The PRE-ADD screen. Score a candidate's return correlation to the SPEAR specifically (the
    dominant bet a second thesis must be independent FROM) and to the whole book (the weighted
    portfolio series), and return the verdict + the SENTINEL flag when REDUNDANT. ``book_returns_by_
    ticker`` is ``{ticker: [returns]}`` for the held names (date-aligned to ``cand_returns`` by the
    caller). The headline verdict is on ρ-to-spear; ρ-to-book is reported alongside. Pure; graceful —
    no spear history ⇒ INSUFFICIENT, never a guess."""
    cfg = _cfg(config)
    min_n = int(cfg["min_n"])
    spear_rets = (book_returns_by_ticker or {}).get(spear)
    rho_spear = pearson(cand_returns, spear_rets, min_n=min_n)
    book_series = _weighted_book_series(book_returns_by_ticker, weights, exclude=set())
    rho_book = pearson(cand_returns, book_series, min_n=min_n)

    verdict = independence_verdict(rho_spear, config=config)
    book_v = independence_verdict(rho_book, config=config)
    available = rho_spear is not None or rho_book is not None

    flags, events = [], []
    nm = name or "candidate"
    if verdict["verdict"] == "REDUNDANT":
        flags.append({"id": "redundant_thesis", "ticker": name or None, "level": "warn", "active": True,
                      "corr": verdict["rho"],
                      "text": f"{nm} ρ{verdict['rho']:+.2f} to {spear} — REDUNDANT; concentrates the existing bet, not a 2nd thesis"})
        events.append({"type": "correlation", "level": "warn", "ticker": name or None,
                       "text": f"{nm} screened REDUNDANT — ρ{verdict['rho']:+.2f} to {spear}; a leveraged duplicate, not an independent thesis"})
    elif verdict["verdict"] == "PARTIAL":
        flags.append({"id": "partial_thesis", "ticker": name or None, "level": "info", "active": True,
                      "corr": verdict["rho"],
                      "text": f"{nm} ρ{verdict['rho']:+.2f} to {spear} — PARTIAL; diversifies but shares a beta (name the overlap)"})

    if not available:
        read = f"{nm}: independence n/a (need ≥{min_n} aligned return points vs {spear}/the book)"
    else:
        sp = f"ρ{rho_spear:+.2f} to {spear}" if rho_spear is not None else f"ρ n/a to {spear}"
        bk = f"ρ{rho_book:+.2f} to book" if rho_book is not None else "ρ n/a to book"
        read = f"{nm}: {sp}, {bk} → {verdict['verdict']}"

    return {"available": available, "name": name, "spear": spear,
            "rho_to_spear": (round(rho_spear, 3) if rho_spear is not None else None),
            "rho_to_book": (round(rho_book, 3) if rho_book is not None else None),
            "verdict": verdict["verdict"], "verdict_label": verdict["label"],
            "book_verdict": book_v["verdict"], "read": read, "flags": flags, "events": events,
            "glossary": {k: correlation_tooltip(k) for k in CORRELATION_GLOSSARY}}


def drift(rho_short: Any, rho_long: Any, *, ticker: str = "", spear: str = "AGA.V",
          lane: str = "", config: Optional[dict] = None) -> dict:
    """The TREND gauge: a sleeve heading INTO correlation with the spear. ``delta = ρ_short − ρ_long``;
    DRIFTING when delta ≥ ``drift_warn`` AND ρ_short is in correlated territory (> independent_max) —
    so a hedge tightening from −0.4 to −0.2 does NOT fire (it is getting MORE useful), only a name
    climbing toward the spear does. A CONVENTIONAL sleeve that is supposed to be independent escalates
    the level (warn → risk). Returns the flag the SENTINEL fires. Pure; graceful."""
    cfg = _cfg(config)
    rs, rl = _num(rho_short), _num(rho_long)
    ind, warn = float(cfg["independent_max"]), float(cfg["drift_warn"])
    tk = ticker or "name"
    if rs is None or rl is None:
        return {"available": False, "ticker": ticker, "drifting": False, "delta": None,
                "rho_short": rs, "rho_long": rl, "flags": [], "events": [],
                "read": f"{tk} drift n/a (need both short- and long-window ρ to {spear})"}
    delta = rs - rl
    drifting = bool(delta >= warn and rs > ind)
    is_conv = "conv" in str(lane or "").lower()
    flags, events = [], []
    read = f"{tk} ρ to {spear}: {rl:+.2f}→{rs:+.2f} ({delta:+.2f})"
    if drifting:
        level = "risk" if is_conv else "warn"
        why = ("a CONVENTIONAL sleeve correlating to the spear — it is supposed to be the independent thesis"
               if is_conv else "a ballast creeping toward the spear — it is quietly ceasing to diversify")
        read += f" — DRIFTING: {why}"
        flags.append({"id": "correlation_drift", "ticker": ticker or None, "level": level, "active": True,
                      "corr": round(rs, 3), "delta": round(delta, 3),
                      "text": f"{tk} ρ to {spear} rising {rl:+.2f}→{rs:+.2f} ({delta:+.2f}) — {why}"})
        events.append({"type": "correlation_drift", "level": level, "ticker": ticker or None,
                       "text": f"SENTINEL: {tk} drifting toward {spear} (ρ {rl:+.2f}→{rs:+.2f}, {delta:+.2f}) — {why}"})
    return {"available": True, "ticker": ticker, "drifting": drifting, "delta": round(delta, 3),
            "rho_short": round(rs, 3), "rho_long": round(rl, 3), "level_if_flag": ("risk" if is_conv else "warn"),
            "flags": flags, "events": events, "read": read}


def assess_book_independence(corr_matrix: Optional[dict], holdings: Any, *, spear: str = "AGA.V",
                            corr_matrix_long: Optional[dict] = None, config: Optional[dict] = None) -> dict:
    """The ongoing, lane-aware read over the engine's cached correlation matrices. For each non-spear
    holding it reports ρ to the spear (level, from the 60d matrix) and — when the long-window matrix is
    supplied — the drift trend (60d vs 120d). It SEPARATES conventional sleeves (which should be low-ρ
    to the spear) from resource ballast, so a conventional name drifting toward the spear is the alarm
    that matters most. ``holdings`` is ``[{ticker, lane?, slot?, archetype?}]``. Names with no cached
    ρ land in ``coverage.missing`` (honest coverage). Pure; this complements — never duplicates —
    ``book_factor``'s static level alarm."""
    cfg = _cfg(config)
    red = float(cfg["redundant_min"])
    by_t: dict = {}
    flags, events, covered, missing = [], [], [], []
    n_conv = n_res = 0
    for h in (holdings or []):
        tk = str((h or {}).get("ticker") or "").strip()
        if not tk or tk == spear:
            continue
        lane = str((h or {}).get("lane") or "").strip()
        is_conv = "conv" in lane.lower()
        n_conv += 1 if is_conv else 0
        n_res += 0 if is_conv else 1
        rs = _corr(corr_matrix, spear, tk)
        if rs is None:
            missing.append({"ticker": tk, "reason": f"no cached ρ to {spear}"})
            by_t[tk] = {"available": False, "ticker": tk, "lane": lane or "resource",
                        "read": f"{tk} independence n/a — no cached ρ to {spear}"}
            continue
        covered.append(tk)
        rl = _corr(corr_matrix_long, spear, tk) if corr_matrix_long else None
        d = drift(rs, rl, ticker=tk, spear=spear, lane=lane, config=config) if rl is not None else None
        rec = {"available": True, "ticker": tk, "lane": lane or "resource",
               "rho_to_spear": round(rs, 3), "verdict": independence_verdict(rs, config=config)["verdict"],
               "drift": d}
        # a conventional sleeve at/above the redundancy bar is a standing alarm even without a trend
        if is_conv and rs >= red:
            f = {"id": "conventional_redundant", "ticker": tk, "level": "risk", "active": True, "corr": round(rs, 3),
                 "text": f"{tk} ρ{rs:+.2f} to {spear} — a CONVENTIONAL sleeve riding the spear; the second thesis has collapsed into the first"}
            flags.append(f)
            events.append({"type": "correlation", "level": "risk", "ticker": tk, "text": f["text"]})
        if d and d.get("drifting"):
            flags.extend(d["flags"])
            events.extend(d["events"])
        rec["read"] = d["read"] if d else f"{tk} ρ{rs:+.2f} to {spear} ({rec['verdict']})"
        by_t[tk] = rec
    if not covered:
        read = f"book independence n/a (no non-spear names carry a cached ρ to {spear})"
    else:
        drifters = [t for t, r in by_t.items() if (r.get("drift") or {}).get("drifting")]
        read = (f"{len(covered)} sleeve(s) read vs {spear} — "
                + (f"drifting toward the spear: {', '.join(drifters)}" if drifters
                   else "none drifting toward the spear"))
    return {"available": bool(covered), "spear": spear, "by_ticker": by_t, "flags": flags,
            "events": events, "n_conventional": n_conv, "n_resource": n_res,
            "coverage": {"covered": covered, "missing": missing}, "read": read,
            "glossary": {k: correlation_tooltip(k) for k in CORRELATION_GLOSSARY}}


def book_macro_summary(book_factor_result: Optional[dict],
                       independence_result: Optional[dict] = None) -> dict:
    """Distill the book's MACRO-CORRELATION into one render-ready summary: the average pairwise ρ, the
    single-factor verdict (is this a portfolio, or one bet wearing different tickers?), each non-spear
    name's ρ to the spear, and any drift. Consumes ``book_factor.factor_concentration`` (+ optionally
    ``assess_book_independence``); pure, graceful on thin inputs."""
    bf = book_factor_result or {}
    ind = independence_result or {}
    drift = []
    for tk, rec in (ind.get("by_ticker") or {}).items():
        d = (rec or {}).get("drift") or {}
        if d.get("drifting"):
            drift.append({"ticker": tk, "delta": d.get("delta"),
                          "rho_short": d.get("rho_short"), "rho_long": d.get("rho_long")})
    flags = list(bf.get("flags") or []) + list(ind.get("flags") or [])
    return {"available": bool(bf.get("available")), "avg_pairwise": bf.get("avg_pairwise"),
            "single_factor": bf.get("single_factor"),
            "single_factor_threshold": bf.get("single_factor_threshold"),
            "spear": bf.get("spear"), "spear_corr": dict(bf.get("spear_corr") or {}),
            "drift": drift, "flags": flags,
            "read": bf.get("read") or "macro-correlation n/a (need ≥2 book names with cached correlations)"}


def _default_factor_fn(cand: dict) -> Optional[str]:
    """Candidate → its dominant resource-metal factor key, or None (no single resource factor — a
    conventional business / diversified holdco). Reuses ``divergence_monitor.factor_for`` when present
    (one source of truth), else a local commodity check. Pure."""
    try:
        import divergence_monitor
        key, _ = divergence_monitor.factor_for(commodity=(cand or {}).get("commodity", ""),
                                               slot=(cand or {}).get("slot", ""),
                                               archetype=(cand or {}).get("archetype", ""))
        return key
    except Exception:
        c = str((cand or {}).get("commodity") or "").strip().lower()
        return c if c in RESOURCE_FACTORS else None


def screen_uncorrelated(candidates: Any, *, candidate_returns: Optional[dict] = None,
                        book_returns_by_ticker: Optional[dict] = None,
                        book_factor_keys: Optional[Any] = None, spear: str = "AGA.V",
                        weights: Optional[dict] = None, factor_fn=None,
                        config: Optional[dict] = None) -> dict:
    """Rank a candidate universe by INDEPENDENCE from the book — the diversifier search. For each
    candidate: a MEASURED ρ (``assess_candidate``) when its aligned return history is supplied in
    ``candidate_returns``; otherwise a FACTOR-class PROXY — does its dominant factor sit OUTSIDE the
    book's factor family (``book_factor_keys``, default the resource-metal set)? Distinct-factor ⇒ a
    likely diversifier (labeled proxy — backfill prices to measure); same-factor ⇒ likely correlated.
    Returns the ranked list (most independent first), each labeled ``measured``/``proxy``, + a summary.
    Pure; the honest 'whole universe is one factor ⇒ no diversifier here' result is built in."""
    factor_fn = factor_fn or _default_factor_fn
    book_keys = set(book_factor_keys) if book_factor_keys is not None else set(RESOURCE_FACTORS)
    cr = candidate_returns or {}
    book_rets = book_returns_by_ticker or {}
    rows = []
    for cand in candidates or []:
        tk = str((cand or {}).get("ticker") or "").strip()
        if not tk:
            continue
        cand_rets = cr.get(tk) or cr.get(tk.upper())
        a = (assess_candidate(cand_rets, book_rets, spear=spear, weights=weights, name=tk, config=config)
             if (cand_rets and book_rets) else None)
        if a and a.get("available"):
            rho = a.get("rho_to_spear")
            rows.append({"ticker": tk, "basis": "measured", "verdict": a["verdict"],
                         "rho_to_spear": a.get("rho_to_spear"), "rho_to_book": a.get("rho_to_book"),
                         "rank": (rho if rho is not None else 0.5), "read": a["read"],
                         "commodity": (cand or {}).get("commodity"), "vehicle": (cand or {}).get("vehicle"),
                         "flags": a.get("flags") or []})
            continue
        fac = factor_fn(cand)
        distinct = (fac is None) or (str(fac).strip().lower() not in book_keys)
        verdict = "DISTINCT-FACTOR" if distinct else "SAME-FACTOR"
        read = (f"{tk}: {('no resource-factor load' if fac is None else fac)} — "
                + ("a different macro factor than the book (proxy: likely uncorrelated — backfill prices to measure)"
                   if distinct else "loads the book's resource factor (proxy: likely correlated)"))
        rows.append({"ticker": tk, "basis": "proxy", "verdict": verdict, "factor": fac,
                     "rank": (0.35 if distinct else 0.85), "read": read,
                     "commodity": (cand or {}).get("commodity"), "vehicle": (cand or {}).get("vehicle"),
                     "flags": []})
    rows.sort(key=lambda r: (r["rank"], r["ticker"]))
    n_measured = sum(1 for r in rows if r["basis"] == "measured")
    diversifiers = [r for r in rows if r["verdict"] in ("INDEPENDENT", "PARTIAL", "DISTINCT-FACTOR")]
    if not rows:
        read = "no candidates to screen for independence (the universe is empty)"
    elif not diversifiers:
        read = (f"{len(rows)} candidates screened — NONE is a structural diversifier: the universe loads "
                f"the book's single factor. Diversification lives in the conventional core (lane: conventional).")
    else:
        read = (f"{len(rows)} candidates → {len(diversifiers)} potential diversifier(s) "
                f"({n_measured} measured by ρ, the rest factor-proxy)")
    return {"available": bool(rows), "candidates": rows, "n": len(rows), "n_measured": n_measured,
            "n_diversifiers": len(diversifiers), "spear": spear, "read": read,
            "glossary": {k: correlation_tooltip(k) for k in CORRELATION_GLOSSARY}}


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "") -> tuple:
    """Dedup the firing so a drift/redundancy alarm pins ONCE per event, not every cycle. ``fired`` is
    the engine's rolling ledger ``{tk: {date, bucket}}``; a flag is FRESH when this ticker hasn't fired
    today OR its correlation bucket worsened since it last fired (a 0.4→0.7 step is a new event worth a
    new pin). ``bucket`` = round(corr, 1) so jitter inside a decile does not re-fire. Returns
    ``(fresh, fired_next)``. Pure; mirrors ``divergence_monitor.select_fresh``."""
    fired_next = dict(fired or {})
    fresh: list = []
    for r in (flagged or []):
        tk = str((r or {}).get("ticker") or "").strip()
        if not tk:
            continue
        corr = _num((r or {}).get("corr"))
        bucket = round(corr, 1) if corr is not None else None
        prev = fired_next.get(tk) or {}
        worsened = (bucket is not None and prev.get("bucket") is not None and bucket > prev.get("bucket"))
        if prev.get("date") == today and not worsened:
            continue                                       # already pinned today and no worse → skip
        fresh.append(r)
        fired_next[tk] = {"date": today, "bucket": bucket, "corr": (round(corr, 3) if corr is not None else None),
                          "id": (r or {}).get("id")}
    return fresh, fired_next
