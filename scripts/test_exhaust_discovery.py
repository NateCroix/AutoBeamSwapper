#!/usr/bin/env python3
"""
Phase 0 — Exhaust Solver Exploration & Data Validation

Validates architecture assumptions from docs/exhaust_solver.md against real
BeamNG and Camso data:
  1. Enumerates target engine files for multiple vehicles
  2. Parses each engine, counts isExhaust nodes per engine_block group
  3. Traces downstream exhaust slot chains (find_some_exhaust_slot logic)
  4. Validates Camso adapted engine output preserves isExhaust
  5. Reports findings per vehicle with expected vs. actual comparison

Run from scripts/ directory:
    python test_exhaust_discovery.py
"""

import sys
import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from dataclasses import dataclass, field

# --- Setup path and imports ---
sys.path.insert(0, str(Path(__file__).parent))
from engineswap import JBeamParser

try:
    from analyze_powertrains import get_search_folders
except ImportError:
    get_search_folders = None

logger = logging.getLogger(__name__)

# =====================================================================
# Data structures
# =====================================================================

@dataclass
class IsExhaustNode:
    """An engine node with isExhaust property."""
    name: str
    x: float
    y: float
    z: float
    group: str  # active nodeGroup at this node's position
    source_part: str
    source_file: str

@dataclass
class ExhaustSlotInfo:
    """Result of tracing an exhaust slot chain."""
    downstream_component_name: str       # e.g. "pickup_header_v8"
    downstream_component_slotType: str   # e.g. "pickup_header_v8"
    exhaust_slot_type: str               # e.g. "pickup_exhaust_v8"
    chain_path: str                      # human-readable chain
    node_names: List[str] = field(default_factory=list)
    node_positions: List[Tuple[float, float, float]] = field(default_factory=list)

@dataclass
class EngineExhaustProfile:
    """Complete exhaust profile for one engine."""
    engine_file: str
    engine_name: str              # primary engine part name
    is_exhaust_count: int
    is_exhaust_nodes: List[IsExhaustNode]
    exhaust_slots: List[ExhaustSlotInfo]   # found downstream exhaust connections
    pattern_classification: str    # A, A', B, C, or unknown
    notes: List[str] = field(default_factory=list)

# =====================================================================
# Node extraction with group tracking
# =====================================================================

EXHAUST_SLOT_PATTERNS = re.compile(
    r'(header|exhmanifold|exhaust|downpipe)', re.IGNORECASE
)

def extract_isExhaust_nodes(
    parsed_data: Dict[str, Any],
    source_file: str,
    vehicle_name: str = ""
) -> Dict[str, List[IsExhaustNode]]:
    """Extract all isExhaust nodes from parsed jbeam data, grouped by part.

    Tracks nodeGroup/group modifier state to determine which group each
    isExhaust node belongs to.
    """
    results: Dict[str, List[IsExhaustNode]] = {}

    for part_name, part_data in parsed_data.items():
        if not isinstance(part_data, dict):
            continue

        nodes_sections = part_data.get('nodes', [])
        if not isinstance(nodes_sections, list):
            continue

        is_exhaust_nodes: List[IsExhaustNode] = []
        current_group = ""

        for item in nodes_sections:
            if isinstance(item, dict):
                # Property modifier row — track group state
                if 'group' in item:
                    g = item['group']
                    if isinstance(g, list):
                        current_group = ', '.join(str(x) for x in g)
                    elif isinstance(g, str):
                        current_group = g
                    else:
                        current_group = str(g) if g else ""
                if 'nodeGroup' in item:
                    g = item['nodeGroup']
                    if isinstance(g, list):
                        current_group = ', '.join(str(x) for x in g)
                    elif isinstance(g, str):
                        current_group = g
                    else:
                        current_group = str(g) if g else ""
                continue

            if not isinstance(item, list) or len(item) < 4:
                continue

            # Skip header rows
            if isinstance(item[0], str) and item[0] in ('id', 'id1', 'id2'):
                continue

            node_name = item[0] if isinstance(item[0], str) else str(item[0])
            node_name = node_name.rstrip(',').strip('"')

            # Check for isExhaust in inline properties
            has_is_exhaust = False
            if len(item) >= 5 and isinstance(item[4], dict):
                if 'isExhaust' in item[4]:
                    has_is_exhaust = True
            # Also check item[3] in case it's a property dict (3-element nodes)
            if len(item) >= 4 and isinstance(item[3], dict):
                if 'isExhaust' in item[3]:
                    has_is_exhaust = True

            if has_is_exhaust:
                try:
                    x = float(item[1])
                    y = float(item[2])
                    z = float(item[3]) if not isinstance(item[3], dict) else 0.0
                except (TypeError, ValueError):
                    continue

                is_exhaust_nodes.append(IsExhaustNode(
                    name=node_name,
                    x=x, y=y, z=z,
                    group=current_group,
                    source_part=part_name,
                    source_file=str(source_file)
                ))

        if is_exhaust_nodes:
            results[part_name] = is_exhaust_nodes

    return results


