"""
M5 SensingProfile - the sim-to-real honesty hooks (X-15 hooks; live UI deferred).

A perfect simulator is the easiest thing to attack: "your robots know their
position exactly, real ones do not". These hooks let the engine degrade the
state that COORDINATION sees, while the engine itself keeps the true state.
That distinction is the whole point - the reported position carries noise, the
physics does not.

All noise is drawn from the engine's seeded RNG, so enabling noise does not
break determinism: the same seed still reproduces the same trace.
"""

from __future__ import annotations

from dataclasses import dataclass


# Frozen because a sensing profile is a value object: it is shared by every
# robot in a run and embedded in a frozen ScenarioSpec, so it must be hashable
# and must never be mutated mid-run (that would silently break determinism).
@dataclass(frozen=True)
class SensingProfile:
    """Imperfection model applied to REPORTED state, not to true state.


    localisation_sigma_m  Gaussian position error added to reported position.
    odometry_drift_m_per_m  Systematic drift accumulated per metre travelled.
    actuation_delay_ticks  Ticks between a verdict and the motion changing.
    intent_jitter_ticks  Ticks of jitter on intent publication.
    """

    localisation_sigma_m: float = 0.0
    odometry_drift_m_per_m: float = 0.0
    actuation_delay_ticks: int = 0
    intent_jitter_ticks: int = 0

    @property
    def enabled(self) -> bool:
        return (self.localisation_sigma_m > 0.0
                or self.odometry_drift_m_per_m > 0.0
                or self.actuation_delay_ticks > 0
                or self.intent_jitter_ticks > 0)

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "localisation_sigma_m": self.localisation_sigma_m,
            "odometry_drift_m_per_m": self.odometry_drift_m_per_m,
            "actuation_delay_ticks": self.actuation_delay_ticks,
            "intent_jitter_ticks": self.intent_jitter_ticks,
        }


# Default: a clean simulator. The knob exists and is honest about being off.
SENSING_IDEAL = SensingProfile()

# A defensible "realistic AMR" profile: 5 cm localisation sigma, 0.2% odometry
# drift, one tick of actuation lag. Values chosen to be conservative for an
# indoor LiDAR/SLAM AMR rather than flattering.
SENSING_REALISTIC = SensingProfile(
    localisation_sigma_m=0.05,
    odometry_drift_m_per_m=0.002,
    actuation_delay_ticks=1,
    intent_jitter_ticks=1,
)

# File contains AI-generated response based on internal company sources
