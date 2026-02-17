#!/usr/bin/env python3
"""Test transfer case adaptation with drive type logic."""

from pathlib import Path
import sys

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from engineswap import EngineTransplantUtility, VehicleInfo, VehicleArchitecture
from mount_solver import DriveType

def main():
    base = Path(r'M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles')
    out = Path(r'M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles')
    util = EngineTransplantUtility(base, out, 'test_tc')
    
    # Proper VehicleInfo initialization
    target = VehicleInfo(
        name='pickup',
        architecture=VehicleArchitecture.COMMON,
        base_path=base / 'common' / 'vehicles' / 'common' / 'pickup',
        engine_slot_type='pickup_engine'
    )
    print(f'Target: {target}')
    
    # Test 1: AWD transfer case (should inject nodes)
    print()
    print('=' * 60)
    print('TEST 1: AWD Transfer Case (should inject tra2/tra3 nodes)')
    print('=' * 60)
    
    util._last_donor_drive_type = DriveType.AWD
    awd_tc = Path(r'M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles\persh_crayenne_moracc\ec8ba\camso_transfercase_ec8ba.jbeam')
    
    if awd_tc.exists():
        result = util.generate_adapted_transfercase(awd_tc, target)
        if result and result.exists():
            print(f'\nGenerated: {result.name}')
            # Show a snippet of the output
            content = result.read_text()[:2000]
            print(f'\nOutput snippet:\n{content}...')
        else:
            print('Generation failed')
    else:
        print(f'File not found: {awd_tc}')
    
    # Test 2: RWD transfer case (should skip node injection)
    print()
    print('=' * 60)
    print('TEST 2: RWD Transfer Case (should SKIP node injection)')
    print('=' * 60)
    
    util._last_donor_drive_type = DriveType.RWD
    rwd_tc = Path(r'M:\BeamNG_Modding_Temp\mods\unpacked\script_test_rwd\vehicles\test_rwd\79971\camso_transfercase_79971.jbeam')
    
    if rwd_tc.exists():
        result = util.generate_adapted_transfercase(rwd_tc, target)
        if result and result.exists():
            print(f'\nGenerated: {result.name}')
            # Show a snippet of the output
            content = result.read_text()[:2000]
            print(f'\nOutput snippet:\n{content}...')
        else:
            print('Generation failed')
    else:
        print(f'File not found: {rwd_tc}')

if __name__ == '__main__':
    main()
