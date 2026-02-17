"""
Test drive type extraction from Camso transfer case files.
"""
from pathlib import Path
import sys

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from engineswap import JBeamParser, EngineTransplantUtility
from mount_solver import DonorDriveTypeExtractor, DriveType

def test_drive_type(name: str, transfer_case_path: Path):
    """Test drive type extraction for a given transfer case file."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"File: {transfer_case_path.name}")
    print('='*60)
    
    if not transfer_case_path.exists():
        print(f"  ERROR: File not found")
        return
    
    # Parse the transfer case file
    data = JBeamParser.parse_jbeam(transfer_case_path)
    if not data:
        print(f"  ERROR: Failed to parse file")
        return
    
    print(f"  Parsed {len(data)} parts:")
    for part_name in data.keys():
        print(f"    - {part_name}")
    
    # Extract drive type
    extractor = DonorDriveTypeExtractor(data)
    drive_type = extractor.extract_drive_type()
    drive_info = extractor.get_drive_info()
    
    print(f"\n  Drive Type: {drive_type.value.upper()}")
    print(f"  Details:")
    print(f"    - Front driveshaft: {'YES' if drive_info['has_front_driveshaft'] else 'NO'}")
    print(f"    - Rear driveshaft: {'YES' if drive_info['has_rear_driveshaft'] else 'NO'}")
    print(f"    - 4WD indicators: {'YES' if drive_info['has_4wd_indicators'] else 'NO'}")
    print(f"    - AWD indicators: {'YES' if drive_info['has_awd_indicators'] else 'NO'}")
    
    return drive_type


def test_via_engine_file(name: str, engine_path: Path):
    """Test drive type extraction via the engine file path (using utility method)."""
    print(f"\n{'='*60}")
    print(f"Testing via engine file: {name}")
    print(f"Engine: {engine_path.name}")
    print('='*60)
    
    if not engine_path.exists():
        print(f"  ERROR: Engine file not found")
        return None
    
    # Use the utility method
    util = EngineTransplantUtility(
        base_vehicles_path=Path(r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles"),
        output_path=Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles")
    )
    
    drive_type = util._determine_donor_drive_type(engine_path)
    
    if drive_type:
        print(f"\n  Drive Type: {drive_type.value.upper()}")
    else:
        print(f"\n  Drive Type: UNKNOWN (could not determine)")
    
    return drive_type


def main():
    print("=" * 70)
    print("CAMSO DRIVE TYPE EXTRACTION TEST")
    print("=" * 70)
    
    # === Part 1: Direct transfer case file tests ===
    print("\n" + "=" * 70)
    print("PART 1: DIRECT TRANSFER CASE FILE TESTS")
    print("=" * 70)
    
    test_cases = [
        (
            "Camso RWD (script_test_rwd)",
            Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\script_test_rwd\vehicles\test_rwd\79971\camso_transfercase_79971.jbeam")
        ),
        (
            "Camso AWD (persh_crayenne_moracc)", 
            Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles\persh_crayenne_moracc\ec8ba\camso_transfercase_ec8ba.jbeam")
        ),
        (
            "Camso AWD (persh_crayenne_offr)",
            Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_offr\common\1fb46\camso_transfercase_1fb46.jbeam")
        ),
    ]
    
    results = {}
    for name, path in test_cases:
        drive_type = test_drive_type(name, path)
        if drive_type:
            results[name] = drive_type
    
    # === Part 2: Via engine file path tests ===
    print("\n" + "=" * 70)
    print("PART 2: VIA ENGINE FILE PATH TESTS")
    print("=" * 70)
    
    engine_tests = [
        (
            "RWD via engine file",
            Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\script_test_rwd\vehicles\test_rwd\camso_engine_balancing.jbeam")
        ),
        (
            "AWD via engine file",
            Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles\persh_crayenne_moracc\eng_3813e\camso_engine_3813e.jbeam")
        ),
    ]
    
    for name, path in engine_tests:
        drive_type = test_via_engine_file(name, path)
        if drive_type:
            results[name] = drive_type
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for name, drive_type in results.items():
        expected = "RWD" if "rwd" in name.lower() else "AWD"
        actual = drive_type.value.upper()
        status = "PASS" if expected.lower() == actual.lower() else "FAIL"
        print(f"  [{status}] {name}: Expected {expected}, Got {actual}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
