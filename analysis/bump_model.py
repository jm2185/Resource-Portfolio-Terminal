"""AGA/BNKR bump model — what ratio is fair under each Red Mountain outcome,
and what it costs Bunker Hill to pay it."""

R      = 0.1724      # BNKR shares per AGA share (agreement)
S_AGA  = 0.433       # AGA holders' pro-forma share of combined (press release)
N_A    = 208.6       # AGA shares out, millions (med confidence, not primary-sourced)
FX     = 1.37        # USDCAD

# --- share structure, derived from the two disclosed anchors -----------------
new_sh  = N_A * R                    # BNKR shares issued to AGA holders
total   = new_sh / S_AGA             # implied combined share count
N_B     = total - new_sh             # BNKR shares outstanding

print("=== SHARE STRUCTURE (derived from R and the 43.3% split) ===")
print(f"BNKR shares issued to AGA holders : {new_sh:6.2f}M")
print(f"BNKR shares outstanding (derived) : {N_B:6.2f}M")
print(f"Combined shares                   : {total:6.2f}M")
print(f"AGA share of combined             : {new_sh/total*100:5.2f}%   (target 43.3%)")

# validation against the reported pro-forma market cap at signing
print(f"\nVALIDATION  pro-forma mcap @ BNKR 5.38 = C${total*5.38:6.1f}M = US${total*5.38/FX:5.0f}M"
      f"   (desk record: ~US$326M)")

# --- the fair-ratio identity ------------------------------------------------
# ownership split must equal value split:  N_A*R/(N_B+N_A*R) = V_A/(V_A+V_B)
#   =>  R* = (V_A/V_B) * (N_B/N_A)
K = N_B / N_A
print(f"\n=== FAIR-RATIO IDENTITY ===")
print(f"R* = (V_A / V_B) x {K:.5f}        [V_A, V_B = STANDALONE values]")
print(f"Struck R = {R} implies the boards priced AGA standalone at "
      f"{R/K*100:.2f}% of Bunker Hill standalone.")

# --- what the market said, undisturbed --------------------------------------
AGA_und, BNK_und = 0.67, 5.38
A_mkt = AGA_und * N_A
B_mkt = BNK_und * N_B
print(f"\n=== MARKET vs DEAL, at the undisturbed marks ===")
print(f"AGA  mcap  C${A_mkt:6.1f}M  (208.6M x 0.67)")
print(f"BNKR mcap  C${B_mkt:6.1f}M  ({N_B:.1f}M x 5.38)")
print(f"market V_A/V_B = {A_mkt/B_mkt:.4f}   ->  market-implied fair ratio {A_mkt/B_mkt*K:.4f}")
print(f"deal   V_A/V_B = {R/K:.4f}   ->  struck ratio                {R:.4f}")
print(f"the premium = the gap between those two.")

# --- what BNKR is actually buying -------------------------------------------
CASH = 48.0                                   # C$M working capital, as_of 2026-06-12
OZ   = 236.3                                  # Moz AgEq in ground (reconciled per-district)
cash_ratio = CASH / (N_A * BNK_und)           # ratio justified by AGA's cash alone
noncash    = (R - cash_ratio) * N_A * BNK_und
print(f"\n=== WHAT BNKR IS PAYING FOR ===")
print(f"AGA cash C${CASH:.0f}M alone justifies a ratio of {cash_ratio:.4f} "
      f"({cash_ratio/R*100:.0f}% of the struck ratio)")
print(f"=> non-cash consideration C${noncash:.1f}M (US${noncash/FX:.0f}M) for {OZ:.1f} Moz AgEq + Belmont")
print(f"=> US${noncash/FX/OZ:.3f} per AgEq oz in the ground  "
      f"[junior Ag comps ~US$0.30-1.50/oz; T1 US jurisdiction]")

# --- the bump table ---------------------------------------------------------
# D = Red Mountain's value delta to AGA STANDALONE, as a % re-rate of A_mkt
print(f"\n=== BUMP TABLE — fair ratio by Red Mountain outcome ===")
print("(B held at its undisturbed C$253M; assays move AGA standalone, not BNKR standalone)")
print(f"\n{'RM outcome':22} {'dV_A':>7} {'V_A':>8} {'fair R*':>8} {'bump':>8} "
      f"{'AGA sh%':>8} {'BNKR legacy dil':>16}")
print("-"*84)
scen = [("BUST  -20%",      -0.20),
        ("no-news   0%",     0.00),
        ("MODEST  +10%",     0.10),
        ("GOOD    +40%",     0.40),
        ("DISCOVERY +83%",   0.83),   # WAM base rate: +82.8% on first visual evidence
        ("BLOWOUT +150%",    1.50)]
rows=[]
for name, g in scen:
    V_A  = A_mkt * (1 + g)
    Rst  = V_A / B_mkt * K
    s_new= (N_A*Rst)/(N_B + N_A*Rst)
    legacy_now, legacy_new = 1-S_AGA, 1-s_new
    dil  = (legacy_new/legacy_now - 1)*100
    rows.append((name,g,V_A,Rst,s_new,dil))
    print(f"{name:22} {g*100:+6.0f}% {V_A:7.0f}M {Rst:8.4f} {Rst/R-1:+7.1%} "
          f"{s_new*100:7.1f}% {dil:+15.1f}%")

print(f"\nNOTE: at the STRUCK ratio the deal already pays a 38.4% premium, i.e. it embeds")
print(f"      a re-rate of AGA standalone. Fair R* above the struck {R:.4f} means the")
print(f"      MINORITY IS WORSE OFF ACCEPTING than continuing standalone.")

# --- the indifference threshold ---------------------------------------------
thresh_g = (R/K*B_mkt)/A_mkt - 1
print(f"\n=== INDIFFERENCE THRESHOLD ===")
print(f"AGA minority is indifferent when V_A = {R/K:.4f} x V_B = C${R/K*B_mkt:.1f}M")
print(f"  = a {thresh_g*100:+.1f}% re-rate of AGA's undisturbed C${A_mkt:.1f}M mcap")
print(f"  => ANY Red Mountain outcome that re-rates AGA standalone by more than "
      f"{thresh_g*100:.0f}%\n     makes this deal VALUE-DESTRUCTIVE for the AGA minority.")
