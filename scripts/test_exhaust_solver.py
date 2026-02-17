#!/usr/bin/env python3
"""Exhaust Solver Unit & Integration Tests (Phase 1 + Phase 2)

Tests cover:
  Phase 1:
  - Slot format helpers (_get_combined_slots, _is_slot_header, _extract_slot_fields)
  - Node extraction (extract_isExhaust_nodes)
  - Slot chain tracing (find_exhaust_slots_in_part, find_all_child_slots, trace_exhaust_chain)
  - Pattern classification (classify_pattern)
  - Candidate classification & strategy selection
  - Integration: real vehicle data validation (6 vehicles, 4 patterns)
  - Integration: adapted engine donor counting

  Phase 2:
  - Full node extraction (_extract_part_nodes_full)
  - Beam property extraction (_extract_beam_properties_from_part)
  - Adapted node generation (generate_adapted_nodes)
  - Structural beam generation (generate_structural_beams)
  - Matching isExhaust beams (1↔1, 2↔2 distance pairing)
  - Mismatch isExhaust beams (Y-pipe all↔all)
  - Slot entry generation (generate_slot_entry)
  - Full component generation (generate_adapted_exhaust_component)
  - Integration: strategy + component generation with real vehicle data
"""

import sys
import unittest
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exhaust_solver import (
    # Data classes
    IsExhaustNode, ExhaustSlotInfo, EngineExhaustProfile, ExhaustSolverResult,
    # Slot helpers
    _get_combined_slots, _is_slot_header, _extract_slot_fields,
    # Node extraction
    extract_isExhaust_nodes, _extract_part_nodes, count_donor_isExhaust_nodes,
    # File discovery
    find_engine_files, find_exhaust_files, find_body_frame_files,
    # Merged data
    build_merged_vehicle_data,
    # Slot tracing
    find_exhaust_slots_in_part, find_all_child_slots, _find_part_by_slotType,
    find_body_frame_exhaust_slots, trace_exhaust_chain,
    # Classification
    classify_pattern, _is_primary_engine_part,
    # Strategy
    classify_candidates, select_strategy, profile_vehicle_exhausts,
    # Phase 2 — Component Generation
    _extract_part_nodes_full, _extract_beam_properties_from_part,
    _euclidean_distance, _get_best_exhaust_slot_info,
    generate_adapted_nodes, generate_structural_beams,
    generate_matching_isExhaust_beams, generate_mismatch_isExhaust_beams,
    generate_slot_entry, generate_adapted_exhaust_component,
    # Constants
    EXHAUST_SLOT_PATTERNS, SLOTS_HEADER_KEYS, PARSER_AVAILABLE,
    _AUDIO_PROPS, _DEFAULT_BEAM_PROPS, _MAX_BEAM_SPRING,
)

BASE = Path(__file__).resolve().parent.parent
STEAM_BASE = BASE / 'SteamLibrary_content_vehicles'
MOD_BASE = BASE / 'mods' / 'unpacked' / 'engineswaps' / 'vehicles'


# =========================================================================
# Mock Data Builders
# =========================================================================

def _mock_engine_with_header_and_exhaust() -> Dict[str, Any]:
    """Pattern A: engine → header → exhaust."""
    return {
        "test_engine_v8": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e2r", 0.2, -1.0, 0.3, {"isExhaust": "mainEngine"}],
                ["e2l", -0.2, -1.0, 0.3, {"isExhaust": "mainEngine"}],
                ["e1r", 0.2, -1.5, 0.3],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_header", "test_header_v8", "Header"],
            ],
        },
        "test_header_v8": {
            "slotType": "test_header",
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                ["exm1r", 0.3, -0.8, 0.1],
                ["exm1l", -0.3, -0.8, 0.1],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_exhaust_v8", "test_exhaust_stock", "Exhaust"],
            ],
        },
    }


def _mock_engine_with_sibling_exhaust() -> Dict[str, Any]:
    """Pattern A': engine has exhaust as sibling (header is leaf)."""
    return {
        "test_engine_i6": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e4r", 0.2, -1.0, 0.5, {"isExhaust": "mainEngine"}],
                ["e1r", 0.2, -1.5, 0.3],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_header", "test_header_i6", "Header"],
                ["test_exhaust_i6", "test_exhaust_stock", "Exhaust"],
            ],
        },
        "test_header_i6": {
            "slotType": "test_header",
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                ["exm1r", 0.3, -0.9, 0.1],
            ],
            # No exhaust child slot — header is leaf node
        },
    }


def _mock_engine_intake_nested() -> Dict[str, Any]:
    """Pattern B: engine → intake → header → exhaust."""
    return {
        "test_engine_sohc": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e3r", 0.2, -1.0, 0.4, {"isExhaust": "mainEngine"}],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_intake", "test_intake_sohc", "Intake"],
            ],
        },
        "test_intake_sohc": {
            "slotType": "test_intake",
            "slots": [
                ["type", "default", "description"],
                ["test_header_sohc", "test_exhmanifold_sohc", "Header"],
            ],
        },
        "test_exhmanifold_sohc": {
            "slotType": "test_header_sohc",
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                ["exm1r", 0.3, -0.7, 0.15],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_exhaust", "test_exhaust_stock", "Exhaust"],
            ],
        },
    }


def _mock_body_frame_exhaust() -> Dict[str, Any]:
    """Pattern C: body/frame hosts exhaust, engine chain is leaf."""
    return {
        "test_engine_turbo": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e3l", -0.2, -1.0, 0.4, {"isExhaust": "mainEngine"}],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_header", "test_header_turbo", "Header"],
            ],
        },
        "test_header_turbo": {
            "slotType": "test_header",
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                ["exm1r", 0.3, -0.8, 0.1],
            ],
            # Leaf node — no exhaust child
        },
        "test_body": {
            "slotType": "test_body",
            "slots": [
                ["type", "default", "description"],
                ["test_engine", "test_engine_turbo", "Engine"],
                ["test_exhaust", "test_exhaust_stock", "Exhaust"],
            ],
        },
    }


def _mock_engine_slots2() -> Dict[str, Any]:
    """Modern slots2 format."""
    return {
        "test_engine_modern": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e3l", -0.2, -1.0, 0.4, {"isExhaust": "mainEngine"}],
            ],
            "slots2": [
                ["type", ["allowTypes"], ["denyTypes"], "default", "description"],
                ["test_header", ["test_header"], [], "test_header_mod", "Header"],
            ],
        },
    }


def _mock_engine_no_exhaust() -> Dict[str, Any]:
    """Engine with no exhaust system (electric or stripped)."""
    return {
        "test_engine_electric": {
            "slotType": "test_engine",
            "mainEngine": {},
            "nodes": [
                ["id", "posX", "posY", "posZ"],
                {"group": "engine_block"},
                ["e1l", -0.2, -1.5, 0.3],
                ["e1r", 0.2, -1.5, 0.3],
            ],
            "slots": [
                ["type", "default", "description"],
                ["test_motor_controller", "test_mc_default", "Motor Controller"],
            ],
        },
    }


# =========================================================================
# Unit Tests — Slot Format Helpers
# =========================================================================

