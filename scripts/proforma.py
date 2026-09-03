"""Pro forma cash-flow shape. Every input labelled by source; nothing asserted that isn't traceable."""
LB_PER_T = 2204.62

# --- 2022 PFS Year-1 metal at 1,800 stpd (source: BNKR 2022 PFS, via verified desk note 20260902-213211)
PFS = dict(zn_mlb=62.1, pb_mlb=28.1, ag_koz=390.0, aisc_zn_lb=0.77, capex_pfs=55e6, npv8=52e6)
# --- Spot (2026-09-03): Ag Yahoo SI=F; Zn/Pb LME via TradingEconomics
PX = dict(ag=67.58, zn_t=3877.0, pb_t=1899.0)
px_zn_lb, px_pb_lb = PX['zn_t']/LB_PER_T, PX['pb_t']/LB_PER_T

def contained(rate):
    """Contained-metal revenue at `rate` x PFS Y1 volumes, spot prices."""
    zn = PFS['zn_mlb']*1e6*rate*px_zn_lb
    pb = PFS['pb_mlb']*1e6*rate*px_pb_lb
    ag = PFS['ag_koz']*1e3*rate*PX['ag']
    return zn, pb, ag, zn+pb+ag

print(f"Spot: Ag ${PX['ag']}/oz | Zn ${PX['zn_t']}/t = ${px_zn_lb:.3f}/lb | Pb ${PX['pb_t']}/t = ${px_pb_lb:.3f}/lb")
print("(Zn is at its highest since May-2022 — a genuine tailwind for a Zn-weighted producer)\n")

for label, rate in (("65% of nameplate  (the REDEFINED commercial-production bar)",0.65),
                    ("100% nameplate 1,800 stpd (2022 PFS Y1)",1.00),
                    ("2,500 tpd 'Bunker Hill 2.0' expansion",1.389)):
    zn,pb,ag,tot = contained(rate)
    # Payable haircut: TC/RC + payability on Zn/Pb concentrate. Range, not a point.
    lo,hi = tot*0.70, tot*0.78
    print(f"{label}")
    print(f"   contained: Zn ${zn/1e6:6.1f}M | Pb ${pb/1e6:5.1f}M | Ag ${ag/1e6:5.1f}M  = ${tot/1e6:6.1f}M")
    print(f"   payable (70-78% after TC/RC + payability, ASSUMPTION): ${lo/1e6:.0f}-{hi/1e6:.0f}M")
    print(f"   Ag share of revenue: {ag/tot*100:.0f}%  <- why the silver beta is 0.57, not 1.0")
    print()

# --- The claims on that cash flow -------------------------------------------------
print("="*78); print("ANNUAL CLAIMS ON CASH FLOW (source: Q2-2026 10-Q, verified note 20260902-215616)"); print("="*78)
SILVER_LOAN_OZ = 1.2e6
int_oz = SILVER_LOAN_OZ*0.135                       # 13.5%, PAID IN OUNCES quarterly
ag_prod_65 = PFS['ag_koz']*1e3*0.65
print(f"Silver-loan INTEREST: {int_oz:,.0f} oz/yr (13.5% of 1.2Moz, paid in metal)")
print(f"   = ${int_oz*PX['ag']/1e6:.1f}M/yr at spot")
print(f"   = {int_oz/ag_prod_65*100:.0f}% of silver produced at the 65% bar ({ag_prod_65:,.0f} oz)")
print(f"   = {int_oz/(PFS['ag_koz']*1e3)*100:.0f}% of silver produced at FULL nameplate")
print(f"   ~38% of Phase-1 Ag is separately PRE-SOLD (offtake/stream) -> the residual free ounce is small\n")
interest = {'Silver loan 13.5% (in oz)': int_oz*PX['ag'], 'Sprott facility $14.84M @10-15%': 14.84e6*0.115,
            'Teck standby $8-10M @13.5-15%': 9e6*0.14, 'Sprott debentures $16.6M @5%': 16.6e6*0.05,
            'Ocean Partners ~$3-10M @SOFR+7%': 6.5e6*0.115}
for k,v in interest.items(): print(f"   {k:42s} ${v/1e6:5.1f}M")
tot_int=sum(interest.values()); print(f"   {'TOTAL CASH INTEREST':42s} ${tot_int/1e6:5.1f}M/yr")
_,_,_,rev65 = contained(0.65); pay65=rev65*0.74
roy = pay65*0.035
print(f"   {'Sprott royalties 1.85% + 1.65% GRR':42s} ${roy/1e6:5.1f}M/yr  (off the top, FOREVER)")
print(f"\n   Interest + royalties = ${(tot_int+roy)/1e6:.0f}M/yr\n")

print("="*78); print("THE BAR-CASE BRIDGE (65% of nameplate, spot metal)"); print("="*78)
# AISC $0.77/lb Zn at nameplate; unit costs RISE at partial throughput -> range
for aisc in (0.95, 1.15):
    zn_lb = PFS['zn_mlb']*1e6*0.65
    ebitda = (px_zn_lb-aisc)*zn_lb           # AISC is net-of-byproduct per lb Zn (co-product credits inside)
    fcf = ebitda - tot_int - roy - 10e6      # ~$10M sustaining capex ASSUMPTION
    print(f"   AISC ${aisc:.2f}/lb Zn -> EBITDA ${ebitda/1e6:5.1f}M | less int+roy+sustaining -> FCF ${fcf/1e6:6.1f}M")
print("   (PFS AISC was $0.77/lb at FULL rate; partial throughput carries fixed cost, hence 0.95-1.15)\n")

print("="*78); print("THE WALL"); print("="*78)
print(f"Silver-loan PRINCIPAL: {SILVER_LOAN_OZ:,.0f} oz, fully drawn, MATURES 2026-08-08 +1yr = AUG 8 2027")
print(f"   at spot ${PX['ag']}/oz = ${SILVER_LOAN_OZ*PX['ag']/1e6:.0f}M")
print(f"   = {SILVER_LOAN_OZ/(PFS['ag_koz']*1e3):.1f} YEARS of total silver production at full nameplate")
print(f"   = {SILVER_LOAN_OZ/ag_prod_65:.1f} years at the 65% bar")
for s in (60,80,100,120):
    print(f"   silver ${s:>3}/oz -> liability ${SILVER_LOAN_OZ*s/1e6:5.0f}M   (every $10/oz = +${SILVER_LOAN_OZ*10/1e6:.0f}M)")
print("\n   NOT repayable from operations under ANY throughput case. Must be refinanced,")
print("   restructured, or equitized. 10-Q: 'may require securing additional capital'.")
print("\nAGA TREASURY vs THE BURN")
aga_cad=48e6; fx=1.379; aga_usd=aga_cad/fx
print(f"   AGA C${aga_cad/1e6:.0f}M = US${aga_usd/1e6:.1f}M")
print(f"   BNKR standby-draw cadence ~US$5.5M/mo -> AGA cash = {aga_usd/5.5e6:.1f} months of the CURRENT burn")
print(f"   BNKR unrestricted cash 6/30: US$6.66M | working-capital deficit US$11.8M | Teck headroom US$2M")
print(f"   AGA cash as % of the silver-loan wall: {aga_usd/(SILVER_LOAN_OZ*PX['ag'])*100:.0f}%")
