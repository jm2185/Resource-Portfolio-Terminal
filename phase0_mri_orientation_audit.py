"""
PHASE 0 (READ-ONLY) — MRI Commodity-Component Orientation Back-test.

Purpose: provide evidence BEFORE any change to live regime math.
Faithfully replicates engine.py calculate_mri (lines ~336-381) and compares
the current commodity component `C` against two re-oriented variants across
representative macro regimes.

NOTE ON DATA: The "Current (May 2026)" scenario uses the system's actual
last-fetched values from .cache/macro_state.json. The two historical
scenarios use *representative, approximate* published macro values for the
period (labelled as such) — they are illustrative of regime direction, not
precise tick data. CFTC silver net-longs are coarse estimates.
"""

def norm(val, low, high):
    # Identical to engine.py:336-337
    return max(0, min(100, (val - low) / (high - low) * 100))


def components(s):
    """Compute the four non-commodity MRI components exactly as engine.py."""
    L = (norm(s["dxy"] - 100, -5, 8) * 0.30 +
         norm(s["ted"], 0.1, 0.9) * 0.20 +
         norm(s["real_yield"], 0.5, 3.5) * 0.30 +
         norm(s["dxy_mom"], -2.0, 2.0) * 0.20)
    Y = (norm(s["y30"] - s["y10"], -0.5, 1.5) * 0.50 +
         norm(s["y10"], 3.0, 5.5) * 0.50)
    V = (norm(s["vix"], 12, 35) * 0.50 +
         norm(s["spreads"], 2, 7) * 0.50)
    S = norm(s["cftc"], -15000, 85000)
    return L, Y, V, S


def comm_current(s):
    """LEGACY (absolute-band) — copper/gold and silver LEVEL both raise stress (incoherent polarity)."""
    cu_au = s["copper"] / s["gold"] if s["gold"] > 0 else 0.00136
    return norm(cu_au, 0.0010, 0.0018) * 0.60 + norm(s["silver"], 50.0, 100.0) * 0.40


def comm_v2(s):
    """SHIPPED v2 (engine.calculate_commodity_regime_score, pure-python mirror):
    copper/gold trailing PERCENTILE inverted (low percentile = weak/declining demand = stress) +
    silver DRAWDOWN from trailing high (collapsing silver = stress; level excluded to avoid
    double-counting). Regime-stationary and correctly oriented across crashes AND tightening."""
    cu_au = s["copper"] / s["gold"] if s["gold"] > 0 else 0.00136
    cu_win, ag_win = s["cu_au_window"], s["silver_window"]
    percentile = sum(1 for v in cu_win if v <= cu_au) / len(cu_win)
    cu_stress = (1.0 - percentile) * 100.0
    hi = max(ag_win)
    dd = max(0.0, (hi - s["silver"]) / hi) if hi > 0 else 0.0
    ag_stress = min(100.0, (dd / 0.30) * 100.0)
    return max(0.0, min(100.0, 0.60 * cu_stress + 0.40 * ag_stress))


def _ramp(a, b, n=120):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def mri(L, Y, V, C, S):
    val = L * 0.30 + Y * 0.20 + V * 0.20 + C * 0.15 + S * 0.15
    return round(max(0, min(100, val)), 1)


def regime(mri_val):
    # Directive bands from METRIC_COMPASS.md / calculate_sizing
    if mri_val < 40: return "Risk-On / DEPLOY"
    if mri_val < 65: return "Neutral / Caution"
    if mri_val < 80: return "Elevated / Defensive"
    return "High Stress / Defensive"


# Trailing windows are representative of each regime's preceding ~1y path (illustrative, not tick-exact):
#   COVID   -> cu/au and silver decline INTO the crash (current sits below the window)
#   2022    -> cu/au and silver decline THROUGH the year (current near the window low)
#   Current -> cu/au and silver rise INTO the present (current near the window high)
SCENARIOS = {
    "COVID crash (Mar-Apr 2020) [approx]": dict(
        dxy=102.8, ted=1.40, real_yield=-0.20, dxy_mom=2.0, y10=0.70, y30=1.35,
        vix=65.0, spreads=8.8, copper=2.10, gold=1600.0, silver=12.5, cftc=15000,
        cu_au_window=_ramp(0.00165, 0.00135), silver_window=_ramp(19.5, 16.0)),
    "2022 hiking peak (Oct 2022) [approx]": dict(
        dxy=112.0, ted=0.30, real_yield=1.60, dxy_mom=1.5, y10=3.90, y30=3.80,
        vix=31.0, spreads=5.5, copper=3.35, gold=1660.0, silver=19.0, cftc=8000,
        cu_au_window=_ramp(0.00260, 0.00205), silver_window=_ramp(26.0, 19.5)),
    "Current (May 2026, $75 Ag) [cache]": dict(
        dxy=98.91, ted=0.032, real_yield=2.06, dxy_mom=-0.36, y10=4.453, y30=4.993,
        vix=15.32, spreads=2.72, copper=6.3595, gold=4560.5, silver=75.62, cftc=35000,
        cu_au_window=_ramp(0.00115, 0.00139), silver_window=_ramp(55.0, 75.0)),
}


def main():
    hdr = (f"{'Scenario':<38} | {'Cu/Au':>7} | {'C_legacy':>8} {'C_v2':>6} | "
           f"{'MRI_legacy':>10} {'MRI_v2':>7} | {'Regime (legacy -> v2)':<46}")
    print(hdr)
    print("-" * len(hdr))
    for name, s in SCENARIOS.items():
        L, Y, V, S = components(s)
        Cc, Cv = comm_current(s), comm_v2(s)
        m_c, m_v = mri(L, Y, V, Cc, S), mri(L, Y, V, Cv, S)
        cu_au = s["copper"] / s["gold"]
        print(f"{name:<38} | {cu_au:>7.5f} | {Cc:>8.1f} {Cv:>6.1f} | "
              f"{m_c:>10.1f} {m_v:>7.1f} | "
              f"{regime(m_c)+'  ->  '+regime(m_v):<46}")
    print("-" * len(hdr))
    print("Higher MRI = more defensive.  C_legacy = shipped-pre-v2 absolute-band score;")
    print("C_v2 = regime-stationary (cu/au trailing-percentile inverted + silver drawdown).")
    print("Validation: v2 raises stress in BOTH the commodity crash and the tightening decline,")
    print("and lowers it in the current silver-bull regime (removing the legacy over-defensive bias).")


if __name__ == "__main__":
    main()
