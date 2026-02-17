#!/usr/bin/env python3
"""Phase 5 test suite: Strategy-specific TC adaptation (slot pruning + device name normalization).

Tests the three Phase 5 helper methods and their integration into
generate_adapted_transfercase().
"""
import sys
import copy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engineswap import EngineTransplantUtility, JBeamParser

BASE = Path(__file__).resolve().parent.parent

# ============================================================================
# Unit Tests: _prune_driveshaft_slots
# ============================================================================

def test_prune_rear_only():
    """RWD/4WD: prune Camso_driveshaft_rear, leave everything else."""
    part = {
        "slots": [
            ["type", "default", "description"],
            ["Camso_driveshaft_rear", "Camso_driveshaft_rear", "Rear Driveshaft"],
            ["Camso_4wd_controller", "Camso_4wd_controller_2hi4hi4lo", "4WD Controller", {"coreSlot": True}],
        ]
    }
    pruned = EngineTransplantUtility._prune_driveshaft_slots(part, ["Camso_driveshaft_rear"])
    assert pruned == ["Camso_driveshaft_rear"], f"Expected rear pruned, got: {pruned}"
    # Should keep header + 4wd controller
    remaining = [e for e in part["slots"] if isinstance(e, list) and e[0] != "type"]
    assert len(remaining) == 1, f"Expected 1 remaining slot, got {len(remaining)}"
    assert remaining[0][0] == "Camso_4wd_controller", f"Expected 4wd controller kept, got: {remaining[0]}"
    return True

def test_prune_both():
    """AWD: prune both front and rear driveshaft slots."""
    part = {
        "slots": [
            ["type", "default", "description"],
            ["Camso_driveshaft_front", "Camso_driveshaft_front", "Front Driveshaft"],
            ["Camso_driveshaft_rear", "Camso_driveshaft_rear", "Rear Driveshaft"],
        ]
    }
    pruned = EngineTransplantUtility._prune_driveshaft_slots(
        part, ["Camso_driveshaft_front", "Camso_driveshaft_rear"]
    )
    assert sorted(pruned) == ["Camso_driveshaft_front", "Camso_driveshaft_rear"], f"Expected both pruned: {pruned}"
    remaining = [e for e in part["slots"] if isinstance(e, list) and e[0] != "type"]
    assert len(remaining) == 0, f"Expected 0 remaining slots, got {len(remaining)}"
    return True

def test_prune_nothing():
    """FWD: no slots to prune (empty prune list)."""
    part = {
        "slots": [
            ["type", "default", "description"],
        ]
    }
    pruned = EngineTransplantUtility._prune_driveshaft_slots(part, [])
    assert pruned == [], f"Expected nothing pruned: {pruned}"
    return True

def test_prune_no_match():
    """Prune targets don't exist in slots."""
    part = {
        "slots": [
            ["type", "default", "description"],
            ["Camso_4wd_controller", "ctrl", "Controller"],
        ]
    }
    pruned = EngineTransplantUtility._prune_driveshaft_slots(part, ["Camso_driveshaft_rear"])
    assert pruned == [], f"Expected nothing pruned: {pruned}"
    remaining = [e for e in part["slots"] if isinstance(e, list) and e[0] != "type"]
    assert len(remaining) == 1, f"Expected controller kept"
    return True

# ============================================================================
# Unit Tests: _normalize_powertrain_device_names
# ============================================================================

def test_normalize_powertrain_names():
    """Normalize transferCase → transfercase in powertrain array."""
    part = {
        "powertrain": [
            ["type", "name", "inputName", "inputIndex"],
            ["differential", "transferCase", "gearbox", 1, {"diffType": "lsd"}],
        ],
        "transferCase": {"diffTorqueSplit": 0.50},
    }
    count = EngineTransplantUtility._normalize_powertrain_device_names(part, {"transferCase": "transfercase"})
    assert count >= 2, f"Expected >= 2 renames, got {count}"
    # Check powertrain device name
    assert part["powertrain"][1][1] == "transfercase", f"Device name not renamed: {part['powertrain'][1][1]}"
    # Check config section key
    assert "transfercase" in part, "Config section not renamed"
    assert "transferCase" not in part, "Old config section key still present"
    return True

def test_normalize_input_name():
    """Normalize transferCase in inputName field."""
    part = {
        "powertrain": [
            ["type", "name", "inputName", "inputIndex"],
            ["shaft", "rearDriveShaft", "transferCase", 1, {}],
        ],
    }
    count = EngineTransplantUtility._normalize_powertrain_device_names(part, {"transferCase": "transfercase"})
    assert part["powertrain"][1][2] == "transfercase", f"inputName not renamed: {part['powertrain'][1][2]}"
    return True