class TestSlotHelpers(unittest.TestCase):
    """Test dual slots/slots2 support helpers."""

    def test_get_combined_slots_legacy_only(self):
        data = {"slots": [["a", "b", "c"], ["d", "e", "f"]]}
        result = _get_combined_slots(data)
        self.assertEqual(len(result), 2)

    def test_get_combined_slots_modern_only(self):
        data = {"slots2": [["a", ["x"], [], "b", "c"]]}
        result = _get_combined_slots(data)
        self.assertEqual(len(result), 1)

    def test_get_combined_slots_both(self):
        data = {
            "slots": [["a", "b", "c"]],
            "slots2": [["d", ["x"], [], "e", "f"]],
        }
        result = _get_combined_slots(data)
        self.assertEqual(len(result), 2)

    def test_get_combined_slots_empty(self):
        result = _get_combined_slots({})
        self.assertEqual(result, [])

    def test_is_slot_header_legacy(self):
        self.assertTrue(_is_slot_header(["type", "default", "description"]))

    def test_is_slot_header_modern(self):
        self.assertTrue(_is_slot_header(["type", ["allowTypes"], ["denyTypes"], "default", "description"]))

    def test_is_slot_header_real_slot(self):
        self.assertFalse(_is_slot_header(["pickup_engine", "pickup_engine_v8", "Engine"]))

    def test_is_slot_header_empty(self):
        self.assertFalse(_is_slot_header([]))

    def test_extract_slot_fields_legacy(self):
        st, default, desc = _extract_slot_fields(["test_engine", "test_v8", "V8 Engine"])
        self.assertEqual(st, "test_engine")
        self.assertEqual(default, "test_v8")
        self.assertEqual(desc, "V8 Engine")

    def test_extract_slot_fields_slots2(self):
        entry = ["test_engine", ["test_engine"], [], "test_v8", "V8 Engine"]
        st, default, desc = _extract_slot_fields(entry)
        self.assertEqual(st, "test_engine")
        self.assertEqual(default, "test_v8")
        self.assertEqual(desc, "V8 Engine")


# =========================================================================
# Unit Tests — Node Extraction
# =========================================================================

class TestNodeExtraction(unittest.TestCase):
    """Test isExhaust node extraction."""

    def test_extract_pattern_a(self):
        data = _mock_engine_with_header_and_exhaust()
        result = extract_isExhaust_nodes(data, "test_file.jbeam")
        self.assertIn("test_engine_v8", result)
        nodes = result["test_engine_v8"]
        self.assertEqual(len(nodes), 2)
        names = {n.name for n in nodes}
        self.assertEqual(names, {"e2r", "e2l"})

    def test_extract_pattern_a_group(self):
        data = _mock_engine_with_header_and_exhaust()
        result = extract_isExhaust_nodes(data, "test_file.jbeam")
        for node in result["test_engine_v8"]:
            self.assertEqual(node.group, "engine_block")

    def test_extract_single_isexhaust(self):
        data = _mock_engine_with_sibling_exhaust()
        result = extract_isExhaust_nodes(data, "test_file.jbeam")
        self.assertIn("test_engine_i6", result)
        self.assertEqual(len(result["test_engine_i6"]), 1)
        self.assertEqual(result["test_engine_i6"][0].name, "e4r")

    def test_extract_no_isexhaust(self):
        data = _mock_engine_no_exhaust()
        result = extract_isExhaust_nodes(data, "test_file.jbeam")
        self.assertEqual(len(result), 0)

    def test_extract_part_nodes(self):
        data = _mock_engine_with_header_and_exhaust()
        nodes = _extract_part_nodes(data, "test_header_v8")
        self.assertEqual(len(nodes), 2)
        names = {n['name'] for n in nodes}
        self.assertEqual(names, {"exm1r", "exm1l"})

    def test_extract_part_nodes_nonexistent(self):
        data = _mock_engine_with_header_and_exhaust()
        nodes = _extract_part_nodes(data, "nonexistent_part")
        self.assertEqual(len(nodes), 0)

    def test_group_tracking_across_modifiers(self):
        """Verify nodeGroup modifier correctly changes tracked group."""
        data = {
            "test_part": {
                "slotType": "test",
                "nodes": [
                    ["id", "posX", "posY", "posZ"],
                    {"group": "first_group"},
                    ["n1", 0, 0, 0, {"isExhaust": "mainEngine"}],
                    {"nodeGroup": "second_group"},
                    ["n2", 1, 1, 1, {"isExhaust": "mainEngine"}],
                ],
            }
        }
        result = extract_isExhaust_nodes(data, "test.jbeam")
        self.assertEqual(len(result["test_part"]), 2)
        self.assertEqual(result["test_part"][0].group, "first_group")
        self.assertEqual(result["test_part"][1].group, "second_group")


# =========================================================================
# Unit Tests — Slot Chain Tracing
# =========================================================================

class TestSlotChainTracing(unittest.TestCase):
    """Test exhaust slot chain discovery."""

    def test_find_exhaust_slots_pattern_a(self):
        data = _mock_engine_with_header_and_exhaust()
        slots = find_exhaust_slots_in_part(data, "test_engine_v8")
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0][0], "test_header")

    def test_find_exhaust_slots_header_has_exhaust(self):
        data = _mock_engine_with_header_and_exhaust()
        slots = find_exhaust_slots_in_part(data, "test_header_v8")
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0][0], "test_exhaust_v8")

    def test_find_exhaust_slots_sibling(self):
        data = _mock_engine_with_sibling_exhaust()
        slots = find_exhaust_slots_in_part(data, "test_engine_i6")
        # Should find both header AND exhaust sibling
        types = [s[0] for s in slots]
        self.assertIn("test_header", types)
        self.assertIn("test_exhaust_i6", types)

    def test_find_all_child_slots(self):
        data = _mock_engine_with_sibling_exhaust()
        all_slots = find_all_child_slots(data, "test_engine_i6")
        self.assertEqual(len(all_slots), 2)
        types = [s[0] for s in all_slots]
        self.assertIn("test_header", types)
        self.assertIn("test_exhaust_i6", types)

    def test_find_part_by_slotType(self):
        data = _mock_engine_with_header_and_exhaust()
        part = _find_part_by_slotType(data, "test_header")
        self.assertEqual(part, "test_header_v8")

    def test_find_part_by_slotType_missing(self):
        data = _mock_engine_with_header_and_exhaust()
        part = _find_part_by_slotType(data, "nonexistent_slot")
        self.assertIsNone(part)

    def test_trace_chain_pattern_a(self):
        """Pattern A: engine → header → exhaust."""
        data = _mock_engine_with_header_and_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_v8", Path("."), "test")
        self.assertTrue(len(chains) >= 1)
        # Should find test_exhaust_v8 through the header
        exhaust_types = [c.exhaust_slot_type for c in chains]
        self.assertIn("test_exhaust_v8", exhaust_types)

    def test_trace_chain_pattern_a_prime(self):
        """Pattern A': engine has sibling exhaust slot."""
        data = _mock_engine_with_sibling_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_i6", Path("."), "test")
        # Should find sibling exhaust AND header (leaf)
        self.assertTrue(len(chains) >= 2)
        has_sibling = any('sibling' in c.chain_path.lower() for c in chains)
        self.assertTrue(has_sibling)

    def test_trace_chain_pattern_b(self):
        """Pattern B: engine → intake → header → exhaust."""
        data = _mock_engine_intake_nested()
        chains = trace_exhaust_chain(data, "test_engine_sohc", Path("."), "test")
        self.assertTrue(len(chains) >= 1)
        exhaust_types = [c.exhaust_slot_type for c in chains]
        self.assertIn("test_exhaust", exhaust_types)
        # Chain should go through intake
        has_intake_path = any('intake' in c.chain_path.lower() for c in chains)
        self.assertTrue(has_intake_path, f"Expected intake in chain path, got: {[c.chain_path for c in chains]}")

    def test_trace_chain_records_node_info(self):
        """Chain tracing should capture downstream component nodes."""
        data = _mock_engine_with_header_and_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_v8", Path("."), "test")
        exhaust_chain = [c for c in chains if c.exhaust_slot_type == "test_exhaust_v8"][0]
        self.assertEqual(len(exhaust_chain.node_names), 2)
        self.assertIn("exm1r", exhaust_chain.node_names)
        self.assertIn("exm1l", exhaust_chain.node_names)

    def test_find_exhaust_slots_slots2_format(self):
        """Test slot discovery in slots2 format."""
        data = _mock_engine_slots2()
        slots = find_exhaust_slots_in_part(data, "test_engine_modern")
        # "test_header" matches EXHAUST_SLOT_PATTERNS via "header"
        types = [s[0] for s in slots]
        self.assertIn("test_header", types)


