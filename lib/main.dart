/*
 * CommodityEx Terminal — Quant Monitor v5.2  ("Command Deck" redesign)
 * ---------------------------------------------------------------------
 * A single, edge-to-edge high-density instrument panel for a high-conviction
 * silver / junior-mining quant strategy. Premium fintech aesthetic (Mercury /
 * Bloomberg) over a layered near-black surface system with a single brand green.
 *
 * Architecture (all v5.1 functionality preserved):
 *   • TerminalState      — live WebSocket feed + auto-reconnect (unchanged contract).
 *   • HighlightState     — the bidirectional "glow" engine that traces metric
 *                          relationships across the whole dashboard on click.
 *   • Layout             — Header bar  ▸  KPI cockpit strip  ▸  3-column workspace
 *                          (Risk/Forensics · Kelly Engine · Valuation/Health).
 *   • Metric Compass     — slide-in glossary drawer (the only "navigation").
 *   • Centerpiece        — the Kelly Sizing Waterfall, now with proportional
 *                          capital-decay bars on every sieve step.
 *
 * Design tokens live in the `k*` constants below so the whole surface stays
 * visually coherent and easy to retune.
 */
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'package:flutter/foundation.dart';

// ======================================================================
//  DESIGN SYSTEM TOKENS
//  Layered surfaces + one accent. Keeping these centralized is what gives
//  the redesign its coherent, premium feel.
// ======================================================================
const Color kBg = Color(0xFF050507); // app background (deepest)
const Color kPanel = Color(0xFF0D0D10); // card / panel surface
const Color kPanelHi = Color(0xFF141418); // elevated chips inside panels
const Color kChrome = Color(0xFF09090B); // header / structural chrome
const Color kBorder = Color(0xFF1B1B21); // hairline divider / card border
const Color kBorderHi = Color(0xFF27272F); // stronger border on hover/group
const Color kAccent = Color(0xFF00E676); // brand green — the single accent
const Color kDim = Color(0xFF8A8A95); // secondary text
const Color kFaint = Color(0xFF5C5C66); // tertiary / label text

void main() => runApp(const CommodityExApp());

class CommodityExApp extends StatelessWidget {
  const CommodityExApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CommodityEx Terminal',
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: kBg,
        primaryColor: kAccent,
        cardColor: kPanel,
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

// ======================================================================
//  HIGHLIGHT / GLOW ENGINE  (unchanged behavior)
//  Clicking any metric traces its related metrics across the whole board.
//  Relationships are bidirectional: forward (selected -> related) and
//  reverse (target lists selected as related).
// ======================================================================
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

    // Forward check: does the selected metric list 'id' as related?
    final metricMeta = _metadata[_highlightedMetricId];
    if (metricMeta != null && metricMeta['related_metrics'] != null) {
      final List<dynamic> related = metricMeta['related_metrics'];
      if (related.any((e) => e.toString().toLowerCase() == id.toLowerCase())) {
        return true;
      }
    }

    // Reverse check: does the target metric 'id' list the selected metric as related?
    // This makes glow pathways bidirectional.
    final targetMeta = _metadata[id];
    if (targetMeta != null && targetMeta['related_metrics'] != null) {
      final List<dynamic> targetRelated = targetMeta['related_metrics'];
      if (targetRelated.any((e) =>
          e.toString().toLowerCase() == _highlightedMetricId!.toLowerCase())) {
        return true;
      }
    }

    return false;
  }

  /// Glow color convention preserved from v5.1: JSF traces in amber
  /// (forensic alarm), everything else traces in the brand green.
  Color get activeGlowColor =>
      (_highlightedMetricId?.toUpperCase() == 'JSF')
          ? Colors.orangeAccent
          : kAccent;
}

// ======================================================================
//  LIVE DATA  (unchanged WebSocket contract + auto-reconnect)
// ======================================================================
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

  /// Test-only seam: seed a fixed payload and skip the live socket so the
  /// dashboard can be rendered deterministically (e.g. overflow tests).
  TerminalState.seeded(Map<String, dynamic> seed) {
    _data = seed;
    _isLoading = false;
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
    // Guard: a seeded (test) instance never opened a channel.
    try {
      _channel.sink.close();
    } catch (_) {}
    super.dispose();
  }
}

class MainTerminalView extends StatefulWidget {
  /// Optional injected state for tests; production passes null and connects live.
  final TerminalState? injected;
  const MainTerminalView({super.key, this.injected});

  @override
  State<MainTerminalView> createState() => _MainTerminalViewState();
}