def test_normalize_controller():
    """Normalize deviceName in controller section."""
    part = {
        "powertrain": [
            ["type", "name", "inputName", "inputIndex"],
            ["splitShaft", "transferCase", "gearbox", 1, {}],
        ],
        "controller": [
            ["drivingDynamics/actuators/electronicSplitShaftLock", {
                "name": "electronicSplitShaftLock",
                "splitShaftName": "transferCase"
            }],
        ],
        "transferCase": {},
    }
    count = EngineTransplantUtility._normalize_powertrain_device_names(part, {"transferCase": "transfercase"})
    # Controller splitShaftName
    ctrl_props = part["controller"][0][1]
    assert ctrl_props["splitShaftName"] == "transfercase", f"Controller splitShaftName not renamed: {ctrl_props}"
    return True

def test_normalize_fwd_device():
    """FWD special case: frontDriveShaft → transfercase."""
    part = {
        "powertrain": [
            ["type", "name", "inputName", "inputIndex"],
            ["shaft", "frontDriveShaft", "gearbox", 1, {"friction": 0}],
        ],
    }
    count = EngineTransplantUtility._normalize_powertrain_device_names(
        part, {"transferCase": "transfercase", "frontDriveShaft": "transfercase"}
    )
    assert part["powertrain"][1][1] == "transfercase", f"frontDriveShaft not renamed: {part['powertrain'][1][1]}"
    return True

# ============================================================================
# Integration Test: Full generate with real donor files
# ============================================================================

def test_integration_awd_donor_pickup():
    """Full pipeline: AWD→pickup (DIRECT_AWD). Verify output file pruning."""
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    utility.base_vehicles_path = BASE / "SteamLibrary_content_vehicles"
    utility.donor_mods_path = BASE / "mods" / "unpacked"
    utility._swap_config = {"transfercase_to_adapt": "auto"}
    utility._last_donor_drive_type = None
    
    # Get swap decision
    tc_catalog = utility.analyze_target_powertrain("pickup")
    donor_catalog = utility.analyze_donor_powertrain(
        BASE / "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/eng_3813e/camso_engine_3813e.jbeam"
    )
    swap_decision = utility.select_swap_strategy(donor_catalog, tc_catalog, "pickup")
    injection_targets = utility.extract_injection_targets(swap_decision)
    
    assert swap_decision["strategy"] == "DIRECT_AWD", f"Expected DIRECT_AWD, got {swap_decision['strategy']}"
    
    # Parse the TC file directly and test _apply_tc_strategy_adaptations
    tc_file = BASE / "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/ec8ba/camso_transfercase_ec8ba.jbeam"
    tc_data = JBeamParser.parse_jbeam(tc_file)
    
    # Deep copy to simulate adaptation
    adapted = {}
    for pn, pd in tc_data.items():
        if not isinstance(pd, dict):
            continue
        adapted[pn] = copy.deepcopy(pd)
    
    # Apply Phase 5
    summary = utility._apply_tc_strategy_adaptations(adapted, swap_decision)
    
    # Verify pruning
    assert "Camso_driveshaft_front" in summary["slots_pruned"], "Front driveshaft should be pruned"
    assert "Camso_driveshaft_rear" in summary["slots_pruned"], "Rear driveshaft should be pruned"
    
    # Verify center diff has no driveshaft slots
    center_diff = adapted.get("Camso_differential_center_ec8ba", {})
    for entry in center_diff.get("slots", [])[1:]:
        if isinstance(entry, list):
            assert "driveshaft" not in entry[0].lower(), f"Driveshaft slot not pruned: {entry}"
    
    # Verify device name normalization
    pt = center_diff.get("powertrain", [])
    for entry in pt:
        if isinstance(entry, list) and len(entry) >= 2:
            assert entry[1] != "transferCase", f"Device name not normalized: {entry[1]}"
    
    # Verify config section key
    assert "transferCase" not in center_diff, "Old config key 'transferCase' still present"
    assert "transfercase" in center_diff, "New config key 'transfercase' not found"
    
    # Verify front shaft injection (AWD donors lack powertrain-level front output)
    assert "devices_injected" in summary, "Summary should include devices_injected"
    assert "transfercase_F" in summary["devices_injected"], \
        f"transfercase_F should be injected for AWD donor, got: {summary['devices_injected']}"
    
    # Verify the injected entry is in the center diff's powertrain array
    pt_names = [e[1] for e in pt if isinstance(e, list) and len(e) >= 2 and e[1] != "name"]
    assert "transfercase_F" in pt_names, \
        f"Injected transfercase_F not found in powertrain: {pt_names}"
    
    # Verify the injected entry has correct structure
    tc_f_entry = [e for e in pt if isinstance(e, list) and len(e) >= 4 and e[1] == "transfercase_F"]
    assert len(tc_f_entry) == 1, f"Expected exactly 1 transfercase_F entry, got {len(tc_f_entry)}"
    entry = tc_f_entry[0]
    assert entry[0] == "shaft", f"Expected type 'shaft', got '{entry[0]}'"
    assert entry[2] == "transfercase", f"Expected inputName 'transfercase', got '{entry[2]}'"
    assert entry[3] == 2, f"Expected inputIndex 2, got {entry[3]}"
    
    # Verify provenance includes injection record
    inj_provenance = [p for p in summary["device_name_provenance"] if p.get("donor_name") is None]
    assert len(inj_provenance) >= 1, "Should have injection provenance record"
    assert inj_provenance[0]["target_name"] == "transfercase_F", \
        f"Injection provenance target should be transfercase_F: {inj_provenance[0]}"
    
    return True

