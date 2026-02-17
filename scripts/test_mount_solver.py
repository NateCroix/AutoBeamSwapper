"""
Test script for Transplant Mounting Solver (TMS) extractors.

This script tests the DonorEngineExtractor and TargetVehicleExtractor
with real Camso and pickup jbeam data.
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
    Vec3,
)

# Import the jbeam parser from engineswap
from engineswap import JBeamParser


def test_donor_extraction():
    """Test extracting Camso engine nodes."""
    print("\n" + "=" * 60)
    print("TEST: Camso Donor Engine Extraction")
    print("=" * 60)
    
    camso_structure_path = Path(
        r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles"
        r"\persh_crayenne_moracc\ec8ba\camso_engine_structure_ec8ba.jbeam"
    )
    
    if not camso_structure_path.exists():
        print(f"ERROR: File not found: {camso_structure_path}")
        return None
    
    # Parse the jbeam file using classmethod
    try:
        data = JBeamParser.parse_jbeam(camso_structure_path)
        if data is None:
            print(f"ERROR: Failed to parse {camso_structure_path.name}")
            return None
        print(f"✓ Parsed {camso_structure_path.name}")
    except Exception as e:
        print(f"✗ Parse error: {e}")
        return None
    
    # Extract engine cube
    extractor = DonorEngineExtractor(data)
    try:
        cube = extractor.extract()
        print(f"✓ Extracted engine cube with {len(cube.nodes)} nodes")
        
        # Display nodes
        print("\n  Engine Cube Nodes:")
        for name, node in sorted(cube.nodes.items()):
            print(f"    {name}: ({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
        
        # Display derived geometry
        print(f"\n  Centroid: {cube.centroid}")
        min_c, max_c = cube.get_aabb()
        print(f"  AABB Min: {min_c}")
        print(f"  AABB Max: {max_c}")
        
        # Test plane nodes
        flywheel_nodes = cube.get_flywheel_plane_nodes()
        floor_nodes = cube.get_floor_plane_nodes()
        print(f"\n  Flywheel plane nodes ({len(flywheel_nodes)}): {[n.name for n in flywheel_nodes]}")
        print(f"  Floor plane nodes ({len(floor_nodes)}): {[n.name for n in floor_nodes]}")
        
        flywheel_centroid = cube.get_plane_centroid(flywheel_nodes)
        floor_centroid = cube.get_plane_centroid(floor_nodes)
        print(f"  Flywheel plane centroid Y: {flywheel_centroid.y:.4f}")
        print(f"  Floor plane centroid Z: {floor_centroid.z:.4f}")
        
        # Get gearbox nodes
        gearbox = extractor.get_gearbox_nodes()
        print(f"\n  Gearbox Nodes ({len(gearbox)}):")
        for name, node in sorted(gearbox.items()):
            print(f"    {name}: ({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
        
        return cube
        
    except Exception as e:
        print(f"✗ Extraction error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_target_extraction():
    """Test extracting pickup target vehicle nodes."""
    print("\n" + "=" * 60)
    print("TEST: Pickup Target Vehicle Extraction")
    print("=" * 60)
    
    # We need to load multiple files for complete picture:
    # 1. Engine file (defines e1l, e1r, etc. and em1l, em1r)
    # 2. Transmission file (defines tra1)
    
    engine_path = Path(
        r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles\common"
        r"\vehicles\common\pickup\pickup_engine_v8_5.5.jbeam"
    )
    
    transmission_path = Path(
        r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles\common"
        r"\vehicles\common\pickup\pickup_transmission.jbeam"
    )
    
    parser = JBeamParser()
    combined_data = {}
    
    for filepath in [engine_path, transmission_path]:
        if not filepath.exists():
            print(f"ERROR: File not found: {filepath}")
            continue
        try:
            data = JBeamParser.parse_jbeam(filepath)
            if data:
                combined_data.update(data)
                print(f"✓ Parsed {filepath.name}")
            else:
                print(f"✗ Failed to parse {filepath.name}")
        except Exception as e:
            print(f"✗ Parse error for {filepath.name}: {e}")
    
    if not combined_data:
        print("ERROR: No data loaded")
        return None, None
    
    # Extract mount nodes
    extractor = TargetVehicleExtractor(combined_data)
    
    mounts = extractor.extract_mounts()
    print(f"\n✓ Extracted {len(mounts)} mount nodes:")
    for mount in mounts:
        print(f"    {mount.name} ({mount.mount_type}): ({mount.position.x:.4f}, {mount.position.y:.4f}, {mount.position.z:.4f})")
    
    # Extract reference engine cube
    ref_cube = extractor.extract_engine_cube()
    if ref_cube:
        print(f"\n✓ Extracted reference engine cube with {len(ref_cube.nodes)} nodes")
        
        print("\n  Engine Cube Nodes (BeamNG pattern):")
        for name, node in sorted(ref_cube.nodes.items()):
            print(f"    {name}: ({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
        
        print(f"\n  Centroid: {ref_cube.centroid}")
        
        flywheel_nodes = ref_cube.get_flywheel_plane_nodes()
        floor_nodes = ref_cube.get_floor_plane_nodes()
        flywheel_centroid = ref_cube.get_plane_centroid(flywheel_nodes)
        floor_centroid = ref_cube.get_plane_centroid(floor_nodes)
        print(f"  Flywheel plane centroid Y: {flywheel_centroid.y:.4f}")
        print(f"  Floor plane centroid Z: {floor_centroid.z:.4f}")
    else:
        print("\n! No reference engine cube found")
    
    return mounts, ref_cube


def test_solver():
    """Test the full solver with real data."""
    print("\n" + "=" * 60)
    print("TEST: Mount Solver")
    print("=" * 60)
    
    # Get donor cube
    donor_cube = test_donor_extraction()
    if not donor_cube:
        print("ERROR: Failed to extract donor cube")
        return
    
    # Get target mounts and reference
    target_mounts, target_ref = test_target_extraction()
    if not target_mounts:
        print("WARNING: No mount nodes extracted from target")
    
    # Load parameters from swap_parameters.json
    params_file = Path(r"M:\BeamNG_Modding_Temp\configs\swap_parameters.json")
    if params_file.exists():
        params = SwapParameters.from_file(params_file)
        print(f"\n  ✓ Loaded parameters from {params_file.name}")
        print(f"    shrink_or_expand: {params.shrink_or_expand.value}")
        print(f"    fore_aft_offset: {params.fore_aft_offset}")
    else:
        params = SwapParameters.defaults()
        print("\n  Using default parameters (file not found)")
    
    solver = MountSolver(
        donor_cube=donor_cube,
        target_mounts=target_mounts or [],
        target_reference_cube=target_ref,
        params=params
    )
    
    # Solve
    print("\n  Running solver...")
    result = solver.solve()
    
    print(f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  Translation: {result.translation}")
    print(f"  Scale applied: {result.scale_applied:.4f}")
    
    if result.warnings:
        print(f"\n  Warnings:")
        for w in result.warnings:
            print(f"    - {w}")
    
    if result.errors:
        print(f"\n  Errors:")
        for e in result.errors:
            print(f"    - {e}")
    
    if result.engine_cube:
        print(f"\n  Translated Engine Cube ({result.engine_cube.source_pattern} naming):")
        for name, node in sorted(result.engine_cube.nodes.items()):
            print(f"    {name}: ({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
        
        # Generate jbeam output
        jbeam_nodes = result.to_jbeam_nodes()
        print(f"\n  JBeam node arrays ({len(jbeam_nodes)} nodes):")
        for node_arr in jbeam_nodes[:4]:  # Show first 4
            print(f"    {node_arr}")
        if len(jbeam_nodes) > 4:
            print(f"    ... and {len(jbeam_nodes) - 4} more")


if __name__ == "__main__":
    print("=" * 60)
    print("Transplant Mounting Solver - Real Data Test")
    print("=" * 60)
    
    test_solver()
    
    print("\n" + "=" * 60)
    print("Tests complete")
    print("=" * 60)


# =========================================================================
# Unit Tests — Gearbox isExhaust Promotion
# =========================================================================

import unittest

from mount_solver import EngineNode


def _mock_camso_nodes_with_gearbox_exhaust():
    """Simulate c9a0e engine: isExhaust on engine_Gearbox8/9, not engine cube.

    Geometry matches the real c9a0e engine from mid_longitudinal_rearwd.
    Floor plane Z = 0.384707 (bottom 4 cube nodes + both gearbox exhaust nodes).
    Top plane  Z = 0.684462.
    engine3 has engineGroup=["engine_block"] (rear-right-bottom, eligible).
    engine7 has engineGroup=["engine_block", "engine_intake"] (rear-right-top, ineligible).
    """
    return {
        "Camso_engine_structure_test": {
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine", "selfCollision": False},
                {"nodeWeight": 36.6122},
                # --- engine cube (engine0-7) ---
                ["engine0", -0.353223, 0.894515, 0.384707, {"engineGroup": ["engine_block"]}],
                ["engine1",  0.353223, 0.894515, 0.384707, {"engineGroup": ["engine_block"]}],
                ["engine2",  0.353223, 1.39033,  0.384707, {"engineGroup": ["engine_block"]}],
                ["engine3", -0.353223, 1.39033,  0.384707, {"engineGroup": ["engine_block"]}],
                ["engine4", -0.353223, 0.894515, 0.684462, {"engineGroup": ["engine_block", "engine_intake"]}],
                ["engine5",  0.353223, 0.894515, 0.684462, {"engineGroup": ["engine_block"]}],
                ["engine6",  0.353223, 1.39033,  0.684462, {"engineGroup": ["engine_block"]}],
                ["engine7", -0.353223, 1.39033,  0.684462, {"engineGroup": ["engine_block", "engine_intake"]}],
                # --- gearbox nodes (isExhaust here, NOT on cube) ---
                {"nodeWeight": 14.9746},
                ["engine_Gearbox8",  -0.176611, 1.51428, 0.384707, {"isExhaust": "mainEngine"}],
                ["engine_Gearbox9",   0.176611, 1.51428, 0.384707, {"isExhaust": "mainEngine"}],
                ["engine_Gearbox10",  0.176611, 1.51428, 0.534585, {}],
                ["engine_Gearbox11", -0.176611, 1.51428, 0.534585, {}],
            ],
        },
    }


def _mock_camso_nodes_normal():
    """Simulate a standard engine: isExhaust on engine2 (engine cube node)."""
    return {
        "Camso_engine_structure_normal": {
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine"},
                {"nodeWeight": 30.0},
                ["engine0",  0.2, 0.8, 0.3, {"engineGroup": ["engine_block"]}],
                ["engine1", -0.2, 0.8, 0.3, {"engineGroup": ["engine_block"]}],
                ["engine2", -0.2, 1.3, 0.3, {"engineGroup": ["engine_block"], "isExhaust": "mainEngine"}],
                ["engine3",  0.2, 1.3, 0.3, {"engineGroup": ["engine_block"]}],
                ["engine4",  0.2, 0.8, 0.6, {"engineGroup": ["engine_block"]}],
                ["engine5", -0.2, 0.8, 0.6, {"engineGroup": ["engine_block"]}],
                ["engine6", -0.2, 1.3, 0.6, {"engineGroup": ["engine_block"]}],
                ["engine7",  0.2, 1.3, 0.6, {"engineGroup": ["engine_block"]}],
                {"nodeWeight": 10.0},
                ["engine_Gearbox8",  -0.1, 1.5, 0.3, {}],
                ["engine_Gearbox9",   0.1, 1.5, 0.3, {}],
                ["engine_Gearbox10",  0.1, 1.5, 0.5, {}],
                ["engine_Gearbox11", -0.1, 1.5, 0.5, {}],
            ],
        },
    }


class TestGearboxIsExhaustPromotion(unittest.TestCase):
    """Test _promote_gearbox_isExhaust in DonorEngineExtractor."""

    def test_promotes_dual_gearbox_isExhaust(self):
        """c9a0e pattern: 2 gearbox nodes carry isExhaust → promoted to cube."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        # After extraction, the cube nodes should carry isExhaust
        exhaust_nodes = {
            name: node for name, node in cube.nodes.items()
            if node.node_properties.get("isExhaust")
        }
        self.assertEqual(len(exhaust_nodes), 2, f"Expected 2 isExhaust, got: {list(exhaust_nodes)}")

    def test_promotes_to_floor_plane_only(self):
        """isExhaust should land on bottom-plane nodes (same Z as gearbox)."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        for name, node in cube.nodes.items():
            if node.node_properties.get("isExhaust"):
                self.assertAlmostEqual(
                    node.position.z, 0.384707, places=3,
                    msg=f"isExhaust node {name} not on floor plane (z={node.position.z})",
                )

    def test_avoids_intake_nodes(self):
        """isExhaust must not land on nodes with engine_intake in engineGroup."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        for name, node in cube.nodes.items():
            if node.node_properties.get("isExhaust"):
                engine_group = node.node_properties.get("engineGroup", [])
                self.assertNotIn(
                    "engine_intake", engine_group,
                    f"isExhaust promoted to intake node {name}",
                )

    def test_correct_target_nodes_c9a0e(self):
        """For c9a0e geometry, Gearbox8→engine3, Gearbox9→engine2 (nearest)."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        # engine3 is at (-0.353, 1.390, 0.385) — nearest to Gearbox8 at (-0.177, 1.514, 0.385)
        # engine2 is at ( 0.353, 1.390, 0.385) — nearest to Gearbox9 at ( 0.177, 1.514, 0.385)
        self.assertEqual(
            cube.nodes["engine3"].node_properties.get("isExhaust"), "mainEngine",
            "engine3 should receive isExhaust from engine_Gearbox8",
        )
        self.assertEqual(
            cube.nodes["engine2"].node_properties.get("isExhaust"), "mainEngine",
            "engine2 should receive isExhaust from engine_Gearbox9",
        )

    def test_no_op_when_cube_has_isExhaust(self):
        """Normal engines with isExhaust already on cube nodes — no changes."""
        data = _mock_camso_nodes_normal()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        # engine2 should still have isExhaust
        self.assertEqual(
            cube.nodes["engine2"].node_properties.get("isExhaust"), "mainEngine",
        )
        # Only 1 isExhaust total
        count = sum(
            1 for n in cube.nodes.values()
            if n.node_properties.get("isExhaust")
        )
        self.assertEqual(count, 1)

    def test_gearbox_nodes_stripped_of_isExhaust_after_promotion(self):
        """After promotion, gearbox nodes should no longer carry isExhaust."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        extractor.extract()

        for node in extractor.get_gearbox_nodes().values():
            self.assertIsNone(
                node.node_properties.get("isExhaust"),
                f"Gearbox node {node.name} still has isExhaust after promotion",
            )

    def test_beamng_names_preserve_promoted_isExhaust(self):
        """After with_beamng_names(), promoted isExhaust survives on eNx nodes."""
        data = _mock_camso_nodes_with_gearbox_exhaust()
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()
        beamng_cube = cube.with_beamng_names()

        exhaust_nodes = {
            name: node for name, node in beamng_cube.nodes.items()
            if node.node_properties.get("isExhaust")
        }
        self.assertEqual(len(exhaust_nodes), 2)
        # engine2→e1l, engine3→e1r (the map in EngineCube)
        self.assertIn("e1l", exhaust_nodes, "engine2 → e1l should carry isExhaust")
        self.assertIn("e1r", exhaust_nodes, "engine3 → e1r should carry isExhaust")


