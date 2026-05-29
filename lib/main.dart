import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';

void main() => runApp(const CommodityExApp());

class CommodityExApp extends StatelessWidget {
  const CommodityExApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CommodityEx Terminal',
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF0A0A0A),
        textTheme: ThemeData.dark().textTheme.apply(fontFamily: 'Roboto'),
      ),
      home: const DashboardScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: SafeArea(child: MainTerminalView()),
    );
  }
}

class MainTerminalView extends StatefulWidget {
  const MainTerminalView({super.key});

  @override
  State<MainTerminalView> createState() => _MainTerminalViewState();
}

class _MainTerminalViewState extends State<MainTerminalView> {
  final _channel = WebSocketChannel.connect(Uri.parse('ws://127.0.0.1:8000/ws'));
  bool _censorSensitiveData = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('COMMODITYEX // MASTER ARCHITECTURE v4.0', 
            style: TextStyle(fontFamily: 'monospace', fontSize: 14)),
        actions: [
          IconButton(
            icon: Icon(_censorSensitiveData ? Icons.visibility_off : Icons.visibility),
            onPressed: () => setState(() => _censorSensitiveData = !_censorSensitiveData),
            tooltip: 'Toggle Censor Sensitive Data',
          ),
        ],
      ),
      body: StreamBuilder(
        stream: _channel.stream,
        builder: (context, snapshot) {
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator(color: Colors.amber));
          }

          final data = Map<String, dynamic>.from(jsonDecode(snapshot.data as String));
          final metrics = data['metrics'] ?? {};
          final val = data['v4_valuation'] ?? data['v3_valuation'] ?? {};
          final nodes = data['nodes'] ?? {};
          final bvs = (val['BVS'] ?? 45.0).toDouble();
          final regime = data['macro_regime'] ?? "Pending Data...";
          final directive = data['directive'] ?? "Waiting for tape...";

          final hasRealData = val.isNotEmpty && val.containsKey('Total_Equity');
          
          bool isDataDegraded = false;
          metrics.forEach((key, value) {
            final status = value['status']?.toString() ?? '';
            if (status.contains('STALE') || status.contains('FALLBACK')) {
              isDataDegraded = true;
            }
          });

          String headerText;
          Color headerColor;

          if (!hasRealData) {
            headerText = "CONNECTING • INITIALIZING TAPES...";
            headerColor = Colors.orangeAccent;
          } else if (isDataDegraded) {
            headerText = "LIVE (DEGRADED DATA) • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = Colors.amber;
          } else {
            headerText = "LIVE • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = bvs < 40 
                ? Colors.greenAccent 
                : bvs < 65 
                    ? Colors.orangeAccent 
                    : Colors.redAccent;
          }

          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  headerText,
                  style: TextStyle(
                    color: headerColor,
                    fontSize: 13,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 12),

                _buildMacroRiskDashboard(bvs, regime, directive),
                const SizedBox(height: 20),

                _buildSynthesisPanel(val, bvs),
                const SizedBox(height: 24),

                _buildForensicCovariancePanel(data['forensics'] ?? {}, data['portfolio_stats'] ?? {}),
                const SizedBox(height: 24),

                _buildFluidMacroGrid(metrics),
                const SizedBox(height: 24),

                _buildDetailedBreakdown(val),
                const SizedBox(height: 24),

                _buildBarbell(nodes, metrics['VIX']?['value']?.toDouble() ?? 16.5),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildSynthesisPanel(Map<String, dynamic> val, double bvs) {
    final currentValue = (val['Total_Equity'] ?? 0.0).toDouble();
    final targetCapital = (val['E_Target'] ?? 0.0).toDouble();
    final kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final impliedEdge = (val['Implied_Upside'] ?? 0.0).toDouble();
    final repFloor = (val['REP_Floor'] ?? 0.0).toDouble();
    final runway = (val['Cash_Runway_Months'] ?? 0.0).toDouble();

    String displayCurrent = _censorSensitiveData ? "••••••" : "\$${currentValue.toStringAsFixed(2)}";
    String displayTarget = _censorSensitiveData ? "••••••" : "\$${targetCapital.toStringAsFixed(2)}";

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("SYNTHESIS & ACTIONABLE OVERVIEW", 
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.white)),
        const SizedBox(height: 12),

        Row(
          children: [
            Expanded(child: _buildMetricBox("CURRENT VALUE", displayCurrent, Colors.white70)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("TARGET CAPITAL", displayTarget, Colors.greenAccent)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("KELLY MULTIPLE", "${kelly.toStringAsFixed(2)}x", _getKellyColor(kelly))),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _buildMetricBox("REP FLOOR", "\$${repFloor.toStringAsFixed(3)}", Colors.white70)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("CASH RUNWAY", "${runway.toStringAsFixed(1)} mo", _getRunwayColor(runway))),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("IMPLIED EDGE", "${impliedEdge.toStringAsFixed(1)}%", _getEdgeColor(impliedEdge))),
          ],
        ),

        const SizedBox(height: 16),
        _buildActionableInsights(val, bvs),
      ],
    );
  }

  Widget _buildActionableInsights(Map<String, dynamic> val, double bvs) {
    final kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final edge = (val['Implied_Upside'] ?? 0.0).toDouble();

    String recommendation = "HOLD POSITION - Monitor tape and structural asset tracking";
    Color recColor = Colors.orange;

    if (bvs < 40 && edge > 80) {
      recommendation = "HIGH CONVICTION ZONE - System signals expansion. Opportunistically scale barbell adds.";
      recColor = Colors.greenAccent;
    } else if (kelly > 1.5) {
      recommendation = "CAUTION - Allocation limits breached via Kelly criteria. Trim positions on technical strength.";
      recColor = Colors.redAccent;
    } else if (bvs > 65) {
      recommendation = "DEFENSIVE MODE - Sovereign macro volatility elevated. Preserve cash equity buffer.";
      recColor = Colors.redAccent;
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: recColor.withOpacity(0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: recColor.withOpacity(0.5)),
      ),
      child: Text(
        recommendation,
        style: TextStyle(color: recColor, fontSize: 13, fontWeight: FontWeight.bold),
      ),
    );
  }

  Widget _buildDetailedBreakdown(Map<String, dynamic> val) {
    final agaIntrinsic = (val['AGA_Intrinsic'] ?? 0.0).toDouble();
    final isIai = (val['IS_IAI_Per_Share'] ?? 0.0).toDouble();
    final expPremium = (val['Exp_Premium_Per_Share'] ?? 0.0).toDouble();
    final ppi = (val['PPI'] ?? 0.0).toDouble();
    final evBlended = (val['EV_Blended'] ?? 0.0).toDouble();
    final probability = (val['Probability'] ?? 0.65).toDouble();
    final rov = (val['ROV'] ?? 1.18).toDouble();
    final advCap = (val['ADV_Cap_CAD'] ?? 0.0).toDouble();
    final peerDiscCost = (val['Discovery_Efficiency_Comps'] ?? 0.48).toDouble();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("DETAILED FORENSIC BREAKDOWN", 
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.white)),
        const SizedBox(height: 12),

        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _buildMetricBox("AGA INTRINSIC", "\$${agaIntrinsic.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("IS-IAI / SHARE", "\$${isIai.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("EXP. PREMIUM / SHARE", "\$${expPremium.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("PPI", "\$${ppi.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("EV BLENDED", "\$${evBlended.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("BLENDED PROBABILITY", "${(probability*100).toStringAsFixed(1)}%", Colors.white70),
            _buildMetricBox("ROV MULTIPLE", rov.toStringAsFixed(2), Colors.white70),
            _buildMetricBox("ADV SIZING CAP", "\$${advCap.toStringAsFixed(0)}", Colors.orangeAccent),
            _buildMetricBox("PEER DISC COST", "\$${peerDiscCost.toStringAsFixed(2)}/oz", Colors.white70),
          ],
        ),
      ],
    );
  }

  Widget _buildForensicCovariancePanel(Map<String, dynamic> forensics, Map<String, dynamic> stats) {
    final jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final penalty = (forensics['penalty_factor'] ?? 1.0).toDouble();
    final runway = (forensics['runway'] ?? 0.0).toDouble();
    final sloanCfo = (forensics['sloan_cfo'] ?? 0.0).toDouble();
    final sloanBs = (forensics['sloan_bs'] ?? 0.0).toDouble();
    final es95 = (stats['expected_shortfall_95'] ?? 0.0).toDouble();
    final avgCorr = (stats['avg_correlation'] ?? 0.0).toDouble();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("FORENSIC RISK SHIELD & COVARIANCE (v5)", 
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.white)),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _buildMetricBox("JSF SCORE", "${jsf.toStringAsFixed(1)} / 4.0", jsf == 4.0 ? Colors.greenAccent : Colors.orangeAccent)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("PENALTY DISCOUNT", "${penalty.toStringAsFixed(3)}x", penalty == 1.0 ? Colors.greenAccent : Colors.redAccent)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("EXPECTED SHORTFALL", "${es95.toStringAsFixed(2)}%", Colors.orangeAccent)),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _buildMetricBox("SLOAN CFO ACCRUALS", sloanCfo.toStringAsFixed(4), sloanCfo < 0.05 ? Colors.greenAccent : Colors.redAccent)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("SLOAN BS ACCRUALS", sloanBs.toStringAsFixed(4), sloanBs < 0.05 ? Colors.greenAccent : Colors.redAccent)),
            const SizedBox(width: 12),
            Expanded(child: _buildMetricBox("PORTFOLIO CORR", avgCorr.toStringAsFixed(2), Colors.white70)),
          ],
        ),
      ],
    );
  }

  Widget _buildMetricBox(String label, String value, Color color) {
    return Tooltip(
      message: _getRichTooltip(label),
      child: Container(
        width: 170,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF1A1A1A),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(0.4), width: 1.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11)),
            const SizedBox(height: 6),
            Text(value, style: TextStyle(color: color, fontSize: 19, fontWeight: FontWeight.bold, fontFamily: 'Courier')),
          ],
        ),
      ),
    );
  }

  String _getRichTooltip(String label) {
    switch (label) {
      case "CURRENT VALUE": return "Real-time portfolio market equity value scaled in CAD.";
      case "TARGET CAPITAL": return "Model-recommended sizing using Kelly optimization scaled against real-time macro stress floors.";
      case "KELLY MULTIPLE": return "Ratio of actual deployment vs risk-balanced limit targets.";
      case "REP FLOOR": return "Liquidation and replacement cost floor evaluation for structural safety bounds.";
      case "CASH RUNWAY": return "Corporate cash lifespan. Under 18 months prompts dilution warning triggers.";
      case "IMPLIED EDGE": return "Calculated mispricing yield between portfolio index price and blended model intrinsic value.";
      case "CFTC MM POSITION": return "Commitment of Traders net contract positioning of Managed Money. Low values mean speculative capitulation (bullish contrarian).";
      default: return label;
    }
  }

  Color _getKellyColor(double kelly) {
    if (kelly <= 1.0) return Colors.greenAccent;
    if (kelly <= 1.5) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Color _getEdgeColor(double edge) {
    if (edge >= 80) return Colors.greenAccent;
    if (edge >= 40) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Color _getRunwayColor(double months) {
    if (months >= 24) return Colors.greenAccent;
    if (months >= 12) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Widget _buildMacroRiskDashboard(double bvs, String regime, String directive) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text("MACRO RISK DASHBOARD", style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
            Text("BVS: ${bvs.toStringAsFixed(1)}", style: const TextStyle(fontSize: 14, color: Colors.white)),
          ],
        ),
        const SizedBox(height: 8),
        LinearProgressIndicator(
          value: bvs / 100,
          backgroundColor: Colors.grey[800],
          color: bvs < 40 ? Colors.greenAccent : bvs < 65 ? Colors.orangeAccent : Colors.redAccent,
        ),
        const SizedBox(height: 6),
        Text("$regime // $directive", style: const TextStyle(color: Colors.grey, fontSize: 12)),
      ],
    );
  }

  Color _getMetricColor(String key, double value) {
    if (value == 0) return Colors.white70;
    switch (key) {
      case '10Y':
        if (value < 3.75) return Colors.greenAccent;
        if (value <= 4.75) return Colors.orangeAccent;
        return Colors.redAccent;
      case '30Y':
        if (value < 4.00) return Colors.greenAccent;
        if (value <= 5.00) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'DXY':
        if (value < 100.0) return Colors.greenAccent;
        if (value <= 104.5) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'Spreads':
        if (value < 3.50) return Colors.greenAccent;
        if (value <= 5.00) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'TED':
        if (value < 0.20) return Colors.greenAccent;
        if (value <= 0.45) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'VIX':
        if (value < 15.0) return Colors.greenAccent;
        if (value <= 23.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'WTI':
        if (value >= 65.0 && value <= 85.0) return Colors.greenAccent;
        if ((value >= 50.0 && value < 65.0) || (value > 85.0 && value <= 95.0)) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'Spot_Ag':
        if (value >= 32.0) return Colors.greenAccent;
        if (value >= 24.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'CFTC':
        if (value < 15000) return Colors.greenAccent;
        if (value <= 65000) return Colors.orangeAccent;
        return Colors.redAccent;
      default:
        return Colors.white70;
    }
  }

  Widget _buildFluidMacroGrid(Map<String, dynamic> metrics) {
    final double cftcVal = (metrics['CFTC_Silver_Net_Longs']?['value'] ?? 35000.0).toDouble();
    
    String formatContracts(double val) {
      if (val.abs() >= 1000) {
        return "${(val / 1000).toStringAsFixed(1)}k";
      }
      return val.toStringAsFixed(0);
    }

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        _buildMetricBox("10Y YIELD", "${(metrics['10Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('10Y', (metrics['10Y']?['value'] ?? 0).toDouble())),
        _buildMetricBox("30Y YIELD", "${(metrics['30Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('30Y', (metrics['30Y']?['value'] ?? 0).toDouble())),
        _buildMetricBox("DXY", "${(metrics['DXY']?['value'] ?? 0).toStringAsFixed(1)}", _getMetricColor('DXY', (metrics['DXY']?['value'] ?? 0).toDouble())),
        _buildMetricBox("HY SPREADS", "${(metrics['Spreads']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('Spreads', (metrics['Spreads']?['value'] ?? 0).toDouble())),
        _buildMetricBox("TED SPREAD", "${(metrics['TED']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('TED', (metrics['TED']?['value'] ?? 0).toDouble())),
        _buildMetricBox("VIX INDEX", "${(metrics['VIX']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('VIX', (metrics['VIX']?['value'] ?? 0).toDouble())),
        _buildMetricBox("WTI CRUDE", "\$${(metrics['WTI']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('WTI', (metrics['WTI']?['value'] ?? 0).toDouble())),
        _buildMetricBox("SILVER", "\$${(metrics['Spot_Ag']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('Spot_Ag', (metrics['Spot_Ag']?['value'] ?? 0).toDouble())),
        _buildMetricBox("CFTC MM POSITION", formatContracts(cftcVal), _getMetricColor('CFTC', cftcVal)),
      ],
    );
  }

  Widget _buildBarbell(Map<String, dynamic> nodes, double vix) {
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: nodes.entries.map((e) {
        bool isSpear = e.value['role'] == 'The Spear';
        return Tooltip(
          message: isSpear 
              ? "The Spear (60% allocation)\nHigh-conviction torque engine - primary source of upside"
              : "Ballast (40% allocation)\nStable royalty/producer exposure for risk mitigation",
          child: Container(
            width: 175,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A1A),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: (isSpear && vix > 23.0) ? Colors.redAccent : Colors.transparent, 
                width: 2
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(e.key, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                Text("\$${e.value['price']}", style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold)),
                Text(e.value['role'], style: TextStyle(color: isSpear ? Colors.amber : Colors.grey, fontSize: 12)),
              ],
            ),
          ),
        );
      }).toList(),
    );
  }
}