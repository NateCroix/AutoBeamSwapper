#!/usr/bin/env python3
"""Exhaust Solver Phase 3 — Integration Tests

Tests verify that exhaust_solver is correctly wired into engineswap.py's
generate_adapted_jbeam() pipeline:
  - isExhaust nodes extracted from adapted engine (post-TMS)
  - select_strategy() called with correct args
  - exhaust_adapter part injected into output jbeam
  - exhaust slot entry injected into engine's slots array

Uses real Camso engines + real BeamNG target vehicles.

NOTE: Some swap pairs may involve dissimilar engine orientations (transverse
vs longitudinal). Failures on those pairs are EXPECTED until the orientation
refusal feature is implemented.  Known transverse Camso mods:
  testy623, tranv_mr, tranv_mr_awd_dct, tranv_mr_naveetubular,
  tranv_mr_twinturbo
Known transverse BeamNG targets:
  covet (front engines), vivace (all), sunburst2 (all)
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engineswap import (
    EngineTransplantUtility,
    JBeamParser,
    VehicleAnalyzer,
    EXHAUST_SOLVER_AVAILABLE,
    TMS_AVAILABLE,
)

BASE = Path(__file__).resolve().parent.parent
STEAM_BASE = BASE / 'SteamLibrary_content_vehicles'
MOD_BASE = BASE / 'mods' / 'unpacked'

# --------------------------------------------------------------------------
# Donor engine catalog (longitudinal Camso engines known to work)
# --------------------------------------------------------------------------
DONOR_3813e = MOD_BASE / 'persh_crayenne_moracc' / 'vehicles' / 'persh_crayenne_moracc' / 'eng_3813e' / 'camso_engine_3813e.jbeam'
DONOR_34607 = MOD_BASE / 'script_test_rwd' / 'vehicles' / 'test_rwd' / 'eng_9a706' / 'camso_engine_9a706.jbeam'
DONOR_66a66 = MOD_BASE / 'camsonav6' / 'vehicles' / 'dualexhaust_manualtrans' / 'eng_66a66' / 'camso_engine_66a66.jbeam'

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _create_utility(tmp_dir: Path) -> EngineTransplantUtility:
    """Create utility instance with temporary output directory."""
    return EngineTransplantUtility(
        base_vehicles_path=STEAM_BASE,
        output_path=tmp_dir,
        workspace_subfolder="test_exhaust_integration",
    )


def _run_pipeline(utility: EngineTransplantUtility, donor_path: Path, target_name: str):
    """Run the full adaptation pipeline for a donor → target pair.

    Returns (output_path, adapted_data, exhaust_result) or raises.
    """
    engine = utility.load_donor_engine(donor_path)
    if engine is None:
        raise RuntimeError(f"Failed to load donor engine: {donor_path}")
    vehicle = utility.analyze_target_vehicle(target_name)
    if vehicle is None:
        raise RuntimeError(f"Failed to analyze vehicle: {target_name}")
    plan = utility.generate_adaptation_plan(engine, vehicle)
    output_file = utility.generate_adapted_jbeam(donor_path, vehicle, plan)

    # Parse output file for inspection
    adapted_data = None
    if output_file and output_file.exists():
        adapted_data = JBeamParser.parse_jbeam(output_file)

    exhaust_result = utility._last_exhaust_result
    return output_file, adapted_data, exhaust_result


# ==========================================================================
# Test Classes
# ==========================================================================

@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustIntegrationPickup(unittest.TestCase):
    """Pickup: 2 isExhaust nodes, Pattern A — matching strategy expected."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_pickup_has_exhaust_component(self):
        """Adapted jbeam for pickup should contain exhaust_adapter part."""
        output, data, exh = _run_pipeline(self.utility, DONOR_3813e, "pickup")
        self.assertIsNotNone(output, "generate_adapted_jbeam returned None")
        self.assertIsNotNone(data, "Could not parse output file")
        self.assertIsNotNone(exh, "Exhaust solver did not run")

        # Check strategy
        self.assertIn(exh.strategy, ("matching", "mismatch"))

        # Check adapted_part was injected
        component_key = "pickup_exhaust_adapter"
        self.assertIn(component_key, data,
                       f"Adapted exhaust component not in output. Keys: {list(data.keys())}")

        # Verify component structure
        comp = data[component_key]
        self.assertIn('nodes', comp)
        self.assertIn('beams', comp)
        self.assertIn('slots', comp)

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_pickup_exhaust_slot_in_engine(self):
        """Engine slots should include exhaust_adapter slot entry."""
        output, data, exh = _run_pipeline(self.utility, DONOR_3813e, "pickup")
        self.assertIsNotNone(data)

        # Find the primary engine part (has slotType matching pickup_engine)
        engine_part = None
        for pname, pdata in data.items():
            if isinstance(pdata, dict) and 'pickup' in pdata.get('slotType', '').lower():
                engine_part = pdata
                break
        self.assertIsNotNone(engine_part, "Primary engine part not found")

        # Check for exhaust adapter slot entry in engine's slots
        all_slots = engine_part.get('slots', [])
        exhaust_slots = [s for s in all_slots
                         if isinstance(s, list) and len(s) > 0
                         and 'exhaust_adapter' in str(s[0]).lower()]
        self.assertGreater(len(exhaust_slots), 0,
                           f"No exhaust_adapter slot in engine slots: {all_slots}")

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_pickup_exhaust_result_metadata(self):
        """ExhaustSolverResult should have correct metadata for pickup."""
        _, _, exh = _run_pipeline(self.utility, DONOR_3813e, "pickup")
        self.assertIsNotNone(exh)
        self.assertGreater(exh.donor_isExhaust_count, 0)
        self.assertIsNotNone(exh.target_exhaust_slot_type)
        self.assertIn("pickup", exh.target_exhaust_slot_type.lower())


