/*
 * CommodityEx Terminal Cockpit v5.1
 * High-Density Monospace Quant Cockpit & Interactive Educator
 */
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
        scaffoldBackgroundColor: const Color(0xFF050507),
        primaryColor: const Color(0xFF00E676),
        cardColor: const Color(0xFF101012),
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

// Lightweight state manager isolating visual glow highlights and metadata mapping
class HighlightState extends ChangeNotifier {
  String? _highlightedMetricId;
  Map<String, dynamic> _metadata = {};

  String? get highlightedMetricId => _highlightedMetricId;
  Map<String, dynamic> get metadata => _metadata;

  void updateMetadata(Map<String, dynamic> newMeta) {
    _metadata = newMeta;
  }

  void toggleHighlight(String metricId) {
    if (_highlightedMetricId == metricId) {
      _highlightedMetricId = null;
    } else {
      _highlightedMetricId = metricId;
    }
    notifyListeners();
  }

  void clear() {
    if (_highlightedMetricId != null) {
      _highlightedMetricId = null;
      notifyListeners();
    }
  }

  bool isHighlighted(String id) {
    if (_highlightedMetricId == null) return false;
    if (_highlightedMetricId!.toLowerCase() == id.toLowerCase()) return true;

    // Check relationship map
    final metricMeta = _metadata[_highlightedMetricId];
    if (metricMeta != null && metricMeta['related_metrics'] != null) {
      final List<dynamic> related = metricMeta['related_metrics'];
      return related.any((e) => e.toString().toLowerCase() == id.toLowerCase());
    }
    return false;
  }
}

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
          _error = "WebSocket closed. Reconnecting...";
          _isLoading = false;
          notifyListeners();
          Future.delayed(const Duration(seconds: 3), () => _connect());
        },
      );
    } catch (e) {
      _error = "WebSocket failed. Retrying...";
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
  late final HighlightState _highlightState;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  bool _censorSensitiveData = false;
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _state = TerminalState();
    _highlightState = HighlightState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _state.dispose();
    _highlightState.dispose();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: const Color(0xFF050507),
      appBar: AppBar(
        backgroundColor: const Color(0xFF09090B),
        elevation: 0,
        toolbarHeight: 38,
        leadingWidth: 0,
        leading: const SizedBox.shrink(),
        title: Row(
          children: [
            ListenableBuilder(
              listenable: _state,
              builder: (context, _) {
                final isDataDegraded = _state.data['status'] == "DEGRADED_STALE";
                return ConnectionIndicator(
                  error: _state.error,
                  isLoading: _state.isLoading,
                  isDegraded: isDataDegraded,
                  pulseAnimation: Tween<double>(begin: 0.5, end: 1.0).animate(_pulseController),
                );
              },
            ),
            const SizedBox(width: 8),
            const Text(
              'COMMODITYEX // MONITOR v5.1',
              style: TextStyle(fontFamily: 'monospace', fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.5),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.menu_book, size: 18),
            onPressed: () => _scaffoldKey.currentState?.openDrawer(),
            tooltip: 'Open Metric Glossary Compass',
          ),
          IconButton(
            icon: Icon(_censorSensitiveData ? Icons.visibility_off : Icons.visibility, size: 18),
            onPressed: () => setState(() => _censorSensitiveData = !_censorSensitiveData),
            tooltip: 'Censor Portfolio Values',
          ),
        ],
      ),
      drawer: Drawer(
        backgroundColor: const Color(0xFF0C0C0F),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: const [
                      Icon(Icons.menu_book, color: Color(0xFF00E676), size: 16),
                      SizedBox(width: 8),
                      Text(
                        "METRIC COMPASS GLOSSARY",
                        style: TextStyle(fontFamily: 'monospace', fontSize: 11, fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                    ],
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, color: Colors.grey, size: 16),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                ],
              ),
              const Divider(color: Color(0xFF222226)),
              Expanded(
                child: ListenableBuilder(
                  listenable: _state,
                  builder: (context, _) {
                    final metadata = _state.data['metric_metadata'] ?? {};
                    return SingleChildScrollView(
                      child: _buildMetricDictionary(metadata),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
      body: ListenableBuilder(
        listenable: _state,
        builder: (context, child) {
          if (_state.isLoading) {
            return const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)));
          }

          if (_state.error != null && _state.data.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.wifi_off, size: 36, color: Colors.orangeAccent),
                  const SizedBox(height: 12),
                  Text(
                    _state.error!,
                    style: const TextStyle(color: Colors.orangeAccent, fontFamily: 'monospace', fontSize: 11),
                  ),
                ],
              ),
            );
          }

          final data = _state.data;
          final metrics = data['metrics'] ?? {};
          final val = data['v4_valuation'] ?? data['v3_valuation'] ?? {};
          final nodes = data['nodes'] ?? {};
          final mri = (data['mri'] ?? val['MRI'] ?? 45.0).toDouble();
          final regime = data['macro_regime'] ?? "Pending...";
          final directive = data['directive'] ?? "Waiting...";
          final metadata = data['metric_metadata'] ?? {};

          // Supply the relationship map dynamically
          _highlightState.updateMetadata(metadata);

          final hasRealData = val.isNotEmpty && val.containsKey('Total_Equity');
          bool isDataDegraded = data['status'] == "DEGRADED_STALE";

          String headerText;
          Color headerColor;

          if (!hasRealData) {
            headerText = "CONNECTING • SYSTEM INITIALIZATION...";
            headerColor = Colors.orangeAccent;
          } else if (isDataDegraded) {
            headerText = "LIVE (DEGRADED STALE DATA) • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = Colors.orange;
          } else {
            headerText = "LIVE REAL-TIME • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = mri < 40 
                ? Colors.greenAccent 
                : mri < 65 
                    ? Colors.orangeAccent 
                    : Colors.redAccent;
          }

          final healthRadar = data['health_radar'] ?? {};
          final double score = (healthRadar['health_rating'] ?? 10.0).toDouble();

          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Top Banner
                  ListenableBuilder(
                    listenable: _highlightState,
                    builder: (context, _) {
                      final selectedId = _highlightState.highlightedMetricId;
                      final isGlow = selectedId != null;
                      final glowColor = (selectedId?.toUpperCase() == 'JSF')
                          ? Colors.orangeAccent
                          : Colors.greenAccent;

                      return AnimatedContainer(
                        duration: const Duration(milliseconds: 200),
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          color: headerColor.withOpacity(0.05),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(
                            color: isGlow ? glowColor : headerColor.withOpacity(0.18),
                            width: isGlow ? 1.5 : 1.0,
                          ),
                          boxShadow: isGlow ? [
                            BoxShadow(color: glowColor.withOpacity(0.2), blurRadius: 6, spreadRadius: 1)
                          ] : null,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Row(
                                children: [
                                  Icon(isDataDegraded ? Icons.warning_amber_rounded : Icons.sensors, color: headerColor, size: 12),
                                  const SizedBox(width: 6),
                                  Expanded(
                                    child: Text(
                                      headerText,
                                      style: TextStyle(color: headerColor, fontSize: 9.5, fontWeight: FontWeight.bold, letterSpacing: 0.5),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Text(
                              "HEALTH SHIELD: ${score.toStringAsFixed(1)} / 10",
                              style: TextStyle(
                                color: isGlow ? glowColor : const Color(0xFF00E676),
                                fontSize: 9.5,
                                fontWeight: FontWeight.bold,
                                fontFamily: 'monospace',
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                  const SizedBox(height: 6),

                  _buildMacroRiskDashboard(mri, regime, directive),
                  const SizedBox(height: 6),

                  // Desktop Horizontal Layout safety
                  LayoutBuilder(
                    builder: (context, constraints) {
                      const double minWidth = 1100;
                      final Widget content = Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Left Column (flex: 12)
                          Expanded(
                            flex: 12,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                _buildForensicCovariancePanel(data['forensics'] ?? {}, data['portfolio_stats'] ?? {}),
                                const SizedBox(height: 10),
                                _buildBarbell(nodes, metrics['VIX']?['value']?.toDouble() ?? 16.5),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),

                          // Middle Column (flex: 28)
                          Expanded(
                            flex: 28,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                _buildDetailedBreakdown(val, nodes),
                                const SizedBox(height: 10),
                                _buildFluidMacroGrid(metrics, isDataDegraded),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),

                          // Right Column (flex: 20)
                          Expanded(
                            flex: 20,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                _buildSizingConstraintsWidget(val, mri, data['forensics'] ?? {}, data['portfolio_stats'] ?? {}, metrics, nodes),
                                const SizedBox(height: 6),
                                _buildModelHealthAndRadar(healthRadar),
                              ],
                            ),
                          ),
                        ],
                      );

                      if (constraints.maxWidth < minWidth) {
                        return SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: SizedBox(
                            width: minWidth,
                            child: content,
                          ),
                        );
                      }

                      return content;
                    },
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildSizingConstraintsWidget(Map<String, dynamic> val, double mri, Map<String, dynamic> forensics, Map<String, dynamic> stats, Map<String, dynamic> metrics, Map<String, dynamic> nodes) {
    final double currentValue = (val['Total_Equity'] ?? 0.0).toDouble();
    final double targetCapital = (val['E_Target'] ?? 0.0).toDouble();
    final double kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final double impliedEdge = (val['Implied_Upside'] ?? 0.0).toDouble();
    final double repFloor = (val['REP_Floor'] ?? 0.0).toDouble();
    final double runway = (val['Cash_Runway_Months'] ?? 0.0).toDouble();

    final double jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final Map<String, dynamic> corrMatrix = stats['correlations'] ?? {};

    final double fKelly = (val['fractional_kelly_multiplier'] ?? 0.5).toDouble();
    final double maxSpearPos = (val['max_spear_position_pct'] ?? 0.60).toDouble();

    final double portVol = (stats['port_vol'] ?? 0.40).toDouble();
    final double portVariance = (portVol * portVol < 0.04) ? 0.04 : portVol * portVol;
    final double rawPortfolioKelly = (impliedEdge / 100.0 / portVariance) * fKelly;

    final double groyCorr = corrMatrix['AGA.V']?['GROY']?.toDouble() ?? 0.50;
    final double urcCorr = corrMatrix['AGA.V']?['URC.TO']?.toDouble() ?? 0.50;
    final double gmxCorr = corrMatrix['AGA.V']?['GMX.TO']?.toDouble() ?? 0.50;
    final double avgBallastCorr = (groyCorr + urcCorr + gmxCorr) / 3.0;
    final double avgCPenalty = 1.0 - (avgBallastCorr > 0.30 ? (avgBallastCorr - 0.30) * 0.40 : 0.0);

    final double vix = (metrics['VIX']?['value'] ?? 16.5).toDouble();
    double maxLeverageAllowed = 1.5;
    if (vix > 15.0) {
      maxLeverageAllowed = 1.5 - ((vix - 15.0) * 0.045);
      if (maxLeverageAllowed < 0.60) maxLeverageAllowed = 0.60;
    }

    final double targetPortfolioLeverage = (rawPortfolioKelly < maxLeverageAllowed ? rawPortfolioKelly : maxLeverageAllowed) * avgCPenalty;
    final bool isAligned = (mri < 45.0) && (jsf >= 3.5);
    final double flexibilityMult = isAligned ? 1.25 : 1.0;

    double multiplier = 1.00;
    if (mri < 40) {
      multiplier = 1.00;
    } else if (mri < 65) {
      multiplier = 0.85;
    } else if (mri < 80) {
      multiplier = 0.55;
    } else {
      multiplier = 0.25;
    }

    final double rawTargetCap = currentValue * targetPortfolioLeverage * multiplier;
    final double maxPosLimitCad = currentValue * maxSpearPos * flexibilityMult;

    final double advCap = (val['ADV_Cap_CAD'] ?? 0.0).toDouble();
    final double advCapPct = (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();

    final double maxByLiquidityCap = advCap / 0.60;
    final double maxBySinglePosCap = maxPosLimitCad / 0.60;
    final double cappedTargetCap = targetCapital;

    final bool isPosBinding = (cappedTargetCap - maxBySinglePosCap).abs() < 1.0;
    final bool isLiqBinding = (cappedTargetCap - maxByLiquidityCap).abs() < 1.0;

    final Color posCapColor = isPosBinding ? const Color(0xFFFF9800) : const Color(0xFF00E676);
    final Color liqCapColor = isLiqBinding ? const Color(0xFFFF9800) : const Color(0xFF00E676);

    String displayCurrent = _censorSensitiveData ? "••••••" : "\$${currentValue.toStringAsFixed(0)}";
    String displayTarget = _censorSensitiveData ? "••••••" : "\$${targetCapital.toStringAsFixed(0)}";

    final double usdToCad = (val['usd_to_cad'] ?? stats['usd_to_cad'] ?? metrics['USDCAD=X']?['value'] ?? 1.38).toDouble();

    double currentValueSum = 0.0;
    final Map<String, double> weights = {
      "AGA.V": 0.60,
      "GROY": 0.15,
      "URC.TO": 0.15,
      "GMX.TO": 0.10,
    };

    weights.forEach((ticker, w) {
      final node = nodes[ticker] ?? {};
      final double price = (node['price'] ?? (ticker == "AGA.V" ? 0.71 : ticker == "GROY" ? 3.22 : ticker == "URC.TO" ? 4.82 : 2.04)).toDouble();
      double shares = (node['shares'] ?? 0.0).toDouble();
      if (shares == 0.0) {
        shares = (ticker == "AGA.V" ? 5000.0 : ticker == "GROY" ? 161.0 : ticker == "URC.TO" ? 130.0 : 230.0);
      }
      double val = shares * price;
      if (ticker == "GROY") {
        val *= usdToCad;
      }
      currentValueSum += val;
    });
    if (currentValueSum == 0.0) {
      currentValueSum = currentValue;
    }

    final List<TableRow> tableRows = [
      const TableRow(
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFF1E1E22), width: 1.0))),
        children: [
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Text("ASSET", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace')))),
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Text("ROLE", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace')))),
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text("WT", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace'))))),
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text("TGT WT", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace'))))),
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text("DELTA", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace'))))),
          TableCell(child: Padding(padding: EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.center, child: Text("ORDER", style: TextStyle(color: Colors.grey, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace'))))),
        ],
      ),
    ];

    weights.forEach((ticker, w) {
      final node = nodes[ticker] ?? {};
      final double price = (node['price'] ?? (ticker == "AGA.V" ? 0.71 : ticker == "GROY" ? 3.22 : ticker == "URC.TO" ? 4.82 : 2.04)).toDouble();
      
      double shares = (node['shares'] ?? 0.0).toDouble();
      if (shares == 0.0) {
        shares = (ticker == "AGA.V" ? 5000.0 : ticker == "GROY" ? 161.0 : ticker == "URC.TO" ? 130.0 : 230.0);
      }
      
      double currentValue = shares * price;
      if (ticker == "GROY") {
        currentValue *= usdToCad;
      }
      
      final double currentWeight = currentValue / currentValueSum * 100.0;
      final double targetValue = cappedTargetCap * w;
      final double targetWeight = w * 100.0;
      final double divPrice = ticker == "GROY" ? (price * usdToCad) : price;
      final double targetShares = divPrice > 0 ? (targetValue / divPrice) : 0.0;
      final double deltaShares = targetShares - shares;
      
      String directive = "HOLD";
      Color dirColor = const Color(0xFF888888);
      Color bgColor = Colors.transparent;
      
      if (deltaShares.abs() < 100) {
        directive = "HOLD";
        dirColor = const Color(0xFF888888);
        bgColor = Colors.transparent;
      } else if (deltaShares > 0) {
        double intrinsicVal = 999.0;
        if (ticker == "AGA.V") {
          intrinsicVal = (val['AGA_Intrinsic'] ?? impliedEdge).toDouble();
        }
        
        if (ticker == "AGA.V" && price > intrinsicVal) {
          directive = "HOLD (GT)";
          dirColor = const Color(0xFFFF9800);
          bgColor = const Color(0xFFFF9800).withOpacity(0.05);
        } else {
          directive = "BUY";
          dirColor = const Color(0xFF00E676);
          bgColor = const Color(0xFF00E676).withOpacity(0.05);
        }
      } else {
        directive = "TRIM";
        dirColor = const Color(0xFFFF9800);
        bgColor = const Color(0xFFFF9800).withOpacity(0.05);
      }
      
      final String deltaSharesStr = (deltaShares > 0 ? "+" : "") + deltaShares.toStringAsFixed(0);
      
      tableRows.add(
        TableRow(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFF161619)))),
          children: [
            TableCell(child: Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Text(ticker, style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white, fontSize: 8.5, fontFamily: 'monospace')))),
            TableCell(child: Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Text(ticker == "AGA.V" ? "Spear" : "Ballast", style: const TextStyle(color: Colors.grey, fontSize: 8, fontFamily: 'monospace')))),
            TableCell(child: Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text("${currentWeight.toStringAsFixed(1)}%", style: const TextStyle(color: Colors.white70, fontSize: 8, fontFamily: 'monospace'))))),
            TableCell(child: Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text("${targetWeight.toStringAsFixed(1)}%", style: const TextStyle(color: Color(0xFF00E676), fontSize: 8, fontFamily: 'monospace'))))),
            TableCell(child: Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1), child: Align(alignment: Alignment.centerRight, child: Text(deltaSharesStr, style: TextStyle(color: dirColor, fontWeight: FontWeight.bold, fontSize: 8, fontFamily: 'monospace'))))),
            TableCell(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 1.5, horizontal: 1),
                child: Align(
                  alignment: Alignment.center,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 0.5),
                    decoration: BoxDecoration(
                      color: bgColor,
                      border: Border.all(color: dirColor.withOpacity(0.25)),
                      borderRadius: BorderRadius.circular(2),
                    ),
                    child: Text(
                      directive,
                      style: TextStyle(color: dirColor, fontSize: 7, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    });

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "PORTFOLIO KELLY SIZING WATERFALL", 
          style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5),
        ),
        const SizedBox(height: 4),

        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            MetricCard(id: "Total_Equity", label: "CURRENT VALUE", value: displayCurrent, color: Colors.white70, highlightState: _highlightState),
            MetricCard(id: "E_Target", label: "TARGET DEPLOY", value: displayTarget, color: Colors.greenAccent, highlightState: _highlightState),
            MetricCard(id: "Kelly_Multiple", label: "KELLY MULT", value: "${kelly.toStringAsFixed(2)}x", color: _getKellyColor(kelly), highlightState: _highlightState),
            MetricCard(id: "REP Floor", label: "REP FLOOR", value: "\$${repFloor.toStringAsFixed(2)}", color: Colors.white70, highlightState: _highlightState),
            MetricCard(id: "CBA", label: "CASH RUNWAY", value: "${runway.toStringAsFixed(0)} mo", color: _getRunwayColor(runway), highlightState: _highlightState),
            MetricCard(id: "Implied_Upside", label: "IMPLIED EDGE", value: "${impliedEdge.toStringAsFixed(1)}%", color: _getEdgeColor(impliedEdge), highlightState: _highlightState),
          ],
        ),

        const SizedBox(height: 6),
        ListenableBuilder(
          listenable: _highlightState,
          builder: (context, _) {
            final isMriGlow = _highlightState.isHighlighted('MRI');
            final sieveBorderColor = isMriGlow ? Colors.greenAccent : const Color(0xFF222226);

            return AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFF101012),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(
                  color: sieveBorderColor, 
                  width: isMriGlow ? 1.5 : 1.0,
                ),
                boxShadow: isMriGlow ? [
                  BoxShadow(color: Colors.greenAccent.withOpacity(0.2), blurRadius: 6, spreadRadius: 1)
                ] : null,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        "VERTICAL SIZING WATERFALL SIEVE",
                        style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.bold, color: Colors.grey, fontFamily: 'monospace'),
                      ),
                      if (isMriGlow)
                        const Text(
                          "★ MRI DAMPENED",
                          style: TextStyle(fontSize: 8, color: Colors.greenAccent, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                        ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  _buildSieveRow("[1] RAW KELLY", _censorSensitiveData ? "••••••" : "\$${(rawTargetCap / multiplier).toStringAsFixed(0)} CAD", Colors.white),
                  _buildSieveRow("[2] FORENSIC-ADJUSTED", _censorSensitiveData ? "••••••" : "\$${(rawTargetCap / multiplier * (1.0 - (1.0 - (jsf / 4.0)) * 0.30)).toStringAsFixed(0)} CAD", jsf >= 3.5 ? Colors.white : Colors.orangeAccent),
                  _buildSieveRow("[3] REGIME-SCALED", _censorSensitiveData ? "••••••" : "\$${rawTargetCap.toStringAsFixed(0)} CAD", Colors.white),
                  _buildSieveRow(
                    "[4] SPEAR CEILING (60%)",
                    _censorSensitiveData ? "••••••" : "\$${maxPosLimitCad.toStringAsFixed(0)} CAD${isPosBinding ? ' ◆ ACT' : ''}",
                    posCapColor,
                  ),
                  _buildSieveRow(
                    "[5] ADV CAP (${advCapPct.toStringAsFixed(0)}% ADV)",
                    _censorSensitiveData ? "••••••" : "\$${advCap.toStringAsFixed(0)} CAD${isLiqBinding ? ' ◆ ACT' : ''}",
                    liqCapColor,
                  ),
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 3),
                    child: Divider(color: Color(0xFF222226), height: 1),
                  ),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        "● MODEL TARGET DEPLOYMENT",
                        style: TextStyle(color: Color(0xFF00E676), fontWeight: FontWeight.bold, fontSize: 9, fontFamily: 'monospace'),
                      ),
                      Text(
                        _censorSensitiveData ? "••••••" : "\$${cappedTargetCap.toStringAsFixed(0)} CAD",
                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF00E676), fontFamily: 'monospace'),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        ),

        const SizedBox(height: 6),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: const Color(0xFF101012),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: const Color(0xFF1E1E22)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "ASSET ALLOCATIONS DIRECTIVES",
                style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.bold, color: Colors.grey, fontFamily: 'monospace'),
              ),
              const SizedBox(height: 3),
              Table(
                defaultColumnWidth: const FlexColumnWidth(),
                children: tableRows,
              ),
            ],
          ),
        ),
        const SizedBox(height: 4),
        _buildActionableInsights(val, mri, jsf: jsf),
      ],
    );
  }

  Widget _buildSieveRow(String label, String value, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1.5),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Color(0xFFCCCCCC), fontSize: 9, fontFamily: 'monospace')),
          Text(
            _censorSensitiveData && value.contains('\$') && !value.contains('RAW') ? "••••••" : value,
            style: TextStyle(fontWeight: FontWeight.bold, color: color, fontSize: 9, fontFamily: 'monospace'),
          ),
        ],
      ),
    );
  }

  Widget _buildActionableInsights(Map<String, dynamic> val, double mri, {double jsf = 4.0}) {
    final kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final edge = (val['Implied_Upside'] ?? 0.0).toDouble();

    String recommendation = "HOLD POSITION - Monitor tape";
    Color recColor = Colors.orange;

    if (mri < 40 && edge > 80 && jsf >= 3.5) {
      recommendation = "HIGH CONVICTION ZONE - System signals expansion. Scale spear.";
      recColor = Colors.greenAccent;
    } else if (mri < 40 && edge > 80 && jsf < 3.5) {
      recommendation = "CONVICTION GATED - JSF forensics degraded. Scale conservatively.";
      recColor = Colors.orangeAccent;
    } else if (kelly > 1.5) {
      recommendation = "CAUTION - Sizer overallocated under current limits.";
      recColor = Colors.redAccent;
    } else if (mri > 65) {
      recommendation = "DEFENSIVE MODE - High sovereign stress. Keep cash buffers.";
      recColor = Colors.redAccent;
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(
        color: recColor.withOpacity(0.05),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: recColor.withOpacity(0.25)),
      ),
      child: Text(
        recommendation,
        style: TextStyle(color: recColor, fontSize: 9, fontWeight: FontWeight.bold, height: 1.2),
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
    final forensicPenalty = (val['Forensic_Penalty'] ?? 1.0).toDouble();
    final rov = (val['ROV'] ?? 1.18).toDouble();
    final repFloor = (val['REP_Floor'] ?? 0.0).toDouble();
    final advCapPct = (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();

    final double repComponent = 0.15 * repFloor;
    final double isIaiComponent = 0.70 * isIai * forensicPenalty;
    final double rovComponent = 0.15 * rov;
    final double computedIntrinsic = repComponent + isIaiComponent + rovComponent + expPremium;

    Color advCapColor = Colors.greenAccent;
    if (advCapPct < 5.0) {
      advCapColor = Colors.redAccent;
    } else if (advCapPct < 10.0) {
      advCapColor = Colors.orangeAccent;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("DETAILED MODEL VALUATION METRICS", 
            style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 4),

        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            MetricCard(id: "AGA.V Intrinsic", label: "AGA INTRINSIC", value: "\$${agaIntrinsic.toStringAsFixed(3)}", color: _getValuationColor(agaIntrinsic, agaPrice), highlightState: _highlightState),
            MetricCard(id: "IS-IAI", label: "IS-IAI / SHARE", value: "\$${isIai.toStringAsFixed(3)}", color: _getValuationColor(isIai, agaPrice), highlightState: _highlightState),
            MetricCard(id: "Discovery Premium", label: "EXP. PREMIUM", value: "\$${expPremium.toStringAsFixed(3)}", color: expPremium > 0 ? Colors.greenAccent : Colors.white70, highlightState: _highlightState),
            MetricCard(id: "PPI", label: "PPI INDEX", value: "\$${ppi.toStringAsFixed(3)}", color: _getValuationColor(ppi, agaPrice), highlightState: _highlightState),
            MetricCard(id: "EV_Blended", label: "EV BLENDED", value: "\$${evBlended.toStringAsFixed(3)}", color: _getValuationColor(evBlended, agaPrice), highlightState: _highlightState),
            MetricCard(id: "Probability", label: "BLENDED PROB", value: "${(probability*100).toStringAsFixed(0)}%", color: probability >= 0.7 ? Colors.greenAccent : Colors.orangeAccent, highlightState: _highlightState),
            MetricCard(id: "Forensic Penalty", label: "FORENSIC PENALTY", value: "${forensicPenalty.toStringAsFixed(3)}x", color: forensicPenalty == 1.0 ? Colors.greenAccent : Colors.orangeAccent, highlightState: _highlightState),
            MetricCard(id: "ROV", label: "ROV MULTIPLE", value: rov.toStringAsFixed(2), color: rov >= 1.3 ? Colors.greenAccent : Colors.white70, highlightState: _highlightState),
            MetricCard(id: "ADV Cap", label: "ADV EXIT CAP", value: "\$${(val['ADV_Cap_CAD'] ?? 0.0).toStringAsFixed(0)}", color: advCapColor, highlightState: _highlightState),
            MetricCard(id: "Peer EV/oz", label: "PEER DISC COST", value: "\$${(val['Discovery_Efficiency_Comps'] ?? 0.48).toStringAsFixed(2)}/oz", color: Colors.white70, highlightState: _highlightState),
          ],
        ),

        const SizedBox(height: 6),
        FormulaTraceWidget(
          repFloor: repFloor,
          repComponent: repComponent,
          isIai: isIai,
          isIaiComponent: isIaiComponent,
          forensicPenalty: forensicPenalty,
          rov: rov,
          rovComponent: rovComponent,
          expPremium: expPremium,
          computedIntrinsic: computedIntrinsic,
          agaIntrinsic: agaIntrinsic,
          highlightState: _highlightState,
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
    final Map<String, dynamic> vols = stats['vols'] ?? {};
    final spearVol = (vols['AGA.V'] ?? 0.45).toDouble();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("FORENSIC SHIELDS & COVARIANCE STATS", 
            style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 4),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            MetricCard(
              id: "JSF", 
              label: "JSF SHIELD SCORE", 
              value: "${jsf.toStringAsFixed(1)} / 4.0", 
              color: jsf == 4.0 ? Colors.greenAccent : Colors.orangeAccent, 
              highlightState: _highlightState,
            ),
            MetricCard(id: "Forensic Penalty", label: "PENALTY DISCOUNT", value: "${penalty.toStringAsFixed(3)}x", color: penalty == 1.0 ? Colors.greenAccent : Colors.redAccent, highlightState: _highlightState),
            MetricCard(id: "ES95", label: "EXPECTED SHORTFALL", value: "${es95.toStringAsFixed(2)}%", color: Colors.orangeAccent, highlightState: _highlightState),
            MetricCard(id: "Spear Volatility", label: "SPEAR VOL (AGA)", value: "${(spearVol * 100).toStringAsFixed(0)}%", color: Colors.white70, highlightState: _highlightState),
            MetricCard(id: "Sloan CFO", label: "SLOAN CFO ACCRUALS", value: sloanCfo.toStringAsFixed(4), color: sloanCfo < 0.05 ? Colors.greenAccent : Colors.redAccent, highlightState: _highlightState),
            MetricCard(id: "Sloan BS", label: "SLOAN BS ACCRUALS", value: sloanBs.toStringAsFixed(4), color: sloanBs < 0.05 ? Colors.greenAccent : Colors.redAccent, highlightState: _highlightState),
            MetricCard(id: "Diversification Correlation", label: "BARBELL DIVERSIF", value: avgCorr.toStringAsFixed(2), color: Colors.white70, highlightState: _highlightState),
          ],
        ),
      ],
    );
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
    return ListenableBuilder(
      listenable: _highlightState,
      builder: (context, _) {
        final isGlow = _highlightState.highlightedMetricId == 'MRI';

        return GestureDetector(
          onTap: () => _highlightState.toggleHighlight('MRI'),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: const Color(0xFF101012),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(
                color: isGlow ? Colors.greenAccent : const Color(0xFF222226),
                width: isGlow ? 1.5 : 1.0,
              ),
              boxShadow: isGlow ? [
                BoxShadow(color: Colors.greenAccent.withOpacity(0.2), blurRadius: 6, spreadRadius: 1)
              ] : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      "MACRO REGIME INDEX (MRI) — CLICK CARD TO TRACE MACRO DELTAS", 
                      style: TextStyle(fontSize: 8, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.5),
                    ),
                    Text(
                      "MRI Score: ${mri.toStringAsFixed(1)}", 
                      style: TextStyle(
                        fontSize: 9.5, 
                        fontWeight: FontWeight.bold,
                        color: mri < 40 
                            ? Colors.greenAccent 
                            : mri < 65 
                                ? Colors.orangeAccent 
                                : Colors.redAccent,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 3),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: mri / 100,
                    minHeight: 3.5,
                    backgroundColor: const Color(0xFF222226),
                    color: mri < 40 
                        ? Colors.greenAccent 
                        : mri < 65 
                            ? Colors.orangeAccent 
                            : Colors.redAccent,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  "$regime // $directive", 
                  style: const TextStyle(color: Colors.white70, fontSize: 9, fontWeight: FontWeight.bold, height: 1.2),
                ),
              ],
            ),
          ),
        );
      },
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
      default:
        return Colors.white70;
    }
  }

  Widget _buildFluidMacroGrid(Map<String, dynamic> metrics, bool isFallback) {
    final double cftcVal = (metrics['CFTC_Silver_Net_Longs']?['value'] ?? 35000.0).toDouble();
    
    String formatContracts(double val) {
      if (val.abs() >= 1000) {
        return "${(val / 1000).toStringAsFixed(0)}k contr.";
      }
      return "${val.toStringAsFixed(0)} contr.";
    }

    Widget buildCell(String label, String value, Color color, String metricId) {
      return ListenableBuilder(
        listenable: _highlightState,
        builder: (context, _) {
          final isHighlighted = _highlightState.isHighlighted(metricId);
          final source = _highlightState.highlightedMetricId?.toUpperCase();
          final highlightColor = (source == 'JSF') ? Colors.orangeAccent : Colors.greenAccent;

          return GestureDetector(
            onTap: () => _highlightState.toggleHighlight(metricId),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 3),
              decoration: BoxDecoration(
                border: isHighlighted ? Border.all(color: highlightColor, width: 0.5) : null,
                color: isHighlighted ? highlightColor.withOpacity(0.05) : Colors.transparent,
                borderRadius: BorderRadius.circular(2),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      Text(label, style: const TextStyle(color: Colors.grey, fontSize: 8.5, fontFamily: 'monospace', fontWeight: FontWeight.bold)),
                      if (metricId == "10Y" || metricId == "30Y" || metricId == "TED") ...[
                        const SizedBox(width: 3),
                        Text(
                          isFallback ? "YF" : "FR",
                          style: TextStyle(
                            color: isFallback ? Colors.orangeAccent.withOpacity(0.6) : Colors.greenAccent.withOpacity(0.6),
                            fontSize: 6.5,
                            fontWeight: FontWeight.bold,
                            fontFamily: 'monospace',
                          ),
                        ),
                      ],
                    ],
                  ),
                  Text(value, style: TextStyle(color: isHighlighted ? highlightColor : color, fontSize: 9.5, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
                ],
              ),
            ),
          );
        },
      );
    }

    Widget buildColumn(String header, List<Widget> cells) {
      return Expanded(
        child: Container(
          decoration: BoxDecoration(
            color: const Color(0xFF101012),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: const Color(0xFF1C1C20)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 3),
                decoration: const BoxDecoration(
                  color: Color(0xFF151517),
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(3),
                    topRight: Radius.circular(3),
                  ),
                ),
                child: Text(
                  header,
                  style: const TextStyle(color: Colors.grey, fontSize: 7.5, fontWeight: FontWeight.bold, letterSpacing: 0.5, fontFamily: 'monospace'),
                ),
              ),
              ...cells,
            ],
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("FLUID MACRO & COMMODITY TAPE", 
            style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 4),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            buildColumn("SOVEREIGN RATES", [
              buildCell("10Y US YLD", "${(metrics['10Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('10Y', (metrics['10Y']?['value'] ?? 0).toDouble()), "10Y"),
              buildCell("30Y US YLD", "${(metrics['30Y']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('30Y', (metrics['30Y']?['value'] ?? 0).toDouble()), "30Y"),
              buildCell("SOFR SPREAD", "${(metrics['TED']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('TED', (metrics['TED']?['value'] ?? 0).toDouble()), "TED"),
            ]),
            const SizedBox(width: 4),
            buildColumn("LIQUIDITY & CREDIT", [
              buildCell("DXY INDEX", "${(metrics['DXY']?['value'] ?? 0).toStringAsFixed(1)}", _getMetricColor('DXY', (metrics['DXY']?['value'] ?? 0).toDouble()), "DXY"),
              buildCell("HY CORPORATE", "${(metrics['Spreads']?['value'] ?? 0).toStringAsFixed(2)}%", _getMetricColor('Spreads', (metrics['Spreads']?['value'] ?? 0).toDouble()), "Spreads"),
              buildCell("VIX VOLATILITY", "${(metrics['VIX']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('VIX', (metrics['VIX']?['value'] ?? 0).toDouble()), "VIX"),
            ]),
            const SizedBox(width: 4),
            buildColumn("PHYSICAL COMMODITIES", [
              buildCell("WTI CRUDE", "\$${(metrics['WTI']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('WTI', (metrics['WTI']?['value'] ?? 0).toDouble()), "WTI"),
              buildCell("SPOT SILVER", "\$${(metrics['Spot_Ag']?['value'] ?? 0).toStringAsFixed(2)}", _getMetricColor('Spot_Ag', (metrics['Spot_Ag']?['value'] ?? 0).toDouble()), "Spot_Ag"),
              buildCell("CFTC POSITION", formatContracts(cftcVal), Colors.white, "CFTC_Silver_Net_Longs"),
            ]),
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
            style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5)),
        const SizedBox(height: 4),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: nodes.entries.map((e) {
            bool isSpear = e.value['role'] == 'The Spear';
            return Tooltip(
              message: isSpear 
                  ? "The Spear (60% allocation)\nHigh-conviction silver explorer torque engine."
                  : "Ballast (40% allocation)\nStable cash-generating royalty ballast.",
              child: Container(
                width: 110,
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
                decoration: BoxDecoration(
                  color: const Color(0xFF101012),
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(
                    color: (isSpear && vix > 23.0) ? Colors.redAccent : const Color(0xFF1E1E22), 
                    width: 1.0
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(e.key, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 9.5, color: Colors.white)),
                    const SizedBox(height: 2),
                    Text("\$${e.value['price']}", style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
                    const SizedBox(height: 1.5),
                    Text(e.value['role'], style: const TextStyle(color: Colors.grey, fontSize: 7.5, fontWeight: FontWeight.bold)),
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
    if (ratio >= 1.5) return Colors.greenAccent; 
    if (ratio <= 0.85) return Colors.redAccent;  
    return Colors.orangeAccent;                  
  }

  Widget _buildModelHealthAndRadar(Map<String, dynamic> radarData) {
    if (radarData.isEmpty) return const SizedBox.shrink();
    
    final score = (radarData['health_rating'] ?? 10.0).toDouble();
    final ratingDesc = radarData['rating_desc']?.toString() ?? "PENDING DATA";
    final ratingColorName = radarData['rating_color']?.toString() ?? "white";
    final healthSummary = radarData['health_summary']?.toString() ?? "Loading...";
    final priorities = List<Map<String, dynamic>>.from(
      (radarData['priorities'] as List? ?? []).map((e) => Map<String, dynamic>.from(e))
    );
    
    Color ratingColor = Colors.white70;
    if (ratingColorName == "green") ratingColor = Colors.greenAccent;
    else if (ratingColorName == "orange") ratingColor = Colors.orangeAccent;
    else if (ratingColorName == "red") ratingColor = Colors.redAccent;
    
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

    return ListenableBuilder(
      listenable: _highlightState,
      builder: (context, _) {
        final selectedId = _highlightState.highlightedMetricId;
        final isGlow = selectedId != null;
        final glowColor = (selectedId?.toUpperCase() == 'JSF') ? Colors.orangeAccent : Colors.greenAccent;

        return AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: const Color(0xFF101012),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: isGlow ? glowColor : ratingColor.withOpacity(0.18), 
              width: isGlow ? 1.5 : 1.0,
            ),
            boxShadow: isGlow ? [
              BoxShadow(color: glowColor.withOpacity(0.2), blurRadius: 6, spreadRadius: 1)
            ] : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    "TACTICAL HEALTH RADAR",
                    style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 0.5),
                  ),
                  Text(
                    "H Rating: ${score.toStringAsFixed(1)}",
                    style: TextStyle(color: ratingColor, fontSize: 9, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                  ),
                ],
              ),
              const SizedBox(height: 3),
              Text(
                "$ratingDesc — $healthSummary",
                style: const TextStyle(color: Colors.grey, fontSize: 8.5, height: 1.2),
              ),
              const SizedBox(height: 3),
              const Divider(color: Color(0xFF222226), height: 6),
              Column(
                children: priorities.take(2).map((p) => _buildPriorityItem(
                  _getIconData(p['icon']?.toString() ?? ''),
                  _getColor(p['color']?.toString() ?? ''),
                  p['title']?.toString() ?? '',
                  p['desc']?.toString() ?? ''
                )).toList(),
              )
            ],
          ),
        );
      },
    );
  }

  Widget _buildPriorityItem(IconData icon, Color color, String title, String desc) {
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 10),
          const SizedBox(width: 5),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: const TextStyle(fontSize: 8.5, fontFamily: 'monospace', height: 1.15),
                children: [
                  TextSpan(text: "$title: ", style: TextStyle(color: color, fontWeight: FontWeight.bold)),
                  TextSpan(text: desc, style: const TextStyle(color: Colors.grey)),
                ],
              ),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildMetricDictionary(Map<String, dynamic> metadata) {
    if (metadata.isEmpty) {
      return const Center(
        child: Text("Connecting and loading database metrics glossary...", style: TextStyle(color: Colors.grey, fontSize: 9)),
      );
    }
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: const [
            Icon(Icons.help, color: Colors.grey, size: 12),
            SizedBox(width: 5),
            Text(
              "GLOSSARY COMPASS & ENGINE FORMULAS",
              style: TextStyle(fontSize: 9, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.5),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ...metadata.entries.map((e) {
          final def = e.value['definition'] ?? '';
          final calc = e.value['calculation'] ?? '';
          final use = e.value['actionability'] ?? '';
          
          return Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  e.key,
                  style: const TextStyle(color: Colors.white, fontSize: 9.5, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 1.5),
                RichText(
                  text: TextSpan(
                    style: const TextStyle(fontSize: 8.5, color: Colors.grey, height: 1.2, fontFamily: 'Courier'),
                    children: [
                      const TextSpan(text: "Definition: ", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
                      TextSpan(text: "$def\n"),
                      const TextSpan(text: "Formula: ", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
                      TextSpan(text: "$calc\n"),
                      const TextSpan(text: "Actionability: ", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
                      TextSpan(text: "$use", style: const TextStyle(color: Colors.grey)),
                    ],
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ],
    );
  }
}

// Performant MetricCard listening only to highlight updates
class MetricCard extends StatelessWidget {
  final String id;
  final String label;
  final String value;
  final Color color;
  final HighlightState highlightState;
  final VoidCallback? onTap;

  const MetricCard({
    super.key,
    required this.id,
    required this.label,
    required this.value,
    required this.color,
    required this.highlightState,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: highlightState,
      builder: (context, _) {
        final isGlow = highlightState.isHighlighted(id);
        final source = highlightState.highlightedMetricId?.toUpperCase();
        final glowColor = (source == 'JSF')
            ? Colors.orangeAccent
            : Colors.greenAccent;

        return Tooltip(
          message: _getRichTooltip(label),
          child: GestureDetector(
            onTap: onTap ?? () => highlightState.toggleHighlight(id),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 110,
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xFF101012),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(
                  color: isGlow ? glowColor : color.withOpacity(0.22),
                  width: isGlow ? 1.5 : 1.0,
                ),
                boxShadow: isGlow
                    ? [BoxShadow(color: glowColor.withOpacity(0.2), blurRadius: 5, spreadRadius: 1)]
                    : null,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: const TextStyle(color: Colors.grey, fontSize: 7.5, fontWeight: FontWeight.bold, letterSpacing: 0.3),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    value,
                    style: TextStyle(color: isGlow ? glowColor : color, fontSize: 11.5, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

// Mathematical valuation trace widget reacting visually to clicked metrics
class FormulaTraceWidget extends StatelessWidget {
  final double repFloor;
  final double repComponent;
  final double isIai;
  final double isIaiComponent;
  final double forensicPenalty;
  final double rov;
  final double rovComponent;
  final double expPremium;
  final double computedIntrinsic;
  final double agaIntrinsic;
  final HighlightState highlightState;

  const FormulaTraceWidget({
    super.key,
    required this.repFloor,
    required this.repComponent,
    required this.isIai,
    required this.isIaiComponent,
    required this.forensicPenalty,
    required this.rov,
    required this.rovComponent,
    required this.expPremium,
    required this.computedIntrinsic,
    required this.agaIntrinsic,
    required this.highlightState,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: highlightState,
      builder: (context, _) {
        final isJsfGlow = highlightState.isHighlighted('JSF');
        final isMriGlow = highlightState.isHighlighted('MRI');
        final isRepGlow = highlightState.isHighlighted('REP Floor');
        final isIaiGlow = highlightState.isHighlighted('IS-IAI');
        final isRovGlow = highlightState.isHighlighted('ROV');
        final isPremiumGlow = highlightState.isHighlighted('Discovery Premium');

        Color diagramBorder = const Color(0xFF222226);
        if (isMriGlow) {
          diagramBorder = Colors.greenAccent;
        } else if (isJsfGlow) {
          diagramBorder = Colors.orangeAccent;
        }

        Widget buildSieveRow(String label, String value, Color color, bool isGlowItem) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 1.5),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    color: isGlowItem ? Colors.white : const Color(0xFFCCCCCC),
                    fontWeight: isGlowItem ? FontWeight.bold : FontWeight.normal,
                    fontSize: 9,
                    fontFamily: 'monospace',
                  ),
                ),
                Text(
                  value,
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: color,
                    fontSize: 9,
                    fontFamily: 'monospace',
                  ),
                ),
              ],
            ),
          );
        }

        return Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: const Color(0xFF101012),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(
              color: diagramBorder,
              width: (isMriGlow || isJsfGlow) ? 1.5 : 1.0,
            ),
            boxShadow: (isMriGlow || isJsfGlow)
                ? [BoxShadow(color: diagramBorder.withOpacity(0.2), blurRadius: 6, spreadRadius: 1)]
                : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "INTRINSIC MATHEMATICAL FORMULA TRACE",
                style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.bold, color: Colors.grey, fontFamily: 'monospace'),
              ),
              const SizedBox(height: 4),
              buildSieveRow(
                "[A] 15% × REP Floor (\$${repFloor.toStringAsFixed(3)})",
                "\$${repComponent.toStringAsFixed(3)}",
                isRepGlow ? Colors.greenAccent : Colors.white,
                isRepGlow,
              ),
              buildSieveRow(
                "[B] 70% × IS-IAI (\$${isIai.toStringAsFixed(3)}) × Forensic (${forensicPenalty.toStringAsFixed(3)}x)",
                "\$${isIaiComponent.toStringAsFixed(3)}",
                isIaiGlow ? Colors.orangeAccent : Colors.white,
                isIaiGlow || isJsfGlow,
              ),
              buildSieveRow(
                "[C] 15% × ROV (${rov.toStringAsFixed(2)})",
                "\$${rovComponent.toStringAsFixed(3)}",
                isRovGlow ? Colors.greenAccent : Colors.white,
                isRovGlow || isMriGlow,
              ),
              buildSieveRow(
                "[D] Exp. Premium / Share",
                "\$${expPremium.toStringAsFixed(3)}",
                isPremiumGlow ? Colors.greenAccent : Colors.white,
                isPremiumGlow,
              ),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 3),
                child: Divider(color: Color(0xFF222226), height: 1),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    "● COMPUTED INTRINSIC (A+B+C+D)",
                    style: TextStyle(color: Color(0xFF00E676), fontWeight: FontWeight.bold, fontSize: 9, fontFamily: 'monospace'),
                  ),
                  Text(
                    "\$${computedIntrinsic.toStringAsFixed(3)}",
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      color: (computedIntrinsic - agaIntrinsic).abs() < 0.02 ? const Color(0xFF00E676) : Colors.redAccent,
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

// Space-efficient connection diagnostic widget
class ConnectionIndicator extends StatelessWidget {
  final String? error;
  final bool isLoading;
  final bool isDegraded;
  final Animation<double> pulseAnimation;

  const ConnectionIndicator({
    super.key,
    required this.error,
    required this.isLoading,
    required this.isDegraded,
    required this.pulseAnimation,
  });

  @override
  Widget build(BuildContext context) {
    Color indicatorColor = Colors.greenAccent;
    IconData icon = Icons.sensors;
    String statusText = "LIVE";

    if (error != null) {
      indicatorColor = Colors.redAccent;
      icon = Icons.wifi_off;
      statusText = "DISCONNECTED";
    } else if (isLoading) {
      indicatorColor = Colors.orangeAccent;
      icon = Icons.hourglass_empty;
      statusText = "CONNECTING";
    } else if (isDegraded) {
      indicatorColor = Colors.orange;
      icon = Icons.warning_amber_rounded;
      statusText = "DEGRADED";
    }

    return FadeTransition(
      opacity: pulseAnimation,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
        decoration: BoxDecoration(
          color: indicatorColor.withOpacity(0.1),
          border: Border.all(color: indicatorColor.withOpacity(0.3), width: 0.5),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: indicatorColor, size: 9),
            const SizedBox(width: 3),
            Text(
              statusText,
              style: TextStyle(
                color: indicatorColor,
                fontSize: 7.5,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _getRichTooltip(String label) {
  final String cleanLabel = label.toUpperCase();
  if (cleanLabel.contains("ADV")) {
    return "[ADV CAP - ACTIONABLE] Maximum safe position size in CAD based on exit liquidity limits. High MRI contracts caps to 2% ADV to avoid trapping.";
  }
  if (cleanLabel.contains("JSF")) {
    return "[JSF SHIELD - FORENSIC] Junior Survival Factor (0-4). Scores < 3.5 trigger strict position caps and a 30% resource penalty to shield against dilution.";
  }
  if (cleanLabel.contains("SHORTFALL") || cleanLabel.contains("ES95")) {
    return "[EXPECTED SHORTFALL - RISK] Average daily return loss in the worst 5% of return scenarios. High ES (>5%) penalizes Health Rating.";
  }
  if (cleanLabel.contains("SLOAN CFO")) {
    return "[SLOAN CFO - ACCRUALS] CFO Sloan accrual check. Ratios > 5% warn of non-cash earnings inflation or balance sheet capitalization stress.";
  }
  if (cleanLabel.contains("SLOAN BS")) {
    return "[SLOAN BS - ACCRUALS] Balance Sheet Sloan accrual check. Measures working capital expansion to verify corporate cash flow integrity.";
  }
  if (cleanLabel.contains("DIVERSIFICATION") || cleanLabel.contains("CORR")) {
    return "[PORTFOLIO CORRELATION] Weighted average correlation of the barbell. Lower correlations (~0.25) expand diversification.";
  }
  if (cleanLabel.contains("INTRINSIC")) {
    return "[AGA.V INTRINSIC - VALUATION] Blended intrinsic value: 15% REP Floor, 70% Forensic-discounted IS-IAI, 15% ROV, and exploration upside.";
  }
  if (cleanLabel.contains("IS-IAI")) {
    return "[IS-IAI / SHARE] In-Situ resource value. Calculated using effective ounces times peer multiples times Discovery Premium.";
  }
  if (cleanLabel.contains("EXP. PREMIUM")) {
    return "[EXPLORATION PREMIUM] Probability-weighted valuation of projected ounces to reward efficient drilling and resource expansion.";
  }
  if (cleanLabel.contains("PPI")) {
    return "[PORTFOLIO PRICE INDEX] Real-time market cost to acquire the 60/40 silver barbell index. Benchmark for evaluating intrinsic edge.";
  }
  if (cleanLabel.contains("EV BLENDED")) {
    return "[EV BLENDED] The model's target intrinsic value of the entire barbell portfolio index in CAD.";
  }
  if (cleanLabel.contains("PROB") || cleanLabel.contains("PROBABILITY")) {
    return "[BLENDED PROBABILITY] Statistical confidence rate that the spear asset will converge to its geological intrinsic value.";
  }
  if (cleanLabel.contains("PENALTY") || cleanLabel.contains("DISCOUNT")) {
    return "[FORENSIC PENALTY] Valuation haircut multiplier based on JSF. Runway < 18mo or high burn applies up to a 30% discount.";
  }
  if (cleanLabel.contains("ROV")) {
    return "[ROV PREMIUM - OPTIONALITY] Real Option Value. Base premium (1.18x) scales as negative real yields drop <1% or precious metals volatility surges.";
  }
  if (cleanLabel.contains("PEER DISC")) {
    return "[PEER DISCOVERY COST] Weighted average cost to discover an ounce of silver equivalent across comps. Benchmarks explorer efficiency.";
  }
  if (cleanLabel.contains("SOFR SPREAD") || cleanLabel.contains("TED")) {
    return "[SOFR SPREAD - MACRO] SOFR minus 3-Month Treasury Rate. Measures acute money-market credit and funding stress.";
  }
  if (cleanLabel.contains("CURRENT VALUE")) {
    return "[PORTFOLIO EQUITY VALUE] Total live asset equity scaled in CAD. Used as the capital base for Kelly sizer calculations.";
  }
  if (cleanLabel.contains("TARGET DEPLOY") || cleanLabel.contains("TARGET CAPITAL")) {
    return "[TARGET DEPLOYMENT - ACTIONABLE] Dynamic capital allocation calculated using fractional Kelly, scaled by MRI and constrained by exit liquidity.";
  }
  if (cleanLabel.contains("KELLY MULT") || cleanLabel.contains("KELLY MULTIPLE")) {
    return "[KELLY MULTIPLE] Ratio of actual barbell holdings vs target. Multiples > 1.0 indicate capital overallocation.";
  }
  if (cleanLabel.contains("REP FLOOR")) {
    return "[REP FLOOR - SUPPORT] Cash + stressed defined resource replacement cost floor. Buying below this represents buying assets below cost.";
  }
  if (cleanLabel.contains("CASH RUNWAY") || cleanLabel.contains("RUNWAY")) {
    return "[CASH RUNWAY] Months of corporate cash burn remaining. Runway under 18 months prompts immediate dilution warning flags.";
  }
  if (cleanLabel.contains("IMPLIED EDGE")) {
    return "[IMPLIED EDGE - ARBITRAGE] Percentage discrepancy between current market index price and computed intrinsic value.";
  }
  if (cleanLabel.contains("SPEAR VOL")) {
    return "[SPEAR VOLATILITY] 10-day historical trading volatility of AGA.V. Volatility increases tail-risk but expands ROV premium option torque.";
  }
  
  return "[$label] Detailed strategic engine metric. Hover to inspect definitions and formulas.";
}