# =========================================================================
# Unit Tests — Pattern Classification
# =========================================================================

class TestPatternClassification(unittest.TestCase):
    """Test exhaust architecture pattern detection."""

    def test_classify_pattern_a(self):
        data = _mock_engine_with_header_and_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_v8", Path("."), "test")
        pattern = classify_pattern(chains, Path("."), "test", data, "test_engine_v8")
        self.assertEqual(pattern, "A")

    def test_classify_pattern_a_prime(self):
        data = _mock_engine_with_sibling_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_i6", Path("."), "test")
        pattern = classify_pattern(chains, Path("."), "test", data, "test_engine_i6")
        self.assertEqual(pattern, "A'")

    def test_classify_pattern_b(self):
        data = _mock_engine_intake_nested()
        chains = trace_exhaust_chain(data, "test_engine_sohc", Path("."), "test")
        pattern = classify_pattern(chains, Path("."), "test", data, "test_engine_sohc")
        self.assertEqual(pattern, "B")

    def test_classify_pattern_c(self):
        data = _mock_body_frame_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_turbo", Path("."), "test")
        pattern = classify_pattern(chains, Path("."), "test", data, "test_engine_turbo")
        self.assertEqual(pattern, "C")

    def test_classify_no_exhaust(self):
        data = _mock_engine_no_exhaust()
        chains = trace_exhaust_chain(data, "test_engine_electric", Path("."), "test")
        pattern = classify_pattern(chains, Path("."), "test", data, "test_engine_electric")
        self.assertEqual(pattern, "no_exhaust")


# =========================================================================
# Unit Tests — Candidate Classification & Strategy Selection
# =========================================================================

class TestCandidateClassification(unittest.TestCase):
    """Test matching/mismatch classification and strategy selection."""

    def _make_profile(self, name, count, pattern, exhaust_type="test_exhaust"):
        return EngineExhaustProfile(
            engine_file="test.jbeam",
            engine_name=name,
            is_exhaust_count=count,
            is_exhaust_nodes=[],
            exhaust_slots=[ExhaustSlotInfo(
                downstream_component_name="header",
                downstream_component_slotType="test_header",
                exhaust_slot_type=exhaust_type,
                chain_path="test chain",
            )] if pattern != "no_exhaust" else [],
            pattern=pattern,
        )

    def test_classify_matching(self):
        profiles = [
            self._make_profile("engine_v8", 2, "A"),
            self._make_profile("engine_i6", 1, "A'"),
        ]
        matching, mismatch = classify_candidates(profiles, donor_count=2)
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].engine_name, "engine_v8")
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0].engine_name, "engine_i6")

    def test_classify_all_matching(self):
        profiles = [
            self._make_profile("engine_v8_55", 2, "A"),
            self._make_profile("engine_v8_69", 2, "A"),
        ]
        matching, mismatch = classify_candidates(profiles, donor_count=2)
        self.assertEqual(len(matching), 2)
        self.assertEqual(len(mismatch), 0)

    def test_classify_skip_zero_count(self):
        profiles = [
            self._make_profile("engine_electric", 0, "no_exhaust"),
            self._make_profile("engine_v8", 2, "A"),
        ]
        matching, mismatch = classify_candidates(profiles, donor_count=2)
        self.assertEqual(len(matching), 1)

    def test_classify_skip_race_engine(self):
        """Engines with >2 isExhaust should be skipped."""
        profiles = [
            self._make_profile("engine_race", 4, "A"),
            self._make_profile("engine_v8", 2, "A"),
        ]
        matching, mismatch = classify_candidates(profiles, donor_count=2)
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].engine_name, "engine_v8")

    def test_is_primary_engine_part_with_mainEngine(self):
        self.assertTrue(_is_primary_engine_part({"mainEngine": {}}))

    def test_is_primary_engine_part_by_slotType(self):
        self.assertTrue(_is_primary_engine_part({"slotType": "pickup_engine"}))

    def test_is_primary_engine_part_rejects_internals(self):
        self.assertFalse(_is_primary_engine_part({"slotType": "pickup_engine_internals"}))

    def test_is_primary_engine_part_rejects_mounts(self):
        self.assertFalse(_is_primary_engine_part({"slotType": "pickup_enginemounts"}))

    def test_is_primary_engine_part_rejects_mesh(self):
        self.assertFalse(_is_primary_engine_part({"slotType": "pickup_engine_mesh"}))


# =========================================================================
# Integration Tests — Real Vehicle Data
# =========================================================================

