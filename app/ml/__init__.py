"""M3 advisory layer.

Everything in this package is ADVISORY. Architectural law 3: the ML layer is
never in the safety path. The package deliberately imports nothing from
app.coordination, and nothing in app.coordination imports from here, so the
separation is structural rather than a convention that could erode.

Exports:
  Forecaster / Advisory / ZoneForecast  - X-20 congestion prediction
  BudgetMeter / BudgetSample           - X-04 real-time compute budget meter
  Firewall                             - the law-3 override counter
"""

from app.ml.budget import BUDGET_MS, BudgetMeter, BudgetSample, Firewall
from app.ml.forecast import (
    CAPACITY,
    HORIZON_TICKS,
    MIN_CONFIDENCE,
    ZONE_M,
    Advisory,
    Forecaster,
    ZoneForecast,
    zone_of,
)

__all__ = [
    "Advisory",
    "BUDGET_MS",
    "BudgetMeter",
    "BudgetSample",
    "CAPACITY",
    "Firewall",
    "Forecaster",
    "HORIZON_TICKS",
    "MIN_CONFIDENCE",
    "ZONE_M",
    "ZoneForecast",
    "zone_of",
]