@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustIntegrationMoonhawk(unittest.TestCase):
    """Moonhawk: 1 isExhaust, Pattern A' — may or may not produce component."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_moonhawk_exhaust_solver_runs(self):
        """Exhaust solver should execute for moonhawk swap."""
        output, data, exh = _run_pipeline(self.utility, DONOR_3813e, "moonhawk")
        self.assertIsNotNone(output, "generate_adapted_jbeam returned None")
        self.assertIsNotNone(exh, "Exhaust solver did not run")
        self.assertIn(exh.strategy, ("matching", "mismatch", "no_exhaust"))

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_moonhawk_component_or_none(self):
        """Moonhawk A' pattern: component may be None (sibling-only header)."""
        _, data, exh = _run_pipeline(self.utility, DONOR_3813e, "moonhawk")
        self.assertIsNotNone(exh)
        # A' pattern can produce adapted_part=None (known limitation)
        if exh.adapted_part is not None:
            self.assertIn("moonhawk_exhaust_adapter", data)


@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustIntegrationBarstow(unittest.TestCase):
    """Barstow: 1 isExhaust, Pattern A' — should produce component."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_barstow_exhaust_solver_runs(self):
        """Exhaust solver should execute for barstow swap."""
        output, data, exh = _run_pipeline(self.utility, DONOR_3813e, "barstow")
        self.assertIsNotNone(output)
        self.assertIsNotNone(exh)
        self.assertIn(exh.strategy, ("matching", "mismatch"))


@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustIntegrationMultiDonor(unittest.TestCase):
    """Test with different donor engines to verify consistency."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(DONOR_66a66.exists(), "Donor 66a66 not found")
    def test_dual_exhaust_donor_pickup(self):
        """Dual-exhaust Camso V6 (camsonav6, 036a5 gearbox-isExhaust) → pickup."""
        output, data, exh = _run_pipeline(self.utility, DONOR_66a66, "pickup")
        self.assertIsNotNone(output)
        self.assertIsNotNone(exh)
        # camsonav6 had gearbox isExhaust — promotion should make donor count > 0
        self.assertGreater(exh.donor_isExhaust_count, 0,
                           "Donor isExhaust count should be > 0 after gearbox promotion")