@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not available")
class TestIntegrationVehicles(unittest.TestCase):
    """Integration tests against real BeamNG vehicle data."""

    # Expected: (vehicle, min_engines_with_exhaust, expected_patterns, expected_exhaust_slot_substring)
    VEHICLE_EXPECTATIONS = [
        ("pickup", 1, {"A", "A'"}, "exhaust"),
        ("moonhawk", 1, {"A'"}, "exhaust"),
        ("covet", 1, {"B", "A'"}, "exhaust"),
        ("fullsize", 1, {"C"}, "exhaust"),
        ("vivace", 1, {"C"}, "exhaust"),
        ("barstow", 1, {"A'"}, "exhaust"),
    ]

    def test_vehicle_profiles(self):
        """Each vehicle should produce at least one engine profile with exhaust."""
        for vehicle, min_engines, expected_patterns, exhaust_substr in self.VEHICLE_EXPECTATIONS:
            with self.subTest(vehicle=vehicle):
                profiles = profile_vehicle_exhausts(STEAM_BASE, vehicle)

                # Filter to profiles that have a real exhaust chain
                with_exhaust = [
                    p for p in profiles
                    if p.pattern != "no_exhaust"
                ]

                self.assertGreaterEqual(
                    len(with_exhaust), min_engines,
                    f"{vehicle}: expected ≥{min_engines} engines with exhaust, "
                    f"got {len(with_exhaust)}"
                )

                # Check that at least one profile matches an expected pattern
                found_patterns = {p.pattern for p in with_exhaust}
                self.assertTrue(
                    found_patterns & expected_patterns,
                    f"{vehicle}: expected one of {expected_patterns}, "
                    f"got {found_patterns}"
                )

    def test_vehicle_has_exhaust_slot(self):
        """Each vehicle should have a discoverable exhaust slotType."""
        for vehicle, _, _, exhaust_substr in self.VEHICLE_EXPECTATIONS:
            with self.subTest(vehicle=vehicle):
                profiles = profile_vehicle_exhausts(STEAM_BASE, vehicle)
                with_exhaust = [p for p in profiles if p.pattern != "no_exhaust"]

                # At least one profile should have a real exhaust slot
                all_slots = []
                for p in with_exhaust:
                    for s in p.exhaust_slots:
                        if s.exhaust_slot_type != "(none found)":
                            all_slots.append(s.exhaust_slot_type)

                # If pattern is C, also check body/frame
                if not all_slots:
                    body_exhaust = find_body_frame_exhaust_slots(STEAM_BASE, vehicle)
                    all_slots = [s[2] for s in body_exhaust]

                self.assertTrue(
                    any(exhaust_substr in s.lower() for s in all_slots),
                    f"{vehicle}: no exhaust slot found containing '{exhaust_substr}', "
                    f"got: {all_slots}"
                )

    def test_pickup_isexhaust_count(self):
        """Pickup gasoline V8 engines should have 2 isExhaust nodes."""
        profiles = profile_vehicle_exhausts(STEAM_BASE, "pickup")
        v8_profiles = [
            p for p in profiles
            if 'v8' in p.engine_name.lower()
            and 'diesel' not in p.engine_name.lower()
            and p.is_exhaust_count > 0
        ]
        self.assertTrue(len(v8_profiles) > 0, "No gasoline V8 profiles found for pickup")
        for p in v8_profiles:
            self.assertEqual(p.is_exhaust_count, 2,
                             f"{p.engine_name}: expected 2 isExhaust, got {p.is_exhaust_count}")

    def test_moonhawk_isexhaust_count(self):
        """Moonhawk engines should have 1 isExhaust node."""
        profiles = profile_vehicle_exhausts(STEAM_BASE, "moonhawk")
        with_exhaust = [p for p in profiles if p.is_exhaust_count > 0]
        self.assertTrue(len(with_exhaust) > 0)
        for p in with_exhaust:
            self.assertEqual(p.is_exhaust_count, 1,
                             f"{p.engine_name}: expected 1 isExhaust, got {p.is_exhaust_count}")

    def test_strategy_selection_pickup_donor_2(self):
        """Pickup with donor count=2 should select 'matching' strategy."""
        result = select_strategy(STEAM_BASE, "pickup", donor_isExhaust_count=2)
        self.assertEqual(result.strategy, "matching")
        self.assertEqual(result.donor_isExhaust_count, 2)
        self.assertEqual(result.target_isExhaust_count, 2)
        self.assertIsNotNone(result.target_exhaust_slot_type)

    def test_strategy_selection_moonhawk_donor_2(self):
        """Moonhawk with donor count=2 should select 'mismatch' strategy."""
        result = select_strategy(STEAM_BASE, "moonhawk", donor_isExhaust_count=2)
        self.assertEqual(result.strategy, "mismatch")
        self.assertEqual(result.target_isExhaust_count, 1)

    def test_strategy_selection_moonhawk_donor_1(self):
        """Moonhawk with donor count=1 should select 'matching' strategy."""
        result = select_strategy(STEAM_BASE, "moonhawk", donor_isExhaust_count=1)
        self.assertEqual(result.strategy, "matching")

    def test_cross_file_resolution_pickup(self):
        """Pickup should resolve header parts across files."""
        engine_files = find_engine_files(STEAM_BASE, "pickup")
        exhaust_files = find_exhaust_files(STEAM_BASE, "pickup")
        merged = build_merged_vehicle_data(STEAM_BASE, "pickup", engine_files, exhaust_files)

        # pickup_header_v8 should be in merged data (from a different file)
        header_parts = [
            name for name in merged
            if 'header' in name.lower() and 'v8' in name.lower()
        ]
        self.assertTrue(
            len(header_parts) > 0,
            f"Expected pickup header parts in merged data, got parts: "
            f"{[n for n in merged if 'header' in n.lower()]}"
        )

    def test_slots2_vivace(self):
        """Vivace uses slots2 format — verify we can find body exhaust."""
        body_exhaust = find_body_frame_exhaust_slots(STEAM_BASE, "vivace")
        self.assertTrue(
            len(body_exhaust) > 0,
            "Expected to find exhaust slots in vivace body (slots2 format)"
        )
        exhaust_types = [s[2] for s in body_exhaust]
        self.assertTrue(
            any('exhaust' in t.lower() for t in exhaust_types),
            f"Expected exhaust in body slots, got: {exhaust_types}"
        )


# =========================================================================
# Integration Tests — Adapted Donor Engine
# =========================================================================

@unittest.skipUnless(MOD_BASE.exists(), "Mod output directory not available")
class TestDonorCounting(unittest.TestCase):
    """Test counting isExhaust nodes in adapted Camso engine output."""

    def test_adapted_pickup_engine(self):
        """Adapted pickup engines should have isExhaust nodes."""
        adapted_dir = MOD_BASE / 'pickup'
        if not adapted_dir.exists():
            self.skipTest("No adapted pickup engines available")

        adapted_files = list(adapted_dir.glob("*camso*adapted*.jbeam"))
        if not adapted_files:
            self.skipTest("No adapted engine files found")

        for f in adapted_files:
            count, nodes = count_donor_isExhaust_nodes(f)
            if count > 0:
                self.assertIn(count, (1, 2),
                              f"{f.name}: expected 1 or 2 isExhaust, got {count}")
                return

        self.fail("No adapted engine file had isExhaust nodes")


# =========================================================================
# Unit Tests — File Discovery
# =========================================================================

@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not available")
class TestFileDiscovery(unittest.TestCase):
    """Test engine/exhaust file discovery."""

    def test_find_pickup_engines(self):
        files = find_engine_files(STEAM_BASE, "pickup")
        self.assertTrue(len(files) > 0, "No engine files found for pickup")
        # Should NOT include enginemounts files
        for f in files:
            self.assertNotIn('enginemounts', f.stem.lower())

    def test_find_pickup_exhaust(self):
        files = find_exhaust_files(STEAM_BASE, "pickup")
        self.assertTrue(len(files) > 0, "No exhaust files found for pickup")

    def test_find_vivace_body_frame(self):
        files = find_body_frame_files(STEAM_BASE, "vivace")
        self.assertTrue(len(files) > 0, "No body/frame files found for vivace")

    def test_find_engines_common_folder(self):
        """Pickup engines are in common folder — verify discovery."""
        files = find_engine_files(STEAM_BASE, "pickup")
        common_files = [f for f in files if 'common' in str(f)]
        self.assertTrue(
            len(common_files) > 0,
            f"Expected pickup engines in common folder, got: {[f.name for f in files]}"
        )


# =========================================================================
# Phase 2 — Unit Tests: Node Extraction (Full)
# =========================================================================