REAL_C9A0E = Path(
    r"M:\BeamNG_Modding_Temp\mods\unpacked\mid_longitudinal_rearwd"
    r"\vehicles\test_mr\c9a0e\camso_engine_structure_c9a0e.jbeam"
)

REAL_036A5_CAMSONAV6 = Path(
    r"M:\BeamNG_Modding_Temp\mods\unpacked\camsonav6"
    r"\vehicles\dualexhaust_manualtrans\036a5\camso_engine_structure_036a5.jbeam"
)


@unittest.skipUnless(REAL_C9A0E.exists(), "c9a0e engine file not available")
class TestGearboxIsExhaustPromotionRealData(unittest.TestCase):
    """Integration test with real Camso engines that have gearbox isExhaust."""

    def test_c9a0e_dual_gearbox_exhaust(self):
        """Real c9a0e engine: Gearbox8/9 carry isExhaust → promoted to cube."""
        data = JBeamParser.parse_jbeam(REAL_C9A0E)
        self.assertIsNotNone(data)
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        exhaust_nodes = [
            name for name, node in cube.nodes.items()
            if node.node_properties.get("isExhaust")
        ]
        self.assertEqual(len(exhaust_nodes), 2, f"Expected 2 isExhaust on cube, got: {exhaust_nodes}")
        # Both should be floor-plane nodes
        for name in exhaust_nodes:
            self.assertAlmostEqual(cube.nodes[name].position.z, 0.384707, places=3)

    @unittest.skipUnless(REAL_036A5_CAMSONAV6.exists(), "036a5 camsonav6 file not available")
    def test_036a5_dual_gearbox_exhaust(self):
        """Real camsonav6/036a5 engine: same pattern as c9a0e."""
        data = JBeamParser.parse_jbeam(REAL_036A5_CAMSONAV6)
        self.assertIsNotNone(data)
        extractor = DonorEngineExtractor(data)
        cube = extractor.extract()

        exhaust_nodes = [
            name for name, node in cube.nodes.items()
            if node.node_properties.get("isExhaust")
        ]
        self.assertEqual(len(exhaust_nodes), 2, f"Expected 2 isExhaust on cube, got: {exhaust_nodes}")


# =========================================================================
# Run
# =========================================================================