def test_integration_rwd_donor():
    """Test with RWD donor: only Camso_driveshaft_rear should be pruned."""
    tc_file = BASE / "mods/unpacked/script_test_rwd/vehicles/test_rwd/79971/camso_transfercase_79971.jbeam"
    if not tc_file.exists():
        return "SKIP (file not found)"
    
    tc_data = JBeamParser.parse_jbeam(tc_file)
    adapted = {}
    for pn, pd in tc_data.items():
        if not isinstance(pd, dict):
            continue
        adapted[pn] = copy.deepcopy(pd)
    
    # Simulate RWD→RWD DIRECT decision (selected_tc mirrors Phase 1 tc_entry)
    swap_decision = {
        "strategy": "DIRECT",
        "donor_drive_type": "RWD",
        "selected_tc": {
            "part_name": "pickup_transfer_case_RWD",
            "devices": [
                {"type": "shaft", "name": "transfercase", "inputName": "gearbox", "inputIndex": 1},
            ],
        },
    }
    
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(adapted, swap_decision)
    
    assert "Camso_driveshaft_rear" in summary["slots_pruned"], "Rear should be pruned"
    assert "Camso_driveshaft_front" not in summary["slots_pruned"], "Front should NOT be pruned (doesn't exist)"
    
    # Verify device names normalized
    assert summary["device_renames"] > 0, "Should have device renames"
    
    # Verify no driveshaft slots remain
    for pn, pd in adapted.items():
        if not isinstance(pd, dict):
            continue
        for entry in pd.get("slots", [])[1:]:
            if isinstance(entry, list):
                assert "driveshaft" not in entry[0].lower(), f"Driveshaft slot not pruned in {pn}: {entry}"
    
    return True

def test_integration_4wd_donor():
    """Test with 4WD donor: rear pruned, 4wd controller kept."""
    tc_file = BASE / "mods/unpacked/jerp_chadiator_lockers/vehicles/jerp_chadiator/036a5/camso_transfercase_036a5.jbeam"
    if not tc_file.exists():
        return "SKIP (file not found)"
    
    tc_data = JBeamParser.parse_jbeam(tc_file)
    adapted = {}
    for pn, pd in tc_data.items():
        if not isinstance(pd, dict):
            continue
        adapted[pn] = copy.deepcopy(pd)
    
    # Simulate 4WD→4WD DIRECT decision (selected_tc mirrors Phase 1 tc_entry)
    swap_decision = {
        "strategy": "DIRECT",
        "donor_drive_type": "4WD",
        "selected_tc": {
            "part_name": "pickup_transfer_case_4WD",
            "devices": [
                {"type": "rangeBox", "name": "rangebox", "inputName": "gearbox", "inputIndex": 1},
                {"type": "differential", "name": "transfercase", "inputName": "rangebox", "inputIndex": 1},
                {"type": "shaft", "name": "transfercase_F", "inputName": "transfercase", "inputIndex": 2},
            ],
        },
    }
    
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(adapted, swap_decision)
    
    assert "Camso_driveshaft_rear" in summary["slots_pruned"], "Rear should be pruned"
    
    # Verify 4wd controller slot is KEPT
    found_controller = False
    for pn, pd in adapted.items():
        if not isinstance(pd, dict):
            continue
        for entry in pd.get("slots", [])[1:]:
            if isinstance(entry, list) and "4wd_controller" in entry[0].lower():
                found_controller = True
    assert found_controller, "Camso_4wd_controller should be preserved"
    
    # Verify NO device injection for 4WD donors (they already have frontDriveShaft)
    assert len(summary.get("devices_injected", [])) == 0, \
        f"4WD donors should NOT inject devices: {summary.get('devices_injected')}"
    
    return True

