#!/usr/bin/env python3
"""Phase 4 validation: Test Axle Slot Extraction (extract_injection_targets).

Tests cover:
- RWD TC: rear driveshaft slots present, no front slots
- AWD TC: both rear and front driveshaft slots present
- 4WD TC: both rear and front driveshaft slots present
- Non-TC vehicle (SYNTH_TC): returns None
- REFUSE strategy: returns None
- Architecture check: pickup TCs have 0 direct child slots
- Roamer vehicle: same TC family (pickup_*), different downstream counts
- etki vehicle: different TC family with splitShaft AWD
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engineswap import EngineTransplantUtility

BASE = Path(__file__).resolve().parent.parent

# Donor catalog stubs
DONOR_RWD = {"drive_type": "RWD", "awd_subvariant": None, "parts": []}
DONOR_FWD = {"drive_type": "FWD", "awd_subvariant": None, "parts": []}
DONOR_AWD = {"drive_type": "AWD", "awd_subvariant": "helical", "parts": []}
DONOR_4WD = {"drive_type": "4WD", "awd_subvariant": None, "parts": []}


# Test definitions:
# (name, donor, vehicle, config_override,
#  expected: (returns_result, has_rear, has_front, tc_has_direct, strategy))
# has_rear / has_front are bool indicating >=1 slot in that category
TEST_CASES = [
    # --- RWD TC: rear only ---
    (
        "RWD→pickup_RWD (rear only)",
        DONOR_RWD, "pickup", {},
        (True, True, False, False, "DIRECT"),
    ),
    # --- AWD TC: both ---
    (
        "AWD→pickup_AWD (both rear+front)",
        DONOR_AWD, "pickup", {},
        (True, True, True, False, "DIRECT_AWD"),
    ),
    # --- 4WD TC: both ---
    (
        "4WD→pickup_4WD (both rear+front)",
        DONOR_4WD, "pickup", {},
        (True, True, True, False, "DIRECT"),
    ),
    # --- FWD→pickup: MAKE_FWD, picks 4WD TC (has both slots) ---
    (
        "FWD→pickup (MAKE_FWD, both slots in 4WD TC)",
        DONOR_FWD, "pickup", {},
        (True, True, True, False, "MAKE_FWD"),
    ),
    # --- MAKE_RWD via specified AWD TC ---
    (
        "RWD→pickup specified AWD TC (MAKE_RWD, both slots)",
        DONOR_RWD, "pickup",
        {"transfercase_to_adapt": "pickup_transfer_case_AWD"},
        (True, True, True, False, "MAKE_RWD"),
    ),
    # --- Non-TC: SYNTH_TC → returns None ---
    (
        "RWD→moonhawk (SYNTH_TC, no injection targets)",
        DONOR_RWD, "moonhawk", {},
        (False, False, False, False, "SYNTH_TC"),
    ),
    # --- REFUSE → returns None ---
    (
        "FWD→moonhawk (REFUSE, no injection targets)",
        DONOR_FWD, "moonhawk", {},
        (False, False, False, False, "REFUSE"),
    ),
    # --- Roamer (uses pickup_* TCs) ---
    (
        "AWD→roamer_AWD (both rear+front)",
        DONOR_AWD, "roamer", {},
        (True, True, True, False, "DIRECT_AWD"),
    ),
    (
        "RWD→roamer_RWD (rear only)",
        DONOR_RWD, "roamer", {},
        (True, True, False, False, "DIRECT"),
    ),
]

# Additional test: etki (different TC family with splitShaft AWD)
ETKI_TESTS = [
    (
        "AWD→etki_AWD (both rear+front)",
        DONOR_AWD, "etki", {},
        (True, True, True, False, "DIRECT_AWD"),
    ),
    (
        "RWD→etki_RWD (shared slot tree includes front)",
        DONOR_RWD, "etki", {},
        # etki RWD TC uses shaft (not splitShaft) so doesn't power front,
        # but chain_components still include front driveshaft slots because
        # the slot tree is shared across all TC variants. This is correct —
        # Phase 5 needs to know front slots EXIST even if RWD TC doesn't drive them.
        (True, True, True, False, "DIRECT"),
    ),
]


def main():
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    utility.base_vehicles_path = BASE / "SteamLibrary_content_vehicles"
    utility.donor_mods_path = BASE / "mods" / "unpacked"
    utility._swap_config = {"transfercase_to_adapt": "auto"}
    utility._last_donor_drive_type = None

    # Pre-compute TC catalogs
    print("Pre-computing target vehicle TC catalogs...")
    all_tests = TEST_CASES + ETKI_TESTS
    tc_cache = {}
    vehicles_needed = sorted(set(t[2] for t in all_tests))
    for v in vehicles_needed:
        tc_cache[v] = utility.analyze_target_powertrain(v)
        tc_count = len(tc_cache[v]["transfer_cases"]) if tc_cache[v] else 0
        print(f"  {v}: {tc_count} TC variants")

    print()
    print("=" * 72)
    print("Phase 4 Validation: Axle Slot Extraction")
    print("=" * 72)

    passed = 0
    failed = 0
    errors = []

    for name, donor, vehicle, config_override, (exp_result, exp_rear, exp_front, exp_direct, exp_strat) in all_tests:
        # Apply config override
        utility._swap_config = {"transfercase_to_adapt": "auto"}
        utility._swap_config.update(config_override)

        tc_catalog = tc_cache[vehicle]
        
        try:
            # Phase 3: get swap decision
            decision = utility.select_swap_strategy(donor, tc_catalog, vehicle)
            
            # Phase 4: extract injection targets
            targets = utility.extract_injection_targets(decision)
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            errors.append((name, str(e)))
            continue

        checks = []
        
        # Check returns result
        got_result = targets is not None
        if got_result != exp_result:
            checks.append(f"returns_result: got {got_result}, want {exp_result}")
        
        if got_result and exp_result:
            # Check rear slots
            has_rear = len(targets["rear_slots"]) > 0
            if has_rear != exp_rear:
                checks.append(f"has_rear: got {has_rear} ({len(targets['rear_slots'])}), want {exp_rear}")
            
            # Check front slots
            has_front = len(targets["front_slots"]) > 0
            if has_front != exp_front:
                checks.append(f"has_front: got {has_front} ({len(targets['front_slots'])}), want {exp_front}")
            
            # Check direct child slots flag
            has_direct = targets["tc_has_direct_child_slots"]
            if has_direct != exp_direct:
                checks.append(f"tc_has_direct: got {has_direct}, want {exp_direct}")
            
            # Check strategy
            if targets["strategy"] != exp_strat:
                checks.append(f"strategy: got {targets['strategy']}, want {exp_strat}")
            
            # Validate slot data integrity
            for slot in targets["rear_slots"]:
                if not slot.get("slot_type"):
                    checks.append(f"rear slot missing slot_type: {slot}")
                if slot.get("position") != "rear":
                    checks.append(f"rear slot wrong position: {slot}")
            for slot in targets["front_slots"]:
                if not slot.get("slot_type"):
                    checks.append(f"front slot missing slot_type: {slot}")
                if slot.get("position") != "front":
                    checks.append(f"front slot wrong position: {slot}")
        
        if checks:
            print(f"  FAIL  {name}")
            for c in checks:
                print(f"        {c}")
            failed += 1
            errors.append((name, "; ".join(checks)))
        else:
            if targets:
                rear_n = len(targets["rear_slots"])
                front_n = len(targets["front_slots"])
                direct_n = targets["direct_child_count"]
                tc = targets["selected_tc"]
                print(f"  PASS  {name}")
                print(f"        → {targets['strategy']}: "
                      f"rear={rear_n}, front={front_n}, "
                      f"direct_child={direct_n}, tc={tc}")
            else:
                print(f"  PASS  {name}")
                print(f"        → returns None ({exp_strat})")
            passed += 1

    print()
    print("-" * 72)
    print(f"Results: {passed} passed, {failed} failed, "
          f"{len(errors)} errors out of {len(all_tests)} tests")

    if errors:
        print("\nFailures:")
        for n, e in errors:
            print(f"  {n}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