def extract_all_engine_block_nodes(
    parsed_data: Dict[str, Any],
    engine_part_name: str
) -> List[Dict[str, Any]]:
    """Extract all nodes from a specific part, with group tracking.

    Returns list of dicts: {name, x, y, z, group, is_exhaust, properties}
    """
    part_data = parsed_data.get(engine_part_name, {})
    if not isinstance(part_data, dict):
        return []

    nodes_sections = part_data.get('nodes', [])
    if not isinstance(nodes_sections, list):
        return []

    nodes = []
    current_group = ""
    current_props = {}

    for item in nodes_sections:
        if isinstance(item, dict):
            if 'group' in item:
                g = item['group']
                current_group = ', '.join(g) if isinstance(g, list) else str(g or "")
            if 'nodeGroup' in item:
                g = item['nodeGroup']
                current_group = ', '.join(g) if isinstance(g, list) else str(g or "")
            current_props.update(item)
            continue

        if not isinstance(item, list) or len(item) < 4:
            continue
        if isinstance(item[0], str) and item[0] in ('id', 'id1', 'id2'):
            continue

        node_name = str(item[0]).rstrip(',').strip('"')
        inline_props = item[4] if (len(item) >= 5 and isinstance(item[4], dict)) else {}
        has_exhaust = 'isExhaust' in inline_props

        try:
            x, y, z = float(item[1]), float(item[2]), float(item[3]) if not isinstance(item[3], dict) else 0.0
        except (TypeError, ValueError):
            continue

        nodes.append({
            'name': node_name,
            'x': x, 'y': y, 'z': z,
            'group': current_group,
            'is_exhaust': has_exhaust,
            'properties': {**current_props, **inline_props}
        })

    return nodes


# =====================================================================
# Exhaust slot chain tracing
# =====================================================================

# Header rows for slots and slots2 formats
SLOTS_HEADER_KEYS = {'type', 'default', 'name', 'allowTypes', 'denyTypes', 'description'}


def _get_combined_slots(part_data: Dict[str, Any]) -> List:
    """Get slots from both 'slots' (legacy) and 'slots2' (modern) format."""
    result = []
    for key in ('slots', 'slots2'):
        s = part_data.get(key, [])
        if isinstance(s, list):
            result.extend(s)
    return result


def _is_slot_header(slot_entry: list) -> bool:
    """Check if a slot entry is a header row."""
    return isinstance(slot_entry[0], str) and slot_entry[0] in SLOTS_HEADER_KEYS


