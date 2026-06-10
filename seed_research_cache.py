"""
Seed data/research_cache.json with filings-derived fundamentals sourced via the agent
web-search fallback (the "hard data" no market API provides). Re-runnable + auditable: every
value carries its source URL, as-of date, confidence, and a caveat note. This is the
provenance-stamped REPLACEMENT for the old hardcoded v5_config snapshots (ounces, NAV, AISC).

Sourced 2026-06-04 by three research passes (Silver47 / ballast NAVs / silver-explorer peers).
Re-run after a new filing to refresh; values flagged low/med confidence should be re-verified.
"""
from research_cache import ResearchCache

rc = ResearchCache()

# ---------------------------------------------------------------- AGA.V (Silver47 — the spear)
AGA_MERGER = "https://www.newsfilecorp.com/release/260955 (Silver47–Summa merger PR)"
rc.set("AGA.V", "currency", "CAD", AGA_MERGER, "2026-06-04", "high")
rc.set("AGA.V", "in_ground_ageq_oz_indicated", 10_300_000, AGA_MERGER, "2025-08-01", "high",
       "Hughes Indicated; Red Mountain is 100% Inferred (no M&I)")
rc.set("AGA.V", "in_ground_ageq_oz_inferred", 236_300_000, AGA_MERGER, "2025-08-01", "high",
       "Red Mtn 168.6 + Hughes 32.9 + Hughes tailings 2.7 + Mogollon 32.1 Moz AgEq")
rc.set("AGA.V", "shares_out", 208_600_000, "https://stockanalysis.com/quote/tsxv/AGA + Jan-2026 omnibus plan",
       "2026-06-04", "med", "RECONCILE: post Jan-2026 C$34.5M bought deal; verify basic+FD on SEDAR+ MD&A")
rc.set("AGA.V", "cash", 55_000_000, "https://www.kitco.com/opinion/.../fully-funded-silver47 (Jan 2026)",
       "2026-01-29", "med", "~C$55M, no debt, post-financing; confirm vs latest quarterly on SEDAR+")
rc.set("AGA.V", "aisc_per_oz", None, "n/a — no economic study published", "2026-06-04", "high",
       "PENDING: pre-PEA, no company AISC exists yet (PEA is a 2026 milestone)")
rc.set("AGA.V", "nav_per_share", None, "Investing.com / Kitco (targets, not NAV)", "2026-06-04", "med",
       "PENDING: no published NAV/share; analyst price targets cluster C$2.00–2.05")

# ---------------------------------------------------------------- Ballast (book value/sh = real floor)
GROY_FS = "https://www.goldroyalty.com/_resources/financials/GRC-Q1-2026-FS.pdf (EDGAR Q1-2026)"
rc.set("GROY", "currency", "USD", GROY_FS, "2026-03-31", "high")
rc.set("GROY", "book_value_per_share", 3.13, GROY_FS, "2026-03-31", "high",
       "equity US$721.99M / 230,809,201 sh; ~at market — floor is the carried royalty book, not cash")
rc.set("GROY", "cash", 13_598_000, GROY_FS, "2026-03-31", "high", "+US$2.60M short-term investments")
rc.set("GROY", "shares_out", 230_809_201, GROY_FS, "2026-03-31", "high")
rc.set("GROY", "total_equity", 721_994_000, GROY_FS, "2026-03-31", "high")

URC_FS = "https://www.sec.gov/Archives/edgar/data/1711570/000119312526100571/ (URC 6-K, Jan-2026)"
rc.set("URC.TO", "currency", "CAD", URC_FS, "2026-01-31", "high")
rc.set("URC.TO", "book_value_per_share", 2.60, URC_FS, "2026-01-31", "high",
       "equity C$381.0M / 146,477,507 sh; UNDERSTATES NAV — uranium carried at lower of cost/NRV, not spot")
rc.set("URC.TO", "cash", 124_171_000, URC_FS, "2026-01-31", "high", "+C$14.6M short-term investments")
rc.set("URC.TO", "shares_out", 146_477_507, URC_FS, "2026-03-11", "med",
       "pre May-2026 US$40M subscription-receipt placement (~157M on conversion)")
rc.set("URC.TO", "uranium_lbs_u3o8", 2_329_637, URC_FS, "2026-01-31", "high", "carried C$184.9M at cost/NRV")
rc.set("URC.TO", "total_equity", 381_026_000, URC_FS, "2026-01-31", "high")

GMX_FS = "https://newsfile.moomoo.com/.../CSA_SEDAR_PLUS_...2368500.pdf (Globex audited FY2025)"
rc.set("GMX.TO", "currency", "CAD", GMX_FS, "2025-12-31", "high")
rc.set("GMX.TO", "book_value_per_share", 0.71, GMX_FS, "2025-12-31", "high",
       "equity C$40.22M / 56,347,436 sh; near debt-free holdco (cash + marketable securities)")
rc.set("GMX.TO", "cash", 7_851_893, GMX_FS, "2025-12-31", "high", "+C$29.17M marketable securities (FV)")
rc.set("GMX.TO", "shares_out", 56_347_436, GMX_FS, "2025-12-31", "high", "56.97M current (post year-end options)")
rc.set("GMX.TO", "total_equity", 40_215_340, GMX_FS, "2025-12-31", "high")

# ---------------------------------------------------------------- Peers (AgEq oz for EV/oz)
rc.set("BRC.V", "ageq_oz_indicated", 21_139_000,
       "https://www.newsfilecorp.com/release/265525 (Tonopah West updated MRE)", "2025-08-25", "high",
       "PRIME COMP: Tonopah West is adjacent to Silver47's Hughes — same Nevada epithermal vein system")
rc.set("BRC.V", "ageq_oz_inferred", 86_880_000,
       "https://www.newsfilecorp.com/release/265525", "2025-08-25", "high")
rc.set("ABRA.TO", "ageq_oz_mi", 349_927_000,
       "https://www.abrasilver.com/news-releases/...350-moz-ageq-in-mi", "2025-07-21", "high",
       "Argentina (Salta); base-metal/gold credits make AgEq price-assumption sensitive")
rc.set("ABRA.TO", "ageq_oz_inferred", 33_496_000, "https://www.abrasilver.com/news-releases/", "2025-07-21", "high")
rc.set("SSV.V", "ageq_oz_indicated", 116_000_000,
       "https://southernsilverexploration.com/projects/cerro-las-minitas-durango-mexico/", "2024-03-20", "high",
       "Cerro Las Minitas, Mexico; polymetallic CRD — base-metal-heavy AgEq, weakest geological comp")
rc.set("SSV.V", "ageq_oz_inferred", 186_000_000,
       "https://southernsilverexploration.com/projects/cerro-las-minitas-durango-mexico/", "2024-03-20", "high")
rc.set("DV.V", "ageq_oz_indicated", 50_000_000, "https://contangoore.com/projects/kitsault-valley-project/",
       "2022-09-28", "low", "company estimate (NOT in the filed NI 43-101); merged to CTGO Mar-2026; MRE stale")
rc.set("DV.V", "ageq_oz_inferred", 90_000_000, "https://contangoore.com/projects/kitsault-valley-project/",
       "2022-09-28", "low", "company estimate; use as-filed Ag+Au and your own AgEq deck for a clean comp")

if __name__ == "__main__":
    print(f"seeded research_cache for: {', '.join(rc.tickers())}")
