import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'package:flutter/foundation.dart';

void main() => runApp(const CommodityExApp());

class CommodityExApp extends StatelessWidget {
  const CommodityExApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CommodityEx Terminal',
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF070708),
        primaryColor: Colors.amber,
        cardColor: const Color(0xFF141416),
        textTheme: ThemeData.dark().textTheme.apply(fontFamily: 'Courier'),
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

// Managed ChangeNotifier state solution
class TerminalState extends ChangeNotifier {
  late WebSocketChannel _channel;
  Map<String, dynamic> _data = {};
  bool _isLoading = true;
  String? _error;

  Map<String, dynamic> get data => _data;
  bool get isLoading => _isLoading;
  String? get error => _error;

  TerminalState() {
    _connect();
  }

  void _connect() {
    try {
      _channel = WebSocketChannel.connect(Uri.parse('ws://127.0.0.1:8000/ws'));
      _channel.stream.listen(
        (message) async {
          try {
            // Offload JSON decoding to compute isolate (background thread)
            final decoded = await compute(_parseJson, message as String);
            _data = decoded;
            _isLoading = false;
            _error = null;
            notifyListeners();
          } catch (e) {
            _error = "Parsing error: $e";
            notifyListeners();
          }
        },
        onError: (err) {
          _error = "WebSocket disconnected. Reconnecting in 3s...";
          _isLoading = false;
          notifyListeners();
          Future.delayed(const Duration(seconds: 3), () => _connect());
        },
        onDone: () {
          _error = "WebSocket connection closed. Reconnecting...";
          _isLoading = false;
          notifyListeners();
          Future.delayed(const Duration(seconds: 3), () => _connect());
        },
      );
    } catch (e) {
      _error = "WebSocket initialization failed. Retrying...";
      _isLoading = false;
      notifyListeners();
      Future.delayed(const Duration(seconds: 3), () => _connect());
    }
  }

  static Map<String, dynamic> _parseJson(String message) {
    return Map<String, dynamic>.from(jsonDecode(message));
  }

  @override
  void dispose() {
    _channel.sink.close();
    super.dispose();
  }
}

class MainTerminalView extends StatefulWidget {
  const MainTerminalView({super.key});

  @override
  State<MainTerminalView> createState() => _MainTerminalViewState();
}

