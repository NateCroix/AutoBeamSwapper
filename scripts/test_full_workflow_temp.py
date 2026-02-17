"""
Full Workflow Test: Pickup (target) + Camso 3813e (donor) Engine Swap

Tests the complete mount solver pipeline:
1. Load swap parameters from JSON
2. Parse donor Camso engine
3. Parse target pickup vehicle
4. Extract geometry from both
5. Run solver with parameters
6. Generate output nodes
"""

import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from mount_solver import (
    DonorEngineExtractor,
    TargetVehicleExtractor,
    MountSolver,
    SwapParameters,
    solve_engine_mount,
)
from engineswap import JBeamParser

def main():
    print("=" * 70)
    print("FULL WORKFLOW TEST: Pickup + Camso 3813e Engine Swap")
    print("=" * 70)
    
    # ========================================================================
    # STEP 1: Load Swap Parameters
    # ========================================================================
    print("\n[STEP 1] Loading swap parameters from JSON...")
    params_path = Path(r"M:\BeamNG_Modding_Temp\configs\swap_parameters.json")
    
    if params_path.exists():
        params = SwapParameters.from_file(params_path)
        print(f"  ✓ Loaded parameters from {params_path.name}")
        print(f"    - fix_mesh_offset: {params.fix_mesh_offset}")
        print(f"    - shrink_or_expand: {params.shrink_or_expand.value}")
        print(f"    - fore_aft_offset: {params.fore_aft_offset}")
        print(f"    - up_down_offset: {params.up_down_offset}")
        print(f"    - left_right_offset: {params.left_right_offset}")
        print(f"    - max_shrink_percent: {params.max_shrink_percent}")
        print(f"    - output_format: {params.output_format.value}")
    else:
        print(f"  ! Parameters file not found, using defaults")
        params = SwapParameters.defaults()
    
    # ========================================================================
    # STEP 2: Parse Donor Engine (Camso 3813e)
    # ========================================================================
    print("\n[STEP 2] Parsing donor Camso 3813e engine...")
    
    # The Camso engine uses TWO files:
    # - camso_engine_3813e.jbeam: Engine definition, slotType, powertrain
    # - camso_engine_structure_ec8ba.jbeam: Physical nodes (engine0-7)
    
    engine_main_path = Path(
        r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles"
        r"\persh_crayenne_moracc\eng_3813e\camso_engine_3813e.jbeam"
    )
    
    engine_structure_path = Path(
        r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles"
        r"\persh_crayenne_moracc\ec8ba\camso_engine_structure_ec8ba.jbeam"
    )
    
    donor_data = {}
    
    # Parse main engine file (for reference)
    if engine_main_path.exists():
        data = JBeamParser.parse_jbeam(engine_main_path)
        if data:
            donor_data.update(data)
            print(f"  ✓ Parsed {engine_main_path.name}")
            # Show what we found
            for part_name in list(data.keys())[:2]:
                print(f"    - Found part: {part_name}")
    
    # Parse structure file (contains nodes)
    if engine_structure_path.exists():
        data = JBeamParser.parse_jbeam(engine_structure_path)
        if data:
            donor_data.update(data)
            print(f"  ✓ Parsed {engine_structure_path.name}")
            for part_name in data.keys():
                print(f"    - Found part: {part_name}")
    
    if not donor_data:
        print("  ✗ ERROR: Failed to parse donor engine files")
        return
    
    # ========================================================================
    # STEP 3: Extract Donor Geometry
    # ========================================================================
    print("\n[STEP 3] Extracting donor engine geometry...")
    
    donor_extractor = DonorEngineExtractor(donor_data)
    try:
        donor_cube = donor_extractor.extract()
        print(f"  ✓ Extracted engine cube with {len(donor_cube.nodes)} nodes")
        
        # Show key metrics
        print(f"    - Centroid: ({donor_cube.centroid.x:.3f}, {donor_cube.centroid.y:.3f}, {donor_cube.centroid.z:.3f})")
        min_c, max_c = donor_cube.get_aabb()
        dimensions = max_c - min_c
        print(f"    - Dimensions: {dimensions.x:.3f}m × {dimensions.y:.3f}m × {dimensions.z:.3f}m (W×L×H)")
        
        # Show flywheel/floor references
        flywheel_nodes = donor_cube.get_flywheel_plane_nodes()
        flywheel_y = donor_cube.get_plane_centroid(flywheel_nodes).y
        floor_nodes = donor_cube.get_floor_plane_nodes()
        floor_z = donor_cube.get_plane_centroid(floor_nodes).z
        print(f"    - Flywheel plane Y: {flywheel_y:.3f}m")
        print(f"    - Floor plane Z: {floor_z:.3f}m")
        
        # Show gearbox nodes
        gearbox = donor_extractor.get_gearbox_nodes()
        print(f"    - Gearbox nodes: {len(gearbox)}")
        
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        return
    
    # ========================================================================
    # STEP 4: Parse Target Vehicle (Pickup)
    # ========================================================================
    print("\n[STEP 4] Parsing target pickup vehicle...")
    
    # Pickup uses common folder architecture
    pickup_engine_path = Path(
        r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles\common"
        r"\vehicles\common\pickup\pickup_engine_v8_5.5.jbeam"
    )
    
    pickup_transmission_path = Path(
        r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles\common"
        r"\vehicles\common\pickup\pickup_transmission.jbeam"
    )
    
    target_data = {}
    
    for filepath in [pickup_engine_path, pickup_transmission_path]:
        if filepath.exists():
            data = JBeamParser.parse_jbeam(filepath)
            if data:
                target_data.update(data)
                print(f"  ✓ Parsed {filepath.name}")
                # Show first part found
                if data:
                    first_part = list(data.keys())[0]
                    print(f"    - Found part: {first_part}")
    
    if not target_data:
        print("  ✗ ERROR: Failed to parse target vehicle files")
        return
    
    # ========================================================================
    # STEP 5: Extract Target Geometry
    # ========================================================================
    print("\n[STEP 5] Extracting target vehicle geometry...")
    
    target_extractor = TargetVehicleExtractor(target_data)
    
    # Extract mount nodes (em1l, em1r, tra1)
    target_mounts = target_extractor.extract_mounts()
    print(f"  ✓ Extracted {len(target_mounts)} mount nodes:")
    for mount in target_mounts:
        print(f"    - {mount.name} ({mount.mount_type}): ({mount.position.x:.3f}, {mount.position.y:.3f}, {mount.position.z:.3f})")
    
    # Extract reference engine cube (optional, for comparison)
    target_ref_cube = target_extractor.extract_engine_cube()
    if target_ref_cube:
        print(f"  ✓ Extracted reference engine cube ({len(target_ref_cube.nodes)} nodes)")
        print(f"    - Centroid: ({target_ref_cube.centroid.x:.3f}, {target_ref_cube.centroid.y:.3f}, {target_ref_cube.centroid.z:.3f})")
        
        flywheel_nodes = target_ref_cube.get_flywheel_plane_nodes()
        flywheel_y = target_ref_cube.get_plane_centroid(flywheel_nodes).y
        floor_nodes = target_ref_cube.get_floor_plane_nodes()
        floor_z = target_ref_cube.get_plane_centroid(floor_nodes).z
        print(f"    - Flywheel plane Y: {flywheel_y:.3f}m")
        print(f"    - Floor plane Z: {floor_z:.3f}m")
    
    # ========================================================================
    # STEP 6: Run Mount Solver
    # ========================================================================
    print("\n[STEP 6] Running mount solver algorithm...")
    
    solver = MountSolver(
        donor_cube=donor_cube,
        target_mounts=target_mounts,
        target_reference_cube=target_ref_cube,
        params=params
    )
    
    result = solver.solve()
    
    if result.success:
        print(f"  ✓ Solver completed successfully")
    else:
        print(f"  ✗ Solver failed")
    
    print(f"\n  Translation Applied:")
    print(f"    - X (lateral): {result.translation.x:.4f}m ({'right' if result.translation.x > 0 else 'left'})")
    print(f"    - Y (longitudinal): {result.translation.y:.4f}m ({'rearward' if result.translation.y > 0 else 'forward'})")
    print(f"    - Z (vertical): {result.translation.z:.4f}m ({'upward' if result.translation.z > 0 else 'downward'})")
    
    if result.scale_applied != 1.0:
        shrink_pct = (1.0 - result.scale_applied) * 100
        print(f"    - Engine cube scaled: {result.scale_applied:.4f} ({shrink_pct:.1f}% shrink)")
    else:
        print(f"    - No scaling applied")
    
    if result.warnings:
        print(f"\n  ⚠ Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            print(f"    - {warning}")
    
    if result.errors:
        print(f"\n  ✗ Errors ({len(result.errors)}):")
        for error in result.errors:
            print(f"    - {error}")
    
    # ========================================================================
    # STEP 7: Analyze Results
    # ========================================================================
    print("\n[STEP 7] Analyzing translated geometry...")
    
    if result.engine_cube:
        translated_cube = result.engine_cube
        
        # Show translated positions
        print(f"  Translated engine cube (BeamNG naming):")
        print(f"    Node positions (sample):")
        for name in ['e1l', 'e1r', 'e3l', 'e3r']:
            if name in translated_cube.nodes:
                node = translated_cube.nodes[name]
                print(f"      {name}: ({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
        
        # Check clearances to mount nodes
        print(f"\n  Mount node clearances:")
        for mount in target_mounts:
            inside = translated_cube.contains_point(mount.position, margin=-params.min_mount_clearance_m)
            status = "⚠ INSIDE" if inside else "✓ Clear"
            
            # Calculate distance to nearest face
            min_c, max_c = translated_cube.get_aabb()
            clearances = [
                abs(mount.position.x - min_c.x),
                abs(mount.position.x - max_c.x),
                abs(mount.position.y - min_c.y),
                abs(mount.position.y - max_c.y),
                abs(mount.position.z - min_c.z),
                abs(mount.position.z - max_c.z),
            ]
            min_clearance = min(clearances)
            
            print(f"    {mount.name}: {status} (clearance: {min_clearance:.4f}m)")
    
    # ========================================================================
    # STEP 8: Generate Output
    # ========================================================================
    print("\n[STEP 8] Generating jbeam output...")
    
    jbeam_nodes = result.to_jbeam_nodes()
    print(f"  ✓ Generated {len(jbeam_nodes)} node arrays")
    
    print(f"\n  Sample output (first 3 nodes):")
    for i, node_arr in enumerate(jbeam_nodes[:3]):
        # Format: [name, x, y, z, {props}]
        name = node_arr[0]
        x, y, z = node_arr[1], node_arr[2], node_arr[3]
        print(f"    [{name!r}, {x:.4f}, {y:.4f}, {z:.4f}, {{...}}]")
    
    if len(jbeam_nodes) > 3:
        print(f"    ... and {len(jbeam_nodes) - 3} more nodes")
    
    # ========================================================================
    # STEP 9: Summary
    # ========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    print(f"\nDonor Engine (Camso 3813e):")
    print(f"  - Original size: {dimensions.x:.3f}m × {dimensions.y:.3f}m × {dimensions.z:.3f}m")
    print(f"  - Nodes extracted: {len(donor_cube.nodes)} engine + {len(gearbox)} gearbox")
    
    print(f"\nTarget Vehicle (Pickup):")
    print(f"  - Mount nodes: {len(target_mounts)} (em1l, em1r, tra1)")
    print(f"  - Reference engine: {'Available' if target_ref_cube else 'Not available'}")
    
    print(f"\nTransformation:")
    print(f"  - Translation: ({result.translation.x:.4f}, {result.translation.y:.4f}, {result.translation.z:.4f})m")
    print(f"  - Scale: {result.scale_applied:.4f}")
    print(f"  - Interference: {'Resolved' if result.scale_applied < 1.0 else 'None detected' if not result.warnings else 'Detected'}")
    
    print(f"\nOutput:")
    print(f"  - Nodes generated: {len(jbeam_nodes)}")
    print(f"  - Format: {params.output_format.value}")
    print(f"  - Ready for: Integration into engineswap.py")
    
    status = "✓ SUCCESS" if result.success else "✗ FAILED"
    print(f"\nStatus: {status}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