class _MainTerminalViewState extends State<MainTerminalView>
    with SingleTickerProviderStateMixin {
  late final TerminalState _state;
  late final HighlightState _highlightState;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  bool _censorSensitiveData = false;
  late AnimationController _pulseController;

  // Below this width the 3-column deck would crush; we switch to horizontal
  // scroll so the dense layout never collapses or overflows.
  static const double _deckMinWidth = 1320;

  @override
  void initState() {
    super.initState();
    _state = widget.injected ?? TerminalState();
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

  // ====================================================================
  //  BUILD
  // ====================================================================
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: kBg,
      drawer: _buildCompassDrawer(),
      body: ListenableBuilder(
        listenable: _state,
        builder: (context, child) {
          if (_state.isLoading) {
            return const Center(
              child: CircularProgressIndicator(color: kAccent),
            );
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
                    style: const TextStyle(
                        color: Colors.orangeAccent,
                        fontFamily: 'monospace',
                        fontSize: 11),
                  ),
                ],
              ),
            );
          }

          // ---- Unpack the live payload (same contract as v5.1) ----
          final data = _state.data;
          final metrics = data['metrics'] ?? {};
          final val = data['v4_valuation'] ?? data['v3_valuation'] ?? {};
          final nodes = data['nodes'] ?? {};
          final mri = (data['mri'] ?? val['MRI'] ?? 45.0).toDouble();
          final regime = data['macro_regime'] ?? "Pending...";
          final directive = data['directive'] ?? "Waiting...";
          final metadata = data['metric_metadata'] ?? {};
          final forensics = data['forensics'] ?? {};
          final healthRadar = data['health_radar'] ?? {};

          // Feed the relationship graph into the glow engine each tick.
          _highlightState.updateMetadata(metadata);

          final hasRealData = val.isNotEmpty && val.containsKey('Total_Equity');
          final bool isDataDegraded = data['status'] == "DEGRADED_STALE";

          // ---- Header banner state machine (preserved) ----
          String headerText;
          Color headerColor;
          if (!hasRealData) {
            headerText = "CONNECTING • SYSTEM INITIALIZATION...";
            headerColor = Colors.orangeAccent;
          } else if (isDataDegraded) {
            headerText =
                "LIVE (DEGRADED STALE) • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = Colors.orange;
          } else {
            headerText =
                "LIVE REAL-TIME • ${regime.toUpperCase()} // ${directive.toUpperCase()}";
            headerColor = _mriColor(mri);
          }

          final double score = (healthRadar['health_rating'] ?? 10.0).toDouble();

          // ---- Cockpit values ----
          final double currentValue = (val['Total_Equity'] ?? 0.0).toDouble();
          final double impliedEdge = (val['Implied_Upside'] ?? 0.0).toDouble();
          // Triangulated intrinsic surfaced to the headline strip (valuation-forward cockpit).
          final Map<String, dynamic> valDetail0 = data['valuation_detail'] ?? {};
          final double intrinsicSh =
              (valDetail0['intrinsic'] ?? val['AGA_Intrinsic'] ?? 0.0).toDouble();
          final double intrinsicUpside =
              (valDetail0['spear_upside_pct'] ?? 0.0).toDouble();
          final double jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
          final String ratingDesc = healthRadar['rating_desc']?.toString() ??
              (score >= 7 ? "STRONG" : score >= 4 ? "GUARDED" : "STRESSED");

          return Column(
            children: [
              // 1 ── Unified header bar (brand • pulse • banner • health • tools)
              _buildHeaderBar(headerText, headerColor, isDataDegraded, score),

              // 1b ── Integrity alert strip (stale data / active forensic waivers), only when raised
              _integrityStrip(data['integrity'] ?? const {}),

              // 2 ── Chain-of-thought narrative deck (Phase 4c): one fluid vertical
              //       scroll — Macro Weather -> Forensic Shield -> Arbitrage — each
              //       section reflowing on viewport width.
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(10, 8, 10, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _verdictBar(mri, regime.toString(), intrinsicSh,
                          intrinsicUpside, score, impliedEdge),
                      _stepMacro(
                          metrics,
                          isDataDegraded,
                          mri,
                          regime.toString(),
                          directive.toString(),
                          data['macro_tape'] ?? const {},
                          data['mri_decomposition'] ?? const {}),
                      _stepForensic(forensics, data['portfolio_stats'] ?? const {},
                          healthRadar, val, mri),
                      _stepArbitrage(
                          data['valuation_detail'] ?? const {},
                          (nodes['AGA.V']?['price'] ?? 0.71).toDouble(),
                          intrinsicSh,
                          intrinsicUpside),
                      _appendix(
                          val,
                          nodes,
                          mri,
                          forensics,
                          data['portfolio_stats'] ?? const {},
                          metrics,
                          (metrics['VIX']?['value'] ?? 16.5).toDouble()),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  // ====================================================================
  //  HEADER BAR  — fuses brand, live pulse, regime banner, health, tools
  // ====================================================================
  Widget _buildHeaderBar(
      String bannerText, Color bannerColor, bool degraded, double score) {
    return Container(
      height: 46,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: const BoxDecoration(
        color: kChrome,
        border: Border(bottom: BorderSide(color: kBorder)),
      ),
      child: Row(
        children: [
          // Brand mark
          Container(
            width: 22,
            height: 22,
            decoration: BoxDecoration(
              color: kAccent,
              borderRadius: BorderRadius.circular(5),
              boxShadow: [
                BoxShadow(color: kAccent.withOpacity(0.45), blurRadius: 9)
              ],
            ),
            child: const Icon(Icons.show_chart, color: Color(0xFF04130A), size: 14),
          ),
          const SizedBox(width: 9),
          const Text(
            "COMMODITYEX",
            style: TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.5),
          ),
          const SizedBox(width: 7),
          const Text(
            "QUANT MONITOR v5.2",
            style: TextStyle(
                color: kFaint,
                fontSize: 8.5,
                fontWeight: FontWeight.bold,
                letterSpacing: 1.0,
                fontFamily: 'monospace'),
          ),
          const SizedBox(width: 12),
          ConnectionIndicator(
            error: _state.error,
            isLoading: _state.isLoading,
            isDegraded: degraded,
            pulseAnimation:
                Tween<double>(begin: 0.45, end: 1.0).animate(_pulseController),
          ),
          const SizedBox(width: 12),

          // Live regime / directive banner — still reacts to the glow engine.
          Expanded(
            child: ListenableBuilder(
              listenable: _highlightState,
              builder: (context, _) {
                final bool isGlow = _highlightState.highlightedMetricId != null;
                final Color glow = _highlightState.activeGlowColor;
                return AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  height: 28,
                  padding: const EdgeInsets.symmetric(horizontal: 9),
                  decoration: BoxDecoration(
                    color: bannerColor.withOpacity(0.06),
                    borderRadius: BorderRadius.circular(5),
                    border: Border.all(
                      color: isGlow ? glow : bannerColor.withOpacity(0.22),
                      width: isGlow ? 1.4 : 1.0,
                    ),
                    boxShadow: isGlow
                        ? [
                            BoxShadow(
                                color: glow.withOpacity(0.2),
                                blurRadius: 6,
                                spreadRadius: 1)
                          ]
                        : null,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        degraded ? Icons.warning_amber_rounded : Icons.sensors,
                        color: bannerColor,
                        size: 12,
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: Text(
                          bannerText,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: bannerColor,
                            fontSize: 9.5,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 0.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          const SizedBox(width: 12),

          // Health shield chip
          _pill(
            "HEALTH ${score.toStringAsFixed(1)}/10",
            _healthColor(score),
            icon: Icons.shield_outlined,
          ),
          const SizedBox(width: 4),

          // Tools: censor toggle + Metric Compass drawer
          _headerIcon(
            _censorSensitiveData ? Icons.visibility_off : Icons.visibility,
            'Censor portfolio values',
            () => setState(() => _censorSensitiveData = !_censorSensitiveData),
          ),
          _headerIcon(
            Icons.menu_book,
            'Open Metric Compass glossary',
            () => _scaffoldKey.currentState?.openDrawer(),
          ),
        ],
      ),
    );
  }

  // ====================================================================
  //  KPI COCKPIT STRIP — six at-a-glance hero tiles
  //  MRI + JSF are clickable glow anchors, wiring the cockpit into the
  //  dashboard-wide relationship tracing.
  // ====================================================================
  Widget _buildKpiStrip({
    required double currentValue,
    required double intrinsicSh,
    required double intrinsicUpside,
    required double mri,
    required String regime,
    required double score,
    required String ratingDesc,
    required double impliedEdge,
    required double jsf,
  }) {
    String money(double v) =>
        _censorSensitiveData ? "••••••" : "\$${v.toStringAsFixed(0)}";

    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 2),
      child: SizedBox(
        // Fixed height; tiles stretch to it. Generous enough for the tallest
        // (MRI: label + big value + sub + gauge) to never trip a RenderFlex.
        height: 86,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Prominent trio — macro regime + the two valuation anchors.
            Expanded(
              flex: 16,
              child: StatTile(
                id: "MRI",
                label: "MACRO REGIME INDEX",
                value: mri.toStringAsFixed(1),
                valueColor: _mriColor(mri),
                sub: regime.toUpperCase(),
                bar: mri / 100.0,
                barColor: _mriColor(mri),
                clickable: true,
                prominent: true,
                highlightState: _highlightState,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 15,
              child: StatTile(
                id: "Implied_Upside",
                label: "IMPLIED EDGE",
                value: "${impliedEdge.toStringAsFixed(1)}%",
                valueColor: _getEdgeColor(impliedEdge),
                sub: "INTRINSIC ARBITRAGE",
                clickable: true,
                prominent: true,
                highlightState: _highlightState,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 15,
              child: StatTile(
                id: "AGA_Intrinsic",
                label: "INTRINSIC / SH",
                value: "\$${intrinsicSh.toStringAsFixed(2)}",
                valueColor: kAccent,
                sub:
                    "${intrinsicUpside >= 0 ? '+' : ''}${intrinsicUpside.toStringAsFixed(0)}% VS PRICE",
                clickable: true,
                prominent: true,
                highlightState: _highlightState,
              ),
            ),
            const SizedBox(width: 8),
            // Secondary readouts — health, capital, forensic shield.
            Expanded(
              flex: 11,
              child: StatTile(
                id: "Health Rating",
                label: "HEALTH SHIELD",
                value: "${score.toStringAsFixed(1)}/10",
                valueColor: _healthColor(score),
                sub: ratingDesc.toUpperCase(),
                clickable: true,
                highlightState: _highlightState,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 11,
              child: StatTile(
                id: "Total_Equity",
                label: "LIQUID VALUE",
                value: money(currentValue),
                valueColor: Colors.white,
                sub: "DEPLOYABLE",
                clickable: true,
                highlightState: _highlightState,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 11,
              child: StatTile(
                id: "JSF",
                label: "JSF SHIELD",
                value: "${jsf.toStringAsFixed(1)}/4.0",
                valueColor: jsf == 4.0 ? kAccent : Colors.orangeAccent,
                sub: "SURVIVAL",
                clickable: true,
                highlightState: _highlightState,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ====================================================================
  //  WORKSPACE — responsive 3-column deck (each column scrolls on its own)
  // ====================================================================
  Widget _buildWorkspace({
    required Map<String, dynamic> data,
    required Map<String, dynamic> val,
    required Map<String, dynamic> nodes,
    required double mri,
    required Map<String, dynamic> metrics,
    required Map<String, dynamic> forensics,
    required Map<String, dynamic> healthRadar,
    required bool isDataDegraded,
  }) {
    final stats = data['portfolio_stats'] ?? {};
    final double vix = (metrics['VIX']?['value'] ?? 16.5).toDouble();

    // --- LEFT: Risk & forensics + barbell components.
    // (Macro now lives in its own full-width band above the workspace.)
    final Widget left = _scrollColumn([
      PanelCard(
        title: "FORENSIC SHIELDS & COVARIANCE",
        child: _forensicWrap(forensics, stats),
      ),
      PanelCard(
        title: "BARBELL COMPONENT DIRECTORY",
        child: _barbellGrid(nodes, vix),
      ),
    ]);

    // --- CENTER: triangulated valuation is now the centerpiece (expanded + focused) ---
    final Map<String, dynamic> valDetail = data['valuation_detail'] ?? {};
    final double agaPriceRight = (nodes['AGA.V']?['price'] ?? 0.71).toDouble();
    final Widget center = _scrollColumn([
      PanelCard(
        title: "VALUATION TRIANGULATION",
        titleColor: kAccent,
        glow: true,
        trailing: _pill("COST · MARKET · OPTION", kAccent),
        child: _valuationTriangulation(valDetail, agaPriceRight),
      ),
      PanelCard(
        title: "DETAILED MODEL VALUATION",
        child: _valuationWrap(val, nodes),
      ),
    ]);

    // --- RIGHT: Kelly sizing demoted to a collapsed panel (kept, de-emphasized) + health radar ---
    final Widget right = _scrollColumn([
      _Collapsible(
        title: "PORTFOLIO KELLY SIZING WATERFALL",
        titleColor: kAccent,
        trailing: _pill("f* = μ / σ²", kAccent),
        initiallyExpanded: false,
        child: _kellyEngine(val, mri, forensics, stats, metrics, nodes),
      ),
      _buildHealthRadar(healthRadar),
    ]);

    return LayoutBuilder(
      builder: (context, constraints) {
        final Widget row = Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: 25, child: left),
            const SizedBox(width: 8),
            Expanded(flex: 46, child: center),
            const SizedBox(width: 8),
            Expanded(flex: 29, child: right),
          ],
        );

        if (constraints.maxWidth < _deckMinWidth) {
          // Preserve density on narrow viewports via horizontal scroll.
          return SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: SizedBox(
              width: _deckMinWidth,
              height: constraints.maxHeight,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(10, 4, 10, 0),
                child: row,
              ),
            ),
          );
        }

        return Padding(
          padding: const EdgeInsets.fromLTRB(10, 4, 10, 0),
          child: row,
        );
      },
    );
  }

  /// A vertically-scrolling column of stacked cards. Each card carries its
  /// own bottom margin, so spacing is automatic and overflow is impossible.
  Widget _scrollColumn(List<Widget> cards) {
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: cards,
      ),
    );
  }

  // ====================================================================
  //  PHASE 4c — FLUID, CHAIN-OF-THOUGHT NARRATIVE DECK
  //  Macro Weather -> Forensic Shield -> Arbitrage, each reflowing on width.
  // ====================================================================

  /// Width-driven reflow: lays children into 1..n equal columns by viewport
  /// width (no horizontal scroll, no fixed grid). The single replacement for
  /// the old rigid Row/Column workspace.
  Widget _reflow(List<Widget> children, {double minWidth = 300, double gap = 10}) {
    if (children.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(builder: (context, c) {
      int cols = (c.maxWidth / minWidth).floor();
      if (cols < 1) cols = 1;
      if (cols > children.length) cols = children.length;
      final double w = (c.maxWidth - gap * (cols - 1)) / cols;
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [
          for (final child in children) SizedBox(width: w, child: child),
        ],
      );
    });
  }

  /// A numbered narrative step: index chip + question header + one-line
  /// verdict, divider, then the reflowing body. No animation.
  Widget _step(String idx, String question, Widget verdict, Widget body) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        color: kPanel,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: kBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                    color: kAccent.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(4)),
                child: Text(idx,
                    style: const TextStyle(
                        color: kAccent,
                        fontSize: 10,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'monospace')),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(question,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.3)),
              ),
              const SizedBox(width: 8),
              verdict,
            ],
          ),
          const SizedBox(height: 10),
          Container(height: 1, color: kBorder),
          const SizedBox(height: 12),
          body,
        ],
      ),
    );
  }

  Widget _verdictChip(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
          color: kPanelHi,
          borderRadius: BorderRadius.circular(5),
          border: Border.all(color: kBorder)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Text("$label ",
            style: const TextStyle(
                color: kFaint, fontSize: 8.5, fontWeight: FontWeight.bold)),
        Text(value,
            style: TextStyle(
                color: color,
                fontSize: 10,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace')),
      ]),
    );
  }

  /// One-line answer strip — the cockpit verdict, reflow-safe via Wrap.
  Widget _verdictBar(double mri, String regime, double intrinsicSh,
      double intrinsicUpside, double score, double impliedEdge) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        _verdictChip(
            "REGIME", "${regime.toUpperCase()} · ${mri.toStringAsFixed(1)}", _mriColor(mri)),
        _verdictChip(
            "INTRINSIC",
            "\$${intrinsicSh.toStringAsFixed(2)} (${intrinsicUpside >= 0 ? '+' : ''}${intrinsicUpside.toStringAsFixed(0)}%)",
            kAccent),
        _verdictChip("EDGE", "${impliedEdge.toStringAsFixed(1)}%",
            _getEdgeColor(impliedEdge)),
        _verdictChip("HEALTH", "${score.toStringAsFixed(1)}/10", _healthColor(score)),
      ]),
    );
  }

  Widget _lensRow(String label, String value, Color color, {String? sub}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Expanded(
            child: Text(label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    color: kDim, fontSize: 9, fontFamily: 'monospace'))),
        Text(value,
            style: TextStyle(
                color: color,
                fontSize: 10.5,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace')),
        if (sub != null) ...[
          const SizedBox(width: 6),
          Text(sub,
              style: const TextStyle(
                  color: kFaint, fontSize: 8, fontFamily: 'monospace')),
        ],
      ]),
    );
  }

  Widget _macroLensCard(String title, List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
          color: kPanelHi,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: kBorder)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(title,
              style: const TextStyle(
                  color: kFaint,
                  fontSize: 8,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 0.6,
                  fontFamily: 'monospace')),
          const SizedBox(height: 8),
          ...children,
        ],
      ),
    );
  }

  Widget _decompRow(Map<String, dynamic> b, Color c) {
    final String name = (b['name'] ?? '').toString();
    final double sc = (b['score'] ?? 0.0).toDouble();
    final double contrib = (b['contribution'] ?? 0.0).toDouble();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2.5),
      child: Row(children: [
        SizedBox(
            width: 104,
            child: Text(name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    color: kDim, fontSize: 8.5, fontFamily: 'monospace'))),
        Expanded(child: _miniBar((sc / 100.0).clamp(0.0, 1.0), c)),
        const SizedBox(width: 8),
        SizedBox(
            width: 30,
            child: Text(contrib.toStringAsFixed(1),
                textAlign: TextAlign.right,
                style: TextStyle(
                    color: c,
                    fontSize: 9,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace'))),
      ]),
    );
  }

  /// Width-flexible regime hero (replaces the fixed-width _regimeDial): MRI
  /// readout on the left, full MRI decomposition on the right.
  Widget _regimeHero(double mri, String regime, String directive,
      Map<String, dynamic> mriDecomp) {
    final List blocks = (mriDecomp['blocks'] as List?) ?? const [];
    final Color c = _mriColor(mri);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
          color: kPanelHi,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: kBorder)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          width: 156,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text("MACRO REGIME INDEX",
                style: TextStyle(
                    color: kFaint,
                    fontSize: 8,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.6)),
            const SizedBox(height: 4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
                Text(mri.toStringAsFixed(1),
                    style: TextStyle(
                        color: c,
                        fontSize: 32,
                        height: 1.0,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'monospace')),
                const SizedBox(width: 4),
                const Text("/100",
                    style: TextStyle(
                        color: kFaint, fontSize: 10, fontFamily: 'monospace')),
              ],
            ),
            const SizedBox(height: 6),
            _miniBar(mri / 100.0, c),
            const SizedBox(height: 8),
            Text(regime.toUpperCase(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    color: c, fontSize: 10, fontWeight: FontWeight.bold)),
            const SizedBox(height: 2),
            Text(directive,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: kDim, fontSize: 8.5, height: 1.25)),
          ]),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final b in blocks)
                _decompRow(Map<String, dynamic>.from(b as Map), c),
            ],
          ),
        ),
      ]),
    );
  }

  // ---- STEP 1: Macro Weather ----
  Widget _stepMacro(
      Map<String, dynamic> metrics,
      bool isFallback,
      double mri,
      String regime,
      String directive,
      Map<String, dynamic> macroTape,
      Map<String, dynamic> mriDecomp) {
    double mv(String k, [double d = 0.0]) =>
        (metrics[k]?['value'] ?? d).toDouble();
    Map<String, dynamic>? sig(String key) {
      for (final s in (macroTape['signals'] as List?) ?? const []) {
        if (s is Map && s['key'] == key) return Map<String, dynamic>.from(s);
      }
      return null;
    }

    Color biasColor(String? b) => b == 'risk_off'
        ? const Color(0xFFFF5252)
        : (b == 'risk_on' ? kAccent : Colors.white);
    String contracts(double v) => v.abs() >= 1000
        ? "${(v / 1000).toStringAsFixed(0)}k"
        : v.toStringAsFixed(0);

    final double ag = mv('Spot_Ag');
    final double gsr = mv('GSR', 80.0);
    final double gold = (ag > 0 && gsr > 0) ? ag * gsr : 0.0;
    final double real10 = mv('Real_10Y', mv('real_yield_10y'));
    final double copperGold = mv('Copper_Gold');
    final double usdCad = mv('USDCAD=X');
    final Map<String, dynamic>? vt = sig('vix_term');

    final Widget yieldLens = _macroLensCard("YIELD & LIQUIDITY CURVE", [
      _YieldCurveMini(
          y10: mv('10Y'),
          y30: mv('30Y'),
          real10: real10 != 0.0 ? real10 : mv('10Y') - 1.5,
          color: _mriColor(mri)),
      const SizedBox(height: 8),
      _lensRow("10Y UST", "${mv('10Y').toStringAsFixed(2)}%",
          _getMetricColor('10Y', mv('10Y'))),
      _lensRow("30Y UST", "${mv('30Y').toStringAsFixed(2)}%",
          _getMetricColor('30Y', mv('30Y'))),
      if (real10 != 0.0)
        _lensRow("Real 10Y", "${real10.toStringAsFixed(2)}%",
            real10 < 1.0 ? kAccent : Colors.orangeAccent),
      _lensRow("SOFR Spread", "${mv('TED').toStringAsFixed(2)}%",
          _getMetricColor('TED', mv('TED')),
          sub: "funding"),
    ]);
    final Widget riskLens = _macroLensCard("RISK APPETITE", [
      _lensRow("VIX", mv('VIX').toStringAsFixed(1),
          _getMetricColor('VIX', mv('VIX'))),
      if (vt != null)
        _lensRow("VIX Term 3M/1M", vt['display'].toString(),
            biasColor(vt['bias']?.toString())),
      _lensRow("HY Credit OAS", "${mv('Spreads').toStringAsFixed(2)}%",
          _getMetricColor('Spreads', mv('Spreads'))),
      _lensRow("DXY", mv('DXY').toStringAsFixed(1),
          _getMetricColor('DXY', mv('DXY'))),
    ]);
    final Widget realLens = _macroLensCard("REAL ASSETS & FLOWS", [
      _lensRow("Silver", "\$${ag.toStringAsFixed(2)}",
          _getMetricColor('Spot_Ag', ag)),
      if (gold > 0)
        _lensRow("Gold (deriv)", "\$${gold.toStringAsFixed(0)}", Colors.white70),
      _lensRow("Gold / Silver", gsr.toStringAsFixed(1),
          _getMetricColor('GSR', gsr)),
      if (copperGold > 0)
        _lensRow("Copper / Gold", copperGold.toStringAsFixed(3), Colors.white70),
      _lensRow("WTI Crude", "\$${mv('WTI').toStringAsFixed(2)}",
          _getMetricColor('WTI', mv('WTI'))),
      _lensRow("CFTC Ag Net",
          "${contracts(mv('CFTC_Silver_Net_Longs', 35000))} c", Colors.white70),
    ]);

    final List<Widget> allTiles = [
      _macroTile("10Y UST", "${mv('10Y').toStringAsFixed(2)}%", "NOMINAL",
          _getMetricColor('10Y', mv('10Y')), "10Y", isFallback, rate: true),
      _macroTile("30Y UST", "${mv('30Y').toStringAsFixed(2)}%", "LONG BOND",
          _getMetricColor('30Y', mv('30Y')), "30Y", isFallback, rate: true),
      _macroTile("SOFR SPREAD", "${mv('TED').toStringAsFixed(2)}%",
          "FUNDING STRESS", _getMetricColor('TED', mv('TED')), "TED", isFallback,
          rate: true),
      if (real10 != 0.0)
        _macroTile("REAL 10Y", "${real10.toStringAsFixed(2)}%", "TIPS YIELD",
            real10 < 1.0 ? kAccent : Colors.orangeAccent, "Real_10Y",
            isFallback),
      _macroTile("DXY", mv('DXY').toStringAsFixed(1), "USD INDEX",
          _getMetricColor('DXY', mv('DXY')), "DXY", isFallback),
      _macroTile("HY CREDIT", "${mv('Spreads').toStringAsFixed(2)}%",
          "OAS SPREAD", _getMetricColor('Spreads', mv('Spreads')), "Spreads",
          isFallback),
      _macroTile("VIX", mv('VIX').toStringAsFixed(1), "EQUITY VOL",
          _getMetricColor('VIX', mv('VIX')), "VIX", isFallback),
      _macroTile("SILVER", "\$${mv('Spot_Ag').toStringAsFixed(2)}", "USD / OZ",
          _getMetricColor('Spot_Ag', mv('Spot_Ag')), "Spot_Ag", isFallback),
      if (gold > 0)
        _macroTile("GOLD", "\$${gold.toStringAsFixed(0)}", "USD / OZ · DERIV",
            Colors.white, "GSR", isFallback),
      _macroTile("GOLD / SILVER", gsr.toStringAsFixed(1), "GSR CROSS",
          _getMetricColor('GSR', gsr), "GSR", isFallback),
      if (copperGold > 0)
        _macroTile("COPPER / GOLD", copperGold.toStringAsFixed(3),
            "GROWTH PULSE", Colors.white, "Copper_Gold", isFallback),
      if (vt != null)
        _macroTile("VIX TERM 3M/1M", vt['display'].toString(),
            (vt['read'] ?? 'TERM STRUCT').toString().toUpperCase(),
            biasColor(vt['bias']?.toString()), "VIX", isFallback),
      _macroTile("WTI CRUDE", "\$${mv('WTI').toStringAsFixed(2)}", "USD / BBL",
          _getMetricColor('WTI', mv('WTI')), "WTI", isFallback),
      _macroTile(
          "CFTC AG",
          "${contracts(mv('CFTC_Silver_Net_Longs', 35000))} c",
          "MGD MONEY NET",
          Colors.white,
          "CFTC_Silver_Net_Longs",
          isFallback),
      if (usdCad > 0)
        _macroTile("USD / CAD", usdCad.toStringAsFixed(3), "FX RATE",
            Colors.white, "USDCAD=X", isFallback),
    ];

    return _step(
      "01",
      "IS THE MACRO REGIME SAFE?",
      _pill(regime.toUpperCase(), _mriColor(mri)),
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _regimeHero(mri, regime, directive, mriDecomp),
        const SizedBox(height: 10),
        _reflow([yieldLens, riskLens, realLens], minWidth: 230),
        const SizedBox(height: 10),
        _Collapsible(
          initiallyExpanded: false,
          title: "ALL CROSS-ASSET INDICATORS",
          child: Wrap(spacing: 8, runSpacing: 8, children: allTiles),
        ),
      ]),
    );
  }

  // ---- STEP 2: Forensic Shield ----
  Widget _stepForensic(Map<String, dynamic> forensics,
      Map<String, dynamic> stats, Map<String, dynamic> healthRadar,
      Map<String, dynamic> val, double mri) {
    final double jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final double sloanCfo = (forensics['sloan_cfo'] ?? 0.0).toDouble();
    final double sloanBs = (forensics['sloan_bs'] ?? 0.0).toDouble();
    final double es95 = (stats['expected_shortfall_95'] ?? 0.0).toDouble();
    final double avgCorr = (stats['avg_correlation'] ?? 0.0).toDouble();
    final Map<String, dynamic> vols = stats['vols'] ?? const <String, dynamic>{};
    final double spearVol = (vols['AGA.V'] ?? 0.45).toDouble();
    final double impliedEdge = (val['Implied_Upside'] ?? 0.0).toDouble();
    final double score = (healthRadar['health_rating'] ?? 10.0).toDouble();
    final Color hc = _healthColor(score);

    final double axValue = (impliedEdge / 80.0).clamp(0.0, 1.0);
    final double axForensic = (jsf / 4.0).clamp(0.0, 1.0);
    final double axMacro = ((100.0 - mri) / 100.0).clamp(0.0, 1.0);
    final double axTail = (1.0 - es95.abs() / 12.0).clamp(0.0, 1.0);

    final Widget snowflakeCard = _macroLensCard("HEALTH SNOWFLAKE", [
      Center(
        child: SizedBox(
          width: 168,
          height: 168,
          child: _HealthSnowflake(
              value: axValue,
              forensics: axForensic,
              macro: axMacro,
              tail: axTail,
              score: score,
              color: hc),
        ),
      ),
    ]);
    final Widget signalsCard = _macroLensCard("FORENSIC SIGNALS", [
      _lensRow("JSF Shield", "${jsf.toStringAsFixed(1)} / 4.0",
          jsf == 4.0 ? kAccent : Colors.orangeAccent),
      _lensRow("Expected Shortfall 95", "${es95.toStringAsFixed(2)}%",
          Colors.orangeAccent),
      _lensRow("Spear Vol (AGA)", "${(spearVol * 100).toStringAsFixed(0)}%",
          Colors.white70),
      _lensRow("Sloan CFO Accruals", sloanCfo.toStringAsFixed(4),
          sloanCfo < 0.05 ? kAccent : Colors.redAccent),
      _lensRow("Sloan BS Accruals", sloanBs.toStringAsFixed(4),
          sloanBs < 0.05 ? kAccent : Colors.redAccent),
      _lensRow("Barbell Diversification", avgCorr.toStringAsFixed(2),
          Colors.white70),
    ]);

    return _step(
      "02",
      "IS THE ASSET STRUCTURALLY SOUND?",
      _pill(score >= 7 ? "SOUND" : (score >= 4 ? "GUARDED" : "FRAGILE"), hc),
      _reflow([snowflakeCard, signalsCard, _buildHealthRadar(healthRadar)],
          minWidth: 270),
    );
  }

  // ---- STEP 3: Arbitrage ----
  Widget _stepArbitrage(Map<String, dynamic> valDetail, double agaPrice,
      double intrinsicSh, double intrinsicUpside) {
    final Color up =
        intrinsicUpside >= 0 ? kAccent : const Color(0xFFFF5252);
    return _step(
      "03",
      "WHAT'S THE MARGIN OF SAFETY?",
      _pill(
          "\$${intrinsicSh.toStringAsFixed(2)} · ${intrinsicUpside >= 0 ? '+' : ''}${intrinsicUpside.toStringAsFixed(0)}%",
          up),
      _valuationTriangulation(valDetail, agaPrice),
    );
  }

  /// Contribution bridge: REP Floor (cost) -> + Market (incl. option π
  /// sub-segment) -> = Intrinsic, with the live price as a marker line.
  /// Plots weight x leg (contributions), which sum to intrinsic — an honest
  /// bridge for a confidence-weighted blend (not raw additive legs).
  Widget _valuationBridge({
    required double costContrib,
    required double mktContrib,
    required double incContrib,
    required double piShare,
    required double intrinsic,
    required double price,
  }) {
    const Color costColor = Color(0xFF42A5F5);
    const Color marketColor = kAccent;
    const Color incomeColor = Color(0xFFFFB74D);
    final double total = costContrib + mktContrib + incContrib;
    final double domain =
        [intrinsic, price, total].reduce((a, b) => a > b ? a : b) * 1.12;
    final double d = domain <= 1e-9 ? 1.0 : domain;

    Widget track(String label, double start, double len, Color color,
        String amount,
        {double subFromEnd = 0.0, Color? subColor}) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          SizedBox(
              width: 88,
              child: Text(label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 9,
                      fontFamily: 'monospace'))),
          Expanded(child: LayoutBuilder(builder: (ctx, c) {
            final double w = c.maxWidth;
            double fx(double v) => (v / d).clamp(0.0, 1.0) * w;
            return SizedBox(
              height: 14,
              child: Stack(children: [
                Positioned(
                    left: 0,
                    right: 0,
                    top: 6,
                    child: Container(height: 2, color: const Color(0xFF1A1A1F))),
                Positioned(
                    left: fx(start),
                    top: 2,
                    child: Container(
                        height: 10,
                        width: (fx(start + len) - fx(start)).clamp(0.0, w),
                        decoration: BoxDecoration(
                            color: color,
                            borderRadius: BorderRadius.circular(2)))),
                if (subFromEnd > 0 && subColor != null)
                  Positioned(
                      left: fx(start + len - subFromEnd),
                      top: 2,
                      child: Container(
                          height: 10,
                          width: (fx(start + len) - fx(start + len - subFromEnd))
                              .clamp(0.0, w),
                          decoration: BoxDecoration(
                              color: subColor,
                              borderRadius: BorderRadius.circular(2)))),
                Positioned(
                    left: (fx(price) - 1).clamp(0.0, w),
                    top: 0,
                    child: Container(height: 14, width: 1.5, color: Colors.white)),
              ]),
            );
          })),
          const SizedBox(width: 6),
          SizedBox(
              width: 54,
              child: Text(amount,
                  textAlign: TextAlign.right,
                  style: TextStyle(
                      color: color,
                      fontSize: 9,
                      fontWeight: FontWeight.bold,
                      fontFamily: 'monospace'))),
        ]),
      );
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      track("REP Floor", 0, costContrib, costColor,
          "\$${costContrib.toStringAsFixed(2)}"),
      track("+ Market", costContrib, mktContrib, marketColor,
          "+\$${mktContrib.toStringAsFixed(2)}",
          subFromEnd: piShare, subColor: incomeColor),
      if (incContrib > 0.001)
        track("+ Income", costContrib + mktContrib, incContrib, incomeColor,
            "+\$${incContrib.toStringAsFixed(2)}"),
      track("= Intrinsic", 0, total, marketColor.withOpacity(0.85),
          "\$${intrinsic.toStringAsFixed(2)}"),
      Padding(
        padding: const EdgeInsets.only(top: 5, left: 88),
        child: Row(children: [
          _bridgeLegend(costColor, "Cost"),
          const SizedBox(width: 10),
          _bridgeLegend(marketColor, "Market"),
          const SizedBox(width: 10),
          _bridgeLegend(incomeColor, "Option π"),
          const Spacer(),
          Text("price \$${price.toStringAsFixed(2)}",
              style: const TextStyle(
                  color: Colors.white, fontSize: 8, fontFamily: 'monospace')),
        ]),
      ),
    ]);
  }

  Widget _bridgeLegend(Color c, String label) {
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
          width: 8,
          height: 8,
          decoration:
              BoxDecoration(color: c, borderRadius: BorderRadius.circular(2))),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: kFaint, fontSize: 8)),
    ]);
  }

  // ---- APPENDIX: reference + the sidelined sizing engine ----
  Widget _appendix(
      Map<String, dynamic> val,
      Map<String, dynamic> nodes,
      double mri,
      Map<String, dynamic> forensics,
      Map<String, dynamic> stats,
      Map<String, dynamic> metrics,
      double vix) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PanelCard(
        title: "BARBELL COMPONENT DIRECTORY",
        child: _barbellGrid(nodes, vix),
      ),
      _Collapsible(
        initiallyExpanded: false,
        title: "DETAILED MODEL VALUATION",
        child: _valuationWrap(val, nodes),
      ),
      _Collapsible(
        initiallyExpanded: false,
        titleColor: kDim,
        trailing: _pill("f* = μ / σ²", kDim),
        title: "POSITION SIZING — SIDELINED (MACRO-ASYMMETRY MODE)",
        child: _kellyEngine(val, mri, forensics, stats, metrics, nodes),
      ),
    ]);
  }

  // ====================================================================
  //  LEFT COLUMN CONTENT
  // ====================================================================
  Widget _forensicWrap(Map<String, dynamic> forensics, Map<String, dynamic> stats) {
    final jsf = (forensics['jsf_score'] ?? 4.0).toDouble();
    final sloanCfo = (forensics['sloan_cfo'] ?? 0.0).toDouble();
    final sloanBs = (forensics['sloan_bs'] ?? 0.0).toDouble();
    final es95 = (stats['expected_shortfall_95'] ?? 0.0).toDouble();
    final avgCorr = (stats['avg_correlation'] ?? 0.0).toDouble();
    final Map<String, dynamic> vols = stats['vols'] ?? {};
    final spearVol = (vols['AGA.V'] ?? 0.45).toDouble();

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        MetricCard(
          id: "JSF",
          label: "JSF SHIELD SCORE",
          value: "${jsf.toStringAsFixed(1)} / 4.0",
          color: jsf == 4.0 ? kAccent : Colors.orangeAccent,
          highlightState: _highlightState,
        ),
        MetricCard(
          id: "ES95",
          label: "EXPECTED SHORTFALL",
          value: "${es95.toStringAsFixed(2)}%",
          color: Colors.orangeAccent,
          highlightState: _highlightState,
        ),
        MetricCard(
          id: "Spear Volatility",
          label: "SPEAR VOL (AGA)",
          value: "${(spearVol * 100).toStringAsFixed(0)}%",
          color: Colors.white70,
          highlightState: _highlightState,
        ),
        MetricCard(
          id: "Sloan CFO",
          label: "SLOAN CFO ACCRUALS",
          value: sloanCfo.toStringAsFixed(4),
          color: sloanCfo < 0.05 ? kAccent : Colors.redAccent,
          highlightState: _highlightState,
        ),
        MetricCard(
          id: "Sloan BS",
          label: "SLOAN BS ACCRUALS",
          value: sloanBs.toStringAsFixed(4),
          color: sloanBs < 0.05 ? kAccent : Colors.redAccent,
          highlightState: _highlightState,
        ),
        MetricCard(
          id: "Diversification Correlation",
          label: "BARBELL DIVERSIF",
          value: avgCorr.toStringAsFixed(2),
          color: Colors.white70,
          highlightState: _highlightState,
        ),
      ],
    );
  }

  // Barbell directory as a responsive 2-up grid. Each tile lives in an
  // Expanded cell, so it can never overflow the column horizontally, and all
  // text ellipsizes — fixing the prior cramping.
  Widget _barbellGrid(Map<String, dynamic> nodes, double vix) {
    final entries = nodes.entries.toList();
    final List<Widget> rows = [];
    for (int i = 0; i < entries.length; i += 2) {
      // NB: no vertical `stretch` here — this grid lives inside a vertical
      // scroll (unbounded height), and stretch would force an infinite height.
      // The two tiles share an identical structure, so they render equal height.
      rows.add(Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: _barbellTile(entries[i], vix)),
          const SizedBox(width: 8),
          Expanded(
            child: (i + 1 < entries.length)
                ? _barbellTile(entries[i + 1], vix)
                : const SizedBox.shrink(),
          ),
        ],
      ));
      if (i + 2 < entries.length) rows.add(const SizedBox(height: 8));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }

  Widget _barbellTile(MapEntry<String, dynamic> e, double vix) {
    final bool isSpear = e.value['role'] == 'The Spear';
    final bool stressed = isSpear && vix > 23.0;
    return Tooltip(
      message: isSpear
          ? "The Spear (60% allocation)\nHigh-conviction silver explorer torque engine."
          : "Ballast (40% allocation)\nStable cash-generating royalty ballast.",
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
        decoration: BoxDecoration(
          color: kPanelHi,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: stressed ? Colors.redAccent : kBorder,
            width: 1.0,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(e.key,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 10,
                          color: Colors.white)),
                ),
                Container(
                  width: 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: isSpear ? kAccent : kDim,
                    shape: BoxShape.circle,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text("\$${e.value['price']}",
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.bold,
                      fontFamily: 'monospace',
                      color: Colors.white)),
            ),
            const SizedBox(height: 2),
            Text(e.value['role'].toString(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    color: isSpear ? kAccent : kDim,
                    fontSize: 7.5,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.3)),
          ],
        ),
      ),
    );
  }

  // ====================================================================
  //  MACRO BAND — full-width, prominent cross-asset cockpit.
  //  A regime dial anchors the left; a breathable Wrap of indicator tiles
  //  fills the rest. The Wrap reflows (never overflows) and every fixed-width
  //  tile ellipsizes — so this richer tape is structurally overflow-proof.
  // ====================================================================
  Widget _macroBand(Map<String, dynamic> metrics, bool isFallback, double mri,
      String regime, String directive,
      [Map<String, dynamic> macroTape = const {},
      Map<String, dynamic> mriDecomp = const {}]) {
    double mv(String k, [double d = 0.0]) =>
        (metrics[k]?['value'] ?? d).toDouble();

    // Locate a Fluid Macro Tape signal by key (value + bias + one-line read).
    Map<String, dynamic>? sig(String key) {
      for (final s in (macroTape['signals'] as List?) ?? const []) {
        if (s is Map && s['key'] == key) return Map<String, dynamic>.from(s);
      }
      return null;
    }

    Color biasColor(String? b) => b == 'risk_off'
        ? const Color(0xFFFF5252)
        : (b == 'risk_on' ? kAccent : Colors.white);

    final Map<String, dynamic>? vtSig = sig('vix_term');

    final String tilt = (macroTape['net_tilt'] ?? '').toString();
    final Color tiltColor = tilt == 'RISK-OFF'
        ? const Color(0xFFFF5252)
        : (tilt == 'RISK-ON' ? kAccent : kDim);

    String contracts(double v) => v.abs() >= 1000
        ? "${(v / 1000).toStringAsFixed(0)}k"
        : v.toStringAsFixed(0);

    // Derived / optional cross-asset reads (rendered only when sourced).
    final double ag = mv('Spot_Ag');
    final double gsr = mv('GSR', 80.0);
    final double gold = (ag > 0 && gsr > 0) ? ag * gsr : 0.0;
    final double real10 = mv('Real_10Y', mv('real_yield_10y'));
    final double copperGold = mv('Copper_Gold');
    final double usdCad = mv('USDCAD=X');

    final List<Widget> tiles = [
      _macroTile("10Y UST", "${mv('10Y').toStringAsFixed(2)}%", "NOMINAL",
          _getMetricColor('10Y', mv('10Y')), "10Y", isFallback, rate: true),
      _macroTile("30Y UST", "${mv('30Y').toStringAsFixed(2)}%", "LONG BOND",
          _getMetricColor('30Y', mv('30Y')), "30Y", isFallback, rate: true),
      _macroTile("SOFR SPREAD", "${mv('TED').toStringAsFixed(2)}%",
          "FUNDING STRESS", _getMetricColor('TED', mv('TED')), "TED", isFallback,
          rate: true),
      if (real10 != 0.0)
        _macroTile("REAL 10Y", "${real10.toStringAsFixed(2)}%", "TIPS YIELD",
            real10 < 1.0 ? kAccent : Colors.orangeAccent, "Real_10Y",
            isFallback),
      _macroTile("DXY", mv('DXY').toStringAsFixed(1), "USD INDEX",
          _getMetricColor('DXY', mv('DXY')), "DXY", isFallback),
      _macroTile("HY CREDIT", "${mv('Spreads').toStringAsFixed(2)}%",
          "OAS SPREAD", _getMetricColor('Spreads', mv('Spreads')), "Spreads",
          isFallback),
      _macroTile("VIX", mv('VIX').toStringAsFixed(1), "EQUITY VOL",
          _getMetricColor('VIX', mv('VIX')), "VIX", isFallback),
      _macroTile("SILVER", "\$${mv('Spot_Ag').toStringAsFixed(2)}", "USD / OZ",
          _getMetricColor('Spot_Ag', mv('Spot_Ag')), "Spot_Ag", isFallback),
      if (gold > 0)
        _macroTile("GOLD", "\$${gold.toStringAsFixed(0)}", "USD / OZ · DERIV",
            Colors.white, "GSR", isFallback),
      _macroTile("GOLD / SILVER", gsr.toStringAsFixed(1), "GSR CROSS",
          _getMetricColor('GSR', gsr), "GSR", isFallback),
      if (copperGold > 0)
        _macroTile("COPPER / GOLD", copperGold.toStringAsFixed(3),
            "GROWTH PULSE", Colors.white, "Copper_Gold", isFallback),
      if (vtSig != null)
        _macroTile("VIX TERM 3M/1M", vtSig['display'].toString(),
            (vtSig['read'] ?? 'TERM STRUCT').toString().toUpperCase(),
            biasColor(vtSig['bias']?.toString()), "VIX", isFallback),
      _macroTile("WTI CRUDE", "\$${mv('WTI').toStringAsFixed(2)}", "USD / BBL",
          _getMetricColor('WTI', mv('WTI')), "WTI", isFallback),
      _macroTile(
          "CFTC AG",
          "${contracts(mv('CFTC_Silver_Net_Longs', 35000))} c",
          "MGD MONEY NET",
          Colors.white,
          "CFTC_Silver_Net_Longs",
          isFallback),
      if (usdCad > 0)
        _macroTile("USD / CAD", usdCad.toStringAsFixed(3), "FX RATE",
            Colors.white, "USDCAD=X", isFallback),
    ];

    return PanelCard(
      title: "MACRO REGIME & CROSS-ASSET TAPE",
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (tilt.isNotEmpty) ...[
            _pill(tilt, tiltColor),
            const SizedBox(width: 6),
          ],
          _pill(regime.toUpperCase(), _mriColor(mri)),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _regimeDial(mri, regime, directive, mriDecomp),
          const SizedBox(width: 14),
          Expanded(
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: tiles,
            ),
          ),
        ],
      ),
    );
  }

  // Prominent regime dial anchoring the macro band; clickable MRI glow.
  Widget _regimeDial(double mri, String regime, String directive,
      [Map<String, dynamic> mriDecomp = const {}]) {
    final List blocks = (mriDecomp['blocks'] as List?) ?? const [];
    return ListenableBuilder(
      listenable: _highlightState,
      builder: (context, _) {
        final bool isGlow = _highlightState.isHighlighted('MRI');
        final Color c = _mriColor(mri);
        return GestureDetector(
          onTap: () => _highlightState.toggleHighlight('MRI'),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 232,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: kPanelHi,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                  color: isGlow ? kAccent : kBorder, width: isGlow ? 1.4 : 1.0),
              boxShadow: isGlow
                  ? [BoxShadow(color: kAccent.withOpacity(0.18), blurRadius: 8)]
                  : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text("MACRO REGIME INDEX",
                    style: TextStyle(
                        color: kFaint,
                        fontSize: 8,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.6)),
                const SizedBox(height: 5),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(mri.toStringAsFixed(1),
                        style: TextStyle(
                            color: c,
                            fontSize: 30,
                            height: 1.0,
                            fontWeight: FontWeight.w800,
                            fontFamily: 'monospace')),
                    const SizedBox(width: 4),
                    const Text("/100",
                        style: TextStyle(
                            color: kFaint,
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            fontFamily: 'monospace')),
                  ],
                ),
                const SizedBox(height: 7),
                _miniBar(mri / 100.0, c),
                const SizedBox(height: 8),
                Text(regime.toUpperCase(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        color: c,
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.4)),
                const SizedBox(height: 2),
                Text(directive,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: kDim, fontSize: 8.5, height: 1.25)),
                if (blocks.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  ...blocks.take(5).map((b) {
                    final double contrib =
                        (b is Map ? (b['contribution'] ?? 0.0) : 0.0).toDouble();
                    final String name =
                        (b is Map ? (b['name'] ?? '') : '').toString();
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Row(
                        children: [
                          SizedBox(
                            width: 70,
                            child: Text(name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    color: kFaint, fontSize: 7)),
                          ),
                          const SizedBox(width: 5),
                          Expanded(
                              child:
                                  _miniBar((contrib / 30.0).clamp(0.0, 1.0), c)),
                          const SizedBox(width: 5),
                          Text(contrib.toStringAsFixed(1),
                              style: TextStyle(
                                  color: c,
                                  fontSize: 7,
                                  fontWeight: FontWeight.bold,
                                  fontFamily: 'monospace')),
                        ],
                      ),
                    );
                  }),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  // A single fixed-width macro indicator tile (overflow-proof: all text
  // ellipsizes and the headline value scales down to fit).
  Widget _macroTile(String label, String value, String sub, Color color,
      String metricId, bool isFallback,
      {bool rate = false}) {
    return ListenableBuilder(
      listenable: _highlightState,
      builder: (context, _) {
        final bool isOn = _highlightState.isHighlighted(metricId);
        final Color glow = _highlightState.activeGlowColor;
        return GestureDetector(
          onTap: () => _highlightState.toggleHighlight(metricId),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 132,
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
            decoration: BoxDecoration(
              color: kPanelHi,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                  color: isOn ? glow : kBorder, width: isOn ? 1.4 : 1.0),
              boxShadow: isOn
                  ? [BoxShadow(color: glow.withOpacity(0.18), blurRadius: 6)]
                  : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: kDim,
                              fontSize: 8,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 0.3,
                              fontFamily: 'monospace')),
                    ),
                    if (rate) ...[
                      const SizedBox(width: 4),
                      Text(isFallback ? "YF" : "FR",
                          style: TextStyle(
                              color:
                                  (isFallback ? Colors.orangeAccent : kAccent)
                                      .withOpacity(0.6),
                              fontSize: 6.5,
                              fontWeight: FontWeight.bold,
                              fontFamily: 'monospace')),
                    ],
                  ],
                ),
                const SizedBox(height: 3),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(value,
                      style: TextStyle(
                          color: isOn ? glow : color,
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          fontFamily: 'monospace')),
                ),
                const SizedBox(height: 1),
                Text(sub,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: kFaint,
                        fontSize: 7,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.3)),
              ],
            ),
          ),
        );
      },
    );
  }

  // ====================================================================
  //  RIGHT COLUMN CONTENT
  // ====================================================================
  Widget _valuationWrap(Map<String, dynamic> val, Map<String, dynamic> nodes) {
    final double agaPrice = (nodes['AGA.V']?['price'] ?? 0.71).toDouble();
    final agaIntrinsic = (val['AGA_Intrinsic'] ?? 0.0).toDouble();
    final isIai = (val['IS_IAI_Per_Share'] ?? 0.0).toDouble();
    final expPremium = (val['Exp_Premium_Per_Share'] ?? 0.0).toDouble();
    final ppi = (val['PPI'] ?? 0.0).toDouble();
    final evBlended = (val['EV_Blended'] ?? 0.0).toDouble();
    final probability = (val['Probability'] ?? 0.65).toDouble();
    final forensicPenalty = (val['Forensic_Penalty'] ?? 1.0).toDouble();
    final rov = (val['ROV'] ?? 1.18).toDouble();
    final advCapPct =
        (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();

    Color advCapColor = kAccent;
    if (advCapPct < 5.0) {
      advCapColor = Colors.redAccent;
    } else if (advCapPct < 10.0) {
      advCapColor = Colors.orangeAccent;
    }

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        MetricCard(
            id: "AGA.V Intrinsic",
            label: "AGA INTRINSIC",
            value: "\$${agaIntrinsic.toStringAsFixed(3)}",
            color: _getValuationColor(agaIntrinsic, agaPrice),
            highlightState: _highlightState),
        MetricCard(
            id: "IS-IAI",
            label: "IS-IAI / SHARE",
            value: "\$${isIai.toStringAsFixed(3)}",
            color: _getValuationColor(isIai, agaPrice),
            highlightState: _highlightState),
        MetricCard(
            id: "Discovery Premium",
            label: "EXP. PREMIUM",
            value: "\$${expPremium.toStringAsFixed(3)}",
            color: expPremium > 0 ? kAccent : Colors.white70,
            highlightState: _highlightState),
        MetricCard(
            id: "PPI",
            label: "PPI INDEX",
            value: "\$${ppi.toStringAsFixed(3)}",
            color: _getValuationColor(ppi, agaPrice),
            highlightState: _highlightState),
        MetricCard(
            id: "EV_Blended",
            label: "EV BLENDED",
            value: "\$${evBlended.toStringAsFixed(3)}",
            color: _getValuationColor(evBlended, agaPrice),
            highlightState: _highlightState),
        MetricCard(
            id: "Probability",
            label: "BLENDED PROB",
            value: "${(probability * 100).toStringAsFixed(0)}%",
            color: probability >= 0.7 ? kAccent : Colors.orangeAccent,
            highlightState: _highlightState),
        MetricCard(
            id: "Forensic Penalty",
            label: "FORENSIC PENALTY",
            value: "${forensicPenalty.toStringAsFixed(3)}x",
            color: forensicPenalty == 1.0 ? kAccent : Colors.orangeAccent,
            highlightState: _highlightState),
        MetricCard(
            id: "ROV",
            label: "ROV MULTIPLE",
            value: rov.toStringAsFixed(2),
            color: rov >= 1.3 ? kAccent : Colors.white70,
            highlightState: _highlightState),
        MetricCard(
            id: "ADV Cap",
            label: "ADV EXIT CAP",
            value: "\$${(val['ADV_Cap_CAD'] ?? 0.0).toStringAsFixed(0)}",
            color: advCapColor,
            highlightState: _highlightState),
        MetricCard(
            id: "Peer EV/oz",
            label: "PEER DISC COST",
            value:
                "\$${(val['Discovery_Efficiency_Comps'] ?? 0.48).toStringAsFixed(2)}/oz",
            color: Colors.white70,
            highlightState: _highlightState),
      ],
    );
  }

  // ====================================================================
  //  PHASE 4b — VALUATION TRIANGULATION PANEL (Simply-Wall-St-inspired)
  //  Renders the engine's additive `valuation_detail` block: the live
  //  reprice reconciliation vs the legacy formula, confidence-weighted
  //  Cost+Market+Option legs, the option-convexity premium, a base/bull/
  //  bear scenario range, per-project Technical Quality, the margin-of-
  //  safety ledger, and a one-at-a-time sensitivity tornado. Supersedes
  //  the legacy FormulaTraceWidget (which traced the old 4-term blend).
  // ====================================================================
  Widget _valuationTriangulation(Map<String, dynamic> vd, double agaPrice) {
    if (vd.isEmpty) {
      return const Text("Triangulation pending — awaiting first engine cycle…",
          style: TextStyle(color: kFaint, fontSize: 10, fontFamily: 'monospace'));
    }
    Map<String, dynamic> asMap(dynamic x) =>
        (x is Map) ? Map<String, dynamic>.from(x) : <String, dynamic>{};
    List<dynamic> asList(dynamic x) => (x is List) ? x : const <dynamic>[];

    final Map<String, dynamic> legs = asMap(vd['legs']);
    final Map<String, dynamic> weights = asMap(vd['weights']);
    final Map<String, dynamic> opt = asMap(vd['option_premium']);
    final Map<String, dynamic> scen = asMap(vd['scenarios']);
    final Map<String, dynamic> recon = asMap(vd['reconciliation']);
    final Map<String, dynamic> tqByProj = asMap(vd['tq_by_project']);
    final List<dynamic> mos = asList(vd['mos_ledger']);
    final List<dynamic> tornado = asList(scen['tornado']);

    final double intrinsic = (vd['intrinsic'] ?? 0.0).toDouble();
    final double upside = (vd['spear_upside_pct'] ?? 0.0).toDouble();
    final double piOpt = (opt['pi_opt'] ?? 0.0).toDouble();

    const Color costColor = Color(0xFF42A5F5);    // blue  — replacement / cost
    const Color marketColor = kAccent;            // green — market comps
    const Color incomeColor = Color(0xFFFFB74D);  // amber — income / option
    final Color upColor = upside >= 0 ? kAccent : const Color(0xFFFF5252);

    Widget lbl(String t) => Padding(
          padding: const EdgeInsets.only(top: 11, bottom: 5),
          child: Text(t,
              style: const TextStyle(
                  color: kFaint, fontSize: 8.5, fontWeight: FontWeight.bold,
                  letterSpacing: 0.8, fontFamily: 'monospace')),
        );

    // ---- headline: intrinsic + upside + reprice reconciliation ----
    final double legacyV = (recon['legacy_intrinsic'] ?? 0.0).toDouble();
    final double deltaPct = (recon['delta_pct'] ?? 0.0).toDouble();
    final String removedX = (recon['removed_discovery_multiple'] ?? 0).toString();
    final Widget headline = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text("\$${intrinsic.toStringAsFixed(2)}",
              style: const TextStyle(color: Colors.white, fontSize: 25,
                  fontWeight: FontWeight.w700, fontFamily: 'monospace', height: 1.0)),
          const SizedBox(width: 5),
          const Padding(
            padding: EdgeInsets.only(bottom: 3),
            child: Text("intrinsic/sh",
                style: TextStyle(color: kFaint, fontSize: 8.5, fontFamily: 'monospace')),
          ),
          const Spacer(),
          _pill(
              "${upside >= 0 ? '+' : ''}${upside.toStringAsFixed(0)}% vs \$${agaPrice.toStringAsFixed(2)}",
              upColor),
        ]),
        const SizedBox(height: 6),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: kPanelHi,
            borderRadius: BorderRadius.circular(5),
            border: Border.all(color: kBorder),
          ),
          child: Row(children: [
            const Icon(Icons.published_with_changes, size: 11, color: kDim),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                "Reprice: legacy \$${legacyV.toStringAsFixed(2)} → \$${intrinsic.toStringAsFixed(2)} (${deltaPct >= 0 ? '+' : ''}${deltaPct.toStringAsFixed(0)}%) · removed ${removedX}× discovery double-count",
                style: const TextStyle(
                    color: kDim, fontSize: 8.5, height: 1.3, fontFamily: 'monospace'),
              ),
            ),
          ]),
        ),
      ],
    );

    // ---- triangulation legs: confidence weights feed the valuation bridge ----
    final double wCost = (weights['cost'] ?? 0.0).toDouble();
    final double wMkt = (weights['market'] ?? 0.0).toDouble();
    final double wInc = (weights['income'] ?? 0.0).toDouble();

    // ---- option convexity ----
    final double volT = (opt['vol_term'] ?? 0.0).toDouble();
    final double carryT = (opt['carry_term'] ?? 0.0).toDouble();
    final double monT = (opt['moneyness_excess'] ?? 0.0).toDouble();
    final Widget optionRow = Row(children: [
      const Text("π_opt", style: TextStyle(color: kDim, fontSize: 9.5, fontFamily: 'monospace')),
      const SizedBox(width: 6),
      Text("+${(piOpt * 100).toStringAsFixed(1)}%",
          style: const TextStyle(color: incomeColor, fontSize: 12, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
      const Spacer(),
      _pill("vol ${(volT * 100).toStringAsFixed(0)}", incomeColor),
      const SizedBox(width: 4),
      _pill("carry ${(carryT * 100).toStringAsFixed(0)}", carryT > 0 ? incomeColor : kFaint),
      const SizedBox(width: 4),
      _pill("mny ${(monT * 100).toStringAsFixed(0)}", monT > 0 ? incomeColor : kFaint),
    ]);

    // ---- scenario range ----
    final double bear = (scen['bear'] ?? intrinsic).toDouble();
    final double base = (scen['base'] ?? intrinsic).toDouble();
    final double bull = (scen['bull'] ?? intrinsic).toDouble();
    final Map<String, dynamic> upMap = asMap(scen['implied_upside_pct']);
    final Widget scenarioBar = LayoutBuilder(builder: (ctx, c) {
      final double w = c.maxWidth;
      final double lo = (bear < agaPrice ? bear : agaPrice) * 0.95;
      final double hi = (bull > agaPrice ? bull : agaPrice) * 1.03;
      final double span = (hi - lo) <= 1e-9 ? 1.0 : (hi - lo);
      double fx(double v) => ((v - lo) / span).clamp(0.0, 1.0);
      return SizedBox(
        height: 24,
        child: Stack(clipBehavior: Clip.none, children: [
          Positioned(left: 0, right: 0, top: 11,
              child: Container(height: 4,
                  decoration: BoxDecoration(color: const Color(0xFF1A1A1F), borderRadius: BorderRadius.circular(2)))),
          Positioned(left: w * fx(bear), top: 11,
              child: Container(height: 4, width: (w * (fx(bull) - fx(bear))).clamp(0.0, w),
                  decoration: BoxDecoration(
                      gradient: LinearGradient(colors: [const Color(0xFFFF5252).withOpacity(0.55), kAccent.withOpacity(0.65)]),
                      borderRadius: BorderRadius.circular(2)))),
          Positioned(left: (w * fx(base) - 1).clamp(0.0, w), top: 6,
              child: Container(height: 14, width: 2, color: kAccent)),
          Positioned(left: (w * fx(agaPrice) - 1).clamp(0.0, w), top: 3,
              child: Container(height: 18, width: 2, color: Colors.white)),
        ]),
      );
    });
    Widget scenLabel(String tag, double v, double up, Color c) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(tag, style: TextStyle(color: c, fontSize: 8, fontWeight: FontWeight.bold, fontFamily: 'monospace', letterSpacing: 0.5)),
            Text("\$${v.toStringAsFixed(2)}", style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
            Text("${up >= 0 ? '+' : ''}${up.toStringAsFixed(0)}%", style: TextStyle(color: c, fontSize: 8, fontFamily: 'monospace')),
          ],
        );

    // ---- technical quality by project ----
    Widget tqRow(String proj, Map<String, dynamic> d) {
      final double tq = (d['tq'] ?? 1.0).toDouble();
      final double frac = ((tq - 0.55) / (1.70 - 0.55)).clamp(0.0, 1.0);
      final Color c = tq >= 1.0 ? kAccent : Colors.orangeAccent;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 2.5),
        child: Row(children: [
          SizedBox(width: 90,
              child: Text(proj.replaceAll('_', ' '), overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white70, fontSize: 9, fontFamily: 'monospace'))),
          Expanded(child: _miniBar(frac, c)),
          const SizedBox(width: 6),
          SizedBox(width: 38,
              child: Text("${tq.toStringAsFixed(2)}×", textAlign: TextAlign.right,
                  style: TextStyle(color: c, fontSize: 9, fontWeight: FontWeight.bold, fontFamily: 'monospace'))),
        ]),
      );
    }

    // ---- margin-of-safety ledger ----
    Widget mosRow(Map<String, dynamic> m) {
      final String name = (m['name'] ?? '').toString().replaceAll('_', ' ');
      final double factor = (m['factor'] ?? 1.0).toDouble();
      final double cum = (m['cumulative'] ?? 1.0).toDouble();
      final Color c = cum >= 0.85 ? kAccent : (cum >= 0.65 ? Colors.orangeAccent : const Color(0xFFFF5252));
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          SizedBox(width: 90,
              child: Text(name, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white70, fontSize: 9, fontFamily: 'monospace'))),
          Expanded(child: _miniBar(cum.clamp(0.0, 1.0), c)),
          const SizedBox(width: 6),
          SizedBox(width: 56,
              child: Text("×${factor.toStringAsFixed(2)} ▸${cum.toStringAsFixed(2)}", textAlign: TextAlign.right,
                  style: const TextStyle(color: kDim, fontSize: 8, fontFamily: 'monospace'))),
        ]),
      );
    }

    // ---- sensitivity tornado (shared domain across levers) ----
    double tLo = base, tHi = base;
    for (final t in tornado) {
      final tm = asMap(t);
      final double lo = (tm['low'] ?? base).toDouble();
      final double hi = (tm['high'] ?? base).toDouble();
      if (lo < tLo) tLo = lo;
      if (hi > tHi) tHi = hi;
    }
    final double tSpan = (tHi - tLo) <= 1e-9 ? 1.0 : (tHi - tLo);
    Widget tornadoRow(Map<String, dynamic> t) {
      final String name = (t['input'] ?? '').toString();
      final double lo = (t['low'] ?? base).toDouble();
      final double hi = (t['high'] ?? base).toDouble();
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 2.5),
        child: Row(children: [
          SizedBox(width: 74,
              child: Text(name, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white70, fontSize: 8.5, fontFamily: 'monospace'))),
          Expanded(child: LayoutBuilder(builder: (ctx, c) {
            final double w = c.maxWidth;
            double fx(double v) => ((v - tLo) / tSpan).clamp(0.0, 1.0);
            return SizedBox(height: 12, child: Stack(children: [
              Positioned(left: 0, right: 0, top: 5, child: Container(height: 2, color: const Color(0xFF1A1A1F))),
              Positioned(left: w * fx(lo), top: 3,
                  child: Container(height: 6, width: (w * (fx(hi) - fx(lo))).clamp(0.0, w),
                      decoration: BoxDecoration(color: kAccent.withOpacity(0.55), borderRadius: BorderRadius.circular(2)))),
              Positioned(left: (w * fx(base) - 1).clamp(0.0, w), top: 1,
                  child: Container(height: 10, width: 1.5, color: Colors.white70)),
            ]));
          })),
          const SizedBox(width: 6),
          SizedBox(width: 70,
              child: Text("\$${lo.toStringAsFixed(2)}–\$${hi.toStringAsFixed(2)}", textAlign: TextAlign.right,
                  style: const TextStyle(color: kFaint, fontSize: 8, fontFamily: 'monospace'))),
        ]),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        headline,
        lbl("VALUATION BRIDGE — COST → MARKET → INTRINSIC"),
        _valuationBridge(
          costContrib: wCost * (legs['cost'] ?? 0.0).toDouble(),
          mktContrib: wMkt * (legs['market'] ?? 0.0).toDouble(),
          incContrib: wInc * (legs['income'] ?? 0.0).toDouble(),
          piShare: wMkt *
              (legs['market'] ?? 0.0).toDouble() *
              (piOpt / (1.0 + piOpt)),
          intrinsic: intrinsic,
          price: agaPrice,
        ),
        lbl("OPTION CONVEXITY — replaces dead ROV"),
        optionRow,
        lbl("SCENARIO RANGE — bear · base · bull"),
        scenarioBar,
        const SizedBox(height: 2),
        Row(children: [
          scenLabel("BEAR", bear, (upMap['bear'] ?? 0).toDouble(), const Color(0xFFFF5252)),
          const Spacer(),
          scenLabel("BASE", base, (upMap['base'] ?? 0).toDouble(), Colors.white),
          const Spacer(),
          scenLabel("BULL", bull, (upMap['bull'] ?? 0).toDouble(), kAccent),
        ]),
        _Collapsible(
          card: false,
          initiallyExpanded: false,
          title: "DEEP DIVE — TECHNICAL QUALITY · MARGIN OF SAFETY · SENSITIVITY",
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              lbl("TECHNICAL QUALITY — ounces ≠ fungible"),
              ...tqByProj.entries.map((e) => tqRow(e.key, asMap(e.value))),
              lbl("MARGIN OF SAFETY — gross → net"),
              ...mos.map((m) => mosRow(asMap(m))),
              lbl("SENSITIVITY — Δ intrinsic (one-at-a-time)"),
              ...tornado.map((t) => tornadoRow(asMap(t))),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildHealthRadar(Map<String, dynamic> radarData) {
    if (radarData.isEmpty) return const SizedBox.shrink();

    final score = (radarData['health_rating'] ?? 10.0).toDouble();
    final ratingDesc = radarData['rating_desc']?.toString() ?? "PENDING DATA";
    final ratingColorName = radarData['rating_color']?.toString() ?? "white";
    final healthSummary = radarData['health_summary']?.toString() ?? "Loading...";
    final priorities = List<Map<String, dynamic>>.from(
        (radarData['priorities'] as List? ?? [])
            .map((e) => Map<String, dynamic>.from(e)));

    Color ratingColor = Colors.white70;
    if (ratingColorName == "green") {
      ratingColor = kAccent;
    } else if (ratingColorName == "orange") {
      ratingColor = Colors.orangeAccent;
    } else if (ratingColorName == "red") {
      ratingColor = Colors.redAccent;
    }

    IconData iconFor(String name) {
      switch (name) {
        case 'shopping_cart_outlined':
          return Icons.shopping_cart_outlined;
        case 'info_outline':
          return Icons.info_outline;
        case 'warning_amber_rounded':
          return Icons.warning_amber_rounded;
        case 'verified_user_outlined':
          return Icons.verified_user_outlined;
        case 'lock_clock':
          return Icons.lock_clock;
        case 'swap_horizontal_circle_outlined':
          return Icons.swap_horizontal_circle_outlined;
        case 'balance_outlined':
          return Icons.balance_outlined;
        case 'check_circle_outline':
          return Icons.check_circle_outline;
        default:
          return Icons.info_outline;
      }
    }

    Color colorFor(String name) {
      switch (name) {
        case 'green':
          return kAccent;
        case 'orange':
          return Colors.orangeAccent;
        case 'red':
          return Colors.redAccent;
        default:
          return Colors.white70;
      }
    }

    // The radar glows whenever anything is selected (it's the synthesis panel).
    return ListenableBuilder(
      listenable: _highlightState,
      builder: (context, _) {
        final bool isGlow = _highlightState.highlightedMetricId != null;
        final Color glow = _highlightState.activeGlowColor;

        return PanelCard(
          title: "TACTICAL HEALTH RADAR",
          glow: isGlow,
          glowColor: glow,
          trailing: _pill("H ${score.toStringAsFixed(1)}", ratingColor),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "$ratingDesc — $healthSummary",
                style: const TextStyle(color: kDim, fontSize: 8.5, height: 1.3),
              ),
              const SizedBox(height: 8),
              const Divider(color: kBorder, height: 1),
              const SizedBox(height: 4),
              // Show up to 3 prioritized actions for higher information density.
              ...priorities.take(3).map((p) => _buildPriorityItem(
                    iconFor(p['icon']?.toString() ?? ''),
                    colorFor(p['color']?.toString() ?? ''),
                    p['title']?.toString() ?? '',
                    p['desc']?.toString() ?? '',
                  )),
            ],
          ),
        );
      },
    );
  }

  Widget _buildPriorityItem(IconData icon, Color color, String title, String desc) {
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 10),
          const SizedBox(width: 6),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: const TextStyle(
                    fontSize: 8.5, fontFamily: 'monospace', height: 1.2),
                children: [
                  TextSpan(
                      text: "$title: ",
                      style:
                          TextStyle(color: color, fontWeight: FontWeight.bold)),
                  TextSpan(text: desc, style: const TextStyle(color: kDim)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ====================================================================
  //  CENTERPIECE — KELLY SIZING WATERFALL
  //  All engine math is preserved verbatim from v5.1; only the presentation
  //  is upgraded (proportional capital-decay bars on each sieve step).
  // ====================================================================
  Widget _kellyEngine(
    Map<String, dynamic> val,
    double mri,
    Map<String, dynamic> forensics,
    Map<String, dynamic> stats,
    Map<String, dynamic> metrics,
    Map<String, dynamic> nodes,
  ) {
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
    final double portVariance =
        (portVol * portVol < 0.04) ? 0.04 : portVol * portVol;
    // Dimensional coherence (synced with engine.calculate_sizing): convert the TOTAL
    // convergence return (implied upside) into an ANNUALIZED drift before applying
    // Kelly f* = mu / sigma^2.
    final double convergenceMonths =
        (val['intrinsic_convergence_months'] ?? 18.0).toDouble();
    final double convergenceYears =
        (convergenceMonths / 12.0) < 0.25 ? 0.25 : convergenceMonths / 12.0;
    final double muAnnualized = (impliedEdge / 100.0) / convergenceYears;
    final double rawPortfolioKelly = (muAnnualized / portVariance) * fKelly;

    final double groyCorr = corrMatrix['AGA.V']?['GROY']?.toDouble() ?? 0.50;
    final double urcCorr = corrMatrix['AGA.V']?['URC.TO']?.toDouble() ?? 0.50;
    final double gmxCorr = corrMatrix['AGA.V']?['GMX.TO']?.toDouble() ?? 0.50;
    final double avgBallastCorr = (groyCorr + urcCorr + gmxCorr) / 3.0;
    final double avgCPenalty =
        1.0 - (avgBallastCorr > 0.30 ? (avgBallastCorr - 0.30) * 0.40 : 0.0);

    final double vix = (metrics['VIX']?['value'] ?? 16.5).toDouble();
    double maxLeverageAllowed = 1.5;
    if (vix > 15.0) {
      maxLeverageAllowed = 1.5 - ((vix - 15.0) * 0.045);
      if (maxLeverageAllowed < 0.60) maxLeverageAllowed = 0.60;
    }

    // ES95 tail-risk throttle (synced with engine): scale leverage down as daily
    // ES deteriorates.
    final double esPct = (stats['expected_shortfall_95'] ?? 0.0).toDouble();
    const double esNoPen = -5.0, esMaxPen = -12.0, esMaxRed = 0.5;
    double esThrottle = 1.0;
    if (esPct < esNoPen && esNoPen > esMaxPen) {
      double sev = (esNoPen - esPct) / (esNoPen - esMaxPen);
      if (sev > 1.0) sev = 1.0;
      esThrottle = 1.0 - esMaxRed * sev;
    }

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

    // The 60/40 barbell is a hard ceiling: opportunistic flexibility may loosen the
    // engine-side liquidity cap (reflected in ADV_Cap_CAD), but the spear position
    // cap stays fixed at 60%.
    final double maxPosLimitCad = currentValue * maxSpearPos;

    final double advCap = (val['ADV_Cap_CAD'] ?? 0.0).toDouble();
    final double advCapPct =
        (val['ADV_Cap_Percentage'] ?? val['cap_percentage'] ?? 15.0).toDouble();

    // Edge-quality gates folded into f* upstream (parameter-uncertainty + momentum).
    final double edgeConfidence = (val['edge_confidence'] ?? 1.0).toDouble();
    final double catalystFactor = (val['catalyst_factor'] ?? 1.0).toDouble();
    final dynamic spearMomRaw = val['spear_momentum_pct'];
    final double? spearMom = spearMomRaw is num ? spearMomRaw.toDouble() : null;

    final double maxByLiquidityCap = advCap / 0.60;
    final double maxBySinglePosCap = maxPosLimitCad / 0.60;
    final double cappedTargetCap = targetCapital;

    final bool isPosBinding = (cappedTargetCap - maxBySinglePosCap).abs() < 1.0;
    final bool isLiqBinding = (cappedTargetCap - maxByLiquidityCap).abs() < 1.0;

    final Color posCapColor =
        isPosBinding ? const Color(0xFFFF9800) : kAccent;
    final Color liqCapColor =
        isLiqBinding ? const Color(0xFFFF9800) : kAccent;

    final double usdToCad = (val['usd_to_cad'] ??
            stats['usd_to_cad'] ??
            metrics['USDCAD=X']?['value'] ??
            1.38)
        .toDouble();

    // ---- Asset allocation directive table (BUY / TRIM / HOLD) ----
    double currentValueSum = 0.0;
    final Map<String, double> weights = {
      "AGA.V": 0.60,
      "GROY": 0.15,
      "URC.TO": 0.15,
      "GMX.TO": 0.10,
    };

    weights.forEach((ticker, w) {
      final node = nodes[ticker] ?? {};
      final double price = (node['price'] ??
              (ticker == "AGA.V"
                  ? 0.71
                  : ticker == "GROY"
                      ? 3.22
                      : ticker == "URC.TO"
                          ? 4.82
                          : 2.04))
          .toDouble();
      double shares = (node['shares'] ?? 0.0).toDouble();
      if (shares == 0.0) {
        shares = (ticker == "AGA.V"
            ? 5000.0
            : ticker == "GROY"
                ? 161.0
                : ticker == "URC.TO"
                    ? 130.0
                    : 230.0);
      }
      double v = shares * price;
      if (ticker == "GROY") {
        v *= usdToCad;
      }
      currentValueSum += v;
    });
    if (currentValueSum == 0.0) {
      currentValueSum = currentValue;
    }

    final List<TableRow> tableRows = [
      TableRow(
        decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: kBorder, width: 1.0))),
        children: [
          _thCell("ASSET", Alignment.centerLeft),
          _thCell("ROLE", Alignment.centerLeft),
          _thCell("WT", Alignment.centerRight),
          _thCell("TGT", Alignment.centerRight),
          _thCell("DELTA", Alignment.centerRight),
          _thCell("ORDER", Alignment.center),
        ],
      ),
    ];

    weights.forEach((ticker, w) {
      final node = nodes[ticker] ?? {};
      final double price = (node['price'] ??
              (ticker == "AGA.V"
                  ? 0.71
                  : ticker == "GROY"
                      ? 3.22
                      : ticker == "URC.TO"
                          ? 4.82
                          : 2.04))
          .toDouble();

      double shares = (node['shares'] ?? 0.0).toDouble();
      if (shares == 0.0) {
        shares = (ticker == "AGA.V"
            ? 5000.0
            : ticker == "GROY"
                ? 161.0
                : ticker == "URC.TO"
                    ? 130.0
                    : 230.0);
      }

      double currentTickerValue = shares * price;
      if (ticker == "GROY") {
        currentTickerValue *= usdToCad;
      }

      final double currentWeight = currentTickerValue / currentValueSum * 100.0;
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
          dirColor = kAccent;
          bgColor = kAccent.withOpacity(0.06);
        }
      } else {
        directive = "TRIM";
        dirColor = const Color(0xFFFF9800);
        bgColor = const Color(0xFFFF9800).withOpacity(0.05);
      }

      final String deltaSharesStr =
          (deltaShares > 0 ? "+" : "") + deltaShares.toStringAsFixed(0);

      tableRows.add(
        TableRow(
          decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0xFF161619)))),
          children: [
            _tdCell(ticker,
                bold: true, color: Colors.white, align: Alignment.centerLeft),
            _tdCell(ticker == "AGA.V" ? "Spear" : "Ballast",
                color: kDim, align: Alignment.centerLeft),
            _tdCell("${currentWeight.toStringAsFixed(1)}%",
                color: Colors.white70, align: Alignment.centerRight),
            _tdCell("${targetWeight.toStringAsFixed(1)}%",
                color: kAccent, align: Alignment.centerRight),
            _tdCell(deltaSharesStr,
                bold: true, color: dirColor, align: Alignment.centerRight),
            TableCell(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 1),
                child: Align(
                  alignment: Alignment.center,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                    decoration: BoxDecoration(
                      color: bgColor,
                      border: Border.all(color: dirColor.withOpacity(0.3)),
                      borderRadius: BorderRadius.circular(3),
                    ),
                    child: Text(
                      directive,
                      style: TextStyle(
                          color: dirColor,
                          fontSize: 7,
                          fontWeight: FontWeight.bold,
                          fontFamily: 'monospace'),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    });

    // ---- The 7-step sieve intermediates (engine-provided, with fallbacks) ----
    final double wfRawKelly =
        (val['raw_kelly_leverage'] ?? rawPortfolioKelly).toDouble();
    final double wfVixCapped = (val['vix_capped_leverage'] ??
            (rawPortfolioKelly < maxLeverageAllowed
                ? rawPortfolioKelly
                : maxLeverageAllowed))
        .toDouble();
    final double wfPostCorr = (val['post_correlation_leverage'] ??
            (wfVixCapped * avgCPenalty))
        .toDouble();
    final double wfPostEs =
        (val['post_es_leverage'] ?? (wfPostCorr * esThrottle)).toDouble();
    final double wfRegimeScaled = wfPostEs * multiplier;

    final double wfRawCad = currentValue * wfRawKelly;
    final double wfVixCad = currentValue * wfVixCapped;
    final double wfCorrCad = currentValue * wfPostCorr;
    final double wfEsCad = currentValue * wfPostEs;
    final double wfRegimeCad = currentValue * wfRegimeScaled;

    final bool isEsActive = esThrottle < 1.0;
    final bool isCorrActive = avgCPenalty < 0.99;

    // The bar scale anchors on the (largest) theoretical Kelly capital so each
    // subsequent constraint visibly shaves the deployable target down.
    final double barMax = wfRawCad > 0 ? wfRawCad : 1.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // --- Sizing mechanics: the key inputs/outputs of the sieve ---
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            MetricCard(
                id: "Kelly_Multiple",
                label: "KELLY MULT",
                value: "${kelly.toStringAsFixed(2)}x",
                color: _getKellyColor(kelly),
                highlightState: _highlightState),
            MetricCard(
                id: "REP Floor",
                label: "REP FLOOR",
                value: "\$${repFloor.toStringAsFixed(2)}",
                color: Colors.white70,
                highlightState: _highlightState),
            MetricCard(
                id: "CBA",
                label: "CASH RUNWAY",
                value: "${runway.toStringAsFixed(0)} mo",
                color: _getRunwayColor(runway),
                highlightState: _highlightState),
            MetricCard(
                id: "Implied_Upside",
                label: "IMPLIED EDGE",
                value: "${impliedEdge.toStringAsFixed(1)}%",
                color: _getEdgeColor(impliedEdge),
                highlightState: _highlightState),
          ],
        ),
        const SizedBox(height: 10),

        // --- THE WATERFALL SIEVE (visual centerpiece) ---
        ListenableBuilder(
          listenable: _highlightState,
          builder: (context, _) {
            final bool isMriGlow = _highlightState.isHighlighted('MRI');
            return AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: kPanelHi,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(
                  color: isMriGlow ? kAccent : kBorder,
                  width: isMriGlow ? 1.4 : 1.0,
                ),
                boxShadow: isMriGlow
                    ? [
                        BoxShadow(
                            color: kAccent.withOpacity(0.18),
                            blurRadius: 8,
                            spreadRadius: 1)
                      ]
                    : null,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        "7-STEP VERTICAL SIZING SIEVE",
                        style: TextStyle(
                            fontSize: 8.5,
                            fontWeight: FontWeight.bold,
                            color: kDim,
                            letterSpacing: 0.6,
                            fontFamily: 'monospace'),
                      ),
                      if (isMriGlow)
                        const Text(
                          "★ MRI DAMPENED",
                          style: TextStyle(
                              fontSize: 8,
                              color: kAccent,
                              fontWeight: FontWeight.bold,
                              fontFamily: 'monospace'),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  // Edge-quality gates that shape f* BEFORE the sieve: parameter-uncertainty
                  // (uncertainty-adjusted Kelly) and the catalyst/momentum confirmation.
                  Row(
                    children: [
                      Expanded(
                          child: _gatePill(
                              "EDGE CONFIDENCE",
                              edgeConfidence,
                              "Param-uncertainty κ=μ²/(μ²+SE²)")),
                      const SizedBox(width: 6),
                      Expanded(
                          child: _gatePill(
                              "CATALYST",
                              catalystFactor,
                              spearMom == null
                                  ? "Momentum gate"
                                  : "Spear mom ${spearMom >= 0 ? '+' : ''}${spearMom.toStringAsFixed(1)}%")),
                    ],
                  ),
                  const SizedBox(height: 8),
                  _sieveStep("[1] THEORETICAL KELLY  f*=μ/σ²", wfRawCad, barMax,
                      Colors.white),
                  _sieveStep("[2] VIX LEVERAGE LIMIT", wfVixCad, barMax,
                      wfVixCapped < wfRawKelly ? Colors.orangeAccent : Colors.white),
                  _sieveStep("[3] CORRELATION PENALTY", wfCorrCad, barMax,
                      isCorrActive ? Colors.orangeAccent : Colors.white,
                      active: isCorrActive),
                  _sieveStep("[4] ES95 TAIL BRAKE", wfEsCad, barMax,
                      isEsActive ? Colors.orangeAccent : Colors.white,
                      active: isEsActive),
                  _sieveStep("[5] REGIME-SCALED (MRI)", wfRegimeCad, barMax,
                      multiplier < 1.0 ? Colors.orangeAccent : Colors.white),
                  _sieveStep("[6] SPEAR CEILING (60%)", maxPosLimitCad, barMax,
                      posCapColor,
                      active: isPosBinding),
                  _sieveStep(
                      "[7] ADV CAP (${advCapPct.toStringAsFixed(0)}% ADV)",
                      advCap,
                      barMax,
                      liqCapColor,
                      active: isLiqBinding),
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 6),
                    child: Divider(color: kBorder, height: 1),
                  ),
                  // Final deployable target — the resolved output of the sieve.
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
                    decoration: BoxDecoration(
                      color: kAccent.withOpacity(0.07),
                      borderRadius: BorderRadius.circular(5),
                      border: Border.all(color: kAccent.withOpacity(0.3)),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          "● MODEL TARGET DEPLOYMENT",
                          style: TextStyle(
                              color: kAccent,
                              fontWeight: FontWeight.bold,
                              fontSize: 9.5,
                              fontFamily: 'monospace'),
                        ),
                        Text(
                          _censorSensitiveData
                              ? "••••••"
                              : "\$${cappedTargetCap.toStringAsFixed(0)} CAD",
                          style: const TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.bold,
                              color: kAccent,
                              fontFamily: 'monospace'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        ),
        const SizedBox(height: 10),

        // --- Asset allocation directives table ---
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: kPanelHi,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: kBorder),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "ASSET ALLOCATION DIRECTIVES",
                style: TextStyle(
                    fontSize: 8.5,
                    fontWeight: FontWeight.bold,
                    color: kDim,
                    letterSpacing: 0.6,
                    fontFamily: 'monospace'),
              ),
              const SizedBox(height: 5),
              Table(
                defaultColumnWidth: const FlexColumnWidth(),
                columnWidths: const {
                  0: FlexColumnWidth(1.3),
                  1: FlexColumnWidth(1.2),
                  4: FlexColumnWidth(1.2),
                  5: FlexColumnWidth(1.3),
                },
                children: tableRows,
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),

        // --- Plain-language actionable read ---
        _buildActionableInsights(val, mri, jsf: jsf),
      ],
    );
  }

  /// One sieve step: label + value on top, a proportional capital-decay bar
  /// underneath. The bar makes the "whittling down" of deployable capital
  /// instantly legible — the heart of the redesigned centerpiece.
  Widget _sieveStep(String label, double valueCad, double maxCad, Color color,
      {bool active = false}) {
    final double frac = maxCad > 0 ? (valueCad / maxCad).clamp(0.0, 1.0) : 0.0;
    final String valStr =
        _censorSensitiveData ? "••••••" : "\$${valueCad.toStringAsFixed(0)}";
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      color: Color(0xFFCCCCCC),
                      fontSize: 8.5,
                      fontFamily: 'monospace'),
                ),
              ),
              const SizedBox(width: 6),
              Text(
                "$valStr${active ? '  ◆' : ''}",
                style: TextStyle(
                    color: color,
                    fontSize: 9,
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace'),
              ),
            ],
          ),
          const SizedBox(height: 4),
          _miniBar(frac, color),
        ],
      ),
    );
  }

  Widget _buildActionableInsights(Map<String, dynamic> val, double mri,
      {double jsf = 4.0}) {
    final kelly = (val['Kelly_Multiple'] ?? 1.0).toDouble();
    final edge = (val['Implied_Upside'] ?? 0.0).toDouble();

    String recommendation = "HOLD POSITION — Monitor tape";
    Color recColor = Colors.orange;

    if (mri < 40 && edge > 80 && jsf >= 3.5) {
      recommendation =
          "HIGH CONVICTION ZONE — System signals expansion. Scale spear.";
      recColor = kAccent;
    } else if (mri < 40 && edge > 80 && jsf < 3.5) {
      recommendation =
          "CONVICTION GATED — JSF forensics degraded. Scale conservatively.";
      recColor = Colors.orangeAccent;
    } else if (kelly > 1.5) {
      recommendation = "CAUTION — Sizer overallocated under current limits.";
      recColor = Colors.redAccent;
    } else if (mri > 65) {
      recommendation =
          "DEFENSIVE MODE — High sovereign stress. Keep cash buffers.";
      recColor = Colors.redAccent;
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: recColor.withOpacity(0.06),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: recColor.withOpacity(0.28)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.bolt, color: recColor, size: 13),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              recommendation,
              style: TextStyle(
                  color: recColor,
                  fontSize: 9.5,
                  fontWeight: FontWeight.bold,
                  height: 1.25),
            ),
          ),
        ],
      ),
    );
  }

  // ====================================================================
  //  COLOR LOGIC  (semantics unchanged; brand green standardized to kAccent)
  // ====================================================================
  Color _getKellyColor(double kelly) {
    if (kelly <= 1.0) return kAccent;
    if (kelly <= 1.5) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Color _getEdgeColor(double edge) {
    if (edge >= 80) return kAccent;
    if (edge >= 40) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Color _getRunwayColor(double months) {
    if (months >= 24) return kAccent;
    if (months >= 12) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  Color _healthColor(double s) =>
      s >= 7 ? kAccent : (s >= 4 ? Colors.orangeAccent : Colors.redAccent);

  Color _mriColor(double m) =>
      m < 40 ? kAccent : (m < 65 ? Colors.orangeAccent : Colors.redAccent);

  Color _getMetricColor(String key, double value) {
    if (value == 0) return Colors.white70;
    switch (key) {
      case '10Y':
        if (value < 3.75) return kAccent;
        if (value <= 4.75) return Colors.orangeAccent;
        return Colors.redAccent;
      case '30Y':
        if (value < 4.00) return kAccent;
        if (value <= 5.00) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'DXY':
        if (value < 100.0) return kAccent;
        if (value <= 104.5) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'Spreads':
        if (value < 3.50) return kAccent;
        if (value <= 5.00) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'TED':
        if (value < 0.20) return kAccent;
        if (value <= 0.45) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'VIX':
        if (value < 15.0) return kAccent;
        if (value <= 23.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'WTI':
        if (value >= 65.0 && value <= 85.0) return kAccent;
        if ((value >= 50.0 && value < 65.0) || (value > 85.0 && value <= 95.0)) {
          return Colors.orangeAccent;
        }
        return Colors.redAccent;
      case 'Spot_Ag':
        if (value >= 32.0) return kAccent;
        if (value >= 24.0) return Colors.orangeAccent;
        return Colors.redAccent;
      case 'GSR':
        if (value < 75.0) return kAccent;
        if (value <= 85.0) return Colors.orangeAccent;
        return Colors.redAccent;
      default:
        return Colors.white70;
    }
  }

  Color _getValuationColor(double valuation, double price) {
    if (price <= 0.0 || valuation <= 0.0) return Colors.white70;
    final ratio = valuation / price;
    if (ratio >= 1.5) return kAccent;
    if (ratio <= 0.85) return Colors.redAccent;
    return Colors.orangeAccent;
  }

  // ====================================================================
  //  METRIC COMPASS — slide-in glossary drawer (the only "navigation")
  // ====================================================================
  Widget _buildCompassDrawer() {
    return Drawer(
      backgroundColor: const Color(0xFF0B0B0E),
      width: 380,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: const [
                    Icon(Icons.menu_book, color: kAccent, size: 16),
                    SizedBox(width: 8),
                    Text(
                      "METRIC COMPASS GLOSSARY",
                      style: TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          color: Colors.white),
                    ),
                  ],
                ),
                IconButton(
                  icon: const Icon(Icons.close, color: kDim, size: 16),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const Divider(color: kBorder),
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
    );
  }

  Widget _buildMetricDictionary(Map<String, dynamic> metadata) {
    if (metadata.isEmpty) {
      return const Center(
        child: Text("Connecting and loading database metrics glossary...",
            style: TextStyle(color: kDim, fontSize: 9)),
      );
    }

    // Category groupings for educational hierarchy.
    const Map<String, List<String>> categories = {
      "MACRO REGIME": ["MRI"],
      "FORENSIC SHIELDS": ["JSF", "CBA", "Dilution Sieve", "Sloan Ratios"],
      "VALUATION ENGINE": [
        "REP Floor",
        "IS-IAI",
        "ROV",
        "Peer EV/oz",
        "Discovery Premium",
        "AISC Uplift",
        "Term Structure"
      ],
      "RISK & SIZING": ["Health Rating", "ES95", "ADV Cap", "Priorities"],
      "MACRO INPUTS": [
        "10Y",
        "30Y",
        "TED",
        "DXY",
        "Spreads",
        "VIX",
        "WTI",
        "Spot_Ag",
        "GSR",
        "CFTC_Silver_Net_Longs"
      ],
    };

    Widget buildMetricEntry(String key, Map<String, dynamic> value) {
      final def = value['definition'] ?? '';
      final calc = value['calculation'] ?? '';
      final use = value['actionability'] ?? '';
      final rels = value['relationships'] ?? '';
      final sigs = value['signals'] ?? '';

      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              key,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 9.5,
                  fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 1.5),
            RichText(
              text: TextSpan(
                style: const TextStyle(
                    fontSize: 8.5,
                    color: kDim,
                    height: 1.2,
                    fontFamily: 'Courier'),
                children: [
                  const TextSpan(
                      text: "Definition: ",
                      style: TextStyle(
                          color: Colors.white70, fontWeight: FontWeight.bold)),
                  TextSpan(text: "$def\n"),
                  const TextSpan(
                      text: "Formula: ",
                      style: TextStyle(
                          color: Colors.white70, fontWeight: FontWeight.bold)),
                  TextSpan(text: "$calc\n"),
                  const TextSpan(
                      text: "Actionability: ",
                      style: TextStyle(
                          color: Colors.white70, fontWeight: FontWeight.bold)),
                  TextSpan(text: "$use\n"),
                  if (rels.isNotEmpty) ...[
                    const TextSpan(
                        text: "Relationships: ",
                        style: TextStyle(
                            color: kAccent, fontWeight: FontWeight.bold)),
                    TextSpan(
                        text: "$rels\n",
                        style: const TextStyle(color: Color(0xFFAADDCC))),
                  ],
                  if (sigs.isNotEmpty) ...[
                    const TextSpan(
                        text: "Signals: ",
                        style: TextStyle(
                            color: Colors.orangeAccent,
                            fontWeight: FontWeight.bold)),
                    TextSpan(
                        text: sigs,
                        style: const TextStyle(color: Color(0xFFDDCC99))),
                  ],
                ],
              ),
            ),
          ],
        ),
      );
    }

    final List<Widget> children = [
      Row(
        children: const [
          Icon(Icons.menu_book, color: kAccent, size: 12),
          SizedBox(width: 5),
          Text(
            "GLOSSARY COMPASS & ENGINE FORMULAS",
            style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.bold,
                color: kDim,
                letterSpacing: 0.5),
          ),
        ],
      ),
      const SizedBox(height: 8),
    ];

    for (final category in categories.entries) {
      children.add(
        Padding(
          padding: const EdgeInsets.only(top: 6, bottom: 4),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
            decoration: BoxDecoration(
              color: kPanelHi,
              borderRadius: BorderRadius.circular(3),
              border: Border.all(color: kBorder),
            ),
            child: Text(
              category.key,
              style: const TextStyle(
                fontSize: 8.5,
                fontWeight: FontWeight.bold,
                color: kAccent,
                letterSpacing: 1.0,
                fontFamily: 'monospace',
              ),
            ),
          ),
        ),
      );

      for (final key in category.value) {
        if (metadata.containsKey(key)) {
          children.add(buildMetricEntry(key, metadata[key]));
        }
      }
    }

    // Render any uncategorized metrics at the end.
    final Set<String> categorized = categories.values.expand((v) => v).toSet();
    for (final e in metadata.entries) {
      if (!categorized.contains(e.key)) {
        children.add(buildMetricEntry(e.key, e.value));
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }

  // ====================================================================
  //  SMALL SHARED CHROME HELPERS
  // ====================================================================
  // Compact gate readout: label + percentage + proportional bar + sub-caption.
  // Used for the Kelly edge-quality gates (edge confidence, catalyst factor).
  Widget _gatePill(String label, double factor01, String sub) {
    final double f = factor01.clamp(0.0, 1.0);
    final Color c = f >= 0.8
        ? kAccent
        : (f >= 0.5 ? Colors.orangeAccent : const Color(0xFFFF5252));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: kPanel,
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: kBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: Text(label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: kFaint,
                        fontSize: 7.5,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.4,
                        fontFamily: 'monospace')),
              ),
              const SizedBox(width: 4),
              Text("${(f * 100).toStringAsFixed(0)}%",
                  style: TextStyle(
                      color: c,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      fontFamily: 'monospace')),
            ],
          ),
          const SizedBox(height: 4),
          _miniBar(f, c),
          const SizedBox(height: 3),
          Text(sub,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: kFaint, fontSize: 7)),
        ],
      ),
    );
  }

  // Integrity alert strip — collapses to nothing when there are no alerts.
  Widget _integrityStrip(Map<String, dynamic> integrity) {
    final List alerts = (integrity['alerts'] as List?) ?? const [];
    if (alerts.isEmpty) return const SizedBox.shrink();
    const Color warn = Color(0xFFFF9800);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(10, 5, 10, 0),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: warn.withOpacity(0.07),
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: warn.withOpacity(0.35)),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: warn, size: 12),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              alerts.map((a) => a.toString()).join("    •    "),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  color: Color(0xFFFFB74D),
                  fontSize: 8.5,
                  fontWeight: FontWeight.w600,
                  fontFamily: 'monospace',
                  letterSpacing: 0.3),
            ),
          ),
        ],
      ),
    );
  }

  Widget _pill(String text, Color color, {IconData? icon}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withOpacity(0.35), width: 0.8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, color: color, size: 10),
            const SizedBox(width: 4),
          ],
          Text(
            text,
            style: TextStyle(
                color: color,
                fontSize: 8.5,
                fontWeight: FontWeight.bold,
                fontFamily: 'monospace',
                letterSpacing: 0.3),
          ),
        ],
      ),
    );
  }

  Widget _headerIcon(IconData icon, String tooltip, VoidCallback onTap) {
    return SizedBox(
      width: 30,
      height: 30,
      child: IconButton(
        padding: EdgeInsets.zero,
        iconSize: 16,
        splashRadius: 18,
        color: kDim,
        icon: Icon(icon),
        tooltip: tooltip,
        onPressed: onTap,
      ),
    );
  }
}