class _MainTerminalViewState extends State<MainTerminalView> with SingleTickerProviderStateMixin {
  late final TerminalState _state;
  bool _censorSensitiveData = false;
  bool _showMetricDictionary = false;
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _state = TerminalState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _state.dispose();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D0D10),
        elevation: 0,
        title: Row(
          children: [
            FadeTransition(
              opacity: Tween<double>(begin: 0.4, end: 1.0).animate(_pulseController),
              child: Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  color: Colors.greenAccent,
                  shape: BoxShape.circle,
                ),
              ),
            ),
            const SizedBox(width: 10),
            const Text(
              'COMMODITYEX // MRI PROTOCOL TERMINAL v5.1', 
              style: TextStyle(fontFamily: 'monospace', fontSize: 13, fontWeight: FontWeight.bold, letterSpacing: 0.5),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(_showMetricDictionary ? Icons.menu_book : Icons.menu_book_outlined),
            onPressed: () => setState(() => _showMetricDictionary = !_showMetricDictionary),
            tooltip: 'Toggle Metric Dictionary',
          ),
          IconButton(
            icon: Icon(_censorSensitiveData ? Icons.visibility_off : Icons.visibility),
            onPressed: () => setState(() => _censorSensitiveData = !_censorSensitiveData),
            tooltip: 'Censor Equity Portfolio Values',
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: _state,
        builder: (context, child) {
          if (_state.isLoading) {
            return const Center(child: CircularProgressIndicator(color: Colors.amber));
          }

          if (_state.error != null && _state.data.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.wifi_off, size: 48, color: Colors.orangeAccent),
                  const SizedBox(height: 16),
                  Text(
                    _state.error!,
                    style: const TextStyle(color: Colors.orangeAccent, fontFamily: 'monospace', fontSize: 12),
                  ),
                ],
              ),
            );
          }

          final data = _state.data;
          final metrics = data['metrics'] ?? {};
          final val = data['v4_valuation'] ?? data['v3_valuation'] ?? {};
          final nodes = data['nodes'] ?? {};
          final mri = (data['bvs'] ?? val['BVS'] ?? val['MRI'] ?? 45.0).toDouble();
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

          if (data['status'] == "DEGRADED_STALE") {
            isDataDegraded = true;
          }

          String headerText;
          Color headerColor;

          if (!hasRealData) {
            headerText = "CONNECTING • INITIALIZING TAPES...";
            headerColor = Colors.orangeAccent;
          } else if (isDataDegraded) {
            headerText = "LIVE (DEGRADED STALE DATA) • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = Colors.amber;
          } else {
            headerText = "LIVE • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = mri < 40 
                ? Colors.greenAccent 
                : mri < 65 
                    ? Colors.orangeAccent 
                    : Colors.redAccent;
          }

          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FadeTransition(
                  opacity: Tween<double>(begin: 0.7, end: 1.0).animate(_pulseController),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: headerColor.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: headerColor.withOpacity(0.3)),
                    ),
                    child: Row(
                      children: [
                        Icon(isDataDegraded ? Icons.warning_amber_rounded : Icons.sensors, color: headerColor, size: 16),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            headerText,
                            style: TextStyle(
                              color: headerColor,
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                _buildMacroRiskDashboard(mri, regime, directive),
                const SizedBox(height: 24),

                if (_showMetricDictionary) ...[
                  _buildMetricDictionary(),
                  const SizedBox(height: 24),
                ],

                _buildModelHealthAndRadar(data['health_radar'] ?? {}),
                const SizedBox(height: 24),

                _buildSizingConstraintsWidget(val, mri, data['forensics'] ?? {}, data['portfolio_stats'] ?? {}),
                const SizedBox(height: 24),

                _buildForensicCovariancePanel(data['forensics'] ?? {}, data['portfolio_stats'] ?? {}),
                const SizedBox(height: 24),

                _buildFluidMacroGrid(metrics),
                const SizedBox(height: 24),

                _buildDetailedBreakdown(val, nodes),
                const SizedBox(height: 24),

                _buildBarbell(nodes, metrics['VIX']?['value']?.toDouble() ?? 16.5),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildSizingConstraintsWidget(Map<String, dynamic> val, double mri, Map<String, dynamic> forensics, Map<String, dynamic> stats) {
    final double currentValue = (val['Total_Equity'] ?? 0.0).toDouble();
    final double targetCapital = (val['E_Target'] ?? 0.0).toDouble();
    final double kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final double impliedEdge = (val['Implied_Upside'] ?? 0.0).toDouble();
    final double repFloor = (val['REP_Floor'] ?? 0.0).toDouble();
    final double runway = (val['Cash_Runway_Months'] ?? 0.0).toDouble();

    final double jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final Map<String, dynamic> vols = stats['vols'] ?? {};
    final Map<String, dynamic> corrMatrix = stats['correlations'] ?? {};

    // Sizing Allocation Simulator calculations in Dart
    const double fKelly = 0.5;
    const double posLiqCap = 0.15;
    const double maxSinglePos = 0.20;

    final double variance = vols['AGA.V'] != null ? (vols['AGA.V'].toDouble() * vols['AGA.V'].toDouble()) : 0.2025;
    final double rawKelly = (impliedEdge / 100.0 / (variance > 0.04 ? variance : 0.04)) * fKelly;

    final double groyCorr = corrMatrix['AGA.V']?['GROY']?.toDouble() ?? 0.50;
    final double avgCPenalty = 1.0 - (groyCorr > 0.30 ? (groyCorr - 0.30) * 0.40 : 0.0);
    
    // Aligned status for flexibility multiplier
    final bool isAligned = (mri < 45.0) && (jsf >= 3.5);
    final double flexibilityMult = isAligned ? 1.25 : 1.0;

    final double targetPct = (rawKelly < maxSinglePos ? rawKelly : maxSinglePos) * avgCPenalty;
    final double rawTargetCap = currentValue * targetPct;

    final double maxPosLimitCad = currentValue * maxSinglePos * flexibilityMult;

    final double advCap = (val['ADV_Cap_CAD'] ?? 0.0).toDouble();
    final double advCapPct = (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();

    // Capped Actionable Target
    final double maxByLiquidityCap = advCap / 0.60;
    final double maxBySinglePosCap = maxPosLimitCad / 0.60;

    final double cappedTargetCap = targetCapital;

    String displayCurrent = _censorSensitiveData ? "••••••" : "\$${currentValue.toStringAsFixed(2)}";
    String displayTarget = _censorSensitiveData ? "••••••" : "\$${targetCapital.toStringAsFixed(2)}";

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "ADVANCED KELLY ALLOCATION & SIZING CONSTRAINTS", 
          style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5),
        ),
        const SizedBox(height: 12),

        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _buildMetricBox("CURRENT VALUE", displayCurrent, Colors.white70),
            _buildMetricBox("TARGET CAPITAL", displayTarget, Colors.greenAccent),
            _buildMetricBox("KELLY MULTIPLE", "${kelly.toStringAsFixed(2)}x", _getKellyColor(kelly)),
            _buildMetricBox("REP FLOOR", "\$${repFloor.toStringAsFixed(3)}", Colors.white70),
            _buildMetricBox("CASH RUNWAY", "${runway.toStringAsFixed(1)} mo", _getRunwayColor(runway)),
            _buildMetricBox("IMPLIED EDGE", "${impliedEdge.toStringAsFixed(1)}%", _getEdgeColor(impliedEdge)),
          ],
        ),

        const SizedBox(height: 16),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFF111113),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: const Color(0xFF222226)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "PORTFOLIO SIZING SIEVE & CONSTRAINT BOTTLENECKS",
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.3),
              ),
              const SizedBox(height: 12),
              
              _buildConstraintBar("Blended Conviction Target", rawTargetCap, currentValue, const Color(0xFF00BCD4)),
              _buildConstraintBar("Max Single-Position Limit", maxPosLimitCad, currentValue, const Color(0xFFEF5350)),
              _buildConstraintBar("Dynamic ADV Liquidity Cap (Spear)", advCap, currentValue, const Color(0xFFFFB300)),
              _buildConstraintBar("Actionable Target Deployment", cappedTargetCap, currentValue, const Color(0xFF66BB6A)),
              
              if (isAligned) ...[
                const SizedBox(height: 4),
                Row(
                  children: const [
                    Icon(Icons.flash_on, color: Colors.greenAccent, size: 12),
                    SizedBox(width: 6),
                    Text(
                      "DYNAMIC SIZER FLEXIBILITY ACTIVE (+25% limit expansion due to macro/micro alignment)",
                      style: TextStyle(color: Colors.greenAccent, fontSize: 8.5, fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
              ],
              
              _buildConstraintAlert(rawTargetCap, advCap, maxPosLimitCad, cappedTargetCap, maxByLiquidityCap, advCapPct),
            ],
          ),
        ),

        const SizedBox(height: 16),
        _buildActionableInsights(val, mri),
      ],
    );
  }

  Widget _buildConstraintBar(String title, double value, double maxVal, Color color) {
    double pct = maxVal > 0 ? (value / maxVal) : 0.0;
    if (pct > 1.0) pct = 1.0;
    if (pct < 0.0) pct = 0.0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title, style: const TextStyle(fontSize: 9, color: Colors.grey, fontWeight: FontWeight.bold)),
              Text(
                _censorSensitiveData 
                    ? "•••••• (${(pct * 100).toStringAsFixed(1)}%)" 
                    : "\$${value.toStringAsFixed(0)} CAD (${(pct * 100).toStringAsFixed(1)}%)", 
                style: TextStyle(fontSize: 9.5, color: color, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: pct,
              minHeight: 5,
              backgroundColor: const Color(0xFF1B1B1E),
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildConstraintAlert(double rawTargetCap, double advCap, double maxPosLimitCad, double cappedTargetCap, double maxByLiquidityCap, double advCapPct) {
    if (advCap < rawTargetCap && cappedTargetCap == maxByLiquidityCap) {
      return Container(
        padding: const EdgeInsets.all(10),
        margin: const EdgeInsets.only(top: 8),
        decoration: BoxDecoration(
          color: Colors.amber.withOpacity(0.06),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: Colors.amber.withOpacity(0.2)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.warning_amber_rounded, color: Colors.amber, size: 14),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                "CONSTRAINED BY LIQUIDITY POLICY: Conviction target is \$${rawTargetCap.toStringAsFixed(2)} CAD. Exit liquidity limits (restricted to ${advCapPct.toStringAsFixed(1)}% ADV due to MRI stress) limit maximum Spear deployment to \$${advCap.toStringAsFixed(2)} CAD.",
                style: const TextStyle(color: Colors.amber, fontSize: 9.5, fontWeight: FontWeight.bold, height: 1.3),
              ),
            ),
          ],
        ),
      );
    } else if (maxPosLimitCad < rawTargetCap) {
      return Container(
        padding: const EdgeInsets.all(10),
        margin: const EdgeInsets.only(top: 8),
        decoration: BoxDecoration(
          color: Colors.blueAccent.withOpacity(0.06),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: Colors.blueAccent.withOpacity(0.2)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.security, color: Colors.blueAccent, size: 14),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                "CONSTRAINED BY SINGLE-POSITION POLICY CAPS: Barbell sizing adjusted down by \$${(rawTargetCap - cappedTargetCap).toStringAsFixed(2)} CAD to enforce standard position risk ceiling.",
                style: const TextStyle(color: Colors.blueAccent, fontSize: 9.5, fontWeight: FontWeight.bold, height: 1.3),
              ),
            ),
          ],
        ),
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildActionableInsights(Map<String, dynamic> val, double mri) {
    final kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final edge = (val['Implied_Upside'] ?? 0.0).toDouble();

    String recommendation = "HOLD POSITION - Monitor tape and structural asset tracking";
    Color recColor = Colors.orange;

    if (mri < 40 && edge > 80) {
      recommendation = "HIGH CONVICTION ZONE - System signals expansion. Scale barbell allocation dynamically.";
      recColor = Colors.greenAccent;
    } else if (kelly > 1.5) {
      recommendation = "CAUTION - Allocation limits breached via Kelly sizer. Trim positions on technical strength.";
      recColor = Colors.redAccent;
    } else if (mri > 65) {
      recommendation = "DEFENSIVE MODE - Sovereign macro stress elevated. Retain capital buffers.";
      recColor = Colors.redAccent;
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: recColor.withOpacity(0.08),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: recColor.withOpacity(0.4)),
      ),
      child: Text(
        recommendation,
        style: TextStyle(color: recColor, fontSize: 11.5, fontWeight: FontWeight.bold, height: 1.4),
      ),
    );
  }

  Widget _buildDetailedBreakdown(Map<String, dynamic> val, Map<String, dynamic> nodes) {
    final double agaPrice = (nodes['AGA.V']?['price'] ?? 0.71).toDouble();
    final agaIntrinsic = (val['AGA_Intrinsic'] ?? 0.0).toDouble();
    final isIai = (val['IS_IAI_Per_Share'] ?? 0.0).toDouble();
    final expPremium = (val['Exp_Premium_Per_Share'] ?? 0.0).toDouble();
    final ppi = (val['PPI'] ?? 0.0).toDouble();
    final evBlended = (val['EV_Blended'] ?? 0.0).toDouble();
    final probability = (val['Probability'] ?? 0.65).toDouble();
    final rov = (val['ROV'] ?? 1.18).toDouble();
    final advCap = (val['ADV_Cap_CAD'] ?? 0.0).toDouble();
    final advCapPct = (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();
    final peerDiscCost = (val['Discovery_Efficiency_Comps'] ?? 0.48).toDouble();

    Color advCapColor = Colors.greenAccent;
    if (advCapPct < 5.0) {
      advCapColor = Colors.redAccent;
    } else if (advCapPct < 10.0) {
      advCapColor = Colors.orangeAccent;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("DETAILED VALUATION MODEL BREAKDOWN", 
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 12),

        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _buildMetricBox("AGA INTRINSIC", "\$${agaIntrinsic.toStringAsFixed(3)}", _getValuationColor(agaIntrinsic, agaPrice)),
            _buildMetricBox("IS-IAI / SHARE", "\$${isIai.toStringAsFixed(3)}", _getValuationColor(isIai, agaPrice)),
            _buildMetricBox("EXP. PREMIUM / SHARE", "\$${expPremium.toStringAsFixed(3)}", expPremium > 0 ? Colors.greenAccent : Colors.white70),
            _buildMetricBox("PPI", "\$${ppi.toStringAsFixed(3)}", _getValuationColor(ppi, agaPrice)),
            _buildMetricBox("EV BLENDED", "\$${evBlended.toStringAsFixed(3)}", _getValuationColor(evBlended, agaPrice)),
            _buildMetricBox("BLENDED PROBABILITY", "${(probability*100).toStringAsFixed(1)}%", probability >= 0.7 ? Colors.greenAccent : (probability >= 0.5 ? Colors.orangeAccent : Colors.redAccent)),
            _buildMetricBox("ROV MULTIPLE", rov.toStringAsFixed(2), rov >= 1.3 ? Colors.greenAccent : (rov >= 1.15 ? Colors.orangeAccent : Colors.white70)),
            _buildMetricBox("ADV SIZING CAP", "\$${advCap.toStringAsFixed(0)} (${advCapPct.toStringAsFixed(1)}%)", advCapColor),
            _buildMetricBox("PEER DISC COST", "\$${peerDiscCost.toStringAsFixed(2)}/oz", Colors.white70),
          ],
        ),
      ],
    );
  }

  Widget _buildForensicCovariancePanel(Map<String, dynamic> forensics, Map<String, dynamic> stats) {
    final jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final penalty = (forensics['penalty_factor'] ?? 1.0).toDouble();
    final sloanCfo = (forensics['sloan_cfo'] ?? 0.0).toDouble();
    final sloanBs = (forensics['sloan_bs'] ?? 0.0).toDouble();
    final es95 = (stats['expected_shortfall_95'] ?? 0.0).toDouble();
    final avgCorr = (stats['avg_correlation'] ?? 0.0).toDouble();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("FORENSIC RISK SHIELD & COVARIANCE (v5.1)", 
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _buildMetricBox("JSF SCORE", "${jsf.toStringAsFixed(1)} / 4.0", jsf == 4.0 ? Colors.greenAccent : Colors.orangeAccent),
            _buildMetricBox("PENALTY DISCOUNT", "${penalty.toStringAsFixed(3)}x", penalty == 1.0 ? Colors.greenAccent : Colors.redAccent),
            _buildMetricBox("EXPECTED SHORTFALL", "${es95.toStringAsFixed(2)}%", Colors.orangeAccent),
            _buildMetricBox("SLOAN CFO ACCRUALS", sloanCfo.toStringAsFixed(4), sloanCfo < 0.05 ? Colors.greenAccent : Colors.redAccent),
            _buildMetricBox("SLOAN BS ACCRUALS", sloanBs.toStringAsFixed(4), sloanBs < 0.05 ? Colors.greenAccent : Colors.redAccent),
            _buildMetricBox("PORTFOLIO CORR", avgCorr.toStringAsFixed(2), Colors.white70),
          ],
        ),
      ],
    );
  }

  Widget _buildMetricBox(String label, String value, Color color) {
    return Tooltip(
      message: _getRichTooltip(label),
      child: Container(
        width: 175,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF111113),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withOpacity(0.3), width: 1.2),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label, 
              style: const TextStyle(color: Colors.grey, fontSize: 9.5, fontWeight: FontWeight.bold, letterSpacing: 0.3),
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 6),
            Text(
              value, 
              style: TextStyle(color: color, fontSize: 16.5, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }

  String _getRichTooltip(String label) {
    if (label.contains("ADV")) {
      return "Maximum safe position size in CAD based on dynamic exit liquidity limits (scales 2% - 15% ADV depending on macro Stress).";
    }
    switch (label) {
      case "SOFR SPREAD": return "SOFR - DGS3MO credit spread, measuring money-market credit and repo stress to replace the frozen TED rate.";
      case "CURRENT VALUE": return "Real-time portfolio market equity value scaled in CAD.";
      case "TARGET CAPITAL": return "Model-recommended sizing using Kelly optimization scaled against real-time macro stress floors.";
      case "KELLY MULTIPLE": return "Ratio of actual deployment vs risk-balanced limit targets.";
      case "REP FLOOR": return "Liquidation and replacement cost floor evaluation for structural safety bounds.";
      case "CASH RUNWAY": return "Corporate cash lifespan. Under 18 months prompts dilution warning triggers.";
      case "IMPLIED EDGE": return "Calculated mispricing yield between portfolio index price and blended model intrinsic value.";
      case "CFTC MM POSITION": return "Commitment of Traders net contract positioning of Managed Money. Low values mean speculative capitulation (bullish contrarian).";
      case "JSF SCORE": return "Junior Forensic Score (0-4). Measures cash runway, Sloan CFO accruals or cash burn acceleration, share dilution expansion, and G&A overhead.";
      case "PENALTY DISCOUNT": return "Valuation discount factor based on JSF score. Discounts resource valuation by up to 30% for high dilution or runway stress.";
      case "EXPECTED SHORTFALL": return "95% Expected Shortfall (ES). Average daily return loss projected in the worst 5% of historical trading outcomes.";
      case "SLOAN CFO ACCRUALS": return "Operating accruals or Cash Burn Acceleration. A warning limit for earnings quality or cash drain.";
      case "SLOAN BS ACCRUALS": return "Balance Sheet Sloan Ratio. Measures change in non-cash working capital to verify accounting flow integrity.";
      case "PORTFOLIO CORR": return "Weighted average correlation coefficient between barbell components. Lower values expand portfolio diversification convexities.";
      case "PEER DISC COST": return "Weighted average cost of discovery per ounce of gold-equivalent across the peer universe, baselining exploration efficiency.";
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

  Widget _buildMacroRiskDashboard(double mri, String regime, String directive) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0xFF222226)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                "MACRO REGIME INDEX (MRI)", 
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.5),
              ),
              Text(
                "MRI: ${mri.toStringAsFixed(1)}", 
                style: TextStyle(
                  fontSize: 12, 
                  fontWeight: FontWeight.bold,
                  color: mri < 40 
                      ? Colors.greenAccent 
                      : mri < 65 
                          ? Colors.orangeAccent 
                          : Colors.redAccent
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: mri / 100,
              minHeight: 6,
              backgroundColor: const Color(0xFF222226),
              color: mri < 40 
                  ? Colors.greenAccent 
                  : mri < 65 
                      ? Colors.orangeAccent 
                      : Colors.redAccent,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            "$regime // $directive", 
            style: const TextStyle(color: Colors.white70, fontSize: 10.5, fontWeight: FontWeight.bold, height: 1.3),
          ),
        ],
      ),
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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("FLUID MACRO & COMMODITY TAPE", 
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _buildMetricBox("10Y YIELD", "${(metrics['10Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('10Y', (metrics['10Y']?['value'] ?? 0).toDouble())),
            _buildMetricBox("30Y YIELD", "${(metrics['30Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('30Y', (metrics['30Y']?['value'] ?? 0).toDouble())),
            _buildMetricBox("DXY", "${(metrics['DXY']?['value'] ?? 0).toStringAsFixed(1)}", _getMetricColor('DXY', (metrics['DXY']?['value'] ?? 0).toDouble())),
            _buildMetricBox("HY SPREADS", "${(metrics['Spreads']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('Spreads', (metrics['Spreads']?['value'] ?? 0).toDouble())),
            _buildMetricBox("SOFR SPREAD", "${(metrics['TED']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('TED', (metrics['TED']?['value'] ?? 0).toDouble())),
            _buildMetricBox("VIX INDEX", "${(metrics['VIX']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('VIX', (metrics['VIX']?['value'] ?? 0).toDouble())),
            _buildMetricBox("WTI CRUDE", "\$${(metrics['WTI']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('WTI', (metrics['WTI']?['value'] ?? 0).toDouble())),
            _buildMetricBox("SILVER", "\$${(metrics['Spot_Ag']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('Spot_Ag', (metrics['Spot_Ag']?['value'] ?? 0).toDouble())),
            _buildMetricBox("CFTC MM POSITION", formatContracts(cftcVal), _getMetricColor('CFTC', cftcVal)),
          ],
        ),
      ],
    );
  }

  Widget _buildBarbell(Map<String, dynamic> nodes, double vix) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("BARBELL COMPONENT DIRECTORY", 
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 12),
        Wrap(
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
                  color: const Color(0xFF111113),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: (isSpear && vix > 23.0) ? Colors.redAccent : const Color(0xFF222226), 
                    width: 1.5
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(e.key, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.white)),
                    const SizedBox(height: 6),
                    Text("\$${e.value['price']}", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
                    const SizedBox(height: 4),
                    Text(e.value['role'], style: TextStyle(color: isSpear ? Colors.amberAccent : Colors.grey, fontSize: 10, fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Color _getValuationColor(double valuation, double price) {
    if (price <= 0.0 || valuation <= 0.0) return Colors.white70;
    final ratio = valuation / price;
    if (ratio >= 1.5) return Colors.greenAccent; // Massive undervaluation (upside >= 50%)
    if (ratio <= 0.85) return Colors.redAccent;  // Overpriced (downside >= 15%)
    return Colors.orangeAccent;                  // Fair value / neutral
  }

  Widget _buildModelHealthAndRadar(Map<String, dynamic> radarData) {
    if (radarData.isEmpty) {
      return const SizedBox.shrink();
    }
    
    final score = (radarData['health_rating'] ?? 10.0).toDouble();
    final ratingDesc = radarData['rating_desc']?.toString() ?? "PENDING MODEL EVALUATION";
    final ratingColorName = radarData['rating_color']?.toString() ?? "white";
    final healthSummary = radarData['health_summary']?.toString() ?? "Calculations in progress...";
    final double tacticalCeiling = (radarData['tactical_ceiling'] ?? 0.0).toDouble();
    final priorities = List<Map<String, dynamic>>.from(
      (radarData['priorities'] as List? ?? []).map((e) => Map<String, dynamic>.from(e))
    );
    
    Color ratingColor = Colors.white70;
    if (ratingColorName == "green") {
      ratingColor = Colors.greenAccent;
    } else if (ratingColorName == "orange") {
      ratingColor = Colors.orangeAccent;
    } else if (ratingColorName == "red") {
      ratingColor = Colors.redAccent;
    }
    
    IconData _getIconData(String name) {
      switch (name) {
        case 'shopping_cart_outlined': return Icons.shopping_cart_outlined;
        case 'info_outline': return Icons.info_outline;
        case 'warning_amber_rounded': return Icons.warning_amber_rounded;
        case 'verified_user_outlined': return Icons.verified_user_outlined;
        case 'lock_clock': return Icons.lock_clock;
        case 'swap_horizontal_circle_outlined': return Icons.swap_horizontal_circle_outlined;
        case 'balance_outlined': return Icons.balance_outlined;
        case 'check_circle_outline': return Icons.check_circle_outline;
        default: return Icons.info_outline;
      }
    }
    
    Color _getColor(String name) {
      switch (name) {
        case 'green': return Colors.greenAccent;
        case 'orange': return Colors.orangeAccent;
        case 'red': return Colors.redAccent;
        default: return Colors.white70;
      }
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: ratingColor.withOpacity(0.2), width: 1.5),
        boxShadow: [
          BoxShadow(color: ratingColor.withOpacity(0.03), blurRadius: 10, spreadRadius: 2)
        ]
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                "MODEL HEALTH & TACTICAL DEPLOYMENT RADAR",
                style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: ratingColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: ratingColor.withOpacity(0.3)),
                ),
                child: Text(
                  "HEALTH RATING: ${score.toStringAsFixed(1)} / 10",
                  style: TextStyle(color: ratingColor, fontSize: 11, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                ),
              )
            ],
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                ratingDesc,
                style: TextStyle(color: ratingColor, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.8),
              ),
              if (tacticalCeiling > 0)
                Text(
                  "TACTICAL SAFETY CEILING: \$${tacticalCeiling.toStringAsFixed(2)} CAD (${(score*10).toStringAsFixed(0)}% of Kelly)",
                  style: const TextStyle(color: Colors.white70, fontSize: 10.5, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            healthSummary,
            style: const TextStyle(color: Colors.grey, fontSize: 11, height: 1.3),
          ),
          const Divider(color: Color(0xFF222226), height: 24, thickness: 1.2),
          const Text(
            "PRIORITY TACTICAL CHECKLIST",
            style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white70, letterSpacing: 0.5),
          ),
          const SizedBox(height: 12),
          Column(
            children: priorities.map((p) => _buildPriorityItem(
              _getIconData(p['icon']?.toString() ?? ''),
              _getColor(p['color']?.toString() ?? ''),
              p['title']?.toString() ?? '',
              p['desc']?.toString() ?? ''
            )).toList(),
          )
        ],
      ),
    );
  }

  Widget _buildPriorityItem(IconData icon, Color color, String title, String desc) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.3),
                ),
                const SizedBox(height: 3),
                Text(
                  desc,
                  style: const TextStyle(color: Colors.grey, fontSize: 10.5, height: 1.3),
                ),
              ],
            ),
          )
        ],
      ),
    );
  }

  Widget _buildMetricDictionary() {
    final Map<String, Map<String, String>> dict = {
      "MRI (Macro Regime Index)": {
        "formula": "Normalized blend of Real Yields, Yield Curve Slope, VIX, WTI/Gold spreads, and COT Managed Money.",
        "usage": "Sovereign liquidity stress indicator (0-100). Under 40 signals 'Risk-On' expansion. Over 65 triggers 'Defensive Mode' to limit sizing caps."
      },
      "REP Floor (Replacement Floor)": {
        "formula": "conservative_scalar * (Cash + (Resources * stressed_resource_per_oz) + infra_premium) / Shares Outstanding",
        "usage": "Absolute asset liquidation cost boundary. Buying below this price represents buying the assets below their concrete cost of creation."
      },
      "Cash Runway": {
        "formula": "Cash Reserves / Average Monthly Cash Burn Rate",
        "usage": "Months of operational life remaining. A runway under 18 months indicates that the explorer will be forced to dilute equity soon."
      },
      "Implied Edge": {
        "formula": "(Blended Intrinsic Value / Market Price) - 1.0",
        "usage": "The margin of safety and mispricing arbitrage size. Higher implied edge indicates greater undervalued opportunity."
      },
      "Kelly Multiple": {
        "formula": "Actual Allocated Capital / Model Conviction-based Target Capital Allocation",
        "usage": "Capital limits checking. A value above 1.0 means you have overallocated capital beyond the model's recommendation."
      },
      "JSF Score (Junior Shield Forensics)": {
        "formula": "Score from 0.0 to 4.0. Checks: CBA Cash Burn, QoQ Dilution, G&A Drag, and Runway health.",
        "usage": "Measures the operational quality of explorers and producers. Low scores lead to heavy intrinsic value discounts."
      },
      "Sloan Accruals (CFO & BS)": {
        "formula": "CFO Sloan: (Net Income - CFO) / Total Assets. BS Sloan: (Change in Non-Cash Working Capital) / Total Assets.",
        "usage": "Earnings quality check. Values above 0.05 warn that earnings are artificial accruals not backed by cash flow."
      },
      "ADV Sizing Cap": {
        "formula": "10-day Average Daily Volume (ADV) scaled dynamically from 15% down to 2% based on MRI score.",
        "usage": "Maximum safe block trade execution in CAD. Prevents trades from causing excessive market impact on illiquid juniors."
      },
    };

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0F0F11),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.amberAccent.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.help, color: Colors.amberAccent, size: 18),
              SizedBox(width: 8),
              Text(
                "SYSTEM METRIC DICTIONARY & TRADING COMPASS",
                style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.bold, color: Colors.amberAccent, letterSpacing: 0.5),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...dict.entries.map((e) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  e.key,
                  style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                RichText(
                  text: TextSpan(
                    style: const TextStyle(fontSize: 10.5, color: Colors.grey, height: 1.3),
                    children: [
                      const TextSpan(text: "Formula/Math: ", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
                      TextSpan(text: "${e.value['formula']}\n"),
                      const TextSpan(text: "Tactical Utility: ", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
                      TextSpan(text: "${e.value['usage']}", style: const TextStyle(color: Colors.grey)),
                    ],
                  ),
                ),
              ],
            ),
          )).toList(),
        ],
      ),
    );
  }
}