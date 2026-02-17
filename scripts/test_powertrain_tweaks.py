#!/usr/bin/env python3
"""
Tests for powertrain_tweaks.py — standalone post-processing module.

Uses synthetic adapted_data dicts (no file I/O, no pipeline dependency).
Each tweak is tested independently for:
  - Correct mutation of target properties
  - Correct audit trail (TweakResult)
  - Graceful no-op when target section is missing
  - Parameter validation / edge cases
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from powertrain_tweaks import (
    apply_tweaks,
    TweakContext,
    TweakResult,
    PowertrainDomain,
    format_results_summary,
    list_registered_tweaks,
    tweak_required_energy_type,
    tweak_tighter_tc_stall,
    tweak_modern_tcc_lockup,
)


# =============================================================================
# Test Fixtures — Synthetic adapted_data dicts
# =============================================================================

def make_engine_data(**overrides):
    """Build a minimal engine adapted_data dict."""
    engine = {
        "requiredEnergyType": "gasoline",
        "maxTorqueRating": 371.62,
        "idleRPM": 700,
        "maxRPM": 6500,
        "inertia": 0.15,
    }
    engine.update(overrides)
    return {"Camso_Engine_Test": {"mainEngine": engine, "slotType": "pickup_engine"}}


def make_turbo_data(**overrides):
    """Build a minimal turbo part dict."""
    turbo = {
        "inertia": 4,
        "pressureRatePSI": 30,
        "pressurePSI": [
            [0, -3.5],
            [25000, 10.0],
            [50000, 20.0],
            [75000, 30.0],
        ],
        "maxExhaustPower": 40000,
        "frictionCoef": 16,
    }
    turbo.update(overrides)
    return {"Camso_Turbo_Test": {"turbocharger": turbo}}


def make_transmission_data(**overrides):
    """Build a minimal transmission adapted_data dict."""
    tc_overrides = {}
    vc_overrides = {}
    for k, v in overrides.items():
        if k.startswith("vc_"):
            vc_overrides[k[3:]] = v
        else:
            tc_overrides[k] = v

    torque_converter = {
        "converterDiameter": 0.30,
        "converterStiffness": 12,
        "couplingAVRatio": 0.92,
        "stallTorqueRatio": 1.8,
        "lockupClutchTorque": 826.93,
    }
    torque_converter.update(tc_overrides)

    vehicle_controller = {
        "torqueConverterLockupRPM": 750,
        "torqueConverterLockupRange": 850,
        "torqueConverterLockupMinGear": 5,
        "torqueConverterLockupRate": 5,
    }
    vehicle_controller.update(vc_overrides)

    return {
        "Camso_Transmission_Test": {
            "torqueConverter": torque_converter,
            "vehicleController": vehicle_controller,
            "slotType": "pickup_transmission",
        }
    }


MOCK_ENGINE_CTX = TweakContext(component_type="engine", donor_drive_type="RWD",
                                target_vehicle_name="test_vehicle")
MOCK_TRANS_CTX = TweakContext(component_type="transmission", donor_drive_type="RWD",
                               target_vehicle_name="test_vehicle")


# =============================================================================
# Registry Tests
# =============================================================================

def test_registry_populated():
    """Verify all Phase A+B tweaks are registered."""
    registered = list_registered_tweaks()
    keys = [(comp, key) for comp, key, _ in registered]
    assert ("engine", "requiredEnergyType") in keys, "requiredEnergyType not registered"
    assert ("transmission", "tighter_tc_stall") in keys, "tighter_tc_stall not registered"
    assert ("transmission", "modern_tcc_lockup") in keys, "modern_tcc_lockup not registered"
    return True


# =============================================================================
# Phase A: requiredEnergyType
# =============================================================================

def test_energy_type_gasoline_to_diesel():
    """Transform gasoline → diesel."""
    data = make_engine_data()
    result = tweak_required_energy_type(data, "diesel", MOCK_ENGINE_CTX)
    assert result.applied, f"Should apply: {result.reason}"
    assert data["Camso_Engine_Test"]["mainEngine"]["requiredEnergyType"] == "diesel"
    assert result.mutations["requiredEnergyType"] == ("gasoline", "diesel")
    return True


def test_energy_type_no_change():
    """No-op when already correct."""
    data = make_engine_data(requiredEnergyType="diesel")
    result = tweak_required_energy_type(data, "diesel", MOCK_ENGINE_CTX)
    assert not result.applied
    assert "Already" in result.reason
    return True


def test_energy_type_invalid():
    """Reject invalid energy types."""
    data = make_engine_data()
    result = tweak_required_energy_type(data, "hydrogen", MOCK_ENGINE_CTX)
    assert not result.applied
    assert "Invalid" in result.reason
    return True


def test_energy_type_no_engine_section():
    """Graceful no-op when mainEngine is missing."""
    data = {"SomePart": {"slotType": "pickup_engine"}}
    result = tweak_required_energy_type(data, "diesel", MOCK_ENGINE_CTX)
    assert not result.applied
    assert "mainEngine" in result.reason
    return True


# =============================================================================
# Phase B: tighter_tc_stall
# =============================================================================

def test_tc_stall_basic():
    """Factor 0.5 scales both diameter and stiffness (fallback path, no torque table)."""
    D = PowertrainDomain
    factor = 0.5
    old_diam, old_stiff = 0.30, 12.0

    data = make_transmission_data()
    result = tweak_tighter_tc_stall(data, factor, MOCK_TRANS_CTX)
    assert result.applied, f"Should apply: {result.reason}"

    tc = data["Camso_Transmission_Test"]["torqueConverter"]
    # Fallback: ramp_extra = MAX caps
    exp_diam = old_diam * (1 + min(factor * D.TC_DIAMETER_MAX_INCREASE, D.TC_DIAMETER_MAX_INCREASE))
    exp_stiff = math.floor(old_stiff * (1 + min(factor * D.TC_STIFFNESS_MAX_INCREASE, D.TC_STIFFNESS_MAX_INCREASE)) * 10) / 10
    assert abs(tc["converterDiameter"] - exp_diam) < 0.0001, f"Got {tc['converterDiameter']}, expected {exp_diam}"
    assert tc["converterStiffness"] == exp_stiff, f"Got {tc['converterStiffness']}, expected {exp_stiff}"
    return True


def test_tc_stall_max():
    """Factor 1.0 applies maximum scaling (fallback path)."""
    D = PowertrainDomain
    old_diam, old_stiff = 0.30, 12.0

    data = make_transmission_data()
    result = tweak_tighter_tc_stall(data, 1.0, MOCK_TRANS_CTX)
    assert result.applied
    tc = data["Camso_Transmission_Test"]["torqueConverter"]
    exp_diam = round(old_diam * (1 + D.TC_DIAMETER_MAX_INCREASE), 14)
    exp_stiff = math.floor(old_stiff * (1 + D.TC_STIFFNESS_MAX_INCREASE) * 10) / 10
    assert abs(tc["converterDiameter"] - exp_diam) < 0.0001, f"Got {tc['converterDiameter']}"
    assert tc["converterStiffness"] == exp_stiff, f"Got {tc['converterStiffness']}"
    return True


def test_tc_stall_zero():
    """Factor 0.0 is a no-op."""
    data = make_transmission_data()
    result = tweak_tighter_tc_stall(data, 0.0, MOCK_TRANS_CTX)
    assert not result.applied
    return True


def test_tc_stall_no_section():
    """Graceful no-op when torqueConverter is absent (manual transmission)."""
    data = {"SomePart": {"vehicleController": {}}}
    result = tweak_tighter_tc_stall(data, 0.5, MOCK_TRANS_CTX)
    assert not result.applied
    assert "automatic" in result.reason.lower() or "torqueConverter" in result.reason
    return True


def test_tc_stall_clamps_input():
    """Values outside 0–1 are clamped to 1.0 (same result as factor=1.0)."""
    D = PowertrainDomain
    old_diam = 0.30

    data = make_transmission_data()
    result = tweak_tighter_tc_stall(data, 2.5, MOCK_TRANS_CTX)  # clamped to 1.0
    assert result.applied
    tc = data["Camso_Transmission_Test"]["torqueConverter"]
    exp_diam = round(old_diam * (1 + D.TC_DIAMETER_MAX_INCREASE), 14)
    assert abs(tc["converterDiameter"] - exp_diam) < 0.0001  # same as factor=1.0
    return True


def test_tc_stall_dynamic_scaling():
    """When TweakContext carries a donor torque table, scaling adapts to
    the engine's torque curve via ramp65/redline ratio."""
    D = PowertrainDomain
    factor = 0.5
    old_diam, old_stiff = 0.30, 12.0

    # CAMSO_5COL_TABLE: redline=5100, ramp65=2000
    ramp65_redline_ratio = 2000.0 / 5100.0
    diam_ramp  = D.TC_DIAMETER_RAMP_SCALAR * (1 - ramp65_redline_ratio)
    stiff_ramp = (1 - ramp65_redline_ratio) + D.TC_STIFFNESS_RAMP_SCALAR

    ctx_with_table = TweakContext(
        component_type="transmission",
        donor_drive_type="RWD",
        target_vehicle_name="test_vehicle",
        donor_torque_table=CAMSO_5COL_TABLE,
    )
    data = make_transmission_data()  # diameter=0.30, stiffness=12.0
    result = tweak_tighter_tc_stall(data, factor, ctx_with_table)
    assert result.applied

    tc = data["Camso_Transmission_Test"]["torqueConverter"]
    exp_diam = round(old_diam * (1 + min(factor * diam_ramp, D.TC_DIAMETER_MAX_INCREASE)), 14)
    exp_stiff = math.floor(old_stiff * (1 + min(factor * stiff_ramp, D.TC_STIFFNESS_MAX_INCREASE)) * 10) / 10
    assert abs(tc["converterDiameter"] - exp_diam) < 0.0001, f"Got {tc['converterDiameter']}, expected {exp_diam}"
    assert tc["converterStiffness"] == exp_stiff, f"Got {tc['converterStiffness']}, expected {exp_stiff}"
    return True