// ======================================================================
//  PanelCard — the consistent premium card chrome used across the deck.
//  Accent tick + tiny letter-spaced title + hairline divider + body.
//  Optionally glows (border + soft shadow) when its content is "active".
// ======================================================================
// ======================================================================
//  _Collapsible — a tap-to-toggle section used to de-emphasize content
//  without deleting it. With [card]=true it wears full PanelCard chrome
//  (used to demote the Kelly waterfall to a one-tap panel); with
//  [card]=false it is a light inline header (used to tuck the valuation
//  deep-dive analytics under the triangulation focus). Overflow-safe: the
//  body is only built while expanded.
// ======================================================================
class _Collapsible extends StatefulWidget {
  final String title;
  final Widget child;
  final bool initiallyExpanded;
  final bool card;
  final Color titleColor;
  final Widget? trailing;
  final bool glow;

  const _Collapsible({
    required this.title,
    required this.child,
    this.initiallyExpanded = false,
    this.card = true,
    this.titleColor = kDim,
    this.trailing,
    this.glow = false,
  });

  @override
  State<_Collapsible> createState() => _CollapsibleState();
}

class _CollapsibleState extends State<_Collapsible> {
  late bool _open = widget.initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    final Color tick =
        widget.titleColor == kDim ? kAccent : widget.titleColor;