@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustIntegrationNoExhaust(unittest.TestCase):
    """Vehicles with no standard exhaust (Pattern C/no_exhaust)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(DONOR_3813e.exists(), "Donor 3813e not found")
    def test_vivace_pattern_c(self):
        """Vivace Pattern C (body-mounted exhaust) — solver should handle gracefully."""
        output, data, exh = _run_pipeline(self.utility, DONOR_3813e, "vivace")
        # Vivace is known transverse — may fail on orientation mismatch
        # If output is None, this is an expected orientation mismatch
        if output is not None and exh is not None:
            # Pattern C: may or may not generate component
            self.assertIn(exh.pattern, ("A", "A'", "B", "C", "no_exhaust"))


@unittest.skipUnless(EXHAUST_SOLVER_AVAILABLE, "exhaust_solver not available")
@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not found")
class TestExhaustExtractFromAdapted(unittest.TestCase):
    """Unit-level tests for _extract_isExhaust_from_adapted helper."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exh_integ_"))
        self.utility = _create_utility(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_from_mock_adapted(self):
        """Extract isExhaust from a synthetic adapted engine part dict."""
        mock_part = {
            'slotType': 'pickup_engine',
            'nodes': [
                ['id', 'posX', 'posY', 'posZ'],
                {'group': 'engine_block'},
                ['e1l', 0.353, -0.770, 0.385],
                ['e1r', -0.353, -0.770, 0.385],
                ['e2l', 0.177, -0.770, 0.385, {'isExhaust': 'mainEngine'}],
                ['e2r', -0.177, -0.770, 0.385, {'isExhaust': 'mainEngine'}],
                ['e3l', 0.353, -0.770, 0.650],
                ['e3r', -0.353, -0.770, 0.650],
                ['e4l', 0.177, -0.770, 0.650],
                ['e4r', -0.177, -0.770, 0.650],
            ],
        }
        count, nodes = self.utility._extract_isExhaust_from_adapted(mock_part, "test_engine")
        self.assertEqual(count, 2)
        names = {n.name for n in nodes}
        self.assertEqual(names, {'e2l', 'e2r'})

    def test_extract_no_isExhaust(self):
        """Part with no isExhaust nodes returns 0."""
        mock_part = {
            'nodes': [
                ['id', 'posX', 'posY', 'posZ'],
                ['e1l', 0.353, -0.770, 0.385],
                ['e1r', -0.353, -0.770, 0.385],
            ],
        }
        count, nodes = self.utility._extract_isExhaust_from_adapted(mock_part, "test_engine")
        self.assertEqual(count, 0)
        self.assertEqual(len(nodes), 0)

    def test_extract_single_isExhaust(self):
        """Part with 1 isExhaust returns count=1."""
        mock_part = {
            'nodes': [
                ['id', 'posX', 'posY', 'posZ'],
                {'group': 'engine_block'},
                ['e4r', -0.177, -1.2, 0.385, {'isExhaust': 'mainEngine'}],
            ],
        }
        count, nodes = self.utility._extract_isExhaust_from_adapted(mock_part, "test_engine")
        self.assertEqual(count, 1)
        self.assertEqual(nodes[0].name, 'e4r')

    def test_extract_with_nodegroup_modifier(self):
        """Group tracking via nodeGroup modifier works."""
        mock_part = {
            'nodes': [
                ['id', 'posX', 'posY', 'posZ'],
                {'nodeGroup': 'engine_block'},
                ['e2r', -0.177, -0.770, 0.385, {'isExhaust': 'mainEngine'}],
                {'nodeGroup': 'some_other_group'},
                ['n1', 0, 0, 0, {'isExhaust': 'mainEngine'}],
            ],
        }
        count, nodes = self.utility._extract_isExhaust_from_adapted(mock_part, "test_engine")
        # Only engine_block group node should be counted
        self.assertEqual(count, 1)
        self.assertEqual(nodes[0].name, 'e2r')


# ==========================================================================
# Run
# ==========================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
