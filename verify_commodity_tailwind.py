"""
Live verification for the commodity-aware tailwind + real floors rewrite.

Run it against the RUNNING engine (in the cockpit) AFTER restarting:  python verify_commodity_tailwind.py
It pulls /state and prints, per holding: the commodity tag, the T-pillar tailwind with its
decomposition (shared archetype lean vs commodity-specific contribution), and the floor — so you
can confirm GROY/URC/GMX no longer share a tailwind and the floors are the real book values.
"""
import json
import os
import urllib.request

URL = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000") + "/state"


def main():
    try:
        with urllib.request.urlopen(URL, timeout=5) as r:
            state = json.loads(r.read())
    except Exception as e:
        print(f"could not reach engine at {URL}: {e}")
        return
    baskets = ((state.get("conviction_mode") or {}).get("baskets")) or state.get("baskets") or []
    if not baskets:
        print("no baskets in /state (engine warming up?)")
        return
    print(f"{'TICKER':8} {'COMMODITY':11} {'T':>5} {'=arch':>6} {'+cmdty':>7} {'creg':>6} "
          f"{'PRICE':>8} {'FLOOR':>8} {'BASE':>8} {'UPSIDE%':>8} {'RATING':>6}")
    for b in baskets:
        T = (b.get("pillars") or {}).get("T") or {}
        L = b.get("ladder") or {}
        price = b.get("price") or L.get("price")
        base = b.get("base") or (b.get("pillars") or {}).get("V", {}).get("base") or L.get("base")
        up = None
        try:
            if price and base and float(price) > 0:
                up = (float(base) / float(price) - 1.0) * 100
        except (TypeError, ValueError):
            up = None
        print(f"{str(b.get('ticker','?')):8} {str(T.get('commodity','—')):11} "
              f"{_f(T.get('score')):>5} {_f(T.get('alpha_contribution')):>6} "
              f"{_f(T.get('commodity_contribution')):>7} {_f(T.get('commodity_regime')):>6} "
              f"{_money(price):>8} {_money(L.get('floor')):>8} {_money(base):>8} "
              f"{_f(up):>8} {_f(b.get('rating')):>6}")
    print("\nExpect: GROY/URC/GMX show DIFFERENT T (commodity contribution differs by metal),"
          "\n        FLOOR ≈ real book value/share (GROY~3.13 USD→CAD, URC~2.60, GMX~0.71),"
          "\n        and BASE/UPSIDE sane (sourced NAV-anchored — NO 5000% phantom).")


def _f(x):
    try:
        return f"{float(x):.2f}"
    except (TypeError, ValueError):
        return "—"


def _money(x):
    try:
        return f"${float(x):.2f}"
    except (TypeError, ValueError):
        return "—"


if __name__ == "__main__":
    main()
