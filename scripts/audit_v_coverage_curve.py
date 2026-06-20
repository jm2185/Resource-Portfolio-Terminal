"""
P1.5 — V-vs-coverage curve audit (CALIBRATION desk).

Question (from the action plan): is the V pillar's contribution discount-DEPTH-sensitive, or
near-binary around the REP-floor threshold? V is the heaviest pillar for the spear (0.45) AND the
fastest-compressing, so a flat shelf above the floor would over-credit a marginal entry (1.02×
coverage scoring like a deep 1.4× margin of safety).

This sweeps floor-coverage φ = floor ÷ price across 0.90×→1.60× (holding the floor and the bull leg
fixed, varying price), exercising the REAL rating path (compute_asymmetry_rating), and prints V and
its support/payoff terms under BOTH curve shapes:
  * linear  — the shipped default (support ramps over support_band then FLAT-SHELFS at 1.0)
  * depth   — the proposal: a monotonic, concave, never-flat support curve tanh(beta·(φ-lo))

Run:  python scripts/audit_v_coverage_curve.py [--save]
``--save`` writes docs/v_coverage_curve.md (the artifact referenced by the CALIBRATION note).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asymmetry_rating import compute_asymmetry_rating  # noqa: E402

FLOOR = 1.00          # REP / liquidation floor (held fixed)
BULL = 4.00           # realistic bull leg — a 4× convex spear from the floor (held fixed)
BASE = 2.50           # intrinsic base leg
PHIS = [0.90, 0.95, 1.00, 1.02, 1.05, 1.08, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50, 1.60]
DEPTH_CFG = {"conviction_mode": {"support_curve": "depth"}}


def _row(phi: float) -> dict:
    price = FLOOR / phi                                # deeper discount => higher φ
    asset = dict(ticker="SWEEP", archetype="option_convexity",
                 price=price, floor=FLOOR, base=BASE, bull=BULL, bear=BASE * 0.6,
                 mri=40.0, regime_alpha=0.4, forensic_score=3.5, avg_tq=1.12,
                 conviction=0.6, runway_months=24.0, dilution_velocity=0.0)
    lin = compute_asymmetry_rating(asset)["pillars"]["V"]
    dep = compute_asymmetry_rating(asset, DEPTH_CFG)["pillars"]["V"]
    return {"phi": phi, "price": price, "rho": lin["rho"], "payoff": lin["payoff"],
            "sup_lin": lin["support"], "V_lin": lin["score"],
            "sup_dep": dep["support"], "V_dep": dep["score"]}


def _bar(v: float, width: int = 22) -> str:
    n = int(round((v / 10.0) * width))
    return "█" * n + "·" * (width - n)


def build() -> tuple[list[dict], list[str]]:
    rows = [_row(p) for p in PHIS]
    out = []
    out.append("# P1.5 — V vs floor-coverage (φ) curve audit")
    out.append("")
    out.append(f"Fixed: floor={FLOOR:.2f}, bull={BULL:.2f} (a {BULL/FLOOR:.0f}× spear), base={BASE:.2f}; "
               f"price = floor ÷ φ. Archetype=option_convexity (asymmetry mode).")
    out.append("")
    out.append("| φ (cov) | price | ρ payoff | support(lin) | **V linear** | support(depth) | **V depth** |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        mark = "  ← floor" if abs(r["phi"] - 1.00) < 1e-9 else ("  ← band top" if abs(r["phi"] - 1.25) < 1e-9 else "")
        out.append(f"| {r['phi']:.2f}× | {r['price']:.3f} | {r['payoff']:.2f} | {r['sup_lin']:.2f} | "
                   f"**{r['V_lin']:.2f}**{mark} | {r['sup_dep']:.2f} | **{r['V_dep']:.2f}** |")
    out.append("")

    # ---- the diagnostic: marginal ΔV per +0.10 φ in the shallow vs DEEP-below-floor regions ----
    def at(phi):
        return next(r for r in rows if abs(r["phi"] - phi) < 1e-9)
    shallow_lin = at(1.10)["V_lin"] - at(1.00)["V_lin"]
    deep_lin = at(1.50)["V_lin"] - at(1.25)["V_lin"]
    deep_dep = at(1.50)["V_dep"] - at(1.25)["V_dep"]
    out.append("## Finding")
    out.append("")
    out.append(f"- **Below the floor, the LINEAR support term flat-shelfs at φ=1.25** (support hits 1.0 "
               f"and stops). Deep margin of safety past ~25%-below-floor earns **nothing** more from "
               f"support; ρ payoff is already saturated (≈{at(1.25)['payoff']:.2f}).")
    out.append(f"- Marginal V over the DEEP region 1.25×→1.50× (linear): **{deep_lin:+.2f}** points "
               f"(vs {shallow_lin:+.2f} over the shallow 1.00×→1.10×). The curve is **near-flat where the "
               f"margin of safety is deepest** — so 1.02× ≈ 1.40× coverage, over-crediting a marginal entry.")
    out.append(f"- The proposed **depth** curve keeps rewarding depth: V over 1.25×→1.50× = **{deep_dep:+.2f}** "
               f"points — monotonic, concave, never a shelf.")
    out.append("")
    out.append("**Verdict:** 1.08× → high V reflects a *threshold* effect more than a *deliberate, "
               "steep-enough depth curve*. Recommendation (proposal-gated, /confirm): set "
               "`conviction_mode.support_curve = \"depth\"` so the 45%-weight, fast-compressing pillar "
               "rewards margin-of-safety DEPTH, not merely being below the line. Default stays `linear` "
               "until approved.")
    out.append("")
    # ASCII curve (console only)
    return rows, out


def main():
    rows, md = build()
    print("\n".join(md))
    print("\nφ      V linear              V depth")
    for r in rows:
        print(f"{r['phi']:.2f}×  {_bar(r['V_lin'])}  {_bar(r['V_dep'])}")
    if "--save" in sys.argv:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "v_coverage_curve.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")
        print(f"\nsaved → {path}")


if __name__ == "__main__":
    main()