    final Widget header = InkWell(
      onTap: () => setState(() => _open = !_open),
      child: Row(
        children: [
          Container(
            width: 2.5,
            height: 11,
            decoration: BoxDecoration(
                color: tick, borderRadius: BorderRadius.circular(2)),
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              widget.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: widget.titleColor,
                fontSize: 9.5,
                fontWeight: FontWeight.bold,
                letterSpacing: 0.9,
              ),
            ),
          ),
          if (widget.trailing != null) ...[
            widget.trailing!,
            const SizedBox(width: 6),
          ],
          Icon(_open ? Icons.expand_less : Icons.expand_more,
              size: 16, color: kDim),
        ],
      ),
    );

    final Widget body = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        header,
        if (_open) ...[
          const SizedBox(height: 8),
          Container(height: 1, color: kBorder),
          const SizedBox(height: 9),
          widget.child,
        ],
      ],
    );

    if (!widget.card) {
      return Padding(padding: const EdgeInsets.only(top: 8), child: body);
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(11, 9, 11, 11),
      decoration: BoxDecoration(
        color: kPanel,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: widget.glow ? kAccent : kBorder,
          width: widget.glow ? 1.4 : 1.0,
        ),
      ),
      child: body,
    );
  }
}

// ======================================================================
//  _HealthSnowflake — a static 4-axis radar (Value · Forensics · Macro ·
//  Tail-Risk) inspired by the Simply Wall St snowflake. Pure geometry on a
//  CustomPaint; axis labels and the centre score are plain widgets layered
//  on top. No animation.
// ======================================================================
class _HealthSnowflake extends StatelessWidget {
  final double value; // 0..1
  final double forensics; // 0..1
  final double macro; // 0..1
  final double tail; // 0..1
  final double score; // 0..10
  final Color color;