class TestExtractPartNodesFull(unittest.TestCase):
    """Test _extract_part_nodes_full with inline property preservation."""

    def test_basic_extraction(self):
        data = _mock_engine_with_header_and_exhaust()
        nodes = _extract_part_nodes_full(data, "test_header_v8")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]['name'], 'exm1r')
        self.assertAlmostEqual(nodes[0]['x'], 0.3)
        self.assertAlmostEqual(nodes[0]['y'], -0.8)
        self.assertAlmostEqual(nodes[0]['z'], 0.1)

    def test_preserves_audio_props(self):
        data = {
            "test_header": {
                "nodes": [
                    ["id", "posX", "posY", "posZ"],
                    ["exm1r", 0.3, -0.8, 0.1, {
                        "afterFireAudioCoef": 1.0,
                        "exhaustAudioMufflingCoef": 1.0,
                        "exhaustAudioGainChange": 0,
                    }],
                ],
            },
        }
        nodes = _extract_part_nodes_full(data, "test_header")
        self.assertEqual(len(nodes), 1)
        self.assertIn('afterFireAudioCoef', nodes[0]['props'])
        self.assertEqual(nodes[0]['props']['afterFireAudioCoef'], 1.0)

    def test_empty_part(self):
        nodes = _extract_part_nodes_full({}, "nonexistent")
        self.assertEqual(len(nodes), 0)

    def test_nodes_without_props(self):
        data = _mock_engine_with_header_and_exhaust()
        nodes = _extract_part_nodes_full(data, "test_header_v8")
        for n in nodes:
            self.assertIn('props', n)
            # These mock nodes have no inline props
            self.assertEqual(n['props'], {})


# =========================================================================
# Phase 2 — Unit Tests: Beam Property Extraction
# =========================================================================

class TestBeamPropertyExtraction(unittest.TestCase):
    """Test _extract_beam_properties_from_part."""

    def test_extraction_from_beams(self):
        data = {
            "test_header": {
                "beams": [
                    ["id1:", "id2:"],
                    {"beamSpring": 11163370, "beamDamp": 130.43,
                     "beamDeform": 90000, "beamStrength": "FLT_MAX"},
                    ["exm1r", "e2r", {"isExhaust": "mainEngine"}],
                ],
            },
        }
        props = _extract_beam_properties_from_part(data, "test_header")
        # beamSpring should be clamped to _MAX_BEAM_SPRING
        self.assertEqual(props['beamSpring'], _MAX_BEAM_SPRING)
        self.assertAlmostEqual(props['beamDamp'], 130.43)
        self.assertEqual(props['beamDeform'], 90000)
        self.assertEqual(props['beamStrength'], "FLT_MAX")

    def test_defaults_when_no_beams(self):
        data = {"test_header": {"nodes": [["id", "posX", "posY", "posZ"]]}}
        props = _extract_beam_properties_from_part(data, "test_header")
        self.assertEqual(props, _DEFAULT_BEAM_PROPS)

    def test_defaults_when_part_missing(self):
        props = _extract_beam_properties_from_part({}, "nonexistent")
        self.assertEqual(props, _DEFAULT_BEAM_PROPS)

    def test_partial_beam_props(self):
        """Only some beam properties specified — others use defaults."""
        data = {
            "test_header": {
                "beams": [
                    ["id1:", "id2:"],
                    {"beamSpring": 1000000},
                ],
            },
        }
        props = _extract_beam_properties_from_part(data, "test_header")
        self.assertEqual(props['beamSpring'], 1000000)  # Below cap, kept as-is
        # Others should be defaults
        self.assertEqual(props['beamDamp'], _DEFAULT_BEAM_PROPS['beamDamp'])

    def test_beamspring_clamped_when_excessive(self):
        """beamSpring values above _MAX_BEAM_SPRING are clamped."""
        data = {
            "test_header": {
                "beams": [
                    ["id1:", "id2:"],
                    {"beamSpring": 50000000, "beamDamp": 200},
                ],
            },
        }
        props = _extract_beam_properties_from_part(data, "test_header")
        self.assertEqual(props['beamSpring'], _MAX_BEAM_SPRING)
        # beamDamp should not be affected
        self.assertEqual(props['beamDamp'], 200)


# =========================================================================
# Phase 2 — Unit Tests: Adapted Node Generation
# =========================================================================

class TestGenerateAdaptedNodes(unittest.TestCase):
    """Test generate_adapted_nodes."""

    def test_basic_generation(self):
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
            {'name': 'exm1l', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        rows = generate_adapted_nodes(downstream)
        # First row: header
        self.assertEqual(rows[0], ["id", "posX", "posY", "posZ"])
        # Rows 1-6: separate property modifier rows (BeamNG convention)
        modifiers = [r for r in rows[1:] if isinstance(r, dict) and 'group' not in r or (isinstance(r, dict) and r.get('group') != 'none')]
        modifier_keys = set()
        for m in rows[1:]:
            if isinstance(m, dict):
                modifier_keys.update(m.keys())
        self.assertIn('selfCollision', modifier_keys)
        self.assertIn('collision', modifier_keys)
        self.assertIn('nodeWeight', modifier_keys)
        self.assertIn('group', modifier_keys)
        # Find the nodeWeight modifier — should be 4.5 (>=3 required for stability)
        for m in rows[1:]:
            if isinstance(m, dict) and 'nodeWeight' in m:
                self.assertEqual(m['nodeWeight'], 4.5)
        # Find the collision modifier — should be False
        for m in rows[1:]:
            if isinstance(m, dict) and 'collision' in m:
                self.assertFalse(m['collision'])
        # Find the group modifier — should set exhaust_adapter
        for m in rows[1:]:
            if isinstance(m, dict) and m.get('group') == 'exhaust_adapter':
                break
        else:
            self.fail("No group modifier with 'exhaust_adapter' found")
        # Node rows follow modifiers
        node_rows = [r for r in rows if isinstance(r, list) and len(r) >= 4 and r[0] not in ('id',)]
        self.assertEqual(node_rows[0][0], 'exm1r')
        self.assertEqual(node_rows[1][0], 'exm1l')
        # Trailing group:none reset
        self.assertEqual(rows[-1], {'group': 'none'})

    def test_preserves_audio_inline(self):
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {
                'afterFireAudioCoef': 1.0,
                'exhaustAudioMufflingCoef': 1.0,
            }},
        ]
        rows = generate_adapted_nodes(downstream)
        # Find the node row (list with 5 elements: name, x, y, z, props)
        node_rows = [r for r in rows if isinstance(r, list) and len(r) >= 4 and r[0] not in ('id',)]
        self.assertEqual(len(node_rows), 1)
        node_row = node_rows[0]
        self.assertEqual(len(node_row), 5)  # name, x, y, z, props
        self.assertEqual(node_row[4]['afterFireAudioCoef'], 1.0)

    def test_empty_input(self):
        rows = generate_adapted_nodes([])
        self.assertEqual(len(rows), 1)  # Just the header


# =========================================================================
# Phase 2 — Unit Tests: Structural Beam Generation
# =========================================================================