def find_exhaust_slots_in_part(
    parsed_data: Dict[str, Any],
    part_name: str
) -> List[Tuple[str, str]]:
    """Find exhaust-related child slots defined by a part.

    Handles both legacy 'slots' and modern 'slots2' formats.
    Returns list of (slotType, default_value) tuples.
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    slots = _get_combined_slots(part_data)

    exhaust_slots = []
    for slot_entry in slots:
        if not isinstance(slot_entry, list) or len(slot_entry) < 2:
            continue
        if _is_slot_header(slot_entry):
            continue

        slot_type = str(slot_entry[0])
        # slots2 format: [name, allowTypes, denyTypes, default, description]
        # slots format:  [slotType, default, description]
        if isinstance(slot_entry[1], list):
            # slots2 format — default is at index 3
            default = str(slot_entry[3]) if len(slot_entry) > 3 else ""
        else:
            default = str(slot_entry[1]) if len(slot_entry) > 1 else ""

        if EXHAUST_SLOT_PATTERNS.search(slot_type):
            exhaust_slots.append((slot_type, default))

    return exhaust_slots


def find_all_child_slots(
    parsed_data: Dict[str, Any],
    part_name: str
) -> List[Tuple[str, str, str]]:
    """Find ALL child slots defined by a part.

    Handles both legacy 'slots' and modern 'slots2' formats.
    Returns list of (slotType, default_value, description) tuples.
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    slots = _get_combined_slots(part_data)

    result = []
    for slot_entry in slots:
        if not isinstance(slot_entry, list) or len(slot_entry) < 2:
            continue
        if _is_slot_header(slot_entry):
            continue

        slot_type = str(slot_entry[0])
        # Handle both formats
        if isinstance(slot_entry[1], list):
            # slots2: [name, allowTypes, denyTypes, default, description]
            default = str(slot_entry[3]) if len(slot_entry) > 3 else ""
            desc = str(slot_entry[4]) if len(slot_entry) > 4 else ""
        else:
            # slots: [slotType, default, description]
            default = str(slot_entry[1]) if len(slot_entry) > 1 else ""
            desc = str(slot_entry[2]) if len(slot_entry) > 2 else ""
        result.append((slot_type, default, desc))

    return result