  const _HealthSnowflake({
    required this.value,
    required this.forensics,
    required this.macro,
    required this.tail,
    required this.score,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    const labelStyle = TextStyle(
        color: kDim,
        fontSize: 7.5,
        fontWeight: FontWeight.bold,
        letterSpacing: 0.5,
        fontFamily: 'monospace');
    return AspectRatio(
      aspectRatio: 1.0,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _SnowflakePainter(
                values: [value, forensics, macro, tail],
                color: color,
              ),
            ),
          ),
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(score.toStringAsFixed(1),
                    style: TextStyle(
                        color: color,
                        fontSize: 17,
                        height: 1.0,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'monospace')),
                const Text("/10", style: TextStyle(color: kFaint, fontSize: 7.5)),
              ],
            ),
          ),
          const Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: Center(child: Text("VALUE", style: labelStyle))),
          const Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: Center(child: Text("MACRO", style: labelStyle))),
          const Positioned(
              right: 1,
              top: 0,
              bottom: 0,
              child:
                  Align(alignment: Alignment.centerRight, child: Text("FORENSIC", style: labelStyle))),
          const Positioned(
              left: 1,
              top: 0,
              bottom: 0,
              child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text("TAIL-RISK", style: labelStyle))),
        ],
      ),
    );
  }
}

