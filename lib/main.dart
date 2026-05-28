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

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _channel = WebSocketChannel.connect(Uri.parse('ws://127.0.0.1:8000/ws'));
  bool _censorSensitiveData = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('COMMODITYEX // MASTER ARCHITECTURE v3.0', 
            style: TextStyle(fontFamily: 'Courier', fontSize: 14)),
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

          final data = jsonDecode(snapshot.data as String);
          final metrics = data['metrics'] ?? {};
          final val = data['v3_valuation'] ?? {};
          final nodes = data['nodes'] ?? {};
          final bvs = (val['BVS'] ?? 45.0).toDouble();
          final regime = data['macro_regime'] ?? "Pending Data...";
          final directive = data['directive'] ?? "Waiting for tape...";

          final hasRealData = val.isNotEmpty && val.containsKey('Total_Equity');

          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  hasRealData ? "LIVE • ${regime.toUpperCase()} // ${directive.toUpperCase()}" : "PENDING DATA... ${directive.toUpperCase()}",
                  style: TextStyle(
                    color: !hasRealData 
                        ? Colors.orange 
                        : bvs < 40 ? Colors.greenAccent : bvs < 65 ? Colors.orangeAccent : Colors.redAccent,
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),

                _buildMacroRiskDashboard(bvs, metrics),
                const SizedBox(height: 20),

                _buildSynthesisPanel(val, bvs),
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
            Expanded(child: _buildMetricBox("CASH RUNWAY", "${runway.toStringAsFixed(1)} mo", Colors.white70)),
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

    String recommendation = "HOLD POSITION - Monitor next drill results";
    Color recColor = Colors.orange;

    if (bvs < 40 && edge > 80) {
      recommendation = "HIGH CONVICTION ZONE - Consider opportunistic adds if BVS stays low";
      recColor = Colors.green;
    } else if (kelly > 1.5) {
      recommendation = "CAUTION - Over-allocated. Trim on strength";
      recColor = Colors.red;
    } else if (bvs > 65) {
      recommendation = "DEFENSIVE MODE - Protect capital, monitor macro closely";
      recColor = Colors.red;
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: recColor.withOpacity(0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: recColor.withOpacity(0.6)),
      ),
      child: Text(
        recommendation,
        style: TextStyle(color: recColor, fontSize: 14, fontWeight: FontWeight.bold),
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
      case "CURRENT VALUE": return "Your real-time portfolio market value in CAD.\nUsed for: Calculating Kelly Multiple and deployment sizing.";
      case "TARGET CAPITAL": return "Model-recommended capital to have deployed based on edge + macro guardrails.\nUsed for: Deciding whether to add, hold, or trim.";
      case "KELLY MULTIPLE": return "How aggressive your current allocation is vs the model’s conviction.\n<1.0x = Under-allocated | >1.5x = Risky.";
      case "REP FLOOR": return "Stressed replacement / liquidation value per share.\nUsed for: Downside protection assessment.";
      case "CASH RUNWAY": return "Estimated months of cash remaining at current burn rate.\nUsed for: Dilution risk monitoring.";
      case "IMPLIED EDGE": return "How undervalued the barbell appears vs model intrinsic value.\nUsed for: Conviction level and position sizing decisions.";
      case "AGA INTRINSIC": return "Forensic per-share value using treasury, project tiering, recovery rates, and exploration upside.\nCore driver of the entire valuation model.";
      case "IS-IAI / SHARE": return "In-Situ Adjusted Value after jurisdiction and metallurgical recovery adjustments.\nShows quality and realism of your resource ounces.";
      case "EXP. PREMIUM / SHARE": return "Value assigned to future discovery potential (Kennedy, extensions, etc.).\nRepresents the blue-sky asymmetry you’re betting on.";
      case "PPI": return "Portfolio Price Index - weighted average market price of the entire barbell.\nUsed to calculate Implied Edge.";
      case "EV BLENDED": return "Blended Enterprise Value of the entire barbell.\nUsed to calculate Implied Edge.";
      case "BLENDED PROBABILITY": return "Weighted success probability across all AGA.V catalysts.\nHigher = more confidence in the thesis.";
      case "ROV MULTIPLE": return "Resource Optionality Value multiple applied to the base case.\nReflects premium for future upside potential.";
      default: return label;
    }
  }

  Color _getKellyColor(double kelly) {
    if (kelly < 1.0) return Colors.green;
    if (kelly < 1.5) return Colors.orange;
    return Colors.red;
  }

  Color _getEdgeColor(double edge) {
    if (edge > 80) return Colors.green;
    if (edge > 40) return Colors.orange;
    return Colors.red;
  }

  Widget _buildMacroRiskDashboard(double bvs, Map<String, dynamic> metrics) {
    String regimeText = bvs < 40 
        ? "Low Vulnerability • Expansion Regime - Safe to maintain full barbell exposure" 
        : "Moderate Risk • Monitor Liquidity";

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
          color: bvs < 40 ? Colors.green : bvs < 65 ? Colors.orange : Colors.red,
        ),
        const SizedBox(height: 6),
        Text(regimeText, style: const TextStyle(color: Colors.grey, fontSize: 12)),
      ],
    );
  }

  Color _getMetricColor(String key, double value) {
    if (value == 0) return Colors.white70;
    switch (key) {
      case '10Y':
        if (value < 3.5) return Colors.greenAccent;
        if (value < 4.5) return Colors.orangeAccent;
        return Colors.redAccent;
      case '30Y':
        if (value < 4.0) return Colors.greenAccent;
        if (value < 5.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'DXY':
        if (value < 100) return Colors.greenAccent;
        if (value < 105) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'Spreads':
        if (value < 3.5) return Colors.greenAccent;
        if (value < 5.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'TED':
        if (value < 0.25) return Colors.greenAccent;
        if (value < 0.50) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'VIX':
        if (value < 15) return Colors.greenAccent;
        if (value < 20) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'WTI':
        if (value < 75) return Colors.greenAccent;
        if (value < 90) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'Spot_Ag':
        if (value > 30) return Colors.greenAccent;
        if (value > 25) return Colors.orangeAccent;
        return Colors.redAccent;
      default:
        return Colors.white70;
    }
  }

  Widget _buildFluidMacroGrid(Map<String, dynamic> metrics) {
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
                color: (isSpear && vix > 30) ? Colors.red : Colors.transparent, 
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