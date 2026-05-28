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
      ),
      body: StreamBuilder(
        stream: _channel.stream,
        builder: (context, snapshot) {
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator(color: Colors.amber));
          }
          final data = jsonDecode(snapshot.data as String);

          final metrics = data['metrics'] ?? {};
          final valuation = data['v3_valuation'] ?? {};
          final double vix = (metrics['VIX']?['value'] as num?)?.toDouble() ?? 0.0;
          final double bvs = (valuation['BVS'] as num?)?.toDouble() ?? 45.0;
          final double kelly = (valuation['Kelly_Multiple'] as num?)?.toDouble() ?? 1.0;
          final double repFloor = (valuation['REP_Floor'] as num?)?.toDouble() ?? 0.0;
          final double cashRunway = (valuation['Cash_Runway_Months'] as num?)?.toDouble() ?? 0.0;

          return SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data['macro_regime'].toUpperCase(),
                  style: TextStyle(
                    color: _getRegimeColor(data['macro_regime']),
                    fontSize: 32,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(data['directive'], style: const TextStyle(color: Colors.grey)),
                const SizedBox(height: 24),

                _buildMacroRiskDashboard(data, bvs),
                const SizedBox(height: 32),

                _buildFluidGrid(metrics),
                const SizedBox(height: 32),

                if (valuation.isNotEmpty) ...[
                  const Text("V3 EXECUTION LAYER: THE ARBITRAGE GAP",
                      style: TextStyle(color: Colors.grey, letterSpacing: 2)),
                  const SizedBox(height: 4),
                  const Text("60% Spear (AGA.V) + 40% Ballast • V3.0 Weighted Model",
                      style: TextStyle(color: Colors.grey, fontSize: 11)),
                  const SizedBox(height: 12),
                  _buildExecutionPanel(valuation, repFloor, cashRunway, kelly),
                  const SizedBox(height: 32),
                ],

                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text("PHYSICAL BARBELL PROFILE",
                        style: TextStyle(color: Colors.grey, letterSpacing: 2)),
                    Text("KILL-SWITCH: ${data['kill_switches']['AGA_V']}",
                        style: const TextStyle(color: Colors.green)),
                  ],
                ),
                const SizedBox(height: 12),
                _buildBarbell(data['nodes'] ?? {}, vix),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildMacroRiskDashboard(dynamic data, double bvs) {
    Color bvsColor = bvs < 40 ? Colors.greenAccent : 
                     bvs < 65 ? Colors.amber : 
                     bvs < 80 ? Colors.orangeAccent : Colors.redAccent;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        border: Border.all(color: bvsColor.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text("MACRO RISK DASHBOARD", 
                  style: TextStyle(color: Colors.grey, fontSize: 13, letterSpacing: 1.5, fontWeight: FontWeight.w500)),
              Text("BVS: ${bvs.toStringAsFixed(1)}", 
                  style: TextStyle(color: bvsColor, fontSize: 22, fontWeight: FontWeight.bold, fontFamily: 'Courier')),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: bvs / 100,
            backgroundColor: Colors.grey[800],
            valueColor: AlwaysStoppedAnimation<Color>(bvsColor),
          ),
          const SizedBox(height: 10),
          Text(
            _getBvsDescription(bvs),
            style: TextStyle(color: bvsColor, fontSize: 13.5, height: 1.4),
          ),
        ],
      ),
    );
  }

  String _getBvsDescription(double bvs) {
    if (bvs < 40) return "Low Vulnerability • Expansion Regime • Safe to maintain full barbell exposure";
    if (bvs < 65) return "Moderate Vulnerability • The Slow Bleed • Monitor closely, no aggressive adding";
    if (bvs < 80) return "Elevated Vulnerability • Liquidity Squeeze • Consider trimming Spear allocation";
    return "High Vulnerability • Capitulation Risk • Major defensive action recommended (raise cash)";
  }

  Color _getRegimeColor(String regime) {
    if (regime == "Structural Release") return Colors.greenAccent;
    if (regime == "Liquidity Squeeze") return Colors.deepOrange;
    if (regime == "Systemic Capitulation") return Colors.redAccent;
    return Colors.amber;
  }

  Color _getKellyColor(double kelly) {
    if (kelly <= 1.2) return Colors.greenAccent;
    if (kelly <= 1.8) return Colors.amber;
    return Colors.redAccent;
  }

  Widget _buildFluidGrid(dynamic m) {
    return Wrap(spacing: 16, runSpacing: 16, children: [
      _buildMetricCard("10Y YIELD", m['10Y'], "%", "10-Year US Treasury Yield"),
      _buildMetricCard("30Y YIELD", m['30Y'], "%", "30-Year US Treasury Yield"),
      _buildMetricCard("HY SPREADS", m['Spreads'], "%", "High-Yield Corporate Spreads"),
      _buildMetricCard("TED SPREAD", m['TED'], "%", "TED Spread"),
      _buildMetricCard("VIX INDEX", m['VIX'], "", "VIX Index (Fear Gauge)"),
      _buildMetricCard("WTI CRUDE", m['WTI'], "\$", "WTI Crude Oil Price"),
      _buildMetricCard("SILVER", m['Spot_Ag'], "\$", "Current Silver Price per Ounce"),
    ]);
  }

  Widget _buildMetricCard(String title, dynamic metricData, String unit, String tooltipText) {
    double current = (metricData is Map)
        ? (metricData['value'] as num).toDouble()
        : (metricData as num).toDouble();

    Color col = Colors.white70;
    if (title.contains("YIELD")) col = (current > 4.8) ? Colors.amber : Colors.white70;
    if (title == "HY SPREADS" || title == "TED SPREAD") col = Colors.greenAccent;

    String display = unit == "\$" ? "$unit${current.toStringAsFixed(2)}" : "$current$unit";

    return Tooltip(
      message: tooltipText,
      child: Container(
        width: 135,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
            color: const Color(0xFF161616),
            border: Border.all(color: col.withValues(alpha: 0.2))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(
            children: [
              Text(title, style: const TextStyle(color: Colors.grey, fontSize: 11)),
              const SizedBox(width: 4),
              const Icon(Icons.help_outline, size: 14, color: Colors.grey),
            ],
          ),
          Text(display, style: TextStyle(color: col, fontSize: 18, fontWeight: FontWeight.bold)),
        ]),
      ),
    );
  }

  Widget _buildExecutionPanel(Map<String, dynamic> val, double repFloor, double cashRunway, double kelly) {
    double upside = (val['Implied_Upside'] as num).toDouble();
    Color edgeColor = upside > 30.0 ? Colors.greenAccent : (upside > 15 ? Colors.amber : Colors.redAccent);
    Color kellyColor = _getKellyColor(kelly);

    String portfolioValue = _censorSensitiveData ? "••••••" : "\$${val['Total_Equity']}";
    String targetCapital  = _censorSensitiveData ? "••••••" : "\$${val['E_Target']}";

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        border: Border.all(color: edgeColor.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                "PORTFOLIO BREAKDOWN & ACTIONABLE SIGNALS",
                style: TextStyle(color: Colors.grey, fontSize: 13.5, letterSpacing: 1.5, fontWeight: FontWeight.w500),
              ),
              IconButton(
                icon: Icon(_censorSensitiveData ? Icons.visibility_off : Icons.visibility, color: Colors.grey, size: 20),
                onPressed: () => setState(() => _censorSensitiveData = !_censorSensitiveData),
              ),
            ],
          ),
          const SizedBox(height: 20),

          Row(
            children: [
              Expanded(child: Tooltip(message: "Your actual current total portfolio value in CAD", child: _buildMetricBox("CURRENT PORTFOLIO VALUE", portfolioValue, Colors.white))),
              const SizedBox(width: 16),
              Expanded(child: Tooltip(message: "The model's estimate of fair value for your entire barbell", child: _buildMetricBox("BLENDED INTRINSIC (EV)", "\$${val['EV_Blended']}", Colors.white))),
              const SizedBox(width: 16),
              Expanded(child: Tooltip(message: "Current weighted market price of your barbell", child: _buildMetricBox("MARKET PRICE", "\$${val['PPI']}", Colors.grey))),
            ],
          ),
          const SizedBox(height: 12),

          Row(
            children: [
              Expanded(child: Tooltip(message: "Recommended total exposure right now", child: _buildMetricBox("TARGET CAPITAL", targetCapital, Colors.greenAccent))),
              const SizedBox(width: 16),
              Expanded(child: Tooltip(message: "Fair value per share for AGA.V using full V3.0 model", child: _buildMetricBox("AGA INTRINSIC (V3.0)", "\$${val['AGA_Intrinsic']}", Colors.white70))),
              const SizedBox(width: 16),
              Expanded(child: Tooltip(message: "How undervalued the portfolio appears", child: _buildMetricBox("IMPLIED EDGE", "$upside%", edgeColor))),
            ],
          ),
          const SizedBox(height: 12),

          Row(
            children: [
              Expanded(child: Tooltip(
                message: "Kelly Multiple = Current Portfolio Value ÷ Target Capital",
                child: _buildMetricBox("KELLY MULTIPLE", "${kelly.toStringAsFixed(2)}x", kellyColor),
              )),
              const SizedBox(width: 16),
              Expanded(child: Tooltip(
                message: "Weighted probability that AGA.V's key catalysts will succeed",
                child: _buildMetricBox("AGA CATALYST PROBABILITY", "${(val['Probability']*100).toStringAsFixed(1)}%", Colors.amber),
              )),
            ],
          ),

          const SizedBox(height: 24),
          const Divider(color: Colors.grey, thickness: 1),
          const SizedBox(height: 16),

          Wrap(
            spacing: 24,
            runSpacing: 12,
            children: [
              Text("REP Floor: \$${repFloor.toStringAsFixed(2)}", style: const TextStyle(fontSize: 13, color: Colors.grey)),
              Text("Cash Runway: ${cashRunway.toStringAsFixed(0)} months", style: const TextStyle(fontSize: 13, color: Colors.grey)),
              Text("IS-IAI: \$${val['IS_IAI_Per_Share']?.toStringAsFixed(3) ?? 'N/A'}", style: const TextStyle(fontSize: 13, color: Colors.grey)),
              Text("ROV: ${val['ROV'] ?? 'N/A'}x", style: const TextStyle(fontSize: 13, color: Colors.grey)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMetricBox(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        border: Border.all(color: color.withValues(alpha: 0.4), width: 1.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Text(label, style: const TextStyle(color: Colors.grey, fontSize: 10.5, letterSpacing: 0.4)),
              const SizedBox(width: 4),
              const Icon(Icons.help_outline, size: 13, color: Colors.grey),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 21,
              fontWeight: FontWeight.bold,
              fontFamily: 'Courier',
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBarbell(Map<String, dynamic> nodes, double vix) {
    return Wrap(spacing: 16, runSpacing: 16, children: nodes.entries.map((e) {
      bool isSpear = e.value['role'] == 'The Spear';
      return Tooltip(
        message: isSpear 
            ? "The Spear (60% allocation)\nHigh-conviction junior explorer"
            : "Ballast (40% allocation)\nMore stable exposure",
        child: Container(
          width: 180,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
              color: const Color(0xFF1A1A1A),
              border: Border.all(
                  color: (isSpear && vix > 30) ? Colors.red : Colors.transparent, width: 2)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(e.key, style: const TextStyle(fontWeight: FontWeight.bold)),
            Text("\$${e.value['price']}", style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            Text(e.value['role'], style: TextStyle(color: isSpear ? Colors.amber : Colors.grey, fontSize: 12)),
          ]),
        ),
      );
    }).toList());
  }
}