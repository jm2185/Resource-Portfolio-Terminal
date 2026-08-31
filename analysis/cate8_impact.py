"""Cate-8 impact on the AGA/BNKR fair-ratio model."""
R,S_AGA,N_A,FX = 0.1724,0.433,208.6,1.37
new_sh=N_A*R; total=new_sh/S_AGA; N_B=total-new_sh; K=N_B/N_A
A_mkt,B_mkt = 0.67*N_A, 5.38*N_B          # undisturbed standalone marks, C$M
SYN = 25.0

print("=== SCALE CHECK: what is Cate-8 worth, honestly ===")
oz = 2.79                                  # Moz AgEq, EXPLORATION TARGET (not a resource)
print(f"Cate-8 target        : {oz:.2f} Moz AgEq (522k tons @ 5.34 oz/ton, 50 g/t cutoff)")
print(f"AGA Belmont tailings : 2.74 Moz AgEq   <- Cate-8 is the SAME SIZE as Belmont")
print(f"AGA total in-ground  : 236.3 Moz AgEq  -> Cate-8 = {oz/236.3*100:.2f}% of AGA's ounce base")
print(f"AGA implied in-ground: US$0.449/oz (from the deal's non-cash consideration)\n")
print(f"{'US$/oz AgEq':>12} {'US$M':>7} {'C$M':>7} {'% of BNKR mcap':>15}")
for p in [2,4,6,8,12]:
    v=oz*p; print(f"{p:12.0f} {v:7.1f} {v*FX:7.1f} {v*FX/B_mkt*100:14.1f}%")
print("\nnear-mine ounces at an OPERATING mill are worth multiples of remote inferred ounces,")
print("but this is an EXPLORATION TARGET with no resource estimate - discount for confidence.")

print("\n=== THE MECHANICAL CONSEQUENCE: a stronger BNKR RAISES the bar for AGA ===")
print("Fixed ratio => AGA holders capture 43.3% of BNKR's value creation (good, in dollars).")
print("But the FAIRNESS test is relative: R* = (V_A/V_B) x K falls as V_B rises.\n")
print(f"{'Cate-8 adds':>12} {'V_B':>8} {'R* @flat':>9} {'breakeven re-rate AGA must clear':>34}")
print(f"{'(C$M)':>12} {'(C$M)':>8} {'':>9} {'  no-syn      with C$25M syn':>34}")
print("-"*72)
for add in [0,10,20,30,40]:
    VB=B_mkt+add
    Rstar_flat = A_mkt/VB*K
    be_nosyn = (R/K*VB)/A_mkt-1
    be_syn   = ((R/K*VB)-SYN)/A_mkt-1
    star = "  <- as struck" if add==0 else ""
    print(f"{add:12.0f} {VB:8.1f} {Rstar_flat:9.4f} {be_nosyn*100:+13.1f}% {be_syn*100:+15.1f}%{star}")

print("\nREAD: every C$10M Cate-8 adds to Bunker Hill lifts the re-rate Red Mountain must")
print("deliver before a NO vote is justified. Good BNKR news pays you in dollars TODAY")
print("and costs you the fairness argument in NOVEMBER. That is the fixed-ratio trade.")

print("\n=== THE FINANCING LINE — the part that is NOT in the headline ===")
draws=[("2026-08-20","Teck standby draw","+1.0","6.0"),
       ("2026-08-20","Ocean Partners prepay facility (SOFR+7%)","up to +10.0","-"),
       ("2026-08-21","Silver47 'Debt Facility Covenant' ask","up to +5.0","-"),
       ("2026-08-31","Teck standby draw (TODAY)","+2.0","8.0")]
for d,w,amt,tot in draws: print(f"  {d}  {w:44} US${amt:>10}   standby o/s US${tot}")
print("\n  Teck standby: US$6.0M -> US$8.0M in ELEVEN DAYS (+33%).")
print("  Stated reason: 'additional financial flexibility as commissioning activities progress.'")
print("  Total financing arranged/drawn since Aug 20: up to US$23M on a ~US$185M market cap.")
burn = 2.0/11*30
print(f"  Implied standby burn rate ~US${burn:.1f}M/month if the cadence holds.")
print(f"  AGA's C$48M (US${48/FX:.0f}M) covers ~{48/FX/burn:.0f} months of that. THE CASH NEED IS ACCELERATING.")
