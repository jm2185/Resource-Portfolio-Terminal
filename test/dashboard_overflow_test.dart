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
}