class _SnowflakePainter extends CustomPainter {
  final List<double> values; // [top, right, bottom, left] each 0..1
  final Color color;
  _SnowflakePainter({required this.values, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final Offset c = Offset(size.width / 2, size.height / 2);
    final double r = size.shortestSide * 0.34;
    final Paint grid = Paint()
      ..color = const Color(0xFF24242C)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    // concentric diamond rings
    for (final double f in [0.25, 0.5, 0.75, 1.0]) {
      final Path ring = Path()
        ..moveTo(c.dx, c.dy - r * f)
        ..lineTo(c.dx + r * f, c.dy)
        ..lineTo(c.dx, c.dy + r * f)
        ..lineTo(c.dx - r * f, c.dy)
        ..close();
      canvas.drawPath(ring, grid);
    }
    // spokes
    canvas.drawLine(c, Offset(c.dx, c.dy - r), grid);
    canvas.drawLine(c, Offset(c.dx + r, c.dy), grid);
    canvas.drawLine(c, Offset(c.dx, c.dy + r), grid);
    canvas.drawLine(c, Offset(c.dx - r, c.dy), grid);

    double v(int i) => values[i].clamp(0.0, 1.0) * r;
    final Path poly = Path()
      ..moveTo(c.dx, c.dy - v(0))
      ..lineTo(c.dx + v(1), c.dy)
      ..lineTo(c.dx, c.dy + v(2))
      ..lineTo(c.dx - v(3), c.dy)
      ..close();
    canvas.drawPath(poly, Paint()..color = color.withOpacity(0.16));
    canvas.drawPath(
        poly,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.6);

    final Paint dot = Paint()..color = color;
    canvas.drawCircle(Offset(c.dx, c.dy - v(0)), 2.0, dot);
    canvas.drawCircle(Offset(c.dx + v(1), c.dy), 2.0, dot);
    canvas.drawCircle(Offset(c.dx, c.dy + v(2)), 2.0, dot);
    canvas.drawCircle(Offset(c.dx - v(3), c.dy), 2.0, dot);
  }

  @override
  bool shouldRepaint(covariant _SnowflakePainter old) =>
      old.values != values || old.color != color;
}

// ======================================================================
//  _YieldCurveMini — a small static sparkline of the nominal curve (10Y →
//  30Y) with the real-yield anchor. Labels live outside the paint.
// ======================================================================
class _YieldCurveMini extends StatelessWidget {
  final double y10;
  final double y30;
  final double real10;
  final Color color;
  const _YieldCurveMini(
      {required this.y10,
      required this.y30,
      required this.real10,
      required this.color});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 34,
      child: CustomPaint(
        painter: _YieldCurvePainter(
            y10: y10, y30: y30, real10: real10, color: color),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _YieldCurvePainter extends CustomPainter {
  final double y10;
  final double y30;
  final double real10;
  final Color color;
  _YieldCurvePainter(
      {required this.y10,
      required this.y30,
      required this.real10,
      required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final List<double> pts = [y10, y30];
    double lo = pts.reduce((a, b) => a < b ? a : b);
    double hi = pts.reduce((a, b) => a > b ? a : b);
    if (real10 < lo) lo = real10;
    lo -= 0.3;
    hi += 0.3;
    final double span = (hi - lo) <= 1e-9 ? 1.0 : (hi - lo);
    double yfor(double v) => size.height - ((v - lo) / span) * size.height;

    final Paint axis = Paint()
      ..color = const Color(0xFF24242C)
      ..strokeWidth = 1.0;
    canvas.drawLine(Offset(0, size.height - 1), Offset(size.width, size.height - 1), axis);

    // nominal curve 10Y -> 30Y
    final Offset p10 = Offset(size.width * 0.18, yfor(y10));
    final Offset p30 = Offset(size.width * 0.82, yfor(y30));
    final Paint line = Paint()
      ..color = color
      ..strokeWidth = 1.8
      ..style = PaintingStyle.stroke;
    canvas.drawLine(p10, p30, line);
    final Paint dot = Paint()..color = color;
    canvas.drawCircle(p10, 2.4, dot);
    canvas.drawCircle(p30, 2.4, dot);

    // real-yield anchor as a faint reference dash
    final double yr = yfor(real10);
    final Paint refp = Paint()
      ..color = const Color(0xFF8A8A95)
      ..strokeWidth = 1.0;
    for (double x = 0; x < size.width; x += 6) {
      canvas.drawLine(Offset(x, yr), Offset(x + 3, yr), refp);
    }
  }

  @override
  bool shouldRepaint(covariant _YieldCurvePainter old) =>
      old.y10 != y10 || old.y30 != y30 || old.real10 != real10;
}

class PanelCard extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;
  final Color titleColor;
  final bool glow;
  final Color glowColor;
  final EdgeInsetsGeometry padding;

  const PanelCard({
    super.key,
    required this.title,
    required this.child,
    this.trailing,
    this.titleColor = kDim,
    this.glow = false,
    this.glowColor = kAccent,
    this.padding = const EdgeInsets.fromLTRB(11, 9, 11, 11),
  });

  @override
  Widget build(BuildContext context) {
    // The accent tick always carries the brand green unless the title itself
    // is colored (e.g. the centerpiece), in which case they match.
    final Color tick = titleColor == kDim ? kAccent : titleColor;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.only(bottom: 8),
      padding: padding,
      decoration: BoxDecoration(
        color: kPanel,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: glow ? glowColor : kBorder,
          width: glow ? 1.4 : 1.0,
        ),
        boxShadow: glow
            ? [
                BoxShadow(
                    color: glowColor.withOpacity(0.18),
                    blurRadius: 8,
                    spreadRadius: 1)
              ]
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 2.5,
                height: 11,
                decoration: BoxDecoration(
                    color: tick, borderRadius: BorderRadius.circular(2)),
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: titleColor,
                    fontSize: 9.5,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.9,
                  ),
                ),
              ),
              if (trailing != null) trailing!,
            ],
          ),
          const SizedBox(height: 8),
          Container(height: 1, color: kBorder),
          const SizedBox(height: 9),
          child,
        ],
      ),
    );
  }
}

