#!/usr/bin/env python3
"""Phase 2 validation: Test Camso donor drive type classification against all 10 exports."""

import sys
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engineswap import EngineTransplantUtility

# Expected results for each export
EXPECTED = {
    "script_test_rwd":            ("RWD", None),
    "mid_longitudinal_rearwd":    ("RWD", None),
    "tranv_mr":                   ("RWD", None),
    "testy623":                   ("FWD", None),
    "jerp_chadiator_lockers":     ("4WD", None),
    "ondemandawd":                ("AWD", "on_demand"),
    "viscousawd_clutched":        ("AWD", "viscous"),
    "testcvt":                    ("AWD", "helical"),
    "tranv_mr_awd_dct":           ("AWD", "helical"),
    "advancedawd_electricdiffs":  ("AWD", "advanced"),
}

# Engine file paths (pattern: mods/unpacked/<export>/vehicles/<vehicle>/eng_<hash>/camso_engine_<hash>.jbeam)
ENGINE_PATHS = {
    "script_test_rwd":            "mods/unpacked/script_test_rwd/vehicles/test_rwd/eng_9a706/camso_engine_9a706.jbeam",
    "mid_longitudinal_rearwd":    "mods/unpacked/mid_longitudinal_rearwd/vehicles/test_mr/eng_ec3fa/camso_engine_ec3fa.jbeam",
    "tranv_mr":                   "mods/unpacked/tranv_mr/vehicles/test_mr_tranv/eng_7486c/camso_engine_7486c.jbeam",
    "testy623":                   "mods/unpacked/testy623/vehicles/test_623/eng_28457/camso_engine_28457.jbeam",
    "jerp_chadiator_lockers":     "mods/unpacked/jerp_chadiator_lockers/vehicles/jerp_chadiator/eng_34607/camso_engine_34607.jbeam",
    "ondemandawd":                "mods/unpacked/ondemandawd/vehicles/ondemandawd_helicaldiffs/eng_34607/camso_engine_34607.jbeam",
    "viscousawd_clutched":        "mods/unpacked/viscousawd_clutched/vehicles/viscousawd_clutched/eng_34607/camso_engine_34607.jbeam",
    "testcvt":                    "mods/unpacked/testcvt/vehicles/helicalawd/eng_3813e/camso_engine_3813e.jbeam",
    "tranv_mr_awd_dct":           "mods/unpacked/tranv_mr_awd_dct/vehicles/test_mr_tranv_awd_dct/eng_7486c/camso_engine_7486c.jbeam",
    "advancedawd_electricdiffs":  "mods/unpacked/advancedawd_electricdiffs/vehicles/advancedawd_electricdiffs/eng_34607/camso_engine_34607.jbeam",
}


def main():
    base = Path(__file__).resolve().parent.parent
    
    # Minimal utility init
    utility = EngineTransplantUtility.__new__(EngineTransplantUtility)
    utility.base_vehicles_path = base / "SteamLibrary_content_vehicles"
    utility.donor_mods_path = base / "mods" / "unpacked"
    
    passed = 0
    failed = 0
    errors = []
    
    print("=" * 70)
    print("Phase 2 Validation: Camso Donor Drive Type Classification")
    print("=" * 70)
    
    for export_name, (expected_type, expected_sub) in EXPECTED.items():
        engine_rel = ENGINE_PATHS[export_name]
        engine_path = base / engine_rel
        
        if not engine_path.exists():
            print(f"  SKIP  {export_name}: engine file not found ({engine_rel})")
            errors.append((export_name, "FILE_NOT_FOUND"))
            continue
        
        result = utility.analyze_donor_powertrain(engine_path)
        
        if result is None:
            actual_type = "NONE"
            actual_sub = None
        else:
            actual_type = result["drive_type"]
            actual_sub = result.get("awd_subvariant")
        
        type_ok = actual_type == expected_type
        sub_ok = actual_sub == expected_sub
        
        if type_ok and sub_ok:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failed += 1
            errors.append((export_name, f"expected={expected_type}/{expected_sub}, got={actual_type}/{actual_sub}"))
        
        sub_str = f" ({actual_sub})" if actual_sub else ""
        exp_sub_str = f" ({expected_sub})" if expected_sub else ""
        print(f"  {status}  {export_name:<35s} -> {actual_type}{sub_str}"
              f"  (expected: {expected_type}{exp_sub_str})")
    
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed out of {len(EXPECTED)}")
    
    if errors:
        print("\nFailures:")
        for name, detail in errors:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
