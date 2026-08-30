"""Part 2 — what a bump costs BNKR, what they can afford, and the vote arithmetic."""
R, S_AGA, N_A, FX = 0.1724, 0.433, 208.6, 1.37
new_sh = N_A*R; total = new_sh/S_AGA; N_B = total-new_sh; K = N_B/N_A
A_mkt, B_mkt = 0.67*N_A, 5.38*N_B

# ---------------------------------------------------------------- 1. ZERO-SUM
print("=== 1. THE BARGAINING RANGE IS BOUNDED, AND THE BOUND IS SYMMETRIC ===")
print("BNKR legacy value after = (1-s)(V_A+V_B); accretive iff V_A/V_B > s/(1-s) iff R < R*.")
print("With no synergies the deal is EXACTLY zero-sum: BNKR is accretive precisely")
print("when AGA is dilutive. So R* is BOTH the fair ratio AND the most BNKR can")
print("rationally pay. The bargaining range is [struck R, R*]; the vote decides the split.\n")

# --------------------------------------------------- 2. THE FINANCING SYNERGY
SOFR = 4.30
rate = (SOFR + 7.0)/100                 # Ocean Partners prepay cost
debt_displaced_usd = 16.0               # Ocean US$10M + Teck standby US$6M outstanding
annual = debt_displaced_usd*rate
mult = 10
syn_usd = annual*mult; syn_cad = syn_usd*FX
print("=== 2. THE ONE REAL SYNERGY — AND IT IS AGA'S OWN BALANCE SHEET ===")
print(f"BNKR borrows at SOFR+7.0% = {rate*100:.1f}%. AGA's ~C$48M treasury displaces")
print(f"US${debt_displaced_usd:.0f}M of it (Ocean US$10M prepay + Teck standby US$6M drawn).")
print(f"  interest saved  US${annual:.2f}M/yr  -> capitalized {mult}x = US${syn_usd:.0f}M = C${syn_cad:.0f}M")
print(f"  = {syn_cad/B_mkt*100:.1f}% of BNKR's standalone mcap.")
print("These are the districts' ONLY overlap-free synergy: Idaho vs Alaska/Nevada/NM,")
print("no shared mill, no shared workforce. The synergy IS the target's cash.")
print("=> A bump financed out of this synergy costs BNKR legacy holders NOTHING in")
print("   value terms. It is the cleanest possible ask.\n")
R_syn = (A_mkt + syn_cad)/B_mkt*K
print(f"Ratio that hands AGA the full financing synergy at a FLAT (no-RM) outcome:")
print(f"  R = {R_syn:.4f}  vs struck {R:.4f}   ({R_syn/R-1:+.1%})   <- affordable TODAY, no assays needed\n")

# -------------------------------------------------------- 3. COST OF THE BUMP
print("=== 3. WHAT EACH BUMP COSTS BNKR LEGACY (relative dilution) ===")
print(f"{'bumped R':>10} {'vs struck':>10} {'AGA share':>11} {'BNKR legacy':>12} {'dilution':>10} {'extra sh':>10}")
print("-"*70)
for Rn in [0.1724,0.1800,0.1900,0.2000,0.2100,0.2279,0.2500]:
    s=(N_A*Rn)/(N_B+N_A*Rn); dil=((1-s)/(1-S_AGA)-1)*100
    tag=" <- fair @ DISCOVERY" if abs(Rn-0.2279)<1e-9 else (" <- struck" if Rn==R else "")
    print(f"{Rn:10.4f} {Rn/R-1:+9.1%} {s*100:10.1f}% {(1-s)*100:11.1f}% {dil:+9.1f}% "
          f"{(N_A*Rn-new_sh):9.2f}M{tag}")

# ---------------------------------------------------------- 4. VOTE ARITHMETIC
print("\n=== 4. VOTE ARITHMETIC — how big a bloc actually blocks ===")
print("Two hurdles: (a) 66-2/3% of votes CAST; (b) MI 61-101 majority of the MINORITY.")
LOCKED = 0.093          # voting support agreements, AGA side
CB     = 0.05           # ASSUMED collateral-benefit holders excluded from MOM (McNamara et al) - UNVERIFIED
print(f"locked support {LOCKED*100:.1f}% of shares out; collateral-benefit exclusion ASSUMED {CB*100:.0f}% (UNVERIFIED)\n")
print(f"{'turnout':>8} {'votes cast':>11} {'no-votes to fail 66.7%':>24} {'no-votes to fail MOM':>22}")
print("-"*70)
for T in [0.30,0.40,0.50,0.60,0.75]:
    cast = T                                   # as a fraction of shares outstanding
    need_super = cast/3                        # >33.3% of cast defeats the 66-2/3% test
    minority_cast = max(cast-CB, 0.0)          # CB holders' votes stripped from the MOM pool
    need_mom = minority_cast/2
    print(f"{T*100:7.0f}% {cast*100:10.1f}% {need_super*100:23.1f}% {need_mom*100:21.1f}%")
print("\nRead: at a typical 40% TSXV arrangement turnout, a bloc holding ~13.3% of shares")
print("out defeats the 66-2/3% test, and ~17.5% defeats MOM. THE SUPERMAJORITY TEST")
print("BINDS FIRST — it is the cheaper hurdle to fail, and the one a dissident targets.")
print(f"Locked support is only {LOCKED*100:.1f}%; the register is retail-heavy. This is a")
print("winnable no-campaign, which is exactly what makes a bump negotiable.")

# ------------------------------------------------- 5. WHAT THE SPREAD IS SAYING
print("\n=== 5. THE SPREAD AS A BUMP-PROBABILITY GAUGE ===")
BN, AG = 4.77, 0.77
cons = R*BN
print(f"consideration today = {R} x {BN} = C${cons:.4f}; AGA C${AG:.2f} -> "
      f"{(AG/cons-1)*100:+.1f}% (discount)")
print(f"premium decayed: C$0.9275 (+38.4%) -> C${cons:.4f} ({cons/0.67-1:+.1%}) vs undisturbed 0.67")
print("A discount means the market prices deal RISK and ZERO bump. The tell that a")
print("bloc has formed is the spread INVERTING - AGA trading ABOVE consideration.")
print(f"Watch line: AGA > C${cons:.2f} at BNKR {BN} is the first evidence of bump pricing.")