def test_integration_fwd_donor():
    """Test with FWD donor: no slots to prune, frontDriveShaft renamed."""
    tc_file = BASE / "mods/unpacked/testy623/vehicles/test_623/58d60/camso_transfercase_58d60.jbeam"
    if not tc_file.exists():
        return "SKIP (file not found)"
    
    tc_data = JBeamParser.parse_jbeam(tc_file)
    adapted = {}
    for pn, pd in tc_data.items():
        if not isinstance(pd, dict):
            continue
        adapted[pn] = copy.deepcopy(pd)
    
    # Simulate FWD→4WD MAKE_FWD decision (selected_tc mirrors Phase 1 tc_entry)
    swap_decision = {
        "strategy": "MAKE_FWD",
        "donor_drive_type": "FWD",
        "selected_tc": {
            "part_name": "pickup_transfer_case_4WD",
            "devices": [
                {"type": "rangeBox", "name": "rangebox", "inputName": "gearbox", "inputIndex": 1},
                {"type": "differential", "name": "transfercase", "inputName": "rangebox", "inputIndex": 1},
                {"type": "shaft", "name": "transfercase_F", "inputName": "transfercase", "inputIndex": 2},
            ],
        },
    }
    
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(adapted, swap_decision)
    
    assert len(summary["slots_pruned"]) == 0, f"No slots should be pruned for FWD: {summary['slots_pruned']}"
    
    # Verify frontDriveShaft renamed to transfercase
    for pn, pd in adapted.items():
        if not isinstance(pd, dict):
            continue
        for entry in pd.get("powertrain", []):
            if isinstance(entry, list) and len(entry) >= 2:
                assert entry[1] != "frontDriveShaft", f"frontDriveShaft not renamed in {pn}: {entry}"
    
    # FWD donors should NOT inject devices (they're not AWD)
    assert len(summary.get("devices_injected", [])) == 0, \
        f"FWD donors should NOT inject devices: {summary.get('devices_injected')}"
    
    return True

def test_integration_make_awd():
    """Test MAKE_AWD: AWD donor → 4WD target. Should prune + inject front shaft."""
    tc_file = BASE / "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/ec8ba/camso_transfercase_ec8ba.jbeam"
    if not tc_file.exists():
        return "SKIP (file not found)"
    
    tc_data = JBeamParser.parse_jbeam(tc_file)
    adapted = {}
    for pn, pd in tc_data.items():
        if not isinstance(pd, dict):
            continue
        adapted[pn] = copy.deepcopy(pd)
    
    # MAKE_AWD: AWD donor filling a 4WD target TC slot
    # The 4WD TC has rangeBox + differential + shaft (transfercase_F)
    swap_decision = {
        "strategy": "MAKE_AWD",
        "donor_drive_type": "AWD",
        "selected_tc": {
            "part_name": "pickup_transfer_case_4WD",
            "devices": [
                {"type": "rangeBox", "name": "rangebox", "inputName": "gearbox", "inputIndex": 1},
                {"type": "differential", "name": "transfercase", "inputName": "rangebox", "inputIndex": 1},
                {"type": "shaft", "name": "transfercase_F", "inputName": "transfercase", "inputIndex": 2,
                 "properties": {"friction": 0.44, "dynamicFriction": 0.00048, "uiName": "Front Output Shaft"}},
            ],
        },
    }
    
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(adapted, swap_decision)
    
    # AWD pruning: both driveshafts
    assert "Camso_driveshaft_front" in summary["slots_pruned"], "Front should be pruned"
    assert "Camso_driveshaft_rear" in summary["slots_pruned"], "Rear should be pruned"
    
    # Device rename: transferCase should be renamed via type-only fallback
    assert summary["device_renames"] > 0, f"Expected device renames, got {summary['device_renames']}"
    assert "transferCase" in summary["device_name_mapping"], \
        f"transferCase should be in mapping: {summary['device_name_mapping']}"
    
    # Injection: ONLY transfercase_F should be injected (the shaft type the donor lacks)
    # rangebox and transfercase should NOT be injected (donor has differential type)
    assert "transfercase_F" in summary["devices_injected"], \
        f"MAKE_AWD should inject transfercase_F: {summary['devices_injected']}"
    assert "rangebox" not in summary["devices_injected"], \
        f"rangebox should NOT be injected (donor has no rangeBox but AWD doesn't need one)"
    # Only 1 injection expected
    assert len(summary["devices_injected"]) == 1, \
        f"Expected exactly 1 injection (transfercase_F), got: {summary['devices_injected']}"
    
    # Verify the injected entry exists in center diff powertrain
    center_diff = adapted.get("Camso_differential_center_ec8ba", {})
    pt = center_diff.get("powertrain", [])
    tc_f_entries = [e for e in pt if isinstance(e, list) and len(e) >= 4 and e[1] == "transfercase_F"]
    assert len(tc_f_entries) == 1, f"Expected 1 transfercase_F entry, found {len(tc_f_entries)}"
    
    # Verify injected properties came from target analysis
    entry = tc_f_entries[0]
    assert len(entry) >= 5, f"Injected entry should have properties: {entry}"
    props = entry[4]
    assert props.get("uiName") == "Front Output Shaft", f"Properties not injected: {props}"
    
    return True