def trace_exhaust_chain(
    parsed_data: Dict[str, Any],
    engine_part_name: str,
    source_file: str,
    vehicle_name: str
) -> List[ExhaustSlotInfo]:
    """Trace exhaust slot chains starting from an engine part.

    Implements the find_some_exhaust_slot logic from the architecture doc:
    1. Direct engine slots (header, exhaust, manifold, downpipe)
    2. Intermediate-hosted (intake → header → exhaust, turbo → downpipe → exhaust)
    3. Body/frame-hosted exhaust (Pattern C)
    """
    results: List[ExhaustSlotInfo] = []

    # --- Phase 1: Direct exhaust slots on the engine ---
    engine_exhaust_slots = find_exhaust_slots_in_part(parsed_data, engine_part_name)
    all_engine_slots = find_all_child_slots(parsed_data, engine_part_name)

    # Check direct exhaust slots (e.g., barstow_exhaust_v8 as sibling)
    direct_exhaust_slots = [
        (st, dv) for st, dv in engine_exhaust_slots
        if 'exhaust' in st.lower() and 'header' not in st.lower()
           and 'manifold' not in st.lower() and 'downpipe' not in st.lower()
    ]

    # Check header/manifold/downpipe slots
    downstream_slots = [
        (st, dv) for st, dv in engine_exhaust_slots
        if 'header' in st.lower() or 'manifold' in st.lower()
           or 'downpipe' in st.lower()
    ]

    # For each downstream component, check if IT hosts an exhaust slot
    for ds_type, ds_default in downstream_slots:
        # Find the part that fills this slot (by matching slotType)
        ds_part = _find_part_by_slotType(parsed_data, ds_type)
        if ds_part:
            ds_exhaust = find_exhaust_slots_in_part(parsed_data, ds_part)
            # Filter for actual exhaust (not another header/manifold)
            final_exhaust = [
                (st, dv) for st, dv in ds_exhaust
                if 'exhaust' in st.lower() and 'header' not in st.lower()
                   and 'manifold' not in st.lower() and 'downpipe' not in st.lower()
            ]
            # Extract downstream component nodes
            ds_nodes = _extract_part_nodes(parsed_data, ds_part)
            node_names = [n['name'] for n in ds_nodes]
            node_positions = [(n['x'], n['y'], n['z']) for n in ds_nodes]

            if final_exhaust:
                for exh_type, exh_default in final_exhaust:
                    results.append(ExhaustSlotInfo(
                        downstream_component_name=ds_part,
                        downstream_component_slotType=ds_type,
                        exhaust_slot_type=exh_type,
                        chain_path=f"{engine_part_name} → {ds_type}[{ds_part}] → {exh_type}",
                        node_names=node_names,
                        node_positions=node_positions
                    ))
            else:
                # Record the downstream component even without exhaust child
                results.append(ExhaustSlotInfo(
                    downstream_component_name=ds_part,
                    downstream_component_slotType=ds_type,
                    exhaust_slot_type="(none found)",
                    chain_path=f"{engine_part_name} → {ds_type}[{ds_part}] → ???",
                    node_names=node_names,
                    node_positions=node_positions
                ))

    # Record direct exhaust as siblings (Pattern A')
    for exh_type, exh_default in direct_exhaust_slots:
        results.append(ExhaustSlotInfo(
            downstream_component_name="(engine sibling)",
            downstream_component_slotType=exh_type,
            exhaust_slot_type=exh_type,
            chain_path=f"{engine_part_name} → {exh_type} (sibling slot)",
            node_names=[],
            node_positions=[]
        ))

    # --- Phase 2: Intermediate-hosted (intake → header/downpipe → exhaust) ---
    if not downstream_slots:
        # No direct exhaust components — check intake/turbo slots
        non_exhaust_engine_slots = [
            (st, dv, desc) for st, dv, desc in all_engine_slots
            if not EXHAUST_SLOT_PATTERNS.search(st)
        ]
        for int_type, int_default, int_desc in non_exhaust_engine_slots:
            int_part = _find_part_by_slotType(parsed_data, int_type)
            if not int_part:
                continue

            # Check if this intermediate part hosts exhaust-related slots
            int_exhaust_slots = find_exhaust_slots_in_part(parsed_data, int_part)
            for ie_type, ie_default in int_exhaust_slots:
                # This is likely a header or downpipe within intake/turbo
                ie_part = _find_part_by_slotType(parsed_data, ie_type)
                if ie_part:
                    ie_child_exhaust = find_exhaust_slots_in_part(parsed_data, ie_part)
                    ie_nodes = _extract_part_nodes(parsed_data, ie_part)
                    final = [
                        (st, dv) for st, dv in ie_child_exhaust
                        if 'exhaust' in st.lower() and 'header' not in st.lower()
                           and 'downpipe' not in st.lower()
                    ]
                    if final:
                        for exh_type, exh_default in final:
                            results.append(ExhaustSlotInfo(
                                downstream_component_name=ie_part,
                                downstream_component_slotType=ie_type,
                                exhaust_slot_type=exh_type,
                                chain_path=f"{engine_part_name} → {int_type}[{int_part}] → {ie_type}[{ie_part}] → {exh_type}",
                                node_names=[n['name'] for n in ie_nodes],
                                node_positions=[(n['x'], n['y'], n['z']) for n in ie_nodes]
                            ))

            # Also check for turbo variants of the same slot
            for alt_part_name, alt_part_data in parsed_data.items():
                if not isinstance(alt_part_data, dict):
                    continue
                alt_slot_type = alt_part_data.get('slotType', '')
                if alt_slot_type == int_type and alt_part_name != int_part:
                    # Alternative part filling same slot (e.g., turbo filling intake slot)
                    alt_exhaust = find_exhaust_slots_in_part(parsed_data, alt_part_name)
                    for ae_type, ae_default in alt_exhaust:
                        ae_part = _find_part_by_slotType(parsed_data, ae_type)
                        if ae_part:
                            ae_child = find_exhaust_slots_in_part(parsed_data, ae_part)
                            ae_nodes = _extract_part_nodes(parsed_data, ae_part)
                            ae_final = [
                                (st, dv) for st, dv in ae_child
                                if 'exhaust' in st.lower()
                            ]
                            if ae_final:
                                for exh_type, exh_default in ae_final:
                                    results.append(ExhaustSlotInfo(
                                        downstream_component_name=ae_part,
                                        downstream_component_slotType=ae_type,
                                        exhaust_slot_type=exh_type,
                                        chain_path=f"{engine_part_name} → {int_type}[{alt_part_name}] → {ae_type}[{ae_part}] → {exh_type}",
                                        node_names=[n['name'] for n in ae_nodes],
                                        node_positions=[(n['x'], n['y'], n['z']) for n in ae_nodes]
                                    ))

    return results


def _find_part_by_slotType(
    parsed_data: Dict[str, Any],
    slot_type: str
) -> Optional[str]:
    """Find the first part in parsed_data that fills a given slotType."""
    for part_name, part_data in parsed_data.items():
        if isinstance(part_data, dict) and part_data.get('slotType', '') == slot_type:
            return part_name
    return None