// ======================================================================
//  StatTile — a KPI cockpit hero tile. Label on top, big monospace value
//  on the bottom, optional sublabel + mini gauge. Clickable tiles plug
//  straight into the glow engine (same semantics as MetricCard).
// ======================================================================
class StatTile extends StatelessWidget {
  final String id;
  final String label;
  final String value;
  final Color valueColor;
  final String? sub;
  final double? bar; // 0..1 optional gauge
  final Color? barColor;
  final bool clickable;
  final bool prominent; // larger, tinted treatment for the dominant KPIs
  final HighlightState highlightState;

  const StatTile({
    super.key,
    required this.id,
    required this.label,
    required this.value,
    required this.valueColor,
    required this.highlightState,
    this.sub,
    this.bar,
    this.barColor,
    this.clickable = false,
    this.prominent = false,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: highlightState,
      builder: (context, _) {
        final bool isGlow = clickable && highlightState.isHighlighted(id);
        final Color glow = highlightState.activeGlowColor;

        return GestureDetector(
          onTap: clickable ? () => highlightState.toggleHighlight(id) : null,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
            decoration: BoxDecoration(
              color: prominent
                  ? Color.alphaBlend(valueColor.withOpacity(0.07), kPanel)
                  : kPanel,
              borderRadius: BorderRadius.circular(7),
              border: Border.all(
                color: isGlow
                    ? glow
                    : (prominent ? valueColor.withOpacity(0.30) : kBorder),
                width: (isGlow || prominent) ? 1.4 : 1.0,
              ),
              boxShadow: isGlow
                  ? [
                      BoxShadow(
                          color: glow.withOpacity(0.18),
                          blurRadius: 7,
                          spreadRadius: 1)
                    ]
                  : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      color: prominent ? kDim : kFaint,
                      fontSize: prominent ? 8.5 : 8,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.5),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Scale the headline value down rather than overflow a tile.
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Text(
                        value,
                        style: TextStyle(
                          color: isGlow ? glow : valueColor,
                          fontSize: prominent ? 23 : 15,
                          fontWeight: FontWeight.w700,
                          fontFamily: 'monospace',
                        ),
                      ),
                    ),
                    if (sub != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        sub!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: kDim,
                            fontSize: 7.5,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 0.3),
                      ),
                    ],
                    if (bar != null) ...[
                      const SizedBox(height: 4),
                      _miniBar(bar!, barColor ?? kAccent),
                    ],
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ======================================================================
//  MetricCard — compact clickable stat used throughout the panels.
//  Restyled for the new system; behavior (glow + tooltip + toggle) intact.
// ======================================================================
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
        final bool isGlow = highlightState.isHighlighted(id);
        final Color glow = highlightState.activeGlowColor;

        return Tooltip(
          message: _getRichTooltip(label),
          child: GestureDetector(
            onTap: onTap ?? () => highlightState.toggleHighlight(id),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 110,
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 6),
              decoration: BoxDecoration(
                color: kPanelHi,
                borderRadius: BorderRadius.circular(5),
                border: Border.all(
                  color: isGlow ? glow : color.withOpacity(0.22),
                  width: isGlow ? 1.4 : 1.0,
                ),
                boxShadow: isGlow
                    ? [
                        BoxShadow(
                            color: glow.withOpacity(0.2),
                            blurRadius: 5,
                            spreadRadius: 1)
                      ]
                    : null,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: const TextStyle(
                        color: kFaint,
                        fontSize: 7.5,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.3),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    value,
                    style: TextStyle(
                        color: isGlow ? glow : color,
                        fontSize: 11.5,
                        fontWeight: FontWeight.bold,
                        fontFamily: 'monospace'),
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

// ======================================================================
//  FormulaTraceWidget — intrinsic value reconciliation (A+B+C+D).
//  Reacts to JSF / MRI / component highlights. Restyled to the new system.
//  SUPERSEDED (Phase 4b): the old 4-term blend (REP/IS-IAI/ROV/exp) is no
//  longer the authoritative intrinsic; _valuationTriangulation renders the
//  triangulated breakdown + reconciliation. Retained (unused) for reference.
// ======================================================================
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

        Color diagramBorder = kBorder;
        if (isMriGlow) {
          diagramBorder = kAccent;
        } else if (isJsfGlow) {
          diagramBorder = Colors.orangeAccent;
        }

        Widget row(String label, String value, Color color, bool isGlowItem) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 1.5),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      color: isGlowItem ? Colors.white : const Color(0xFFCCCCCC),
                      fontWeight:
                          isGlowItem ? FontWeight.bold : FontWeight.normal,
                      fontSize: 9,
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
                const SizedBox(width: 6),
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

        return AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(11),
          decoration: BoxDecoration(
            color: kPanel,
            borderRadius: BorderRadius.circular(7),
            border: Border.all(
              color: diagramBorder,
              width: (isMriGlow || isJsfGlow) ? 1.4 : 1.0,
            ),
            boxShadow: (isMriGlow || isJsfGlow)
                ? [
                    BoxShadow(
                        color: diagramBorder.withOpacity(0.18),
                        blurRadius: 8,
                        spreadRadius: 1)
                  ]
                : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 2.5,
                    height: 11,
                    decoration: BoxDecoration(
                        color: kAccent, borderRadius: BorderRadius.circular(2)),
                  ),
                  const SizedBox(width: 7),
                  const Text(
                    "INTRINSIC FORMULA TRACE",
                    style: TextStyle(
                        fontSize: 9.5,
                        fontWeight: FontWeight.bold,
                        color: kDim,
                        letterSpacing: 0.9),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Container(height: 1, color: kBorder),
              const SizedBox(height: 8),
              row(
                "[A] 15% × REP Floor (\$${repFloor.toStringAsFixed(3)})",
                "\$${repComponent.toStringAsFixed(3)}",
                isRepGlow ? kAccent : Colors.white,
                isRepGlow,
              ),
              row(
                "[B] 70% × IS-IAI (\$${isIai.toStringAsFixed(3)}) × Forensic (${forensicPenalty.toStringAsFixed(3)}x)",
                "\$${isIaiComponent.toStringAsFixed(3)}",
                isIaiGlow ? Colors.orangeAccent : Colors.white,
                isIaiGlow || isJsfGlow,
              ),
              row(
                "[C] 15% × ROV (${rov.toStringAsFixed(2)})",
                "\$${rovComponent.toStringAsFixed(3)}",
                isRovGlow ? kAccent : Colors.white,
                isRovGlow || isMriGlow,
              ),
              row(
                "[D] Exp. Premium / Share",
                "\$${expPremium.toStringAsFixed(3)}",
                isPremiumGlow ? kAccent : Colors.white,
                isPremiumGlow,
              ),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 4),
                child: Divider(color: kBorder, height: 1),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    "● COMPUTED INTRINSIC (A+B+C+D)",
                    style: TextStyle(
                        color: kAccent,
                        fontWeight: FontWeight.bold,
                        fontSize: 9,
                        fontFamily: 'monospace'),
                  ),
                  Text(
                    "\$${computedIntrinsic.toStringAsFixed(3)}",
                    style: TextStyle(
                      fontSize: 10.5,
                      fontWeight: FontWeight.bold,
                      color: (computedIntrinsic - agaIntrinsic).abs() < 0.02
                          ? kAccent
                          : Colors.redAccent,
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

// ======================================================================
//  ConnectionIndicator — compact pulsing live/degraded/disconnected badge.
// ======================================================================
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
    Color indicatorColor = kAccent;
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
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(
          color: indicatorColor.withOpacity(0.1),
          border: Border.all(color: indicatorColor.withOpacity(0.35), width: 0.6),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: indicatorColor, size: 9),
            const SizedBox(width: 4),
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

// ======================================================================
//  Allocation-directive table cell builders.
//  These return `TableCell` DIRECTLY (TableCell is a ParentDataWidget and is
//  happiest as an immediate child of a TableRow), mirroring the v5.1 layout.
// ======================================================================
TableCell _thCell(String text, Alignment align) {
  return TableCell(
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 1),
      child: Align(
        alignment: align,
        child: Text(
          text,
          style: const TextStyle(
              color: kFaint,
              fontSize: 8,
              fontWeight: FontWeight.bold,
              fontFamily: 'monospace'),
        ),
      ),
    ),
  );
}

TableCell _tdCell(String text,
    {required Color color, required Alignment align, bool bold = false}) {
  return TableCell(
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 3.5, horizontal: 1),
      child: Align(
        alignment: align,
        child: Text(
          text,
          style: TextStyle(
              color: color,
              fontSize: 8.5,
              fontWeight: bold ? FontWeight.bold : FontWeight.normal,
              fontFamily: 'monospace'),
        ),
      ),
    ),
  );
}

// ======================================================================
//  _miniBar — a deterministic, rounded proportional bar (0..1).
//  Used by both the KPI MRI gauge and every Kelly sieve step.
// ======================================================================
Widget _miniBar(double frac, Color color) {
  final double f = frac.clamp(0.0, 1.0);
  return SizedBox(
    height: 3,
    child: ClipRRect(
      borderRadius: BorderRadius.circular(2),
      child: Stack(
        fit: StackFit.expand,
        children: [
          Container(color: const Color(0xFF1A1A1F)), // track
          // Left-anchored proportional fill. heightFactor:1.0 keeps the fill at
          // full bar height (without it an empty Container collapses to 0px),
          // and the explicit alignment anchors growth from the left edge.
          FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: f,
            heightFactor: 1.0,
            child: Container(
              decoration: BoxDecoration(
                color: color,
                boxShadow: [
                  BoxShadow(color: color.withOpacity(0.45), blurRadius: 3)
                ],
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

// ======================================================================
//  Rich tooltips — concise strategic context per metric (unchanged copy).
// ======================================================================
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
  if (cleanLabel.contains("CURRENT VALUE") || cleanLabel.contains("LIQUID VALUE")) {
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
