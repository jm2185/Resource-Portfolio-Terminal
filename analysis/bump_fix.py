R,S_AGA,N_A,FX = 0.1724,0.433,208.6,1.37
new_sh=N_A*R; total=new_sh/S_AGA; N_B=total-new_sh; K=N_B/N_A
A_mkt,B_mkt = 0.67*N_A, 5.38*N_B
V_A_deal = R/K*B_mkt                      # what the struck ratio already concedes to AGA
SYN = 25.0                                # C$M financing synergy (US$18M)

print("CORRECTED SYNERGY BUMP — measured off the DEAL value, not the market value")
print(f"  struck ratio already concedes V_A = C${V_A_deal:.1f}M (the 38.4% premium)")
print(f"  + financing synergy C${SYN:.0f}M  -> C${V_A_deal+SYN:.1f}M")
R_syn=(V_A_deal+SYN)/B_mkt*K
print(f"  => R = {R_syn:.4f}   ({R_syn/R-1:+.1%} bump)  <- affordable TODAY, no assays required\n")

print("=== THE FULL LADDER: synergy + Red Mountain outcome ===")
print(f"{'RM outcome':18} {'fair R* (no syn)':>17} {'fair R* (+syn)':>15} {'bump':>8} {'BNKR dil':>10}")
print("-"*76)
for name,g in [("BUST -20%",-0.20),("flat 0%",0.0),("MODEST +10%",0.10),
               ("GOOD +40%",0.40),("DISCOVERY +83%",0.83),("BLOWOUT +150%",1.50)]:
    V=A_mkt*(1+g)
    R1=V/B_mkt*K; R2=(V+SYN)/B_mkt*K
    s=(N_A*R2)/(N_B+N_A*R2); dil=((1-s)/(1-S_AGA)-1)*100
    print(f"{name:18} {R1:17.4f} {R2:15.4f} {R2/R-1:+7.1%} {dil:+9.1f}%")

print(f"\nBREAKEVEN RE-RATE (incl. synergy): AGA minority indifferent at")
g_star=((R/K*B_mkt)-SYN)/A_mkt-1
print(f"  a {g_star*100:+.1f}% re-rate of AGA standalone -- BELOW that, accept; above it, the")
print(f"  deal transfers value to Bunker Hill. (Was +38.4% ignoring the synergy.)")
print(f"\nWAM discovery base rate = +82.8%. That is {0.828/g_star:.1f}x the breakeven.")