def _extract_part_nodes(
    parsed_data: Dict[str, Any],
    part_name: str
) -> List[Dict[str, Any]]:
    """Extract node positions from a part (simplified, no group tracking)."""
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    nodes_sections = part_data.get('nodes', [])
    if not isinstance(nodes_sections, list):
        return []

    nodes = []
    for item in nodes_sections:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if isinstance(item[0], str) and item[0] in ('id', 'id1', 'id2'):
            continue

        node_name = str(item[0]).rstrip(',').strip('"')
        try:
            x, y, z = float(item[1]), float(item[2]), float(item[3]) if not isinstance(item[3], dict) else 0.0
        except (TypeError, ValueError):
            continue

        nodes.append({'name': node_name, 'x': x, 'y': y, 'z': z})

    return nodes


# =====================================================================
# Vehicle scanning
# =====================================================================

def find_engine_files(base_path: Path, vehicle_name: str) -> List[Path]:
    """Find all engine jbeam files for a target vehicle.

    Searches vehicle-specific and common folders.
    """
    engine_files = []

    # Vehicle-specific folder
    vehicle_path = base_path / vehicle_name / 'vehicles' / vehicle_name
    if vehicle_path.exists():
        for f in vehicle_path.glob(f"*engine*.jbeam"):
            if 'enginemounts' not in f.stem.lower() and 'management' not in f.stem.lower():
                engine_files.append(f)

    # Common folder
    common_path = base_path / 'common' / 'vehicles' / 'common' / vehicle_name
    if common_path.exists():
        for f in common_path.glob(f"*engine*.jbeam"):
            if 'enginemounts' not in f.stem.lower() and 'management' not in f.stem.lower():
                engine_files.append(f)

    return engine_files


def find_exhaust_files(base_path: Path, vehicle_name: str) -> List[Path]:
    """Find all exhaust jbeam files for a target vehicle."""
    exhaust_files = []

    for search_dir in [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]:
        if search_dir.exists():
            for f in search_dir.glob("*exhaust*.jbeam"):
                exhaust_files.append(f)

    return exhaust_files