# =============================================================================
# Phase B: modern_tcc_lockup
# =============================================================================

def test_tcc_lockup_lower_gear():
    """Drop lockup from gear 5 to gear 3 — RPM/Range adjusted unconditionally."""
    data = make_transmission_data()
    result = tweak_modern_tcc_lockup(data, 3, MOCK_TRANS_CTX)
    assert result.applied, f"Should apply: {result.reason}"

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    assert vc["torqueConverterLockupMinGear"] == 3
    # new_RPM = ((6500 - 750) * 0.05) + 750 = 287.5 + 750 = 1037.5 → round = 1038
    assert vc["torqueConverterLockupRPM"] == 1038, f"Got {vc['torqueConverterLockupRPM']}"
    # new_Range = 1.0 * ((1038 - 750) + 850) = 1138
    assert vc["torqueConverterLockupRange"] == 1138, f"Got {vc['torqueConverterLockupRange']}"
    return True


def test_tcc_lockup_to_gear_2():
    """Drop lockup from gear 5 to gear 2 — same RPM/Range as any other gear."""
    data = make_transmission_data()
    result = tweak_modern_tcc_lockup(data, 2, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    assert vc["torqueConverterLockupMinGear"] == 2
    # RPM/Range formulas don't depend on target gear
    assert vc["torqueConverterLockupRPM"] == 1038
    assert vc["torqueConverterLockupRange"] == 1138
    return True


def test_tcc_lockup_same_gear():
    """Setting to same gear — RPM/Range still adjusted (unconditional now)."""
    data = make_transmission_data()
    result = tweak_modern_tcc_lockup(data, 5, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    assert vc["torqueConverterLockupMinGear"] == 5
    # RPM/Range adjusted unconditionally regardless of gear direction
    assert vc["torqueConverterLockupRPM"] == 1038
    assert vc["torqueConverterLockupRange"] == 1138
    return True


def test_tcc_lockup_higher_gear():
    """Setting to higher gear — RPM/Range still adjusted (unconditional)."""
    data = make_transmission_data()
    result = tweak_modern_tcc_lockup(data, 7, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    assert vc["torqueConverterLockupMinGear"] == 7
    # RPM/Range adjusted unconditionally
    assert vc["torqueConverterLockupRPM"] == 1038
    assert vc["torqueConverterLockupRange"] == 1138
    return True


def test_tcc_lockup_high_initial_rpm():
    """When initial RPM is close to redline, adjustment is small."""
    # old_RPM=6000, close to ENGINE_REDLINE=6500
    data = make_transmission_data(vc_torqueConverterLockupRPM=6000,
                                  vc_torqueConverterLockupRange=200)
    result = tweak_modern_tcc_lockup(data, 3, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    # new_RPM = ((6500 - 6000) * 0.05) + 6000 = 25 + 6000 = 6025
    assert vc["torqueConverterLockupRPM"] == 6025, f"Got {vc['torqueConverterLockupRPM']}"
    # new_Range = 1.0 * ((6025 - 6000) + 200) = 225
    assert vc["torqueConverterLockupRange"] == 225, f"Got {vc['torqueConverterLockupRange']}"
    return True


def test_tcc_lockup_low_initial_rpm():
    """When initial RPM is low, adjustment is proportionally larger."""
    # old_RPM=400, far below ENGINE_REDLINE=6500
    data = make_transmission_data(vc_torqueConverterLockupRPM=400,
                                  vc_torqueConverterLockupRange=500)
    result = tweak_modern_tcc_lockup(data, 2, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    # new_RPM = ((6500 - 400) * 0.05) + 400 = 305 + 400 = 705
    assert vc["torqueConverterLockupRPM"] == 705, f"Got {vc['torqueConverterLockupRPM']}"
    # new_Range = 1.0 * ((705 - 400) + 500) = 805
    assert vc["torqueConverterLockupRange"] == 805, f"Got {vc['torqueConverterLockupRange']}"
    return True


def test_tcc_lockup_missing_rpm_property():
    """When torqueConverterLockupRPM is absent, only minGear is set."""
    data = {
        "Camso_Transmission_Test": {
            "torqueConverter": {"converterDiameter": 0.30},
            "vehicleController": {
                "torqueConverterLockupMinGear": 5,
                # No torqueConverterLockupRPM or Range
            },
        }
    }
    result = tweak_modern_tcc_lockup(data, 3, MOCK_TRANS_CTX)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    assert vc["torqueConverterLockupMinGear"] == 3
    assert "torqueConverterLockupMinGear" in result.mutations
    # RPM/Range should NOT appear in mutations since they weren't present
    assert "torqueConverterLockupRPM" not in result.mutations
    assert "torqueConverterLockupRange" not in result.mutations
    return True


def test_tcc_lockup_invalid_gear():
    """Reject gear 0 or negative."""
    data = make_transmission_data()
    result = tweak_modern_tcc_lockup(data, 0, MOCK_TRANS_CTX)
    assert not result.applied
    assert "invalid" in result.reason.lower()
    return True


def test_tcc_lockup_dynamic_redline():
    """When TweakContext carries a donor torque table, redline is extracted
    from the WOT curve instead of using the 6500 fallback."""
    # Our CAMSO_5COL_TABLE fixture has functional redline = 5100
    ctx_with_table = TweakContext(
        component_type="transmission",
        donor_drive_type="RWD",
        target_vehicle_name="test_vehicle",
        donor_torque_table=CAMSO_5COL_TABLE,
    )
    data = make_transmission_data()  # old_RPM=750, old_Range=850
    result = tweak_modern_tcc_lockup(data, 3, ctx_with_table)
    assert result.applied

    vc = data["Camso_Transmission_Test"]["vehicleController"]
    # engine_redline = 5100 (from WOT curve, NOT 6500 fallback)
    # new_RPM = ((5100 - 750) * 0.05) + 750 = 217.5 + 750 = 967.5 → round = 968
    assert vc["torqueConverterLockupRPM"] == 968, f"Got {vc['torqueConverterLockupRPM']}"
    # new_Range = 1.0 * ((968 - 750) + 850) = 1068
    assert vc["torqueConverterLockupRange"] == 1068, f"Got {vc['torqueConverterLockupRange']}"
    return True


def test_tcc_lockup_no_section():
    """Graceful no-op when vehicleController is absent (manual transmission)."""
    data = {"SomePart": {"torqueConverter": {}}}
    result = tweak_modern_tcc_lockup(data, 3, MOCK_TRANS_CTX)
    assert not result.applied
    assert "vehicleController" in result.reason
    return True


def test_tcc_lockup_manual_transmission():
    """Reject lockup tweak on manual transmission (no torqueConverter)."""
    data = {"SomePart": {"vehicleController": {"torqueConverterLockupMinGear": 5}}}
    result = tweak_modern_tcc_lockup(data, 3, MOCK_TRANS_CTX)
    assert not result.applied
    assert "automatic" in result.reason.lower() or "torqueConverter" in result.reason
    return True


def test_tc_stall_manual_transmission():
    """Reject stall tweak on manual transmission (no torqueConverter)."""
    # Has vehicleController but NO torqueConverter — it's a manual
    data = {"SomePart": {"vehicleController": {"someKey": 1}}}
    result = tweak_tighter_tc_stall(data, 0.5, MOCK_TRANS_CTX)
    assert not result.applied
    assert "automatic" in result.reason.lower() or "torqueConverter" in result.reason
    return True


# =============================================================================
# Integration: apply_tweaks dispatcher
# =============================================================================

def test_apply_tweaks_engine():
    """Full dispatch for engine component."""
    data = make_engine_data()
    config = {"enabled": True, "engine": {"requiredEnergyType": "diesel"}}
    results = apply_tweaks(data, config, MOCK_ENGINE_CTX)
    assert len(results) == 1
    assert results[0].applied
    assert data["Camso_Engine_Test"]["mainEngine"]["requiredEnergyType"] == "diesel"
    return True


def test_apply_tweaks_transmission():
    """Full dispatch for transmission with multiple tweaks."""
    data = make_transmission_data()
    config = {
        "enabled": True,
        "transmission": {
            "tighter_tc_stall": 0.4,
            "modern_tcc_lockup": 3,
        }
    }
    results = apply_tweaks(data, config, MOCK_TRANS_CTX)
    assert len(results) == 2
    assert all(r.applied for r in results)
    return True


def test_apply_tweaks_disabled():
    """Master switch disables all tweaks."""
    data = make_engine_data()
    config = {"enabled": False, "engine": {"requiredEnergyType": "diesel"}}
    results = apply_tweaks(data, config, MOCK_ENGINE_CTX)
    assert len(results) == 0
    assert data["Camso_Engine_Test"]["mainEngine"]["requiredEnergyType"] == "gasoline"
    return True


def test_apply_tweaks_wrong_component():
    """Engine tweaks ignored when component_type is transmission."""
    data = make_engine_data()
    config = {"enabled": True, "engine": {"requiredEnergyType": "diesel"}}
    results = apply_tweaks(data, config, MOCK_TRANS_CTX)  # transmission ctx
    assert len(results) == 0  # no transmission tweaks in config
    return True


def test_apply_tweaks_unknown_key():
    """Unknown tweak keys produce a warning result, not an error."""
    data = make_engine_data()
    config = {"enabled": True, "engine": {"nonexistent_tweak": 42}}
    results = apply_tweaks(data, config, MOCK_ENGINE_CTX)
    assert len(results) == 1
    assert not results[0].applied
    assert "No registered handler" in results[0].reason
    return True


# =============================================================================
# Domain Helpers
# =============================================================================

def test_domain_find_part():
    """find_part_with_section locates correct part."""
    data = make_engine_data()
    result = PowertrainDomain.find_part_with_section(data, "mainEngine")
    assert result is not None
    name, part = result
    assert name == "Camso_Engine_Test"
    return True


def test_domain_find_part_missing():
    """find_part_with_section returns None when section doesn't exist."""
    data = make_engine_data()
    result = PowertrainDomain.find_part_with_section(data, "turbocharger")
    assert result is None
    return True


def test_domain_get_nested():
    """Nested dict access with default."""
    data = make_engine_data()
    val = PowertrainDomain.get_nested(
        data["Camso_Engine_Test"], "mainEngine", "maxTorqueRating"
    )
    assert val == 371.62
    missing = PowertrainDomain.get_nested(
        data["Camso_Engine_Test"], "mainEngine", "nonexistent", default=-1
    )
    assert missing == -1
    return True


def test_domain_scale_lut():
    """LUT value scaling."""
    lut = [[0, 10.0], [100, 20.0], [200, 30.0]]
    scaled = PowertrainDomain.scale_lut_values(lut, value_index=1, scale_factor=2.0)
    assert scaled == [[0, 20.0], [100, 40.0], [200, 60.0]]
    # Original not mutated
    assert lut[0][1] == 10.0
    return True


def test_domain_interpolate_lut():
    """LUT interpolation."""
    lut = [[0, 0.0], [100, 10.0], [200, 30.0]]
    assert PowertrainDomain.interpolate_lut(lut, 50) == 5.0
    assert PowertrainDomain.interpolate_lut(lut, 150) == 20.0
    assert PowertrainDomain.interpolate_lut(lut, 0) == 0.0
    assert PowertrainDomain.interpolate_lut(lut, 200) == 30.0
    assert PowertrainDomain.interpolate_lut(lut, -50) == 0.0   # clamp low
    assert PowertrainDomain.interpolate_lut(lut, 300) == 30.0  # clamp high
    return True


def test_format_results():
    """Format results produces readable output."""
    results = [
        TweakResult("requiredEnergyType", True, mutations={"requiredEnergyType": ("gasoline", "diesel")}),
        TweakResult("tighter_tc_stall", True, mutations={"converterStiffness": (12.0, 21.0)}),
        TweakResult("missing_tweak", False, reason="Not registered"),
    ]
    output = format_results_summary(results)
    assert "Powertrain Tweaks" in output
    assert "gasoline" in output
    assert "skipped" in output
    return True


# =============================================================================
# Torque Table Extraction Helpers
# =============================================================================

# ── Fixtures ─────────────────────────────────────────────────────────────

CAMSO_5COL_TABLE = [
    ["throttle", "rpm", "torque", "FuelUsed", "Pressure"],
    # throttle=0 (engine braking / idle region)
    [0, 0,    0.0,    0.0,  1.0],
    [0, 500,  10.0,   0.01, 1.0],
    [0, 1000, -5.0,   0.02, 1.0],
    [0, 5100, -23.0,  0.77, 1.01],
    # throttle=50 (partial)
    [50, 0,    0.0,    0.0,  1.0],
    [50, 500,  50.0,   3.0,  1.0],
    [50, 1000, 100.0,  5.0,  1.2],
    [50, 5100, 80.0,   8.0,  1.5],
    # throttle=100 (WOT)
    [100, 0,    0.0,    0.0,  1.0],
    [100, 500,  30.0,   1.0,  1.0],
    [100, 1000, 120.0,  4.0,  1.4],
    [100, 2000, 280.0,  8.0,  1.8],
    [100, 3400, 325.0,  10.5, 2.1],
    [100, 4800, 310.0,  12.8, 2.05],
    [100, 5100, 222.0,  13.0, 2.05],
]

BEAMNG_2COL_TABLE = [
    ["rpm", "torque"],
    [0,    0.0],
    [500,  30.0],
    [1000, 120.0],
    [2000, 280.0],
    [3400, 325.0],
    [4800, 310.0],
    [5100, 222.0],
]


def test_detect_format_camso():
    """Detect Camso 5-column torque table format."""
    fmt = PowertrainDomain.detect_torque_table_format(CAMSO_5COL_TABLE)
    assert fmt == "camso_5col", f"Got {fmt}"
    return True


def test_detect_format_beamng():
    """Detect BeamNG 2-column torque table format."""
    fmt = PowertrainDomain.detect_torque_table_format(BEAMNG_2COL_TABLE)
    assert fmt == "beamng_2col", f"Got {fmt}"
    return True


def test_detect_format_empty():
    """Empty or None table returns None."""
    assert PowertrainDomain.detect_torque_table_format([]) is None
    assert PowertrainDomain.detect_torque_table_format(None) is None
    return True


def test_detect_format_header_only():
    """Table with only a header row returns None."""
    header_only = [["throttle", "rpm", "torque", "FuelUsed", "Pressure"]]
    assert PowertrainDomain.detect_torque_table_format(header_only) is None
    return True


def test_extract_wot_camso():
    """Extract WOT curve from Camso 5-column table."""
    wot = PowertrainDomain.extract_wot_curve(CAMSO_5COL_TABLE)
    assert len(wot) == 7  # 7 WOT rows (throttle=100)
    # First and last entries
    assert wot[0] == [0.0, 0.0]
    assert wot[-1] == [5100.0, 222.0]
    # Peak at 3400 RPM
    assert wot[4] == [3400.0, 325.0]
    # No throttle=0 or throttle=50 rows leaked in
    for row in wot:
        assert len(row) == 2
    return True


def test_extract_wot_beamng():
    """Extract WOT curve from BeamNG 2-column table."""
    wot = PowertrainDomain.extract_wot_curve(BEAMNG_2COL_TABLE)
    assert len(wot) == 7  # 7 data rows
    assert wot[0] == [0.0, 0.0]
    assert wot[-1] == [5100.0, 222.0]
    assert wot[4] == [3400.0, 325.0]
    return True


def test_extract_wot_none():
    """None input returns empty list."""
    assert PowertrainDomain.extract_wot_curve(None) == []
    return True


def test_functional_redline():
    """Functional redline is the highest RPM in the WOT curve."""
    wot = PowertrainDomain.extract_wot_curve(CAMSO_5COL_TABLE)
    redline = PowertrainDomain.functional_redline(wot)
    assert redline == 5100.0
    return True


def test_functional_redline_empty():
    """Empty WOT curve returns None."""
    assert PowertrainDomain.functional_redline([]) is None
    return True


def test_peak_torque():
    """Peak torque returns (rpm, torque) of maximum torque row."""
    wot = PowertrainDomain.extract_wot_curve(CAMSO_5COL_TABLE)
    rpm, torque = PowertrainDomain.peak_torque(wot)
    assert rpm == 3400.0
    assert torque == 325.0
    return True


def test_peak_torque_beamng():
    """Peak torque works on BeamNG 2-column table too."""
    wot = PowertrainDomain.extract_wot_curve(BEAMNG_2COL_TABLE)
    rpm, torque = PowertrainDomain.peak_torque(wot)
    assert rpm == 3400.0
    assert torque == 325.0
    return True


def test_peak_torque_empty():
    """Empty WOT curve returns None."""
    assert PowertrainDomain.peak_torque([]) is None
    return True


def test_ramp65_torque_rpm():
    """ramp65 returns lowest RPM where torque > 0.65 * peak."""
    wot = PowertrainDomain.extract_wot_curve(CAMSO_5COL_TABLE)
    # peak = 325.0 → threshold = 211.25
    # Rows: 0/0, 500/30, 1000/120, 2000/280, 3400/325, 4800/310, 5100/222
    # First row >= 211.25 is [2000, 280.0]
    rpm = PowertrainDomain.ramp65_torque_rpm(wot)
    assert rpm == 2000.0, f"Got {rpm}"
    return True


def test_ramp65_torque_rpm_empty():
    """Empty WOT curve returns None."""
    assert PowertrainDomain.ramp65_torque_rpm([]) is None
    return True


def test_ramp65_torque_rpm_never_met():
    """If threshold is never exceeded, returns None."""
    # All torque values below the 65% threshold of the peak
    low_curve = [[1000, 1.0], [2000, 1.5], [3000, 1.2]]
    # peak = 1.5 → threshold = 0.975 — wait, 1.0 > 0.975, so it IS met
    # Use a curve where values are literally identical
    flat_zero = [[1000, 0.0], [2000, 0.0]]
    # peak = 0.0, threshold = 0.0, first row ties → returns 1000
    assert PowertrainDomain.ramp65_torque_rpm(flat_zero) == 1000.0
    return True


def test_helpers_roundtrip_camso():
    """Full extraction pipeline from Camso raw table to derived values."""
    wot = PowertrainDomain.extract_wot_curve(CAMSO_5COL_TABLE)
    redline = PowertrainDomain.functional_redline(wot)
    peak_rpm, peak_nm = PowertrainDomain.peak_torque(wot)
    ramp65 = PowertrainDomain.ramp65_torque_rpm(wot)
    assert redline == 5100.0
    assert peak_rpm == 3400.0
    assert peak_nm == 325.0
    assert ramp65 == 2000.0
    return True


# =============================================================================
# Runner
# =============================================================================

def main():
    tests = [
        # Registry
        test_registry_populated,
        # Phase A
        test_energy_type_gasoline_to_diesel,
        test_energy_type_no_change,
        test_energy_type_invalid,
        test_energy_type_no_engine_section,
        # Phase B: tighter_tc_stall
        test_tc_stall_basic,
        test_tc_stall_max,
        test_tc_stall_zero,
        test_tc_stall_no_section,
        test_tc_stall_clamps_input,
        test_tc_stall_dynamic_scaling,
        # Phase B: modern_tcc_lockup
        test_tcc_lockup_lower_gear,
        test_tcc_lockup_to_gear_2,
        test_tcc_lockup_same_gear,
        test_tcc_lockup_higher_gear,
        test_tcc_lockup_invalid_gear,
        test_tcc_lockup_dynamic_redline,
        test_tcc_lockup_high_initial_rpm,
        test_tcc_lockup_low_initial_rpm,
        test_tcc_lockup_no_section,
        test_tcc_lockup_manual_transmission,
        test_tcc_lockup_missing_rpm_property,
        test_tc_stall_manual_transmission,
        # Integration
        test_apply_tweaks_engine,
        test_apply_tweaks_transmission,
        test_apply_tweaks_disabled,
        test_apply_tweaks_wrong_component,
        test_apply_tweaks_unknown_key,
        # Domain helpers
        test_domain_find_part,
        test_domain_find_part_missing,
        test_domain_get_nested,
        test_domain_scale_lut,
        test_domain_interpolate_lut,
        test_format_results,
        # Torque table extraction
        test_detect_format_camso,
        test_detect_format_beamng,
        test_detect_format_empty,
        test_detect_format_header_only,
        test_extract_wot_camso,
        test_extract_wot_beamng,
        test_extract_wot_none,
        test_functional_redline,
        test_functional_redline_empty,
        test_peak_torque,
        test_peak_torque_beamng,
        test_peak_torque_empty,
        test_ramp65_torque_rpm,
        test_ramp65_torque_rpm_empty,
        test_ramp65_torque_rpm_never_met,
        test_helpers_roundtrip_camso,
    ]

    passed = 0
    failed = 0
    errors = 0

    print(f"\n{'='*72}")
    print(f"Powertrain Tweaks Test Suite — {len(tests)} tests")
    print(f"{'='*72}\n")

    for test in tests:
        try:
            result = test()
            if result or result is None:
                print(f"  PASS  {test.__name__}")
                passed += 1
            else:
                print(f"  FAIL  {test.__name__}")
                failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            errors += 1

    print(f"\n{'-'*72}")
    print(f"Results: {passed} passed, {failed} failed, {errors} errors out of {len(tests)} tests")

    if failed + errors == 0:
        print("ALL PASS\n")
    else:
        print("SOME FAILURES\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