class TestGenerateStructuralBeams(unittest.TestCase):
    """Test generate_structural_beams."""

    def test_basic_dual_node(self):
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
            {'name': 'exm1l', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        # 2 isExhaust nodes — 6 non-isExhaust engine nodes left
        engine_nodes = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
        ]
        beam_props = {'beamSpring': 1616333, 'beamDamp': 130.43,
                      'beamDeform': 90000, 'beamStrength': 'FLT_MAX'}

        rows = generate_structural_beams(downstream, engine_nodes, beam_props)
        # Header
        self.assertEqual(rows[0], ["id1:", "id2:"])
        # Modifier rows — separate per BeamNG convention
        modifier_rows = [r for r in rows if isinstance(r, dict)]
        modifier_keys = set()
        for m in modifier_rows:
            modifier_keys.update(m.keys())
        self.assertIn('deformLimitExpansion', modifier_keys)
        self.assertIn('beamSpring', modifier_keys)
        self.assertIn('beamDamp', modifier_keys)
        self.assertIn('beamDeform', modifier_keys)
        self.assertIn('beamStrength', modifier_keys)
        self.assertIn('beamPrecompression', modifier_keys)
        # Verify beamSpring value
        for m in modifier_rows:
            if 'beamSpring' in m:
                self.assertEqual(m['beamSpring'], 1616333)
        # 2 downstream × 6 structural targets = 12 beams
        beam_entries = [r for r in rows if isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) and r[0] != 'id1:']
        self.assertEqual(len(beam_entries), 12)
        # Verify no beams reference isExhaust nodes
        for beam in beam_entries:
            self.assertNotIn(beam[1], ['e2r', 'e2l'])

    def test_single_node(self):
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        engine_nodes = [
            IsExhaustNode('e3r', 0.2, -1.0, 0.4, 'engine_block', 't', 'f'),
        ]
        beam_props = dict(_DEFAULT_BEAM_PROPS)

        rows = generate_structural_beams(downstream, engine_nodes, beam_props)
        beam_entries = [r for r in rows[2:] if isinstance(r, list)]
        # 1 downstream × 7 structural targets = 7 beams
        self.assertEqual(len(beam_entries), 7)
        # e3r is isExhaust — should not appear as target
        for beam in beam_entries:
            self.assertNotEqual(beam[1], 'e3r')


# =========================================================================
# Phase 2 — Unit Tests: isExhaust Beam Wiring
# =========================================================================

class TestMatchingIsExhaustBeams(unittest.TestCase):
    """Test generate_matching_isExhaust_beams."""

    def test_single_1_to_1(self):
        donor = [IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 't', 'f')]
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.9, 'z': 0.1, 'props': {}},
        ]
        beams = generate_matching_isExhaust_beams(donor, downstream)
        self.assertEqual(len(beams), 1)
        self.assertEqual(beams[0][0], 'e4r')
        self.assertEqual(beams[0][1], 'exm1r')
        self.assertEqual(beams[0][2], {"isExhaust": "mainEngine"})

    def test_dual_2_to_2_distance_pairing(self):
        # Donor nodes: e2r is at +X, e2l is at -X
        donor = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
        ]
        # Downstream nodes: exm1r at +X, exm1l at -X
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
            {'name': 'exm1l', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        beams = generate_matching_isExhaust_beams(donor, downstream)
        self.assertEqual(len(beams), 2)
        # Distance pairing should match e2r→exm1r and e2l→exm1l
        nodes_paired = {(b[0], b[1]) for b in beams}
        self.assertIn(('e2r', 'exm1r'), nodes_paired)
        self.assertIn(('e2l', 'exm1l'), nodes_paired)
        # Each beam has isExhaust
        for beam in beams:
            self.assertEqual(beam[2], {"isExhaust": "mainEngine"})

    def test_dual_2_to_2_cross_pairing(self):
        """When closest nodes are cross-paired (R↔L), verify correct matching."""
        # Deliberately swap downstream node positions
        donor = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
        ]
        downstream = [
            {'name': 'exm1r', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},  # at -X!
            {'name': 'exm1l', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},   # at +X!
        ]
        beams = generate_matching_isExhaust_beams(donor, downstream)
        self.assertEqual(len(beams), 2)
        # Distance pairing should cross: e2r→exm1l (+X nearer +X), e2l→exm1r (-X nearer -X)
        nodes_paired = {(b[0], b[1]) for b in beams}
        self.assertIn(('e2r', 'exm1l'), nodes_paired)
        self.assertIn(('e2l', 'exm1r'), nodes_paired)

    def test_no_duplicate_connections(self):
        """Each node consumed exactly once (2↔2)."""
        donor = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
        ]
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
            {'name': 'exm1l', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        beams = generate_matching_isExhaust_beams(donor, downstream)
        donor_used = [b[0] for b in beams]
        ds_used = [b[1] for b in beams]
        self.assertEqual(len(set(donor_used)), 2, "Donor nodes not unique")
        self.assertEqual(len(set(ds_used)), 2, "Downstream nodes not unique")

    def test_empty_inputs(self):
        beams = generate_matching_isExhaust_beams([], [])
        self.assertEqual(len(beams), 0)


class TestMismatchIsExhaustBeams(unittest.TestCase):
    """Test generate_mismatch_isExhaust_beams (Y-pipe)."""

    def test_1_to_2_splitter(self):
        donor = [IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 't', 'f')]
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
            {'name': 'exm1l', 'x': -0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        beams = generate_mismatch_isExhaust_beams(donor, downstream)
        # 1 donor × 2 downstream = 2 beams
        self.assertEqual(len(beams), 2)
        for beam in beams:
            self.assertEqual(beam[0], 'e4r')
            self.assertEqual(beam[2], {"isExhaust": "mainEngine"})

    def test_2_to_1_collector(self):
        donor = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 't', 'f'),
        ]
        downstream = [
            {'name': 'exm1r', 'x': 0.3, 'y': -0.8, 'z': 0.1, 'props': {}},
        ]
        beams = generate_mismatch_isExhaust_beams(donor, downstream)
        # 2 donor × 1 downstream = 2 beams
        self.assertEqual(len(beams), 2)
        targets = [b[1] for b in beams]
        self.assertTrue(all(t == 'exm1r' for t in targets))

    def test_empty_inputs(self):
        beams = generate_mismatch_isExhaust_beams([], [])
        self.assertEqual(len(beams), 0)


# =========================================================================
# Phase 2 — Unit Tests: Slot Entry Generation
# =========================================================================

class TestSlotEntryGeneration(unittest.TestCase):
    """Test generate_slot_entry."""

    def test_basic_generation(self):
        entry = generate_slot_entry("pickup", "pickup_exhaust_v8")
        self.assertEqual(entry[0], "pickup_exhaust_adapter")
        self.assertEqual(entry[1], "pickup_exhaust_adapter")
        self.assertEqual(entry[2], "Exhaust Adapter")
        self.assertEqual(entry[3], {"coreSlot": True})


# =========================================================================
# Phase 2 — Unit Tests: Full Component Generation (Mock Data)
# =========================================================================

