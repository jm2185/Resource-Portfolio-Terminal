// Regression guard for the dashboard layout: renders the FULL dashboard with a
// realistic seeded payload across a range of desktop widths and asserts that no
// RenderFlex/overflow exception is thrown. This is what catches the macro-tape
// and barbell overflow issues at the layout level.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:commodity_ex/main.dart';

Map<String, dynamic> _mockPayload() => {
      "status": "OK",
      "mri": 38.3,
      "macro_regime": "Expansion / Risk-On",
      "directive": "Conviction Gated - JSF Degraded - Scale Conservatively",
      "metric_metadata": <String, dynamic>{},
      "metrics": {
        "10Y": {"value": 4.45},
        "30Y": {"value": 4.99},
        "TED": {"value": 0.0},
        "DXY": {"value": 98.0},
        "Spreads": {"value": 2.72},
        "VIX": {"value": 15.7},
        "WTI": {"value": 87.36},
        "Spot_Ag": {"value": 75.8},
        "GSR": {"value": 60.5},
        "CFTC_Silver_Net_Longs": {"value": 23000.0},
        // Optional cross-asset reads to exercise the conditional tiles.
        "Real_10Y": {"value": 1.85},
        "Copper_Gold": {"value": 0.184},
        "USDCAD=X": {"value": 1.384},
      },
      "v4_valuation": {
        "Total_Equity": 142350.0,
        "E_Target": 168200.0,
        "Kelly_Multiple": 1.00,
        "Implied_Upside": 130.9,
        "REP_Floor": 0.82,
        "Cash_Runway_Months": 71.0,
        "fractional_kelly_multiplier": 0.5,
        "max_spear_position_pct": 0.60,
        "intrinsic_convergence_months": 18.0,
        "ADV_Cap_CAD": 29902.0,
        "ADV_Cap_Percentage": 9.2,
        "AGA_Intrinsic": 4.374,
        "IS_IAI_Per_Share": 6.171,
        "Exp_Premium_Per_Share": 0.030,
        "PPI": 1.851,
        "EV_Blended": 4.274,
        "Probability": 0.73,
        "Forensic_Penalty": 0.935,
        "ROV": 1.21,
        "Discovery_Efficiency_Comps": 0.47,
        "raw_kelly_leverage": 1.8,
        "vix_capped_leverage": 1.45,
        "post_correlation_leverage": 1.25,
        "post_es_leverage": 1.1,
        "usd_to_cad": 1.384,
        // Phase 2: parameter-uncertainty + catalyst gates surfaced in the waterfall.
        "edge_confidence": 0.79,
        "catalyst_factor": 0.85,
        "spear_momentum_pct": 4.2,
      },
      "nodes": {
        "AGA.V": {"price": 0.71, "shares": 5000.0, "role": "The Spear"},
        "GROY": {"price": 3.25, "shares": 161.0, "role": "Ballast"},
        "URC.TO": {"price": 4.87, "shares": 130.0, "role": "Ballast"},
        "GMX.TO": {"price": 2.07, "shares": 230.0, "role": "Ballast"},
      },
      "forensics": {"jsf_score": 3.0, "sloan_cfo": -0.0063, "sloan_bs": -0.2220},
      "portfolio_stats": {
        "expected_shortfall_95": -6.03,
        "avg_correlation": 0.55,
        "port_vol": 0.40,
        "usd_to_cad": 1.384,
        "vols": {"AGA.V": 0.74},
        "correlations": {
          "AGA.V": {"GROY": 0.5, "URC.TO": 0.5, "GMX.TO": 0.5}
        },
      },
      // Phase 2: Fluid Macro Tape, MRI decomposition, and the integrity alert strip.
      "macro_tape": {
        "net_tilt": "RISK-ON",
        "risk_off_count": 2,
        "risk_on_count": 5,
        "top_mri_driver": "Commodity Regime",
        "vix_term_structure": 1.12,
        "signals": [
          {"key": "dxy_gold", "label": "DXY/Gold ×1k", "display": "42.13", "bias": "risk_on", "read": "Gold dominant"},
          {"key": "vix_term", "label": "VIX Term (3M/1M)", "display": "1.12", "bias": "risk_on", "read": "Contango (calm)"},
        ],
      },
      "mri_decomposition": {
        "mri": 38.3,
        "top_driver": "Commodity Regime",
        "blocks": [
          {"key": "commodity", "name": "Commodity Regime", "score": 78.5, "weight": 0.15, "contribution": 11.8},
          {"key": "yield_curve", "name": "Yield & Curve", "score": 47.0, "weight": 0.20, "contribution": 9.4},
          {"key": "sentiment", "name": "Spec Positioning", "score": 50.0, "weight": 0.15, "contribution": 7.5},
          {"key": "liquidity_fx", "name": "Liquidity & FX", "score": 24.3, "weight": 0.30, "contribution": 7.3},
          {"key": "volatility", "name": "Volatility & Credit", "score": 17.0, "weight": 0.20, "contribution": 3.4},
        ],
      },
      "integrity": {
        "status": "DEGRADED_STALE",
        "any_stale": true,
        "alerts": [
          "STALE DATA: cftc past freshness threshold",
          "FORENSIC WAIVER ACTIVE on AGA.V DILUTION (expires in 30d — confirm before relying on JSF)",
        ],
      },
      "health_radar": {
        "health_rating": 8.1,
        "rating_desc": "MODERATE QUALITY - EXERCISE GUARDRAILS",
        "rating_color": "green",
        "health_summary":
            "Mild accounting or dilution drags present, or rising macro stress.",
        "priorities": [
          {
            "icon": "shopping_cart_outlined",
            "color": "green",
            "title": "EXPLOIT SPEAR ARBITRAGE",
            "desc": "AGA.V trading at a massive discount to intrinsic."
          },
          {
            "icon": "warning_amber_rounded",
            "color": "orange",
            "title": "MITIGATE JUNIOR ACCOUNTING STRESS",
            "desc": "JSF degraded; enforce strict allocation caps."
          },
          {
            "icon": "check_circle_outline",
            "color": "green",
            "title": "EXECUTE BLOCK TRADES CONFIDENTLY",
            "desc": "Exit liquidity cap expanded; large adds run safely."
          },
        ],
      },
      // Phase 7: the primary Conviction Mode block (0-10 T-Q-V Asymmetry Rating).
      "conviction_mode": {
        "status": "live",
        "view": "conviction",
        "primary": true,
        "top_pick": "AGA.V",
        "context": {"mri": 38.3, "regime": "RISK-ON"},
        "baskets": [
          {
            "ticker": "AGA.V",
            "archetype": "option_convexity",
            "archetype_code": "I",
            "rating": 7.76,
            "rating_raw": 7.76,
            "band": "STRONG ASYMMETRY",
            "directive": "BELOW FLOOR — ACCUMULATE · watch closely",
            "pillars": {
              "T": {"score": 6.65, "mri": 40.2, "alpha": 0.4, "macro_posture": 0.6,
                    "asymmetry_lean": 0.7, "alpha_contribution": 4.62, "regime_contribution": 2.03},
              "Q": {"score": 7.54, "forensic_score": 3.5, "resource_quality": 0.738,
                    "management": 0.61, "conviction": 0.6,
                    "lenses": {"grade": 0.74, "scale": 1.0, "jurisdiction": 0.76,
                               "metallurgy": 0.71, "permitting": 0.45}},
              "V": {"score": 8.71, "upside_pct": 174.6, "downside_to_floor_pct": 0.0,
                    "rho": 17.5, "floor_coverage": 1.16, "payoff": 1.0, "support": 0.82},
            },
            "pillar_weights": {"T": 0.30, "Q": 0.25, "V": 0.45},
            "gate": {"applied": false, "cap": 10.0, "reason": "clean"},
            "confidence_ribbon": {"plus_minus": 1.03, "quality": "full", "scenario_spread": 1.2},
            "ladder": {"bull": 1.95, "base": 1.69, "price": 0.71, "bear": 1.05, "floor": 0.824},
          },
          {
            "ticker": "GMX.TO",
            "archetype": "commodity_cyclical",
            "archetype_code": "III",
            "rating": 3.9,
            "band": "WEAK / EXPENSIVE",
            "directive": "UPSIDE SPENT — HOLD / TRIM",
            "pillars": {
              "T": {"score": 5.2, "mri": 38.3, "alpha": 0.2},
              "Q": {"score": 4.8, "forensic_score": 2.8, "resource_quality": 0.6, "conviction": 0.5},
              "V": {"score": 2.4, "upside_pct": 8.0, "downside_to_floor_pct": 46.0,
                    "rho": 0.2, "floor_coverage": 0.54, "payoff": 0.1, "support": 0.0},
            },
            "pillar_weights": {"T": 0.25, "Q": 0.30, "V": 0.45},
            "gate": {"applied": false, "cap": 10.0, "reason": "clean"},
            "confidence_ribbon": {"plus_minus": 0.8, "quality": "degraded"},
            "ladder": {"bull": 2.2, "base": 2.3, "price": 2.04, "bear": 1.6, "floor": 1.1},
          },
          {
            "ticker": "BAD.V",
            "archetype": "option_convexity",
            "archetype_code": "I",
            "rating": 3.5,
            "band": "WEAK / EXPENSIVE",
            "directive": "FORENSIC DECAY — AVOID / DE-RISK",
            "pillars": {
              "T": {"score": 6.0, "mri": 38.3, "alpha": 0.1},
              "Q": {"score": 2.0, "forensic_score": 1.0, "resource_quality": 0.4, "conviction": 0.4},
              "V": {"score": 5.0, "upside_pct": 60.0, "downside_to_floor_pct": 30.0,
                    "rho": 1.0, "floor_coverage": 0.7, "payoff": 0.33, "support": 0.0},
            },
            "pillar_weights": {"T": 0.30, "Q": 0.25, "V": 0.45},
            "gate": {"applied": true, "cap": 4.0, "reason": "JSF 1.0 < 1.5; dilution 30%/yr"},
            "confidence_ribbon": {"plus_minus": 1.5, "quality": "sparse"},
            "ladder": {"bull": 3.2, "base": 2.5, "price": 2.0, "bear": 1.4, "floor": 1.4},
          },
        ],
      },
    };

