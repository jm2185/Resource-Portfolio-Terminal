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
    """CURRENT engine.py:361-364 — copper/gold and silver both raise stress."""
    cu_au = s["copper"] / s["gold"] if s["gold"] > 0 else 0.00136
    return norm(cu_au, 0.0010, 0.0018) * 0.60 + norm(s["silver"], 50.0, 100.0) * 0.40


def comm_proposed(s):
    """PROPOSED — copper/gold INVERTED (weak industrial demand = stress); silver DROPPED."""
    cu_au = s["copper"] / s["gold"] if s["gold"] > 0 else 0.00136
    return 100.0 - norm(cu_au, 0.0010, 0.0018)


def comm_alt(s):
    """ALT — copper/gold INVERTED (0.60) + silver INVERTED (0.40, collapsing silver = stress)."""
    cu_au = s["copper"] / s["gold"] if s["gold"] > 0 else 0.00136
    return (100.0 - norm(cu_au, 0.0010, 0.0018)) * 0.60 + (100.0 - norm(s["silver"], 50.0, 100.0)) * 0.40


def mri(L, Y, V, C, S):
    val = L * 0.30 + Y * 0.20 + V * 0.20 + C * 0.15 + S * 0.15
    return round(max(0, min(100, val)), 1)


def regime(mri_val):
    # Directive bands from METRIC_COMPASS.md / calculate_sizing
    if mri_val < 40: return "Risk-On / DEPLOY"
    if mri_val < 65: return "Neutral / Caution"
    if mri_val < 80: return "Elevated / Defensive"
    return "High Stress / Defensive"


SCENARIOS = {
    "COVID crash (Mar-Apr 2020) [approx]": dict(
        dxy=102.8, ted=1.40, real_yield=-0.20, dxy_mom=2.0, y10=0.70, y30=1.35,
        vix=65.0, spreads=8.8, copper=2.10, gold=1600.0, silver=12.5, cftc=15000),
    "2022 hiking peak (Oct 2022) [approx]": dict(
        dxy=112.0, ted=0.30, real_yield=1.60, dxy_mom=1.5, y10=3.90, y30=3.80,
        vix=31.0, spreads=5.5, copper=3.35, gold=1660.0, silver=19.0, cftc=8000),
    "Current (May 2026, $75 Ag) [cache]": dict(
        dxy=98.91, ted=0.032, real_yield=2.06, dxy_mom=-0.36, y10=4.453, y30=4.993,
        vix=15.32, spreads=2.72, copper=6.3595, gold=4560.5, silver=75.62, cftc=35000),
}


def main():
    hdr = (f"{'Scenario':<38} | {'Cu/Au':>7} | {'C_cur':>6} {'C_prop':>7} {'C_alt':>6} | "
           f"{'MRI_cur':>8} {'MRI_prop':>9} {'MRI_alt':>8} | {'Regime (current -> proposed)':<42}")
    print(hdr)
    print("-" * len(hdr))
    for name, s in SCENARIOS.items():
        L, Y, V, S = components(s)
        Cc, Cp, Ca = comm_current(s), comm_proposed(s), comm_alt(s)
        m_c, m_p, m_a = mri(L, Y, V, Cc, S), mri(L, Y, V, Cp, S), mri(L, Y, V, Ca, S)
        cu_au = s["copper"] / s["gold"]
        print(f"{name:<38} | {cu_au:>7.5f} | {Cc:>6.1f} {Cp:>7.1f} {Ca:>6.1f} | "
              f"{m_c:>8.1f} {m_p:>9.1f} {m_a:>8.1f} | "
              f"{regime(m_c)+'  ->  '+regime(m_p):<42}")
    print("-" * len(hdr))
    print("Higher MRI = more defensive.  C_cur=current commodity score, "
          "C_prop=copper/gold inverted+silver dropped, C_alt=both inverted.")


if __name__ == "__main__":
    main()