def test_refuse_skips():
    """REFUSE strategy should apply no modifications."""
    part = {
        "test_part": {
            "slotType": "Camso_TransferCase",
            "slots": [
                ["type", "default", "description"],
                ["Camso_driveshaft_rear", "Camso_driveshaft_rear", "Rear Driveshaft"],
            ],
            "powertrain": [
                ["type", "name", "inputName", "inputIndex"],
                ["shaft", "transferCase", "gearbox", 1, {}],
            ],
        }
    }
    swap_decision = {"strategy": "REFUSE", "donor_drive_type": "RWD"}
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(part, swap_decision)
    
    assert len(summary["slots_pruned"]) == 0, "REFUSE should not prune"
    assert summary["device_renames"] == 0, "REFUSE should not rename"
    # Original data unchanged
    slots = part["test_part"]["slots"]
    assert len(slots) == 2, f"Slots should be unchanged, got {len(slots)}"
    return True

def test_synth_tc_deferred():
    """SYNTH_TC should log warning and skip."""
    part = {"test_part": {"slotType": "Camso_TransferCase"}}
    swap_decision = {"strategy": "SYNTH_TC", "donor_drive_type": "RWD"}
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    summary = utility._apply_tc_strategy_adaptations(part, swap_decision)
    assert len(summary["slots_pruned"]) == 0, "SYNTH_TC should not prune"
    return True

# ============================================================================
# Run all tests
# ============================================================================

UNIT_TESTS = [
    ("prune rear only", test_prune_rear_only),
    ("prune both (AWD)", test_prune_both),
    ("prune nothing (FWD)", test_prune_nothing),
    ("prune no match", test_prune_no_match),
    ("normalize powertrain names", test_normalize_powertrain_names),
    ("normalize inputName", test_normalize_input_name),
    ("normalize controller", test_normalize_controller),
    ("normalize FWD device", test_normalize_fwd_device),
]

INTEGRATION_TESTS = [
    ("AWD→pickup DIRECT_AWD (full pipeline)", test_integration_awd_donor_pickup),
    ("RWD donor (rear pruned)", test_integration_rwd_donor),
    ("4WD donor (rear pruned, controller kept, no injection)", test_integration_4wd_donor),
    ("FWD donor (no pruning, device renamed, no injection)", test_integration_fwd_donor),
    ("MAKE_AWD (AWD\u21924WD, prune+inject)", test_integration_make_awd),
    ("REFUSE skips all", test_refuse_skips),
    ("SYNTH_TC deferred", test_synth_tc_deferred),
]

def main():
    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    
    print("=" * 72)
    print("Phase 5 Validation: Strategy-Specific TC Adaptation")
    print("=" * 72)
    
    for section_name, tests in [("Unit Tests", UNIT_TESTS), ("Integration Tests", INTEGRATION_TESTS)]:
        print(f"\n--- {section_name} ---")
        for name, test_fn in tests:
            try:
                result = test_fn()
                if result is True:
                    print(f"  PASS  {name}")
                    passed += 1
                elif isinstance(result, str) and result.startswith("SKIP"):
                    print(f"  SKIP  {name} — {result}")
                    skipped += 1
                else:
                    print(f"  FAIL  {name} — unexpected result: {result}")
                    failed += 1
            except AssertionError as e:
                print(f"  FAIL  {name} — {e}")
                failed += 1
            except Exception as e:
                print(f"  ERROR {name} — {type(e).__name__}: {e}")
                errors += 1
    
    print(f"\n{'-' * 72}")
    total = passed + failed + skipped + errors
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped, {errors} errors out of {total} tests")
    
    return 0 if (failed == 0 and errors == 0) else 1

if __name__ == "__main__":
    sys.exit(main())
