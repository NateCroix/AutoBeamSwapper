#!/usr/bin/env python3
"""
Powertrain Property Tweaks — Post-Processing Module
====================================================

Standalone post-processor that applies configurable property modifications to
adapted jbeam data dicts. Operates purely on in-memory Dict[str, Any] structures
— no file I/O, no imports from engineswap.py or other project modules.

Integration point:
    Called inside each generate_adapted_*() method in engineswap.py, immediately
    before _write_jbeam_file(). Receives the fully-adapted data dict, applies
    registered tweaks, and returns it (mutated in place).

Architecture:
    - Registry pattern: tweak functions are registered by config key via decorator.
    - TweakContext: immutable dataclass carrying upstream-extracted properties.
    - TweakResult: per-tweak audit record (what changed, old → new values).
    - Domain knowledge: shared constants, extraction helpers, and physics models
      available to all tweak functions via the PowertrainDomain namespace.

Usage from engineswap.py:
    from powertrain_tweaks import apply_tweaks, TweakContext

    ctx = TweakContext(component_type="engine", ...)
    results = apply_tweaks(adapted_data, tweak_config, ctx)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================

@dataclass(frozen=True)
class TweakContext:
    """
    Read-only upstream data available to all tweak functions.

    Populated by engineswap.py from data already extracted during the
    adaptation pipeline — no additional parsing required.

    Attributes:
        component_type: Which generate stage is calling ("engine",
                        "transmission", "transfercase").
        donor_drive_type: Camso donor drive type ("RWD", "FWD", "AWD", "4WD").
        donor_energy_type: Original requiredEnergyType before any tweak.
        donor_peak_torque: mainEngine.maxTorqueRating (Nm), if available.
        donor_peak_power_rpm: RPM at peak power, if extractable from torque table.
        donor_has_turbo: Whether a turbocharger part exists in the donor.
        target_vehicle_name: For logging / audit output.
        donor_torque_table: Raw mainEngine.torque LUT, cached as-is from the
                            donor jbeam. May be Camso 5-column format
                            [throttle, rpm, torque, fuelUsed, pressure] or
                            BeamNG 2-column format [rpm, torque]. Use
                            PowertrainDomain helpers to extract WOT curve,
                            functional redline, peak torque, etc.
        donor_idle_rpm: mainEngine.idleRPM from the donor.
    """
    component_type: str
    donor_drive_type: Optional[str] = None
    donor_energy_type: Optional[str] = None
    donor_peak_torque: Optional[float] = None
    donor_peak_power_rpm: Optional[float] = None
    donor_has_turbo: Optional[bool] = None
    target_vehicle_name: Optional[str] = None
    donor_torque_table: Optional[List[List[Any]]] = None
    donor_idle_rpm: Optional[float] = None


@dataclass
class TweakResult:
    """
    Audit record for a single tweak application.

    Attributes:
        tweak_name: Config key that triggered this tweak.
        applied: Whether the tweak actually mutated data.
        reason: Human-readable explanation (especially useful when not applied).
        mutations: Dict of property_path → (old_value, new_value) for audit.
    """
    tweak_name: str
    applied: bool
    reason: str = ""
    mutations: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)

    def summary_line(self) -> str:
        """One-line console summary."""
        if not self.applied:
            return f"  [{self.tweak_name}] skipped: {self.reason}"
        parts = []
        for prop, (old, new) in self.mutations.items():
            if isinstance(old, float) and isinstance(new, float):
                parts.append(f"{prop} {old:.4g}->{new:.4g}")
            else:
                parts.append(f"{prop} {old!r}->{new!r}")
        return f"  [{self.tweak_name}] {', '.join(parts)}"


# =============================================================================
# Domain Knowledge — Shared Physics Constants & Extraction Helpers
# =============================================================================

class PowertrainDomain:
    """
    Shared domain knowledge namespace for powertrain tweaks.

    Contains physical constants, unit conversions, extraction utilities, and
    empirical models that any tweak function can reference. This is the primary
    mechanism for sharing knowledge across tweaks and avoiding duplicated
    domain logic.

    All methods are static/classmethod — no instance state. This is a namespace,
    not a service.

    Sections:
        1. Unit conversions & physical constants
        2. JBeam structure navigation helpers
        3. Turbocharger physics models
        4. Torque converter physics models
        5. LUT (lookup table) manipulation utilities
        6. Torque table extraction helpers
    """

    # ── 1. Unit Conversions & Physical Constants ──────────────────────────

    PSI_TO_PASCAL = 6894.757      # 1 PSI in Pascals
    PASCAL_TO_BAR = 1e-5          # 1 Pascal in bar
    RPM_TO_RAD_S = math.pi / 30  # RPM → rad/s

    # BeamNG-specific: camsoTurbocharger.lua effective inertia formula
    # effective_inertia = 0.000003 * (jbeam_inertia * 100) * 2.5
    TURBO_INERTIA_SCALE = 0.000003 * 100 * 2.5  # = 0.00075

    # Atmospheric pressure baseline (Pa) for boost reference
    ATMOSPHERIC_PRESSURE_PA = 101325.0

    # Diesel engines: typical vacuum characteristics
    # Diesel has no throttle plate → no manifold vacuum at idle/cruise
    # Represented in BeamNG by near-zero or positive idle boost values
    DIESEL_IDLE_BOOST_PSI = 0.0   # no vacuum (vs gasoline ~ -3.5 PSI)

    # ── 2. JBeam Structure Navigation ────────────────────────────────────

    @staticmethod
    def find_part_with_section(
        adapted_data: Dict[str, Any],
        section_key: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Find the first part in adapted_data that contains a given section key.

        Returns (part_name, part_data) or None.

        Example:
            name, part = PowertrainDomain.find_part_with_section(data, "turbocharger")
            if part:
                turbo = part["turbocharger"]
        """
        for part_name, part_data in adapted_data.items():
            if isinstance(part_data, dict) and section_key in part_data:
                return (part_name, part_data)
        return None

    @staticmethod
    def find_all_parts_with_section(
        adapted_data: Dict[str, Any],
        section_key: str
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Find all parts containing a given section key."""
        results = []
        for part_name, part_data in adapted_data.items():
            if isinstance(part_data, dict) and section_key in part_data:
                results.append((part_name, part_data))
        return results

    @staticmethod
    def get_nested(
        data: Dict[str, Any],
        *keys: str,
        default: Any = None
    ) -> Any:
        """
        Safe nested dict access.

        Example:
            val = PowertrainDomain.get_nested(part, "mainEngine", "maxTorqueRating")
        """
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    @staticmethod
    def set_nested(
        data: Dict[str, Any],
        *keys_and_value: Any
    ) -> bool:
        """
        Safe nested dict set. Last argument is the value.

        Returns True if successfully set, False if path doesn't exist.

        Example:
            PowertrainDomain.set_nested(part, "mainEngine", "requiredEnergyType", "diesel")
        """
        if len(keys_and_value) < 2:
            return False
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        current = data
        for key in keys[:-1]:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return False
        if isinstance(current, dict):
            current[keys[-1]] = value
            return True
        return False

    # ── 3. Turbocharger Physics Models ───────────────────────────────────

    @staticmethod
    def effective_turbo_inertia(jbeam_inertia: float) -> float:
        """
        Convert jbeam turbocharger 'inertia' value to effective rotational
        inertia (kg·m²) as used by camsoTurbocharger.lua.

        The lua computes: 1 / (0.000003 * (inertia * 100) * 2.5)
        So effective inertia = 0.00075 * jbeam_inertia
        """
        return PowertrainDomain.TURBO_INERTIA_SCALE * jbeam_inertia

    @staticmethod
    def pressure_rate_to_response_time(rate_psi: float) -> float:
        """
        Approximate time constant (seconds) for boost pressure to reach
        target, given pressureRatePSI.

        The lua creates a TemporalSmoother with:
            up_rate   = 200 PSI/s  (fixed)
            down_rate = rate_psi PSI/s

        Spool-up is always fast (200 PSI/s). Spool-down is governed by this
        parameter. Lower rate = slower pressure bleed = more perceived lag
        on throttle lift.
        """
        if rate_psi <= 0:
            return float('inf')
        # Approximate time to decay from typical peak (~30 PSI) to atmospheric
        return 30.0 / rate_psi

    # ── 4. Torque Converter Physics Models ───────────────────────────────

    @staticmethod
    def is_automatic_transmission(adapted_data: Dict[str, Any]) -> bool:
        """
        Determine if the adapted_data represents an automatic transmission.

        Automatic transmissions are identified by having a 'torqueConverter'
        section in their jbeam data. Manual transmissions have a 'clutch'
        powertrain entry instead and should NOT receive torque converter tweaks.

        Note: Some Camso transfercase files also contain a 'torqueConverter'
        section as a drivability hack for rangebox variants — that is NOT
        a real automatic transmission and should be ignored. This check is
        designed to run on transmission-component data only.
        """
        return PowertrainDomain.find_part_with_section(
            adapted_data, "torqueConverter"
        ) is not None

    # Tighter TC Stall tuning knobs — exported as class constants so that
    # tests can compute expected values dynamically instead of hardcoding.
    # Change these values freely; tests will adapt automatically.
    TC_DIAMETER_MAX_INCREASE   = 0.28   # hard cap on diameter increase fraction
    TC_STIFFNESS_MAX_INCREASE  = 0.55   # hard cap on stiffness increase fraction
    TC_DIAMETER_RAMP_SCALAR    = 0.35   # sensitivity of diameter to torque broadness
    TC_STIFFNESS_RAMP_SCALAR   = 0.1    # baseline stiffness floor added to ramp

    @staticmethod
    def stall_speed_factor(diameter: float, stiffness: float) -> float:
        """
        Qualitative stall speed indicator from converter properties.

        Smaller diameter + lower stiffness = higher stall speed (more slip).
        Larger diameter + higher stiffness = lower stall speed (tighter coupling).

        This is a relative indicator, not an absolute RPM prediction.
        """
        if diameter <= 0:
            return 0.0
        return stiffness / (diameter * diameter)

    @staticmethod
    def lockup_engagement_rpm(base_rpm: float, lockup_range: float) -> float:
        """
        Approximate RPM at which TCC fully engages.

        lockup begins at torqueConverterLockupRPM
        lockup completes at torqueConverterLockupRPM + torqueConverterLockupRange
        """
        return base_rpm + lockup_range

    # ── 5. LUT (Lookup Table) Manipulation Utilities ─────────────────────

    @staticmethod
    def scale_lut_values(
        lut: List[List[Union[int, float]]],
        value_index: int,
        scale_factor: float
    ) -> List[List[Union[int, float]]]:
        """
        Scale values at a specific column index in a 2D LUT.

        Args:
            lut: List of rows, e.g. [[rpm, pressure], ...]
            value_index: Column to scale (0-based)
            scale_factor: Multiplicative factor

        Returns:
            New LUT with scaled values (original not mutated).
        """
        return [
            [
                row[i] * scale_factor if i == value_index else row[i]
                for i in range(len(row))
            ]
            for row in lut
        ]

    @staticmethod
    def offset_lut_values(
        lut: List[List[Union[int, float]]],
        value_index: int,
        offset: float
    ) -> List[List[Union[int, float]]]:
        """
        Add a constant offset to values at a specific column index in a 2D LUT.

        Returns:
            New LUT with offset values (original not mutated).
        """
        return [
            [
                row[i] + offset if i == value_index else row[i]
                for i in range(len(row))
            ]
            for row in lut
        ]

    @staticmethod
    def clamp_lut_values(
        lut: List[List[Union[int, float]]],
        value_index: int,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None
    ) -> List[List[Union[int, float]]]:
        """
        Clamp values in a LUT column to [min_val, max_val] range.

        Returns:
            New LUT with clamped values.
        """
        def _clamp(v):
            if min_val is not None:
                v = max(v, min_val)
            if max_val is not None:
                v = min(v, max_val)
            return v

        return [
            [
                _clamp(row[i]) if i == value_index else row[i]
                for i in range(len(row))
            ]
            for row in lut
        ]

    @staticmethod
    def interpolate_lut(
        lut: List[List[Union[int, float]]],
        x_value: float,
        x_index: int = 0,
        y_index: int = 1
    ) -> Optional[float]:
        """
        Linear interpolation on a sorted 2D LUT.

        Args:
            lut: Sorted list of [x, y, ...] rows
            x_value: Input value to interpolate at
            x_index: Column index for x (domain)
            y_index: Column index for y (range)

        Returns:
            Interpolated y value, or None if LUT is empty.
        """
        if not lut:
            return None
        if len(lut) == 1:
            return lut[0][y_index]

        # Clamp to LUT bounds
        if x_value <= lut[0][x_index]:
            return lut[0][y_index]
        if x_value >= lut[-1][x_index]:
            return lut[-1][y_index]

        # Find surrounding points
        for i in range(len(lut) - 1):
            x0 = lut[i][x_index]
            x1 = lut[i + 1][x_index]
            if x0 <= x_value <= x1:
                if x1 == x0:
                    return lut[i][y_index]
                t = (x_value - x0) / (x1 - x0)
                y0 = lut[i][y_index]
                y1 = lut[i + 1][y_index]
                return y0 + t * (y1 - y0)

        return lut[-1][y_index]

    # ── 6. Torque Table Extraction Helpers ────────────────────────────────
    #
    # The donor engine's raw mainEngine.torque table is cached on TweakContext
    # and available to ALL tweak functions (engine, transmission, transfercase).
    # These helpers parse the raw table into usable derived values.
    #
    # Two table formats exist:
    #   Camso 5-column: [throttle, rpm, torque, FuelUsed, Pressure]
    #                   101 throttle levels (0–100), each with a full RPM sweep.
    #                   Throttle=100 rows are the WOT (wide-open throttle) curve.
    #   BeamNG 2-column: [rpm, torque]
    #                    Single WOT curve (implicitly 100% throttle).

    @staticmethod
    def _is_header_row(row: List[Any]) -> bool:
        """Check if a row is a header (contains strings)."""
        return any(isinstance(v, str) for v in row)

    @staticmethod
    def detect_torque_table_format(
        table: List[List[Any]]
    ) -> Optional[str]:
        """
        Detect the format of a raw mainEngine.torque table.

        Returns:
            "camso_5col" — 5+ column format with throttle indexing
            "beamng_2col" — 2-column RPM/torque (implicit 100% throttle)
            None — empty or unrecognizable table
        """
        if not table:
            return None
        for row in table:
            if PowertrainDomain._is_header_row(row):
                continue
            if len(row) >= 5:
                return "camso_5col"
            elif len(row) == 2:
                return "beamng_2col"
            else:
                return None
        return None

    @staticmethod
    def extract_wot_curve(
        table: Optional[List[List[Any]]]
    ) -> List[List[float]]:
        """
        Extract the wide-open throttle (WOT) curve from a raw torque table.

        For Camso 5-column tables, filters to throttle=100 rows and extracts
        [rpm, torque]. For BeamNG 2-column tables, returns all data rows as
        [rpm, torque]. Header rows are always skipped.

        Returns:
            List of [rpm, torque] pairs, sorted ascending by RPM.
            Empty list if table is None or unrecognizable.
        """
        if not table:
            return []

        fmt = PowertrainDomain.detect_torque_table_format(table)
        if fmt is None:
            return []

        wot: List[List[float]] = []

        if fmt == "camso_5col":
            # throttle=col[0], rpm=col[1], torque=col[2]
            for row in table:
                if PowertrainDomain._is_header_row(row):
                    continue
                if row[0] == 100:
                    wot.append([float(row[1]), float(row[2])])
        elif fmt == "beamng_2col":
            # rpm=col[0], torque=col[1]
            for row in table:
                if PowertrainDomain._is_header_row(row):
                    continue
                wot.append([float(row[0]), float(row[1])])

        return wot

    @staticmethod
    def functional_redline(wot_curve: List[List[float]]) -> Optional[float]:
        """
        Return the highest RPM value in the WOT curve.

        This is the *operating* redline — the last RPM point in the torque
        table where data exists. NOT the same as mainEngine.maxRPM, which in
        Camso engines is typically 12000 (overspeed damage threshold) and is
        meaningless for transmission tuning context.

        Returns:
            Highest RPM as float, or None if curve is empty.
        """
        if not wot_curve:
            return None
        return max(row[0] for row in wot_curve)

    @staticmethod
    def peak_torque(
        wot_curve: List[List[float]]
    ) -> Optional[Tuple[float, float]]:
        """
        Find the peak torque point on the WOT curve.

        Returns:
            (rpm, torque_nm) tuple for the row with maximum torque,
            or None if curve is empty.
        """
        if not wot_curve:
            return None
        best = max(wot_curve, key=lambda row: row[1])
        return (best[0], best[1])

    @staticmethod
    def ramp65_torque_rpm(wot_curve: List[List[float]]) -> Optional[float]:
        """
        Find the lowest RPM at which torque exceeds 65% of peak torque.

        This represents the point where the engine enters its "usable power
        band" — relevant for lockup engagement, shift scheduling, and
        turbo spool targets.

        Returns:
            RPM as float, or None if curve is empty or threshold never met.
        """
        if not wot_curve:
            return None
        peak = PowertrainDomain.peak_torque(wot_curve)
        if peak is None:
            return None
        threshold = 0.65 * peak[1]
        # Scan ascending RPM for first row exceeding threshold
        sorted_curve = sorted(wot_curve, key=lambda row: row[0])
        for row in sorted_curve:
            if row[1] >= threshold:
                return row[0]
        return None


# =============================================================================
# Tweak Registry
# =============================================================================

# Maps (component_type, config_key) → tweak function
_TWEAK_REGISTRY: Dict[Tuple[str, str], Callable] = {}


def register_tweak(component_type: str, config_key: str):
    """
    Decorator to register a tweak function.

    Usage:
        @register_tweak("engine", "requiredEnergyType")
        def tweak_required_energy_type(adapted_data, params, ctx):
            ...
    """
    def decorator(func: Callable) -> Callable:
        _TWEAK_REGISTRY[(component_type, config_key)] = func
        return func
    return decorator


def list_registered_tweaks() -> List[Tuple[str, str, str]]:
    """Return list of (component_type, config_key, function_name) for all registered tweaks."""
    return [
        (comp, key, func.__name__)
        for (comp, key), func in _TWEAK_REGISTRY.items()
    ]


# =============================================================================
# Public API
# =============================================================================

def apply_tweaks(
    adapted_data: Dict[str, Any],
    tweak_config: Dict[str, Any],
    ctx: TweakContext
) -> List[TweakResult]:
    """
    Apply all configured tweaks to an adapted_data dict.

    This is the sole entry point called by engineswap.py.

    Args:
        adapted_data: The fully-adapted jbeam data dict (mutated in place).
        tweak_config: The "powertrain_tweaks" section from swap_parameters,
                      structured as {"engine": {...}, "transmission": {...}}.
        ctx: Immutable context with upstream-extracted properties.

    Returns:
        List of TweakResult audit records (one per attempted tweak).
    """
    results: List[TweakResult] = []

    if not tweak_config.get("enabled", True):
        return results

    # Get the sub-config for this component type
    component_config = tweak_config.get(ctx.component_type, {})
    if not component_config:
        return results

    for config_key, params in component_config.items():
        registry_key = (ctx.component_type, config_key)
        tweak_func = _TWEAK_REGISTRY.get(registry_key)

        if tweak_func is None:
            logger.warning(
                f"[powertrain_tweaks] Unknown tweak key '{config_key}' "
                f"for component '{ctx.component_type}' — skipping"
            )
            results.append(TweakResult(
                tweak_name=config_key,
                applied=False,
                reason=f"No registered handler for '{ctx.component_type}.{config_key}'"
            ))
            continue

        try:
            result = tweak_func(adapted_data, params, ctx)
            results.append(result)
        except Exception as e:
            logger.error(
                f"[powertrain_tweaks] Error in '{config_key}': {e}",
                exc_info=True
            )
            results.append(TweakResult(
                tweak_name=config_key,
                applied=False,
                reason=f"Error: {e}"
            ))

    return results


def format_results_summary(results: List[TweakResult]) -> str:
    """Format a multi-line summary of tweak results for console output."""
    if not results:
        return ""
    lines = ["=== Powertrain Tweaks ==="]
    for r in results:
        lines.append(r.summary_line())
    return "\n".join(lines)


# =============================================================================
# Phase A Tweaks — Engine
# =============================================================================

@register_tweak("engine", "requiredEnergyType")
def tweak_required_energy_type(
    adapted_data: Dict[str, Any],
    params: str,
    ctx: TweakContext
) -> TweakResult:
    """
    Transform the engine's requiredEnergyType property.

    Params:
        params: Target energy type string ("gasoline", "diesel", "compressedGas").

    Targets:
        mainEngine.requiredEnergyType (string)

    Notes:
        - This is a simple string replacement.
        - For diesel conversion, pair with "convert_to_turbodiesel" tweak which
          handles the associated turbo/vacuum behavioral changes.
        - compressedGas (CNG/LPG) may need fuelLiquidDensity + energyDensity
          adjustments in a future extension.
    """
    VALID_TYPES = {"gasoline", "diesel", "compressedGas"}
    if params not in VALID_TYPES:
        return TweakResult(
            tweak_name="requiredEnergyType",
            applied=False,
            reason=f"Invalid energy type '{params}'. Valid: {VALID_TYPES}"
        )

    result = PowertrainDomain.find_part_with_section(adapted_data, "mainEngine")
    if not result:
        return TweakResult(
            tweak_name="requiredEnergyType",
            applied=False,
            reason="No part with 'mainEngine' section found"
        )

    part_name, part_data = result
    engine = part_data["mainEngine"]
    old_value = engine.get("requiredEnergyType", "gasoline")

    if old_value == params:
        return TweakResult(
            tweak_name="requiredEnergyType",
            applied=False,
            reason=f"Already set to '{params}'"
        )

    engine["requiredEnergyType"] = params

    return TweakResult(
        tweak_name="requiredEnergyType",
        applied=True,
        mutations={"requiredEnergyType": (old_value, params)}
    )


# =============================================================================
# Phase B Tweaks — Transmission
# =============================================================================

@register_tweak("transmission", "tighter_tc_stall")
def tweak_tighter_tc_stall(
    adapted_data: Dict[str, Any],
    params: float,
    ctx: TweakContext
) -> TweakResult:
    """
    Tighten the torque converter stall characteristics for improved drivability.

    Params:
        params: Float 0.0–1.0. 0.0 = no change, 1.0 = maximum tightening.

    Targets:
        torqueConverter.converterDiameter  — increased (larger = tighter coupling)
        torqueConverter.converterStiffness — increased (stiffer = less slip)

    Physics:
        A tighter converter reduces stall speed, meaning the engine must spin
        faster before the converter begins transmitting torque effectively.
        In practice this means:
        - Less "flare" on launch (lower stall RPM)
        - Quicker lockup feel at cruise
        - Slightly reduced low-speed torque multiplication

        Camso converters tend to be modeled with conservative (loose) stall
        characteristics. Real OEM converters are often tighter than Camso defaults.

    Scaling approach (torque-curve-aware):
        The scaling factors are dynamically computed from the donor engine's
        torque characteristics via the ramp65/redline ratio. Engines with a
        higher ramp65_torque_rpm relative to their redline (i.e. peaky power
        band) receive less aggressive tightening; engines with a broad,
        low-onset torque curve receive more.

        ramp65_redline_ratio = ramp65_torque_rpm / functional_redline

        converterDiameter:
            diameter_ramp_extra = DIAMETER_RAMP_SCALAR * (1 - ramp65_redline_ratio)
            scale = 1.0 + params * diameter_ramp_extra, capped at DIAMETER_MAX_INCREASE
            → broad torque band → higher extra → more diameter increase

        converterStiffness:
            stiffness_ramp_extra = (1 - ramp65_redline_ratio) + STIFFNESS_RAMP_SCALAR
            scale = 1.0 + params * stiffness_ramp_extra, capped at STIFFNESS_MAX_INCREASE
            → stiffness floor via STIFFNESS_RAMP_SCALAR ensures minimum tightening
            → truncated to 1 decimal place for cleaner jbeam diffs

        Fallback: when no donor torque table is available, ramp_extra values
        default to the MAX caps, preserving the original fixed-scaling behavior.
    """
    # ── Tuning knobs (sourced from PowertrainDomain class constants) ────────
    DIAMETER_MAX_INCREASE   = PowertrainDomain.TC_DIAMETER_MAX_INCREASE
    STIFFNESS_MAX_INCREASE  = PowertrainDomain.TC_STIFFNESS_MAX_INCREASE
    DIAMETER_RAMP_SCALAR    = PowertrainDomain.TC_DIAMETER_RAMP_SCALAR
    STIFFNESS_RAMP_SCALAR   = PowertrainDomain.TC_STIFFNESS_RAMP_SCALAR

    # Validate parameter range
    try:
        factor = float(params)
    except (TypeError, ValueError):
        return TweakResult(
            tweak_name="tighter_tc_stall",
            applied=False,
            reason=f"Invalid parameter '{params}' — expected float 0.0–1.0"
        )

    factor = max(0.0, min(1.0, factor))
    if factor == 0.0:
        return TweakResult(
            tweak_name="tighter_tc_stall",
            applied=False,
            reason="Factor is 0.0 — no change requested"
        )

    # Guard: only applies to automatic transmissions (torqueConverter present)
    if not PowertrainDomain.is_automatic_transmission(adapted_data):
        return TweakResult(
            tweak_name="tighter_tc_stall",
            applied=False,
            reason="Not an automatic transmission (no torqueConverter section)"
        )

    # Find the torqueConverter section
    result = PowertrainDomain.find_part_with_section(adapted_data, "torqueConverter")
    if not result:
        return TweakResult(
            tweak_name="tighter_tc_stall",
            applied=False,
            reason="No part with 'torqueConverter' section found"
        )

    part_name, part_data = result
    tc = part_data["torqueConverter"]
    mutations = {}

    # ── Compute dynamic ramp values from donor torque curve ──────────
    # Fallback: use MAX caps directly (preserves original fixed behavior)
    diameter_ramp_extra = DIAMETER_MAX_INCREASE
    stiffness_ramp_extra = STIFFNESS_MAX_INCREASE

    if ctx.donor_torque_table:
        wot = PowertrainDomain.extract_wot_curve(ctx.donor_torque_table)
        redline = PowertrainDomain.functional_redline(wot)
        ramp65 = PowertrainDomain.ramp65_torque_rpm(wot)
        if redline and redline > 0 and ramp65 is not None:
            ramp65_redline_ratio = ramp65 / redline
            diameter_ramp_extra = DIAMETER_RAMP_SCALAR * (1 - ramp65_redline_ratio)
            stiffness_ramp_extra = (1 - ramp65_redline_ratio) + STIFFNESS_RAMP_SCALAR

    # Scale converterDiameter (capped at DIAMETER_MAX_INCREASE)
    old_diameter = tc.get("converterDiameter")
    if old_diameter is not None and isinstance(old_diameter, (int, float)):
        diameter_increase = min(factor * diameter_ramp_extra, DIAMETER_MAX_INCREASE)
        diameter_scale = 1.0 + diameter_increase
        new_diameter = round(old_diameter * diameter_scale, 14)
        tc["converterDiameter"] = new_diameter
        mutations["converterDiameter"] = (old_diameter, new_diameter)

    # Scale converterStiffness (capped at STIFFNESS_MAX_INCREASE)
    old_stiffness = tc.get("converterStiffness")
    if old_stiffness is not None and isinstance(old_stiffness, (int, float)):
        stiffness_increase = min(factor * stiffness_ramp_extra, STIFFNESS_MAX_INCREASE)
        stiffness_scale = 1.0 + stiffness_increase
        new_stiffness = math.floor(old_stiffness * stiffness_scale * 10) / 10
        tc["converterStiffness"] = new_stiffness
        mutations["converterStiffness"] = (old_stiffness, new_stiffness)

    if not mutations:
        return TweakResult(
            tweak_name="tighter_tc_stall",
            applied=False,
            reason="converterDiameter and converterStiffness not found as numeric values"
        )

    return TweakResult(
        tweak_name="tighter_tc_stall",
        applied=True,
        mutations=mutations
    )


@register_tweak("transmission", "modern_tcc_lockup")
def tweak_modern_tcc_lockup(
    adapted_data: Dict[str, Any],
    params: int,
    ctx: TweakContext
) -> TweakResult:
    """
    Configure torque converter clutch lockup to engage at a lower gear.

    Params:
        params: Integer gear number for minimum lockup (e.g. 2 = lock from 2nd gear).

    Targets:
        vehicleController.torqueConverterLockupMinGear — set directly
        
        vehicleController.torqueConverterLockupRPM     — adjusted so that:
        new_torqueConverterLockupRPM = (((engine_redline - original_torqueConverterLockupRPM) * LOCKUP_KNOB) + original_torqueConverterLockupRPM) - slightly higher lockup RPM scaled by engine redline.
        
        vehicleController.torqueConverterLockupRange   — adjusted so that:
        new_torqueConverterLockupRange = (RANGE_KNOB * ((new_torqueConverterLockupRPM - original_torqueConverterLockupRPM) + old_torqueConverterLockupRange)) - wider lockup range

    Physics:
        Modern transmissions lock the torque converter much earlier than older
        designs — often by 2nd or 3rd gear — to improve fuel economy and reduce
        heat buildup. Camso transmissions typically default to locking at gear 5+,
        which is unrealistically late for most modern vehicles.

        When lowering lockup gear, we also adjust engagement RPM and range:
        - Lower lockup gear → need lower engagement RPM to avoid shudder
        - Wider lockup range → smoother engagement transition

    Adjustment strategy:
        MinGear:       set to params value directly
        LockupRPM:     new = ((engine_redline - old_RPM) * LOCKUP_KNOB) + old_RPM
                       Slightly raises lockup RPM proportional to engine redline
                       headroom. Higher-revving engines get a larger absolute
                       increase, keeping the lockup point physically appropriate.
        LockupRange:   new = RANGE_KNOB * ((new_RPM - old_RPM) + old_Range)
                       Scales the transition window to accommodate the RPM shift,
                       keeping the ramp-in smooth at the new engagement point.
    """
    # ── Tuning knobs ─────────────────────────────────────────────────────
    # Adjust these to prototype different lockup feel without touching
    # the rest of the function.
    LOCKUP_KNOB = 0.05   # Fraction of (redline - old_RPM) added to lockup RPM
    RANGE_KNOB  = 1.0    # Multiplier on the combined RPM-shift + old range

    # Fallback redline if donor torque table is not available on context.
    FALLBACK_REDLINE = 6500

    # Extract functional redline from the donor engine torque curve when
    # available. Falls back to a hardcoded value for safety.
    engine_redline = FALLBACK_REDLINE
    if ctx.donor_torque_table:
        wot = PowertrainDomain.extract_wot_curve(ctx.donor_torque_table)
        extracted = PowertrainDomain.functional_redline(wot)
        if extracted is not None:
            engine_redline = extracted

    try:
        target_gear = int(params)
    except (TypeError, ValueError):
        return TweakResult(
            tweak_name="modern_tcc_lockup",
            applied=False,
            reason=f"Invalid parameter '{params}' — expected integer gear number"
        )

    if target_gear < 1:
        return TweakResult(
            tweak_name="modern_tcc_lockup",
            applied=False,
            reason=f"Gear {target_gear} is invalid — minimum is 1"
        )

    # Guard: only applies to automatic transmissions (torqueConverter present)
    if not PowertrainDomain.is_automatic_transmission(adapted_data):
        return TweakResult(
            tweak_name="modern_tcc_lockup",
            applied=False,
            reason="Not an automatic transmission (no torqueConverter section)"
        )

    # Find the vehicleController section
    result = PowertrainDomain.find_part_with_section(adapted_data, "vehicleController")
    if not result:
        return TweakResult(
            tweak_name="modern_tcc_lockup",
            applied=False,
            reason="No part with 'vehicleController' section found"
        )

    part_name, part_data = result
    vc = part_data["vehicleController"]
    mutations = {}

    # Set minimum lockup gear
    old_min_gear = vc.get("torqueConverterLockupMinGear")
    if old_min_gear is not None:
        vc["torqueConverterLockupMinGear"] = target_gear
        mutations["torqueConverterLockupMinGear"] = (old_min_gear, target_gear)
    else:
        # torqueConverterLockupMinGear doesn't exist — inject it
        vc["torqueConverterLockupMinGear"] = target_gear
        mutations["torqueConverterLockupMinGear"] = (None, target_gear)

    # Adjust lockup RPM: slightly higher, scaled by engine redline headroom
    # new_RPM = ((engine_redline - old_RPM) * LOCKUP_KNOB) + old_RPM
    old_rpm = vc.get("torqueConverterLockupRPM")
    new_rpm = None
    if isinstance(old_rpm, (int, float)):
        new_rpm = ((engine_redline - old_rpm) * LOCKUP_KNOB) + old_rpm
        new_rpm = round(new_rpm)
        vc["torqueConverterLockupRPM"] = new_rpm
        mutations["torqueConverterLockupRPM"] = (old_rpm, new_rpm)

    # Adjust lockup range: scale to accommodate the RPM shift
    # new_Range = RANGE_KNOB * ((new_RPM - old_RPM) + old_Range)
    old_range = vc.get("torqueConverterLockupRange")
    if isinstance(old_range, (int, float)) and new_rpm is not None and old_rpm is not None:
        rpm_delta = new_rpm - old_rpm
        new_range = RANGE_KNOB * (rpm_delta + old_range)
        new_range = round(new_range)
        vc["torqueConverterLockupRange"] = new_range
        mutations["torqueConverterLockupRange"] = (old_range, new_range)

    if not mutations:
        return TweakResult(
            tweak_name="modern_tcc_lockup",
            applied=False,
            reason="No lockup properties found to modify"
        )

    return TweakResult(
        tweak_name="modern_tcc_lockup",
        applied=True,
        mutations=mutations
    )