def find_body_frame_exhaust_slots(base_path: Path, vehicle_name: str) -> List[Tuple[str, str, str]]:
    """Scan body/frame files for exhaust slots (Pattern C detection).

    Checks both vehicle-specific and common folders.
    Handles both legacy 'slots' and modern 'slots2' formats.
    """
    results = []

    search_dirs = [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in ["*body*.jbeam", "*frame*.jbeam", "*chassis*.jbeam"]:
            for f in search_dir.glob(pattern):
                try:
                    parsed = JBeamParser.parse_jbeam(f)
                    if not parsed:
                        continue
                    for part_name, part_data in parsed.items():
                        if not isinstance(part_data, dict):
                            continue
                        all_slots = _get_combined_slots(part_data)
                        for slot_entry in all_slots:
                            if not isinstance(slot_entry, list) or len(slot_entry) < 2:
                                continue
                            if _is_slot_header(slot_entry):
                                continue
                            st = str(slot_entry[0])
                            if 'exhaust' in st.lower():
                                results.append((str(f.name), part_name, st))
                except Exception:
                    continue

    return results


# =====================================================================
# Profile builder
# =====================================================================

def build_merged_vehicle_data(
    base_path: Path,
    vehicle_name: str,
    engine_files: List[Path],
    exhaust_files: List[Path]
) -> Dict[str, Any]:
    """Build merged parsed data from all engine + exhaust files for cross-file resolution.

    This is critical because exhaust chain components (headers, manifolds)
    are often defined in different files than the engine itself.
    E.g., pickup_header_v8 is in engine_v8_4.5.jbeam, referenced from engine_v8_5.5.jbeam.
    """
    merged: Dict[str, Any] = {}
    seen_files: set = set()

    for flist in [engine_files, exhaust_files]:
        for f in flist:
            if f in seen_files:
                continue
            seen_files.add(f)
            try:
                parsed = JBeamParser.parse_jbeam(f)
                if parsed:
                    merged.update(parsed)
            except Exception:
                continue

    # Also parse body/frame files for Pattern C detection
    search_dirs = [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in ["*body*.jbeam", "*frame*.jbeam"]:
            for f in search_dir.glob(pattern):
                if f in seen_files:
                    continue
                seen_files.add(f)
                try:
                    parsed = JBeamParser.parse_jbeam(f)
                    if parsed:
                        merged.update(parsed)
                except Exception:
                    continue

    return merged


def profile_vehicle_exhausts(
    base_path: Path,
    vehicle_name: str
) -> List[EngineExhaustProfile]:
    """Build complete exhaust profiles for all engines in a vehicle.

    Uses cross-file merged data so chain tracing works across files.
    """
    profiles = []

    engine_files = find_engine_files(base_path, vehicle_name)
    exhaust_files = find_exhaust_files(base_path, vehicle_name)

    if not engine_files:
        print(f"  WARNING: No engine files found for {vehicle_name}")
        return profiles

    # Build merged data from ALL vehicle files for cross-file chain resolution
    merged_data = build_merged_vehicle_data(base_path, vehicle_name, engine_files, exhaust_files)

    for engine_file in engine_files:
        try:
            parsed = JBeamParser.parse_jbeam(engine_file)
        except Exception as e:
            print(f"  ERROR parsing {engine_file}: {e}")
            continue

        if not parsed:
            continue

        # Extract isExhaust nodes from this specific file
        all_exhaust_nodes = extract_isExhaust_nodes(parsed, str(engine_file), vehicle_name)

        # Identify the "primary" engine parts
        for part_name, part_data in parsed.items():
            if not isinstance(part_data, dict):
                continue

            slot_type = part_data.get('slotType', '')
            has_main_engine = 'mainEngine' in part_data

            is_primary = (
                has_main_engine or
                ('engine' in slot_type.lower() and
                 'management' not in slot_type.lower() and
                 'internals' not in slot_type.lower() and
                 'mount' not in slot_type.lower() and
                 'mesh' not in slot_type.lower())
            )
            if not is_primary:
                continue

            engine_exhaust_nodes = all_exhaust_nodes.get(part_name, [])
            engine_block_exhaust = [
                n for n in engine_exhaust_nodes
                if 'engine' in n.group.lower() or 'block' in n.group.lower()
                   or n.group == ''
            ]

            # Use MERGED data for chain tracing (cross-file resolution)
            exhaust_chains = trace_exhaust_chain(merged_data, part_name, str(engine_file), vehicle_name)

            pattern = classify_pattern(exhaust_chains, base_path, vehicle_name, merged_data, part_name)

            notes = []
            if len(engine_exhaust_nodes) > 2:
                notes.append(f"FILTERED: {len(engine_exhaust_nodes)} isExhaust nodes (>2, likely race engine)")

            profiles.append(EngineExhaustProfile(
                engine_file=str(engine_file.name),
                engine_name=part_name,
                is_exhaust_count=len(engine_block_exhaust),
                is_exhaust_nodes=engine_block_exhaust,
                exhaust_slots=exhaust_chains,
                pattern_classification=pattern,
                notes=notes
            ))

    return profiles


def classify_pattern(
    chains: List[ExhaustSlotInfo],
    base_path: Path,
    vehicle_name: str,
    parsed_data: Dict[str, Any],
    engine_part: str
) -> str:
    """Classify the exhaust architecture pattern (A, A', B, C, unknown).

    Patterns:
      A  — engine → header/manifold → exhaust (header hosts exhaust slot)
      A' — engine has sibling exhaust slot directly
      B  — engine → intake/turbo → header/downpipe → exhaust
      C  — body/frame hosts exhaust slot (decoupled from engine chain)
    """
    body_exhaust = find_body_frame_exhaust_slots(base_path, vehicle_name)

    if not chains:
        # No exhaust chain from engine at all
        if body_exhaust:
            return "C (body/frame-hosted)"
        return "no_exhaust"

    # Check if any chain actually found a real exhaust slot
    has_real_exhaust = any(
        c.exhaust_slot_type != "(none found)" for c in chains
    )

    # If chains exist but none have a real exhaust child, check body/frame
    if not has_real_exhaust and body_exhaust:
        return "C (body/frame-hosted)"

    for chain in chains:
        path_lower = chain.chain_path.lower()
        if 'sibling' in path_lower:
            return "A' (engine sibling slots)"
        if 'intake' in path_lower or 'turbo' in path_lower:
            return "B (intake-nested)"

    # Check if there's also a sibling exhaust slot
    all_engine_slots = find_all_child_slots(parsed_data, engine_part)
    has_sibling_exhaust = any(
        'exhaust' in st.lower() and 'header' not in st.lower()
        and 'manifold' not in st.lower()
        for st, _, _ in all_engine_slots
    )
    has_header = any(
        'header' in st.lower() or 'manifold' in st.lower()
        for st, _, _ in all_engine_slots
    )

    if has_sibling_exhaust and has_header:
        return "A' (engine sibling slots)"

    return "A (engine → header → exhaust)"


# =====================================================================
# Camso adapted engine validation
# =====================================================================

def validate_camso_adapted_isExhaust(
    adapted_file: Path
) -> Tuple[int, List[IsExhaustNode]]:
    """Check if isExhaust is preserved in adapted engine output."""
    try:
        parsed = JBeamParser.parse_jbeam(adapted_file)
    except Exception as e:
        print(f"  ERROR parsing adapted file: {e}")
        return 0, []

    if not parsed:
        return 0, []

    all_nodes = extract_isExhaust_nodes(parsed, str(adapted_file))
    flat_nodes = []
    for part_nodes in all_nodes.values():
        flat_nodes.extend(part_nodes)

    return len(flat_nodes), flat_nodes


# =====================================================================
# Main test runner
# =====================================================================

# Expected data from manual research
# Pattern guide:
#   A  = engine → header → exhaust (header hosts exhaust slot)
#   A' = engine has sibling exhaust slot (directly on engine, not through header)
#   B  = engine → intake/turbo → header/downpipe → exhaust (nested chain)
#   C  = body/frame hosts exhaust slot (decoupled from engine chain)
EXPECTED = {
    'pickup':   {'count': 2, 'pattern': 'A'},
    'moonhawk': {'count': 1, 'pattern': "A'"},
    'covet':    {'count': 1, 'pattern': 'B'},    # front engines: intake → header → exhaust
    'fullsize': {'count': 2, 'pattern': 'C'},    # exhaust on frame, not engine chain
    'vivace':   {'count': 1, 'pattern': 'C'},    # exhaust on body, not engine chain
    'barstow':  {'count': 1, 'pattern': "A'"},   # parser limitation: may not parse
}


def run_tests():
    """Run the full exploration suite."""
    base_path = Path(__file__).parent.parent / 'SteamLibrary_content_vehicles'
    adapted_base = Path(__file__).parent.parent / 'mods' / 'unpacked'

    if not base_path.exists():
        print(f"ERROR: BeamNG vehicle data not found at {base_path}")
        return False

    print("=" * 80)
    print("EXHAUST SOLVER — Phase 0 Exploration & Data Validation")
    print("=" * 80)

    vehicles = list(EXPECTED.keys())
    all_good = True
    results_summary = []

    for vehicle in vehicles:
        print(f"\n{'─' * 72}")
        print(f"Vehicle: {vehicle}")
        print(f"{'─' * 72}")

        # Engine file discovery
        engine_files = find_engine_files(base_path, vehicle)
        print(f"  Engine files found: {len(engine_files)}")
        for ef in engine_files:
            print(f"    • {ef.name}")

        # Exhaust file discovery
        exhaust_files = find_exhaust_files(base_path, vehicle)
        print(f"  Exhaust files found: {len(exhaust_files)}")
        for ef in exhaust_files:
            print(f"    • {ef.name}")

        # Body/frame exhaust slots
        body_exhaust = find_body_frame_exhaust_slots(base_path, vehicle)
        if body_exhaust:
            print(f"  Body/frame exhaust slots: {len(body_exhaust)}")
            for src_file, part, slot_type in body_exhaust:
                print(f"    • {src_file} → {part} → {slot_type}")

        # Profile each engine
        profiles = profile_vehicle_exhausts(base_path, vehicle)

        if not profiles:
            print(f"  ⚠ No engine profiles generated")
            all_good = False
            continue

        expected = EXPECTED[vehicle]

        for profile in profiles:
            # Only validate primary engines with mainEngine
            print(f"\n  Engine: {profile.engine_name} ({profile.engine_file})")
            print(f"    isExhaust nodes: {profile.is_exhaust_count}")
            for node in profile.is_exhaust_nodes:
                print(f"      • {node.name} at ({node.x:.3f}, {node.y:.3f}, {node.z:.3f})  group: {node.group}")
            print(f"    Pattern: {profile.pattern_classification}")

            if profile.exhaust_slots:
                print(f"    Exhaust chain(s):")
                for chain in profile.exhaust_slots:
                    print(f"      • {chain.chain_path}")
                    print(f"        exhaust slotType: {chain.exhaust_slot_type}")
                    if chain.node_names:
                        print(f"        bridge nodes: {', '.join(chain.node_names)}")
            else:
                print(f"    Exhaust chain(s): NONE FOUND")

            for note in profile.notes:
                print(f"    NOTE: {note}")

        # Validation
        # Find the primary engine profile — prefer engines with real exhaust chains
        # or most isExhaust nodes. Skip parts with 0 isExhaust.
        primary_candidates = [p for p in profiles if p.is_exhaust_count > 0]
        if not primary_candidates:
            primary_candidates = profiles  # fallback to all

        primary = max(
            primary_candidates,
            key=lambda p: (
                p.pattern_classification != 'no_exhaust',   # prefer classified
                p.is_exhaust_count,                          # then most isExhaust
            )
        ) if primary_candidates else None
        if primary:
            ok_count = primary.is_exhaust_count == expected['count']
            ok_pattern = expected['pattern'] in primary.pattern_classification
            status_count = "PASS" if ok_count else "FAIL"
            status_pattern = "PASS" if ok_pattern else "FAIL"

            # Check that we found an exhaust slot (unless no_exhaust)
            has_exhaust = any(
                c.exhaust_slot_type != "(none found)"
                for c in primary.exhaust_slots
            )
            if expected['pattern'] == 'C':
                # For Pattern C, exhaust chain from engine might be empty
                # But body/frame slots should exist
                has_exhaust = has_exhaust or bool(body_exhaust)

            ok_exhaust = has_exhaust
            status_exhaust = "PASS" if ok_exhaust else "FAIL"

            if not ok_count: all_good = False
            if not ok_pattern: all_good = False
            if not ok_exhaust: all_good = False

            results_summary.append({
                'vehicle': vehicle,
                'isExhaust': f"{status_count} ({primary.is_exhaust_count}, expected {expected['count']})",
                'pattern': f"{status_pattern} ({primary.pattern_classification})",
                'exhaust_found': status_exhaust,
            })
        else:
            all_good = False
            results_summary.append({
                'vehicle': vehicle,
                'isExhaust': 'SKIP',
                'pattern': 'SKIP',
                'exhaust_found': 'SKIP',
            })

    # --- Camso adapted engine validation ---
    print(f"\n{'─' * 72}")
    print("Camso Adapted Engine — isExhaust Preservation Check")
    print(f"{'─' * 72}")

    adapted_files = list((adapted_base / 'engineswaps' / 'vehicles' / 'pickup').glob("*engine*adapted*.jbeam"))
    if not adapted_files:
        # Try other locations
        for mod_dir in adapted_base.iterdir():
            if mod_dir.is_dir() and 'engineswaps' not in mod_dir.name:
                for f in mod_dir.rglob("*engine*adapted*.jbeam"):
                    adapted_files.append(f)
                    break  # one per mod is enough

    if adapted_files:
        for af in adapted_files[:3]:  # Check up to 3
            count, nodes = validate_camso_adapted_isExhaust(af)
            status = "PASS" if count >= 1 else "FAIL"
            print(f"  {status}  {af.name}: {count} isExhaust node(s)")
            for n in nodes:
                print(f"         • {n.name} at ({n.x:.3f}, {n.y:.3f}, {n.z:.3f})")
            if count < 1:
                all_good = False
    else:
        print("  SKIP  No adapted engine files found")

    # --- Summary ---
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"{'Vehicle':<12} {'isExhaust Count':<30} {'Pattern':<35} {'Exhaust Found':<15}")
    print(f"{'─'*12} {'─'*30} {'─'*35} {'─'*15}")
    for r in results_summary:
        print(f"{r['vehicle']:<12} {r['isExhaust']:<30} {r['pattern']:<35} {r['exhaust_found']:<15}")

    print(f"\n{'─' * 72}")
    overall = "ALL PASS" if all_good else "SOME FAILURES"
    print(f"Overall: {overall}")
    print(f"{'─' * 72}")

    return all_good


if __name__ == '__main__':
    # Suppress most logging noise
    logging.basicConfig(level=logging.WARNING)
    success = run_tests()
    sys.exit(0 if success else 1)