class TestGenerateAdaptedExhaustComponent(unittest.TestCase):
    """Test generate_adapted_exhaust_component with mock data."""

    def _make_profile_A(self):
        """Create a Pattern A profile with header that hosts exhaust slot."""
        return EngineExhaustProfile(
            engine_file="test_engine.jbeam",
            engine_name="test_engine_v8",
            is_exhaust_count=2,
            is_exhaust_nodes=[
                IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 'test_engine_v8', 'f'),
                IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 'test_engine_v8', 'f'),
            ],
            exhaust_slots=[
                ExhaustSlotInfo(
                    downstream_component_name="test_header_v8",
                    downstream_component_slotType="test_header",
                    exhaust_slot_type="test_exhaust_v8",
                    chain_path="test_engine_v8 → test_header[test_header_v8] → test_exhaust_v8",
                    node_names=["exm1r", "exm1l"],
                    node_positions=[(0.3, -0.8, 0.1), (-0.3, -0.8, 0.1)],
                )
            ],
            pattern="A",
        )

    def _make_merged_data_A(self):
        """Pattern A merged data with header beams."""
        data = _mock_engine_with_header_and_exhaust()
        # Add beams to header for beam property extraction
        data["test_header_v8"]["beams"] = [
            ["id1:", "id2:"],
            {"beamSpring": 11163370, "beamDamp": 130.43,
             "beamDeform": 90000, "beamStrength": "FLT_MAX"},
            ["exm1r", "e2r", {"isExhaust": "mainEngine"}],
            ["exm1l", "e2l", {"isExhaust": "mainEngine"}],
        ]
        return data

    def test_matching_strategy_dual(self):
        """Matching strategy with 2 donor / 2 target isExhaust nodes."""
        donor_nodes = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 'donor', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 'donor', 'f'),
        ]
        profile = self._make_profile_A()
        merged = self._make_merged_data_A()

        part, slot_entry, warnings = generate_adapted_exhaust_component(
            "test", "matching", donor_nodes, profile, merged,
        )
        self.assertIsNotNone(part)
        self.assertIn("test_exhaust_adapter", part)

        # Check part structure
        part_data = part["test_exhaust_adapter"]
        self.assertEqual(part_data['slotType'], 'test_exhaust_adapter')
        self.assertIn('nodes', part_data)
        self.assertIn('beams', part_data)
        self.assertIn('slots', part_data)

        # Check child exhaust slot
        child_slots = part_data['slots']
        exhaust_entry = [s for s in child_slots if isinstance(s, list) and 'exhaust' in str(s[0]).lower()]
        self.assertTrue(len(exhaust_entry) > 0)
        self.assertEqual(exhaust_entry[0][0], 'test_exhaust_v8')

        # Slot entry for engine injection
        self.assertIsNotNone(slot_entry)
        self.assertEqual(slot_entry[0], "test_exhaust_adapter")
        self.assertTrue(slot_entry[3].get('coreSlot'))

    def test_matching_strategy_single(self):
        """Matching strategy with 1 donor / 1 target isExhaust node."""
        donor_nodes = [
            IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 'donor', 'f'),
        ]
        profile = EngineExhaustProfile(
            engine_file="test_engine.jbeam",
            engine_name="test_engine_i6",
            is_exhaust_count=1,
            is_exhaust_nodes=[
                IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 'test', 'f'),
            ],
            exhaust_slots=[
                ExhaustSlotInfo(
                    downstream_component_name="test_header_i6",
                    downstream_component_slotType="test_header",
                    exhaust_slot_type="test_exhaust_i6",
                    chain_path="test_engine_i6 → test_header[test_header_i6] → test_exhaust_i6",
                    node_names=["exm1r"],
                    node_positions=[(0.3, -0.9, 0.1)],
                )
            ],
            pattern="A",
        )
        merged = _mock_engine_with_sibling_exhaust()
        merged["test_header_i6"]["beams"] = [
            ["id1:", "id2:"],
            {"beamSpring": 5010000, "beamDamp": 90, "beamDeform": 90000, "beamStrength": "FLT_MAX"},
            ["exm1r", "e4r", {"isExhaust": "mainEngine"}],
        ]

        part, slot_entry, warnings = generate_adapted_exhaust_component(
            "test", "matching", donor_nodes, profile, merged,
        )
        self.assertIsNotNone(part)
        part_data = part["test_exhaust_adapter"]

        # Should have 1 isExhaust beam
        all_beams = [b for b in part_data['beams'] if isinstance(b, list) and len(b) == 3
                     and isinstance(b[2], dict) and 'isExhaust' in b[2]]
        self.assertEqual(len(all_beams), 1)

    def test_mismatch_strategy_1_to_2(self):
        """Mismatch strategy: 1 donor → 2 target (reverse Y-pipe)."""
        donor_nodes = [
            IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 'donor', 'f'),
        ]
        profile = self._make_profile_A()
        merged = self._make_merged_data_A()

        part, slot_entry, warnings = generate_adapted_exhaust_component(
            "test", "mismatch", donor_nodes, profile, merged,
        )
        self.assertIsNotNone(part)
        part_data = part["test_exhaust_adapter"]

        # Should have 2 isExhaust beams (1 donor × 2 downstream)
        all_beams = [b for b in part_data['beams'] if isinstance(b, list) and len(b) == 3
                     and isinstance(b[2], dict) and 'isExhaust' in b[2]]
        self.assertEqual(len(all_beams), 2)

    def test_no_downstream_nodes_returns_none(self):
        """If downstream component has no nodes, returns None."""
        profile = EngineExhaustProfile(
            engine_file="test.jbeam",
            engine_name="test_engine",
            is_exhaust_count=1,
            is_exhaust_nodes=[],
            exhaust_slots=[
                ExhaustSlotInfo(
                    downstream_component_name="nonexistent_header",
                    downstream_component_slotType="test_header",
                    exhaust_slot_type="test_exhaust",
                    chain_path="...",
                    node_names=[],
                    node_positions=[],
                )
            ],
            pattern="A",
        )
        donor = [IsExhaustNode('e4r', 0.2, -1.0, 0.5, 'engine_block', 'd', 'f')]
        part, slot, warnings = generate_adapted_exhaust_component(
            "test", "matching", donor, profile, {},
        )
        self.assertIsNone(part)
        self.assertIsNone(slot)
        self.assertTrue(len(warnings) > 0)

    def test_beam_props_borrowed_from_header(self):
        """Structural beams use beam properties from the downstream component."""
        donor_nodes = [
            IsExhaustNode('e2r', 0.2, -1.0, 0.3, 'engine_block', 'donor', 'f'),
            IsExhaustNode('e2l', -0.2, -1.0, 0.3, 'engine_block', 'donor', 'f'),
        ]
        profile = self._make_profile_A()
        merged = self._make_merged_data_A()

        part, _, _ = generate_adapted_exhaust_component(
            "test", "matching", donor_nodes, profile, merged,
        )
        self.assertIsNotNone(part)
        part_data = part["test_exhaust_adapter"]

        # Find the beam modifier row
        modifier = None
        for item in part_data['beams']:
            if isinstance(item, dict) and 'beamSpring' in item:
                modifier = item
                break
        self.assertIsNotNone(modifier, "No beam modifier found")
        # beamSpring from header (11163370) exceeds cap — should be clamped
        self.assertEqual(modifier['beamSpring'], _MAX_BEAM_SPRING)
        self.assertAlmostEqual(modifier['beamDamp'], 130.43)


# =========================================================================
# Phase 2 — Unit Tests: Euclidean Distance
# =========================================================================

