"""The six pure compute engines, mechanically split out of engine.py (Arch 2).

Import order matters in one respect only: engines.util installs the runtime signal shield as
an import side effect, and it is imported (directly, and first inside every class module that
pulls yfinance) before any heavy import here — preserving engine.py's original
shield-before-yfinance order. No module in this package imports engine.py (no cycles).
"""

from engines import util                                   # noqa: F401  (signal shield first)
from engines.macro_regime import MacroRegimeEngine
from engines.peer import PeerEngine
from engines.forensic import ForensicEngine
from engines.valuation import ValuationEngine
from engines.health_radar import HealthRadarEngine
from engines.sizer import PortfolioSizer

__all__ = [
    "MacroRegimeEngine",
    "PeerEngine",
    "ForensicEngine",
    "ValuationEngine",
    "HealthRadarEngine",
    "PortfolioSizer",
    "util",
]