void main() {
  final sizes = <Size>[
    const Size(1920, 1080),
    const Size(1600, 900),
    const Size(1500, 950),
    const Size(1366, 768),
    const Size(1280, 800),
    const Size(1100, 800),
    const Size(900, 700),
    const Size(800, 600),
  ];

  for (final size in sizes) {
    testWidgets('dashboard has no overflow at ${size.width.toInt()}px',
        (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SafeArea(
              child: MainTerminalView(
                injected: TerminalState.seeded(_mockPayload()),
              ),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));

      // Any RenderFlex overflow surfaces here as a thrown FlutterError.
      expect(tester.takeException(), isNull,
          reason: 'overflow at ${size.width.toInt()}x${size.height.toInt()}');
    });
  }

  // ── Phase 7: Conviction Mode is the primary/default view ──
  testWidgets('Conviction Mode renders T-Q-V baskets by default', (tester) async {
    tester.view.physicalSize = const Size(1366, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SafeArea(
            child: MainTerminalView(
              injected: TerminalState.seeded(_mockPayload()),
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 300));

    expect(tester.takeException(), isNull);
    // The default view is Conviction Mode: the top basket + its rating + directive show.
    expect(find.text('AGA.V'), findsWidgets);
    expect(find.text('STRONG ASYMMETRY'), findsOneWidget);
    expect(find.textContaining('ACCUMULATE'), findsOneWidget);
    expect(find.textContaining('CONVICTION MODE'), findsWidgets);
  });

  testWidgets('toggle switches to Detailed Analysis without overflow',
      (tester) async {
    tester.view.physicalSize = const Size(1366, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SafeArea(
            child: MainTerminalView(
              injected: TerminalState.seeded(_mockPayload()),
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 300));

    // Tap the Detailed Analysis segment and confirm the detailed deck renders cleanly.
    await tester.tap(find.textContaining('DETAILED ANALYSIS'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(tester.takeException(), isNull,
        reason: 'overflow after toggling to Detailed Analysis');
  });
}