class TestEuclideanDistance(unittest.TestCase):
    """Test _euclidean_distance helper."""

    def test_same_point(self):
        self.assertAlmostEqual(_euclidean_distance((0, 0, 0), (0, 0, 0)), 0.0)

    def test_unit_distance(self):
        self.assertAlmostEqual(_euclidean_distance((0, 0, 0), (1, 0, 0)), 1.0)

    def test_3d_distance(self):
        self.assertAlmostEqual(_euclidean_distance((1, 2, 3), (4, 6, 3)), 5.0)


# =========================================================================
# Phase 2 — Unit Tests: Best Exhaust Slot Info Selection
# =========================================================================

class TestGetBestExhaustSlotInfo(unittest.TestCase):
    """Test _get_best_exhaust_slot_info."""

    def test_prefers_chain_with_nodes(self):
        chains = [
            ExhaustSlotInfo("(engine sibling)", "test_exhaust", "test_exhaust",
                            "sibling", node_names=[], node_positions=[]),
            ExhaustSlotInfo("test_header", "test_header", "test_exhaust",
                            "chain", node_names=["exm1r"], node_positions=[(0,0,0)]),
        ]
        profile = EngineExhaustProfile("f", "e", 1, [], chains, "A'")
        best = _get_best_exhaust_slot_info(profile)
        self.assertEqual(best.downstream_component_name, "test_header")

    def test_returns_sibling_if_only_option(self):
        chains = [
            ExhaustSlotInfo("(engine sibling)", "test_exhaust", "test_exhaust",
                            "sibling", node_names=[], node_positions=[]),
        ]
        profile = EngineExhaustProfile("f", "e", 1, [], chains, "A'")
        best = _get_best_exhaust_slot_info(profile)
        self.assertIsNotNone(best)
        self.assertEqual(best.exhaust_slot_type, "test_exhaust")

    def test_returns_none_if_none_found(self):
        chains = [
            ExhaustSlotInfo("test_header", "test_header", "(none found)",
                            "...", node_names=["exm1r"], node_positions=[(0,0,0)]),
        ]
        profile = EngineExhaustProfile("f", "e", 1, [], chains, "A")
        best = _get_best_exhaust_slot_info(profile)
        self.assertIsNone(best)


# =========================================================================
# Phase 2 — Integration: Strategy + Component Generation (Real Data)
# =========================================================================

@unittest.skipUnless(STEAM_BASE.exists(), "SteamLibrary_content_vehicles not available")
class TestIntegrationPhase2(unittest.TestCase):
    """Integration tests: select_strategy with donor nodes → full component."""

    def _make_donor_nodes(self, count, names=None):
        """Create mock donor isExhaust nodes with plausible positions."""
        if names is None:
            names = ['e2r', 'e2l', 'e4r'][:count]
        positions = [(0.2, -1.0, 0.3), (-0.2, -1.0, 0.3), (0.2, -1.2, 0.5)]
        return [
            IsExhaustNode(names[i], positions[i % len(positions)][0],
                          positions[i % len(positions)][1],
                          positions[i % len(positions)][2],
                          'engine_block', 'donor', 'donor.jbeam')
            for i in range(count)
        ]

    def test_pickup_matching_2_generates_component(self):
        """Pickup with 2 donor isExhaust → matching strategy → component generated."""
        donor_nodes = self._make_donor_nodes(2)
        result = select_strategy(STEAM_BASE, "pickup", 2, donor_nodes)
        self.assertEqual(result.strategy, "matching")
        self.assertIsNotNone(result.adapted_part, "adapted_part should be generated")
        self.assertIn("pickup_exhaust_adapter", result.adapted_part)
        self.assertIsNotNone(result.exhaust_slot_entry)
        self.assertEqual(result.exhaust_slot_entry[0], "pickup_exhaust_adapter")

        # Verify the part has nodes and beams
        part = result.adapted_part["pickup_exhaust_adapter"]
        self.assertIn('nodes', part)
        self.assertIn('beams', part)
        self.assertIn('slots', part)

    def test_pickup_mismatch_3_generates_component(self):
        """Pickup with 3 donor isExhaust → mismatch (no engine matches 3).
        Best candidate is I6 (1 target, Pattern A), so 3×1 = 3 isExhaust beams."""
        donor_nodes = self._make_donor_nodes(3, names=['e2r', 'e2l', 'e4r'])
        result = select_strategy(STEAM_BASE, "pickup", 3, donor_nodes)
        self.assertEqual(result.strategy, "mismatch")
        self.assertIsNotNone(result.adapted_part)
        part = result.adapted_part["pickup_exhaust_adapter"]

        # Mismatch Y-pipe: 3 donor × 1 downstream (I6 header) = 3 isExhaust beams
        is_exhaust_beams = [
            b for b in part['beams']
            if isinstance(b, list) and len(b) == 3
            and isinstance(b[2], dict) and 'isExhaust' in b[2]
        ]
        self.assertEqual(len(is_exhaust_beams), 3)

    def test_moonhawk_matching_1_generates_component(self):
        """Moonhawk with 1 donor → matching strategy → component."""
        donor_nodes = self._make_donor_nodes(1, names=['e4r'])
        result = select_strategy(STEAM_BASE, "moonhawk", 1, donor_nodes)
        self.assertIn(result.strategy, ("matching", "mismatch"))
        self.assertIsNotNone(result.adapted_part)

    def test_covet_aprime_no_header_returns_none(self):
        """Covet 1.5_R is A' with sibling-only chain — no header nodes to bridge.
        Component generation correctly returns None with a warning."""
        donor_nodes = self._make_donor_nodes(1, names=['e3r'])
        result = select_strategy(STEAM_BASE, "covet", 1, donor_nodes)
        self.assertIn(result.strategy, ("matching", "mismatch"))
        # A'-only with no header nodes → adapted_part is None
        self.assertIsNone(result.adapted_part)

    def test_barstow_matching_1_generates_component(self):
        """Barstow with 1 donor → matching → component."""
        donor_nodes = self._make_donor_nodes(1, names=['e4r'])
        result = select_strategy(STEAM_BASE, "barstow", 1, donor_nodes)
        self.assertIn(result.strategy, ("matching", "mismatch"))
        self.assertIsNotNone(result.adapted_part)

    def test_no_donor_nodes_means_no_component(self):
        """Without donor_isExhaust_nodes, no component is generated (Phase 1 behavior)."""
        result = select_strategy(STEAM_BASE, "pickup", 2)
        self.assertEqual(result.strategy, "matching")
        self.assertIsNone(result.adapted_part)
        self.assertIsNone(result.exhaust_slot_entry)

    def test_child_exhaust_slot_matches_target(self):
        """The adapted component's child exhaust slot matches the target vehicle's exhaust slotType."""
        donor_nodes = self._make_donor_nodes(2)
        result = select_strategy(STEAM_BASE, "pickup", 2, donor_nodes)
        self.assertIsNotNone(result.adapted_part)
        part = result.adapted_part["pickup_exhaust_adapter"]
        # Find the exhaust child slot in the part's slots
        exhaust_child = None
        for s in part.get('slots', []):
            if isinstance(s, list) and 'exhaust' in str(s[0]).lower():
                exhaust_child = s
                break
        self.assertIsNotNone(exhaust_child, "No child exhaust slot in adapted part")
        # Should match the result's target_exhaust_slot_type
        self.assertEqual(exhaust_child[0], result.target_exhaust_slot_type)


# =========================================================================
# Run
# =========================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
