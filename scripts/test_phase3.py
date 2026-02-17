#!/usr/bin/env python3
"""Phase 3 validation: Test the Swap Decision Engine (select_swap_strategy).

Tests cover:
- Auto mode: all 4 Camso drive types × TC-equipped vehicle (pickup)
- Auto mode: non-TC vehicle (moonhawk, fullsize)
- Specified mode: valid part, invalid part, incompatible combination
- Edge case: 4WD donor (expected REFUSE for AWD targets)

Each test case supplies pre-computed donor_catalog and tc_catalog, then verifies
strategy, cost, refused flag, and mode from the decision dict.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engineswap import EngineTransplantUtility

BASE = Path(__file__).resolve().parent.parent

# =============================================================================
# Donor catalog stubs (matching analyze_donor_powertrain output format)
# =============================================================================

DONOR_RWD = {"drive_type": "RWD", "awd_subvariant": None, "parts": []}
DONOR_FWD = {"drive_type": "FWD", "awd_subvariant": None, "parts": []}
DONOR_AWD_HELICAL = {"drive_type": "AWD", "awd_subvariant": "helical", "parts": []}
DONOR_AWD_VISCOUS = {"drive_type": "AWD", "awd_subvariant": "viscous", "parts": []}
DONOR_AWD_ON_DEMAND = {"drive_type": "AWD", "awd_subvariant": "on_demand", "parts": []}
DONOR_AWD_ADVANCED = {"drive_type": "AWD", "awd_subvariant": "advanced", "parts": []}
DONOR_4WD = {"drive_type": "4WD", "awd_subvariant": None, "parts": []}


# =============================================================================
# Test definitions:  (name, donor_catalog, vehicle, config_override, expected)
# expected = (strategy, cost, refused, mode)
# =============================================================================

TEST_CASES = [
    # --- Auto mode: donor types × pickup (TC-equipped) ---
    (
        "RWD × pickup (auto)",
        DONOR_RWD, "pickup", {},
        ("DIRECT", 0, False, "auto"),
    ),
    (
        "FWD × pickup (auto)",
        DONOR_FWD, "pickup", {},
        ("MAKE_FWD", 4, False, "auto"),
    ),
    (
        "AWD(helical) × pickup (auto)",
        DONOR_AWD_HELICAL, "pickup", {},
        ("DIRECT_AWD", 0, False, "auto"),
    ),
    (
        "AWD(viscous) × pickup (auto)",
        DONOR_AWD_VISCOUS, "pickup", {},
        ("DIRECT_AWD", 0, False, "auto"),
    ),
    (
        "AWD(on_demand) × pickup (auto)",
        DONOR_AWD_ON_DEMAND, "pickup", {},
        ("DIRECT_AWD", 0, False, "auto"),
    ),
    (
        "AWD(advanced) × pickup (auto)",
        DONOR_AWD_ADVANCED, "pickup", {},
        ("DIRECT_AWD", 0, False, "auto"),
    ),
    (
        "4WD × pickup (auto)",
        DONOR_4WD, "pickup", {},
        ("DIRECT", 0, False, "auto"),
    ),

    # --- Auto mode: non-TC vehicles (moonhawk, fullsize) ---
    (
        "RWD × moonhawk (non-TC auto)",
        DONOR_RWD, "moonhawk", {},
        ("SYNTH_TC", 5, False, "auto"),
    ),
    (
        "FWD × moonhawk (non-TC auto)",
        DONOR_FWD, "moonhawk", {},
        ("REFUSE", 99, True, "auto"),
    ),
    (
        "AWD × moonhawk (non-TC auto)",
        DONOR_AWD_HELICAL, "moonhawk", {},
        ("REFUSE", 99, True, "auto"),
    ),
    (
        "4WD × moonhawk (non-TC auto)",
        DONOR_4WD, "moonhawk", {},
        ("REFUSE", 99, True, "auto"),
    ),
    (
        "RWD × fullsize (non-TC auto)",
        DONOR_RWD, "fullsize", {},
        ("SYNTH_TC", 5, False, "auto"),
    ),

    # --- Auto mode: roamer (uses pickup_* TCs only) ---
    (
        "AWD(helical) × roamer (auto)",
        DONOR_AWD_HELICAL, "roamer", {},
        ("DIRECT_AWD", 0, False, "auto"),
    ),
    (
        "RWD × roamer (auto)",
        DONOR_RWD, "roamer", {},
        ("DIRECT", 0, False, "auto"),
    ),

    # --- Specified mode: valid part ---
    (
        "RWD × pickup specified(pickup_transfer_case_RWD)",
        DONOR_RWD, "pickup",
        {"transfercase_to_adapt": "pickup_transfer_case_RWD"},
        ("DIRECT", 0, False, "specified"),
    ),
    (
        "AWD × pickup specified(pickup_transfer_case_AWD)",
        DONOR_AWD_HELICAL, "pickup",
        {"transfercase_to_adapt": "pickup_transfer_case_AWD"},
        ("DIRECT_AWD", 0, False, "specified"),
    ),

    # --- Specified mode: valid part but incompatible combo ---
    (
        "AWD × pickup specified(pickup_transfer_case_RWD) → REFUSE",
        DONOR_AWD_HELICAL, "pickup",
        {"transfercase_to_adapt": "pickup_transfer_case_RWD"},
        ("REFUSE", 99, True, "specified"),
    ),
    (
        "RWD × pickup specified(pickup_transfer_case_AWD) → MAKE_RWD",
        DONOR_RWD, "pickup",
        {"transfercase_to_adapt": "pickup_transfer_case_AWD"},
        ("MAKE_RWD", 3, False, "specified"),
    ),

    # --- Specified mode: nonexistent part ---
    (
        "RWD × pickup specified(nonexistent_part) → REFUSE",
        DONOR_RWD, "pickup",
        {"transfercase_to_adapt": "nonexistent_transfer_case"},
        ("REFUSE", 99, True, "specified"),
    ),
]


def main():
    # Build utility with default auto config
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    utility.base_vehicles_path = BASE / "SteamLibrary_content_vehicles"
    utility.donor_mods_path = BASE / "mods" / "unpacked"
    utility._swap_config = {"transfercase_to_adapt": "auto"}
    utility._last_donor_drive_type = None

    # Pre-compute TC catalogs for target vehicles (expensive — do once)
    print("Pre-computing target vehicle TC catalogs...")
    tc_cache = {}
    vehicles_needed = sorted(set(t[2] for t in TEST_CASES))
    for v in vehicles_needed:
        tc_cache[v] = utility.analyze_target_powertrain(v)
        tc_count = len(tc_cache[v]["transfer_cases"]) if tc_cache[v] else 0
        print(f"  {v}: {tc_count} TC variants")

    print()
    print("=" * 72)
    print("Phase 3 Validation: Swap Decision Engine")
    print("=" * 72)

    passed = 0
    failed = 0
    errors = []

    for name, donor, vehicle, config_override, (exp_strat, exp_cost, exp_refused, exp_mode) in TEST_CASES:
        # Apply config override (or reset to auto)
        utility._swap_config = {"transfercase_to_adapt": "auto"}
        utility._swap_config.update(config_override)

        tc_catalog = tc_cache[vehicle]
        try:
            decision = utility.select_swap_strategy(donor, tc_catalog, vehicle)
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            errors.append((name, str(e)))
            continue

        # Validate fields
        checks = []
        if decision["strategy"] != exp_strat:
            checks.append(f"strategy: got {decision['strategy']}, want {exp_strat}")
        if decision["cost"] != exp_cost:
            checks.append(f"cost: got {decision['cost']}, want {exp_cost}")
        if decision["refused"] != exp_refused:
            checks.append(f"refused: got {decision['refused']}, want {exp_refused}")
        if decision["mode"] != exp_mode:
            checks.append(f"mode: got {decision['mode']}, want {exp_mode}")

        if checks:
            print(f"  FAIL  {name}")
            for c in checks:
                print(f"        {c}")
            failed += 1
            errors.append((name, "; ".join(checks)))
        else:
            sel = decision.get("selected_tc")
            sel_name = sel["part_name"] if sel else "(none)"
            sub = decision.get("donor_awd_subvariant", "")
            sub_str = f" [{sub}]" if sub else ""
            print(f"  PASS  {name}")
            print(f"        → {decision['strategy']} (cost:{decision['cost']})"
                  f" tc={sel_name}{sub_str}")
            passed += 1

    print()
    print("-" * 72)
    print(f"Results: {passed} passed, {failed} failed, "
          f"{len(errors)} errors out of {len(TEST_CASES)} tests")

    if errors:
        print("\nFailures:")
        for n, e in errors:
            print(f"  {n}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
