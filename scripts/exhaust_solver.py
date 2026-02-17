#!/usr/bin/env python3
"""
Exhaust Solver — Extraction, Classification, Strategy Selection & Component Generation

Discovers target vehicle exhaust architecture, classifies isExhaust node
counts, selects the optimal exhaust adaptation strategy, and generates
the adapted_exhaust_component jbeam part for Camso → BeamNG engine swaps.

Architecture doc: docs/exhaust_solver.md
Exploration script: scripts/test_exhaust_discovery.py

Module Responsibilities:
  - Parse adapted donor engine to count isExhaust nodes
  - Discover and parse target vehicle engine/exhaust/body files
  - Trace exhaust slot chains (cross-file, slots + slots2)
  - Classify exhaust architecture patterns (A, A', B, C)
  - Select strategy: matching / mismatch / no_exhaust
  - Generate adapted_exhaust_component jbeam part (nodes, beams, slots)
"""

import math
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports from sibling modules — fail gracefully
# ---------------------------------------------------------------------------
# JBeamParser import uses late binding to avoid circular dependency when
# engineswap imports exhaust_solver.  The module-level flag is set eagerly
# on first access via _get_parser().
_JBeamParser = None          # populated lazily
PARSER_AVAILABLE = False     # updated by _get_parser()

def _get_parser():
    """Lazily resolve JBeamParser to break circular import with engineswap."""
    global _JBeamParser, PARSER_AVAILABLE
    if _JBeamParser is not None:
        return _JBeamParser
    try:
        from engineswap import JBeamParser as _P
        _JBeamParser = _P
        PARSER_AVAILABLE = True
        return _JBeamParser
    except ImportError:
        PARSER_AVAILABLE = False
        logger.warning("JBeamParser not available — exhaust_solver cannot parse jbeam files")
        return None

# Convenience alias used by all parse call-sites
class JBeamParser:
    """Thin proxy that delegates to the lazily-loaded real JBeamParser."""
    @staticmethod
    def parse_jbeam(path):
        p = _get_parser()
        if p is None:
            raise RuntimeError("JBeamParser not available")
        return p.parse_jbeam(path)

try:
    from analyze_powertrains import get_search_folders
    SEARCH_FOLDERS_AVAILABLE = True
except ImportError:
    get_search_folders = None  # type: ignore[assignment]
    SEARCH_FOLDERS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXHAUST_SLOT_PATTERNS = re.compile(
    r'(header|exhmanifold|exhaust|downpipe)', re.IGNORECASE
)

# Exhaust manifold bridge node pattern (exm1r, exm1l, exm2r, etc.)
_BRIDGE_NODE_PATTERN = re.compile(r'^exm\d+[rl]?$', re.IGNORECASE)

# Keys that indicate a slot array header row (not a real slot entry)
SLOTS_HEADER_KEYS = frozenset({
    'type', 'name', 'default', 'allowTypes', 'denyTypes', 'description'
})

# File stem substrings to exclude from engine file discovery
ENGINE_FILE_EXCLUDES = frozenset({
    'enginemounts', 'management', 'engineaccessories'
})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IsExhaustNode:
    """An engine node carrying the isExhaust property."""
    name: str
    x: float
    y: float
    z: float
    group: str           # active nodeGroup at this node's position
    source_part: str
    source_file: str


@dataclass
class ExhaustSlotInfo:
    """Result of tracing one exhaust slot chain from an engine."""
    downstream_component_name: str       # e.g. "pickup_header_v8"
    downstream_component_slotType: str   # slotType of that component
    exhaust_slot_type: str               # e.g. "pickup_exhaust_v8" or "(none found)"
    chain_path: str                      # human-readable chain description
    node_names: List[str] = field(default_factory=list)
    node_positions: List[Tuple[float, float, float]] = field(default_factory=list)


@dataclass
class EngineExhaustProfile:
    """Complete exhaust profile for one target engine."""
    engine_file: str
    engine_name: str
    is_exhaust_count: int
    is_exhaust_nodes: List[IsExhaustNode]
    exhaust_slots: List[ExhaustSlotInfo]
    pattern: str            # A, A', B, C, no_exhaust
    notes: List[str] = field(default_factory=list)


@dataclass
class ExhaustSolverResult:
    """Result returned to engineswap.py for integration."""
    strategy: str                                # "matching", "mismatch", "no_exhaust"
    adapted_part: Optional[Dict[str, Any]]       # complete jbeam part dict (Phase 2)
    exhaust_slot_entry: Optional[List]           # slot entry to inject into engine's slots (Phase 2)
    target_exhaust_slot_type: Optional[str]      # downstream exhaust slotType
    candidate_engine: Optional[str]              # which target engine was template
    candidate_profile: Optional[EngineExhaustProfile]  # full profile of chosen engine
    donor_isExhaust_count: int
    target_isExhaust_count: int
    pattern: str                                 # exhaust architecture pattern
    warnings: List[str] = field(default_factory=list)


# =========================================================================
# Slot Format Helpers (dual slots/slots2 support)
# =========================================================================

def _get_combined_slots(part_data: Dict[str, Any]) -> List:
    """Get slot entries from both legacy 'slots' and modern 'slots2' keys."""
    result = []
    for key in ('slots', 'slots2'):
        s = part_data.get(key, [])
        if isinstance(s, list):
            result.extend(s)
    return result


def _is_slot_header(slot_entry: list) -> bool:
    """Check if a slot entry is a header row (not a real slot)."""
    if not slot_entry:
        return False
    return isinstance(slot_entry[0], str) and slot_entry[0] in SLOTS_HEADER_KEYS


def _extract_slot_fields(slot_entry: list) -> Tuple[str, str, str]:
    """Extract (slotType, default, description) from either slot format.

    Legacy slots:  [slotType, default, description]
    Modern slots2: [name, allowTypes[], denyTypes[], default, description, {props}]
    """
    slot_type = str(slot_entry[0])

    if len(slot_entry) >= 2 and isinstance(slot_entry[1], list):
        # slots2 format
        default = str(slot_entry[3]) if len(slot_entry) > 3 else ""
        desc = str(slot_entry[4]) if len(slot_entry) > 4 else ""
    else:
        # legacy slots format
        default = str(slot_entry[1]) if len(slot_entry) > 1 else ""
        desc = str(slot_entry[2]) if len(slot_entry) > 2 else ""

    return slot_type, default, desc


# =========================================================================
# Node Extraction
# =========================================================================

def extract_isExhaust_nodes(
    parsed_data: Dict[str, Any],
    source_file: str,
) -> Dict[str, List[IsExhaustNode]]:
    """Extract all isExhaust nodes from parsed jbeam data, grouped by part.

    Tracks group/nodeGroup modifier state to determine which nodeGroup each
    isExhaust node belongs to.

    Returns:
        Dict mapping part_name → list of IsExhaustNode
    """
    results: Dict[str, List[IsExhaustNode]] = {}

    for part_name, part_data in parsed_data.items():
        if not isinstance(part_data, dict):
            continue

        nodes_section = part_data.get('nodes', [])
        if not isinstance(nodes_section, list):
            continue

        is_exhaust_nodes: List[IsExhaustNode] = []
        current_group = ""

        for item in nodes_section:
            # Property modifier row — track group state
            if isinstance(item, dict):
                for group_key in ('group', 'nodeGroup'):
                    if group_key in item:
                        g = item[group_key]
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

            # Check for isExhaust in inline properties dict
            has_is_exhaust = False
            for idx in (4, 3):  # check item[4] first, then item[3]
                if len(item) > idx and isinstance(item[idx], dict):
                    if 'isExhaust' in item[idx]:
                        has_is_exhaust = True
                        break

            if not has_is_exhaust:
                continue

            node_name = str(item[0]).rstrip(',').strip('"')
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


def _extract_part_nodes(
    parsed_data: Dict[str, Any],
    part_name: str
) -> List[Dict[str, Any]]:
    """Extract all nodes from a specific part (simplified, name+position only)."""
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    nodes_section = part_data.get('nodes', [])
    if not isinstance(nodes_section, list):
        return []

    nodes = []
    for item in nodes_section:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if isinstance(item[0], str) and item[0] in ('id', 'id1', 'id2'):
            continue
        try:
            nodes.append({
                'name': str(item[0]).rstrip(',').strip('"'),
                'x': float(item[1]),
                'y': float(item[2]),
                'z': float(item[3]) if not isinstance(item[3], dict) else 0.0,
            })
        except (TypeError, ValueError):
            continue

    return nodes


def count_donor_isExhaust_nodes(
    adapted_engine_path: Path,
) -> Tuple[int, List[IsExhaustNode]]:
    """Count isExhaust nodes in an adapted Camso engine file.

    Args:
        adapted_engine_path: Path to the adapted engine jbeam file.

    Returns:
        (count, list_of_nodes) — typically 1 or 2 for Camso engines.
    """
    if _get_parser() is None:
        logger.error("JBeamParser not available")
        return 0, []

    parsed = JBeamParser.parse_jbeam(adapted_engine_path)
    if not parsed:
        logger.warning(f"Failed to parse adapted engine: {adapted_engine_path}")
        return 0, []

    all_nodes = extract_isExhaust_nodes(parsed, str(adapted_engine_path))

    # Flatten across all parts
    flat: List[IsExhaustNode] = []
    for nodes in all_nodes.values():
        flat.extend(nodes)

    # Filter to engine_block group only (same as exploration script)
    engine_block_nodes = [
        n for n in flat
        if 'engine' in n.group.lower() or 'block' in n.group.lower() or n.group == ''
    ]

    return len(engine_block_nodes), engine_block_nodes


# =========================================================================
# File Discovery
# =========================================================================

def find_engine_files(base_path: Path, vehicle_name: str,
                      family_prefix: Optional[str] = None) -> List[Path]:
    """Find all engine jbeam files for a target vehicle.

    Searches vehicle-specific and common folders. For family-shared
    architectures (e.g. etk800 uses etk_engine slot type with files in
    common/vehicles/common/etk/), pass family_prefix='etk' to also
    search the family folder.
    """
    engine_files: List[Path] = []

    search_dirs = [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]
    if family_prefix and family_prefix != vehicle_name:
        search_dirs.append(
            base_path / 'common' / 'vehicles' / 'common' / family_prefix
        )

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*engine*.jbeam"):
            stem_lower = f.stem.lower()
            if any(excl in stem_lower for excl in ENGINE_FILE_EXCLUDES):
                continue
            engine_files.append(f)

    return engine_files


def find_exhaust_files(base_path: Path, vehicle_name: str,
                       family_prefix: Optional[str] = None) -> List[Path]:
    """Find all exhaust jbeam files for a target vehicle.

    For family-shared architectures, pass family_prefix to search
    the family's common folder as well.
    """
    exhaust_files: List[Path] = []

    search_dirs = [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]
    if family_prefix and family_prefix != vehicle_name:
        search_dirs.append(
            base_path / 'common' / 'vehicles' / 'common' / family_prefix
        )

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*exhaust*.jbeam"):
            exhaust_files.append(f)

    return exhaust_files


def find_body_frame_files(base_path: Path, vehicle_name: str,
                          family_prefix: Optional[str] = None) -> List[Path]:
    """Find body/frame/chassis jbeam files for a target vehicle.

    For family-shared architectures, pass family_prefix to search
    the family's common folder as well.
    """
    body_files: List[Path] = []

    search_dirs = [
        base_path / vehicle_name / 'vehicles' / vehicle_name,
        base_path / 'common' / 'vehicles' / 'common' / vehicle_name,
    ]
    if family_prefix and family_prefix != vehicle_name:
        search_dirs.append(
            base_path / 'common' / 'vehicles' / 'common' / family_prefix
        )

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in ("*body*.jbeam", "*frame*.jbeam", "*chassis*.jbeam"):
            for f in search_dir.glob(pattern):
                body_files.append(f)

    return body_files


# =========================================================================
# Cross-File Merged Data
# =========================================================================

def build_merged_vehicle_data(
    base_path: Path,
    vehicle_name: str,
    engine_files: Optional[List[Path]] = None,
    exhaust_files: Optional[List[Path]] = None,
    family_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Build merged parsed data from all engine + exhaust + body/frame files.

    Cross-file resolution is MANDATORY because exhaust chain components
    (headers, manifolds) are often defined in different jbeam files than
    the engine referencing them.

    Example: pickup_header_v8 is defined in engine_v8_4.5.jbeam but
    referenced via slotType from engine_v8_5.5.jbeam.

    For family-shared architectures (e.g. etk800 uses etk_engine), pass
    family_prefix='etk' so discovery also searches common/etk/.
    """
    if _get_parser() is None:
        logger.error("JBeamParser not available")
        return {}

    if engine_files is None:
        engine_files = find_engine_files(base_path, vehicle_name, family_prefix)
    if exhaust_files is None:
        exhaust_files = find_exhaust_files(base_path, vehicle_name, family_prefix)

    body_files = find_body_frame_files(base_path, vehicle_name, family_prefix)

    merged: Dict[str, Any] = {}
    seen_files: Set[Path] = set()

    for flist in [engine_files, exhaust_files, body_files]:
        for f in flist:
            abs_f = f.resolve()
            if abs_f in seen_files:
                continue
            seen_files.add(abs_f)
            try:
                parsed = JBeamParser.parse_jbeam(f)
                if parsed:
                    merged.update(parsed)
            except Exception as e:
                logger.debug(f"Skipping unparseable file {f.name}: {e}")
                continue

    logger.debug(f"Merged vehicle data: {len(merged)} parts from {len(seen_files)} files")
    return merged


# =========================================================================
# Slot Chain Tracing
# =========================================================================

def find_exhaust_slots_in_part(
    parsed_data: Dict[str, Any],
    part_name: str,
) -> List[Tuple[str, str]]:
    """Find exhaust-related child slots defined by a part.

    Handles both legacy 'slots' and modern 'slots2' formats.

    Returns:
        List of (slotType, default_value) for exhaust-related slots.
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    slots = _get_combined_slots(part_data)
    exhaust_slots: List[Tuple[str, str]] = []

    for slot_entry in slots:
        if not isinstance(slot_entry, list) or len(slot_entry) < 2:
            continue
        if _is_slot_header(slot_entry):
            continue

        slot_type, default, _ = _extract_slot_fields(slot_entry)

        if EXHAUST_SLOT_PATTERNS.search(slot_type):
            exhaust_slots.append((slot_type, default))

    return exhaust_slots


def find_all_child_slots(
    parsed_data: Dict[str, Any],
    part_name: str,
) -> List[Tuple[str, str, str]]:
    """Find ALL child slots defined by a part.

    Returns:
        List of (slotType, default_value, description).
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    slots = _get_combined_slots(part_data)
    result: List[Tuple[str, str, str]] = []

    for slot_entry in slots:
        if not isinstance(slot_entry, list) or len(slot_entry) < 2:
            continue
        if _is_slot_header(slot_entry):
            continue

        result.append(_extract_slot_fields(slot_entry))

    return result


def _find_part_by_slotType(
    parsed_data: Dict[str, Any],
    slot_type: str,
) -> Optional[str]:
    """Find the first part in parsed_data whose slotType matches."""
    for part_name, part_data in parsed_data.items():
        if isinstance(part_data, dict) and part_data.get('slotType', '') == slot_type:
            return part_name
    return None


def find_body_frame_exhaust_slots(
    base_path: Path,
    vehicle_name: str,
    merged_data: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, str]]:
    """Scan body/frame parts for exhaust slots (Pattern C detection).

    Can use pre-built merged_data to avoid re-parsing files.

    Returns:
        List of (source_file_or_part, part_name, exhaust_slotType).
    """
    results: List[Tuple[str, str, str]] = []

    if merged_data:
        # Use merged data — scan all parts for body/frame-like names
        for part_name, part_data in merged_data.items():
            if not isinstance(part_data, dict):
                continue
            # Heuristic: part names containing body/frame/chassis
            pn_lower = part_name.lower()
            if not any(kw in pn_lower for kw in ('body', 'frame', 'chassis')):
                continue
            all_slots = _get_combined_slots(part_data)
            for slot_entry in all_slots:
                if not isinstance(slot_entry, list) or len(slot_entry) < 2:
                    continue
                if _is_slot_header(slot_entry):
                    continue
                st = str(slot_entry[0])
                if 'exhaust' in st.lower():
                    results.append(("(merged)", part_name, st))
        return results

    # Fallback: parse body/frame files directly
    if _get_parser() is None:
        return results

    body_files = find_body_frame_files(base_path, vehicle_name)
    for f in body_files:
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


def trace_exhaust_chain(
    merged_data: Dict[str, Any],
    engine_part_name: str,
    base_path: Path,
    vehicle_name: str,
) -> List[ExhaustSlotInfo]:
    """Trace exhaust slot chains starting from an engine part.

    Implements find_some_exhaust_slot logic:
    1. Direct engine slots (header, exhaust, manifold, downpipe)
    2. Intermediate-hosted (intake → header → exhaust)
    3. Result includes chain path for pattern classification

    Uses merged_data for cross-file part resolution.

    Note: Pattern C (body/frame) detection is handled by classify_pattern(),
    not here — this function traces ENGINE-based chains only.
    """
    results: List[ExhaustSlotInfo] = []

    # --- Phase 1: Direct exhaust-related slots on the engine ---
    engine_exhaust_slots = find_exhaust_slots_in_part(merged_data, engine_part_name)
    all_engine_slots = find_all_child_slots(merged_data, engine_part_name)

    # Separate direct exhaust slots from header/manifold/downpipe slots
    direct_exhaust_slots = [
        (st, dv) for st, dv in engine_exhaust_slots
        if 'exhaust' in st.lower()
        and 'header' not in st.lower()
        and 'manifold' not in st.lower()
        and 'downpipe' not in st.lower()
    ]

    downstream_slots = [
        (st, dv) for st, dv in engine_exhaust_slots
        if 'header' in st.lower() or 'manifold' in st.lower()
        or 'downpipe' in st.lower()
    ]

    # Trace each downstream component (header/manifold/downpipe)
    for ds_type, ds_default in downstream_slots:
        ds_part = _find_part_by_slotType(merged_data, ds_type)
        if not ds_part:
            continue

        ds_exhaust = find_exhaust_slots_in_part(merged_data, ds_part)
        ds_nodes = _extract_part_nodes(merged_data, ds_part)
        node_names = [n['name'] for n in ds_nodes]
        node_positions = [(n['x'], n['y'], n['z']) for n in ds_nodes]

        # Check if downstream component has a final exhaust slot
        final_exhaust = [
            (st, dv) for st, dv in ds_exhaust
            if 'exhaust' in st.lower()
            and 'header' not in st.lower()
            and 'manifold' not in st.lower()
            and 'downpipe' not in st.lower()
        ]

        if final_exhaust:
            for exh_type, _ in final_exhaust:
                results.append(ExhaustSlotInfo(
                    downstream_component_name=ds_part,
                    downstream_component_slotType=ds_type,
                    exhaust_slot_type=exh_type,
                    chain_path=f"{engine_part_name} → {ds_type}[{ds_part}] → {exh_type}",
                    node_names=node_names,
                    node_positions=node_positions,
                ))
        else:
            # Header exists but has no exhaust child (leaf node — Pattern A' indicator)
            results.append(ExhaustSlotInfo(
                downstream_component_name=ds_part,
                downstream_component_slotType=ds_type,
                exhaust_slot_type="(none found)",
                chain_path=f"{engine_part_name} → {ds_type}[{ds_part}] → ???",
                node_names=node_names,
                node_positions=node_positions,
            ))

    # Record direct exhaust slots as siblings (Pattern A')
    for exh_type, _ in direct_exhaust_slots:
        results.append(ExhaustSlotInfo(
            downstream_component_name="(engine sibling)",
            downstream_component_slotType=exh_type,
            exhaust_slot_type=exh_type,
            chain_path=f"{engine_part_name} → {exh_type} (sibling slot)",
            node_names=[],
            node_positions=[],
        ))

    # --- Phase 2: Intermediate-hosted (intake → header → exhaust) ---
    if not downstream_slots:
        non_exhaust_slots = [
            (st, dv, desc) for st, dv, desc in all_engine_slots
            if not EXHAUST_SLOT_PATTERNS.search(st)
        ]

        for int_type, int_default, _ in non_exhaust_slots:
            int_part = _find_part_by_slotType(merged_data, int_type)
            if not int_part:
                continue

            # Check if intermediate part has exhaust-related child slots
            int_exhaust_slots = find_exhaust_slots_in_part(merged_data, int_part)
            for ie_type, _ in int_exhaust_slots:
                ie_part = _find_part_by_slotType(merged_data, ie_type)
                if not ie_part:
                    continue

                ie_child_exhaust = find_exhaust_slots_in_part(merged_data, ie_part)
                ie_nodes = _extract_part_nodes(merged_data, ie_part)

                final = [
                    (st, dv) for st, dv in ie_child_exhaust
                    if 'exhaust' in st.lower()
                    and 'header' not in st.lower()
                    and 'downpipe' not in st.lower()
                ]

                if final:
                    for exh_type, _ in final:
                        results.append(ExhaustSlotInfo(
                            downstream_component_name=ie_part,
                            downstream_component_slotType=ie_type,
                            exhaust_slot_type=exh_type,
                            chain_path=(
                                f"{engine_part_name} → {int_type}[{int_part}] → "
                                f"{ie_type}[{ie_part}] → {exh_type}"
                            ),
                            node_names=[n['name'] for n in ie_nodes],
                            node_positions=[(n['x'], n['y'], n['z']) for n in ie_nodes],
                        ))

            # Also check alternate parts filling the same slot (turbo variants)
            for alt_name, alt_data in merged_data.items():
                if not isinstance(alt_data, dict):
                    continue
                if alt_data.get('slotType', '') == int_type and alt_name != int_part:
                    alt_exhaust = find_exhaust_slots_in_part(merged_data, alt_name)
                    for ae_type, _ in alt_exhaust:
                        ae_part = _find_part_by_slotType(merged_data, ae_type)
                        if not ae_part:
                            continue
                        ae_child = find_exhaust_slots_in_part(merged_data, ae_part)
                        ae_nodes = _extract_part_nodes(merged_data, ae_part)
                        ae_final = [
                            (st, dv) for st, dv in ae_child
                            if 'exhaust' in st.lower()
                        ]
                        if ae_final:
                            for exh_type, _ in ae_final:
                                results.append(ExhaustSlotInfo(
                                    downstream_component_name=ae_part,
                                    downstream_component_slotType=ae_type,
                                    exhaust_slot_type=exh_type,
                                    chain_path=(
                                        f"{engine_part_name} → {int_type}[{alt_name}] → "
                                        f"{ae_type}[{ae_part}] → {exh_type}"
                                    ),
                                    node_names=[n['name'] for n in ae_nodes],
                                    node_positions=[(n['x'], n['y'], n['z']) for n in ae_nodes],
                                ))

    return results


# =========================================================================
# Pattern Classification
# =========================================================================

def classify_pattern(
    chains: List[ExhaustSlotInfo],
    base_path: Path,
    vehicle_name: str,
    merged_data: Dict[str, Any],
    engine_part: str,
) -> str:
    """Classify the exhaust architecture pattern.

    Patterns:
      A  — engine → header/manifold → exhaust (header hosts exhaust slot)
      A' — engine has sibling exhaust slot directly (header is leaf)
      B  — engine → intake/turbo → header/downpipe → exhaust
      C  — body/frame hosts exhaust slot (decoupled from engine chain)
      no_exhaust — no exhaust system found anywhere
    """
    body_exhaust = find_body_frame_exhaust_slots(
        base_path, vehicle_name, merged_data=merged_data
    )

    if not chains:
        if body_exhaust:
            return "C"
        return "no_exhaust"

    # Check if any chain has a real exhaust slot (not "(none found)")
    has_real_exhaust = any(
        c.exhaust_slot_type != "(none found)" for c in chains
    )

    # If chains exist but none reach an exhaust slot, check body/frame
    if not has_real_exhaust and body_exhaust:
        return "C"

    # Check chain paths for pattern indicators
    for chain in chains:
        path_lower = chain.chain_path.lower()
        if 'sibling' in path_lower:
            return "A'"
        if 'intake' in path_lower or 'turbo' in path_lower:
            return "B"

    # Check if engine has both header AND sibling exhaust (A' indicator)
    all_engine_slots = find_all_child_slots(merged_data, engine_part)
    has_sibling_exhaust = any(
        'exhaust' in st.lower()
        and 'header' not in st.lower()
        and 'manifold' not in st.lower()
        for st, _, _ in all_engine_slots
    )
    has_header = any(
        'header' in st.lower() or 'manifold' in st.lower()
        for st, _, _ in all_engine_slots
    )

    if has_sibling_exhaust and has_header:
        return "A'"

    return "A"


# =========================================================================
# Engine Profiling
# =========================================================================

def _is_primary_engine_part(part_data: Dict[str, Any]) -> bool:
    """Check if a part represents a primary engine (not internals/mounts/mesh)."""
    if 'mainEngine' in part_data:
        return True

    slot_type = part_data.get('slotType', '')
    if not slot_type:
        return False

    st_lower = slot_type.lower()
    if 'engine' not in st_lower:
        return False

    exclude_keywords = ('management', 'internals', 'mount', 'mesh',
                        'accessory', 'accessories', 'cover', 'block')
    return not any(kw in st_lower for kw in exclude_keywords)


def profile_vehicle_exhausts(
    base_path: Path,
    vehicle_name: str,
    family_prefix: Optional[str] = None,
) -> List[EngineExhaustProfile]:
    """Build complete exhaust profiles for all engines in a vehicle.

    Uses cross-file merged data so chain tracing works across jbeam files.

    For family-shared architectures, pass family_prefix to search the
    family's common folder (e.g. family_prefix='etk' for etk800).

    Returns:
        List of EngineExhaustProfile, one per primary engine part.
    """
    if _get_parser() is None:
        logger.error("JBeamParser not available")
        return []

    engine_files = find_engine_files(base_path, vehicle_name, family_prefix)
    exhaust_files = find_exhaust_files(base_path, vehicle_name, family_prefix)

    if not engine_files:
        logger.warning(f"No engine files found for {vehicle_name}")
        return []

    merged_data = build_merged_vehicle_data(
        base_path, vehicle_name, engine_files, exhaust_files, family_prefix
    )

    profiles: List[EngineExhaustProfile] = []

    for engine_file in engine_files:
        try:
            parsed = JBeamParser.parse_jbeam(engine_file)
        except Exception as e:
            logger.warning(f"Error parsing {engine_file.name}: {e}")
            continue

        if not parsed:
            continue

        all_exhaust_nodes = extract_isExhaust_nodes(parsed, str(engine_file))

        for part_name, part_data in parsed.items():
            if not isinstance(part_data, dict):
                continue
            if not _is_primary_engine_part(part_data):
                continue

            engine_exhaust_nodes = all_exhaust_nodes.get(part_name, [])

            # Filter to engine_block group
            engine_block_nodes = [
                n for n in engine_exhaust_nodes
                if 'engine' in n.group.lower()
                or 'block' in n.group.lower()
                or n.group == ''
            ]

            exhaust_chains = trace_exhaust_chain(
                merged_data, part_name, base_path, vehicle_name
            )

            pattern = classify_pattern(
                exhaust_chains, base_path, vehicle_name, merged_data, part_name
            )

            notes: List[str] = []
            if len(engine_exhaust_nodes) > 2:
                notes.append(
                    f"FILTERED: {len(engine_exhaust_nodes)} isExhaust total "
                    f"(>2, likely complex/race engine)"
                )

            profiles.append(EngineExhaustProfile(
                engine_file=str(engine_file.name),
                engine_name=part_name,
                is_exhaust_count=len(engine_block_nodes),
                is_exhaust_nodes=engine_block_nodes,
                exhaust_slots=exhaust_chains,
                pattern=pattern,
                notes=notes,
            ))

    return profiles


# =========================================================================
# Candidate Classification & Strategy Selection
# =========================================================================

def classify_candidates(
    profiles: List[EngineExhaustProfile],
    donor_count: int,
) -> Tuple[List[EngineExhaustProfile], List[EngineExhaustProfile]]:
    """Classify engine profiles into matching vs mismatch candidates.

    Args:
        profiles: All engine exhaust profiles for the target vehicle.
        donor_count: Number of isExhaust nodes in the adapted Camso engine.

    Returns:
        (matching_candidates, mismatch_candidates)
        - matching: target isExhaust count == donor_count
        - mismatch: target isExhaust count ≠ donor_count (but ≤2)
    """
    matching: List[EngineExhaustProfile] = []
    mismatch: List[EngineExhaustProfile] = []

    for profile in profiles:
        if profile.is_exhaust_count == 0:
            continue  # no isExhaust nodes at all — skip
        if profile.is_exhaust_count > 2:
            continue  # complex/race engine — skip
        if profile.pattern == 'no_exhaust':
            continue  # no exhaust system found — skip

        if profile.is_exhaust_count == donor_count:
            matching.append(profile)
        else:
            mismatch.append(profile)

    return matching, mismatch


def _select_best_candidate(
    candidates: List[EngineExhaustProfile],
) -> EngineExhaustProfile:
    """Select the best candidate from a list of profiles.

    Preference order:
    1. Profiles with real exhaust slot found (not "(none found)")
    2. Among those, prefer pattern A > A' > B > C
    3. If tied, prefer first encountered
    """
    pattern_priority = {'A': 0, "A'": 1, 'B': 2, 'C': 3, 'no_exhaust': 4}

    def sort_key(p: EngineExhaustProfile) -> Tuple[int, int, str]:
        has_real = any(
            s.exhaust_slot_type != "(none found)" for s in p.exhaust_slots
        )
        return (
            0 if has_real else 1,
            pattern_priority.get(p.pattern, 99),
            p.engine_name,
        )

    return sorted(candidates, key=sort_key)[0]


def _get_exhaust_slot_type(profile: EngineExhaustProfile) -> Optional[str]:
    """Extract the downstream exhaust slotType from a profile."""
    for slot_info in profile.exhaust_slots:
        if slot_info.exhaust_slot_type != "(none found)":
            return slot_info.exhaust_slot_type
    return None


def _find_bridge_nodes_in_engine_ecosystem(
    merged_data: Dict[str, Any],
    engine_part_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
    """Search engine child parts for exhaust manifold bridge nodes (exm*).

    For A' Direct patterns where bridge nodes live in intake/turbo sub-parts
    rather than in header/exhaust parts. This is common for ETK, miramar,
    scintilla V10, sunburst2, and other vehicles where the exhaust manifold
    node is bundled into the intake slot.

    Args:
        merged_data: Cross-file parsed data.
        engine_part_name: Engine part to search children of.

    Returns:
        (bridge_nodes, beam_props, source_part_name)
        - bridge_nodes: Nodes matching exm* pattern, or empty list.
        - beam_props: Beam properties from the source part.
        - source_part_name: Part that defined the nodes, or None.
    """
    engine_slots = find_all_child_slots(merged_data, engine_part_name)

    for slot_type, _, _ in engine_slots:
        # Skip exhaust-related slots (already handled by standard path)
        if EXHAUST_SLOT_PATTERNS.search(slot_type):
            continue

        # Check all parts that fill this slot type
        for part_name, part_data in merged_data.items():
            if not isinstance(part_data, dict):
                continue
            if part_data.get('slotType', '') != slot_type:
                continue

            all_nodes = _extract_part_nodes_full(merged_data, part_name)
            bridge_nodes = [
                n for n in all_nodes
                if _BRIDGE_NODE_PATTERN.match(n['name'])
            ]

            if bridge_nodes:
                beam_props = _extract_beam_properties_from_part(
                    merged_data, part_name
                )
                logger.info(
                    "  [EXH] Found bridge nodes %s in engine ecosystem "
                    "part '%s' (slotType '%s')",
                    [n['name'] for n in bridge_nodes], part_name, slot_type,
                )
                return bridge_nodes, beam_props, part_name

    return [], {}, None


def _get_best_exhaust_slot_info(
    profile: EngineExhaustProfile,
) -> Optional[ExhaustSlotInfo]:
    """Get the ExhaustSlotInfo with a real exhaust slot from a profile.

    Prefers chains that have actual downstream nodes (Pattern A/B)
    over sibling chains (Pattern A') which have empty node lists.
    """
    real_chains = [
        s for s in profile.exhaust_slots
        if s.exhaust_slot_type != "(none found)"
    ]
    if not real_chains:
        return None

    # Prefer chains with nodes (these are from actual downstream components)
    with_nodes = [c for c in real_chains if c.node_names]
    if with_nodes:
        return with_nodes[0]
    return real_chains[0]


# =========================================================================
# Phase 2 — Exhaust Component Generation
# =========================================================================

# Audio properties to preserve on adapted exhaust nodes
_AUDIO_PROPS = frozenset({
    'afterFireAudioCoef', 'afterFireVisualCoef', 'afterFireVolumeCoef',
    'afterFireMufflingCoef', 'exhaustAudioMufflingCoef',
    'exhaustAudioGainChange',
})

# Default beam properties when candidate header beams are unavailable
_DEFAULT_BEAM_PROPS = {
    'beamSpring': 5010000,
    'beamDamp': 90,
    'beamDeform': 90000,
    'beamStrength': "FLT_MAX",
}

# Upper limit for beamSpring in exhaust adapter beams.
# Target exhaust parts sometimes carry very high beamSpring values that cause
# instant beam breakage on load. This limit keeps the value in a sane range
# while still borrowing from the target when the value is reasonable.
_MAX_BEAM_SPRING = 1616333


def _extract_part_nodes_full(
    parsed_data: Dict[str, Any],
    part_name: str,
) -> List[Dict[str, Any]]:
    """Extract nodes from a part with full inline properties.

    Unlike _extract_part_nodes(), this preserves inline property dicts
    (audio coefficients, isExhaust, etc.) needed for component generation.

    Returns:
        List of dicts: {name, x, y, z, props: {}} where props holds any
        inline dict properties from the node row.
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return []

    nodes_section = part_data.get('nodes', [])
    if not isinstance(nodes_section, list):
        return []

    nodes = []
    for item in nodes_section:
        if not isinstance(item, list) or len(item) < 4:
            continue
        if isinstance(item[0], str) and item[0] in ('id', 'id1', 'id2'):
            continue

        try:
            name = str(item[0]).rstrip(',').strip('"')
            x = float(item[1])
            y = float(item[2])
            z = float(item[3]) if not isinstance(item[3], dict) else 0.0
        except (TypeError, ValueError):
            continue

        # Collect inline properties from any dict items in the row
        props: Dict[str, Any] = {}
        for el in item[3:]:
            if isinstance(el, dict):
                props.update(el)

        nodes.append({'name': name, 'x': x, 'y': y, 'z': z, 'props': props})

    return nodes


def _extract_beam_properties_from_part(
    parsed_data: Dict[str, Any],
    part_name: str,
) -> Dict[str, Any]:
    """Extract beam modifier properties from a downstream exhaust component.

    Scans the beams section for property modifier rows (dicts with beamSpring etc).
    Uses the FIRST modifier row found, since headers consistently set their beam
    properties at the top of the beams section.

    Falls back to _DEFAULT_BEAM_PROPS if no modifier is found.
    """
    part_data = parsed_data.get(part_name, {})
    if not isinstance(part_data, dict):
        return dict(_DEFAULT_BEAM_PROPS)

    beams_section = part_data.get('beams', [])
    if not isinstance(beams_section, list):
        return dict(_DEFAULT_BEAM_PROPS)

    for item in beams_section:
        if isinstance(item, dict) and 'beamSpring' in item:
            result = dict(_DEFAULT_BEAM_PROPS)
            for key in ('beamSpring', 'beamDamp', 'beamDeform', 'beamStrength'):
                if key in item:
                    result[key] = item[key]
            # Clamp beamSpring to prevent instant beam breakage on load
            if isinstance(result['beamSpring'], (int, float)) and result['beamSpring'] > _MAX_BEAM_SPRING:
                logger.warning(
                    "  [EXH] Clamped beamSpring %s -> %s (max limit)",
                    result['beamSpring'], _MAX_BEAM_SPRING,
                )
                result['beamSpring'] = _MAX_BEAM_SPRING
            return result

    return dict(_DEFAULT_BEAM_PROPS)


def _euclidean_distance(
    pos_a: Tuple[float, float, float],
    pos_b: Tuple[float, float, float],
) -> float:
    """Euclidean distance between two 3D positions."""
    return math.sqrt(
        (pos_a[0] - pos_b[0]) ** 2 +
        (pos_a[1] - pos_b[1]) ** 2 +
        (pos_a[2] - pos_b[2]) ** 2,
    )


def generate_adapted_nodes(
    downstream_nodes: List[Dict[str, Any]],
) -> List[List[Any]]:
    """Generate adapted exhaust component node rows from candidate downstream nodes.

    Copies node names and positions from the downstream_exhaust_component
    (header/manifold). Overrides nodeWeight, collision, group. Preserves
    audio properties (afterFireAudioCoef, exhaustAudioMufflingCoef, etc).

    Returns:
        List of jbeam node rows ready for insertion into the part's nodes section.
        First row is the header: ["id", "posX", "posY", "posZ"].
    """
    rows: List[List[Any]] = [["id", "posX", "posY", "posZ"]]

    if not downstream_nodes:
        return rows

    # Node property modifiers — separate rows per BeamNG convention
    rows.append({"selfCollision": False})
    rows.append({"collision": False})
    rows.append({"frictionCoef": 0.5})
    rows.append({"nodeMaterial": "|NM_METAL"})
    rows.append({"nodeWeight": 4.5})
    rows.append({"group": "exhaust_adapter"})

    for node in downstream_nodes:
        row: List[Any] = [node['name'], node['x'], node['y'], node['z']]

        # Preserve audio properties inline
        audio_props: Dict[str, Any] = {}
        for key, val in node.get('props', {}).items():
            if key in _AUDIO_PROPS:
                audio_props[key] = val

        if audio_props:
            row.append(audio_props)

        rows.append(row)

    # Trailing group reset — prevents group leaking to subsequent sections
    rows.append({"group": "none"})

    return rows


def generate_structural_beams(
    downstream_nodes: List[Dict[str, Any]],
    engine_nodes: List[IsExhaustNode],
    beam_props: Dict[str, Any],
) -> List[List[Any]]:
    """Generate structural beams anchoring adapted exhaust nodes to the engine.

    Each adapted_exhaust_component node is connected to every engine_block
    node that does NOT carry isExhaust. This physically anchors the exhaust
    bridge to the engine without interfering with the thermal/sound path.

    Args:
        downstream_nodes: Nodes from the candidate downstream component.
        engine_nodes: All engine isExhaust nodes (used to EXCLUDE from targets).
        beam_props: Beam properties dict (beamSpring, beamDamp, beamDeform, beamStrength).

    Returns:
        List of jbeam beam rows including header, modifier, and beam entries.
    """
    rows: List[List[Any]] = [["id1:", "id2:"]]

    # Beam property modifiers — separate rows per BeamNG convention
    rows.append({"deformLimitExpansion": 1.2})
    rows.append({
        "beamPrecompression": 1,
        "beamType": "|NORMAL",
        "beamLongBound": 1.0,
        "beamShortBound": 1.0,
    })
    rows.append({
        "beamSpring": min(beam_props.get("beamSpring", _DEFAULT_BEAM_PROPS['beamSpring']), _MAX_BEAM_SPRING),
        "beamDamp": beam_props.get("beamDamp", 130.43),
    })
    rows.append({
        "beamDeform": beam_props.get("beamDeform", 90000),
        "beamStrength": beam_props.get("beamStrength", "FLT_MAX"),
    })

    # Determine non-isExhaust engine nodes (for structural connections)
    # Use BeamNG standard engine cube node names, excluding those that carry isExhaust
    is_exhaust_names = {n.name for n in engine_nodes}
    all_engine_cube_names = ['e1l', 'e1r', 'e2l', 'e2r', 'e3l', 'e3r', 'e4l', 'e4r']
    structural_targets = [n for n in all_engine_cube_names if n not in is_exhaust_names]

    if not structural_targets:
        # Fallback: if all 8 nodes are isExhaust (shouldn't happen), use bottom 4
        structural_targets = ['e1l', 'e1r', 'e2l', 'e2r']

    for ds_node in downstream_nodes:
        for eng_node in structural_targets:
            rows.append([ds_node['name'], eng_node])

    return rows


def generate_matching_isExhaust_beams(
    donor_nodes: List[IsExhaustNode],
    downstream_nodes: List[Dict[str, Any]],
) -> List[List[Any]]:
    """Generate isExhaust beams for matching strategy (same count donor ↔ target).

    Single isExhaust (1↔1):
        One beam from engine isExhaust node → adapted node.

    Dual isExhaust (2↔2):
        Distance-paired: each engine isExhaust node connects to its closest
        adapted node. Each connection consumes both nodes — no duplicates.

    Returns:
        List of jbeam beam rows with isExhaust properties.
    """
    rows: List[List[Any]] = []

    if not donor_nodes or not downstream_nodes:
        return rows

    count = len(donor_nodes)
    ds_positions = [
        (n['name'], (n['x'], n['y'], n['z'])) for n in downstream_nodes
    ]

    if count == 1:
        # 1↔1: direct connection to first downstream node
        rows.append([
            donor_nodes[0].name,
            ds_positions[0][0],
            {"isExhaust": "mainEngine"},
        ])
    elif count == 2 and len(ds_positions) >= 2:
        # 2↔2: distance-paired matching
        # Calculate all pairings and pick the one with minimum total distance
        donor_positions = [
            (n.name, (n.x, n.y, n.z)) for n in donor_nodes
        ]

        # Pairing A: donor[0]→ds[0], donor[1]→ds[1]
        dist_a = (
            _euclidean_distance(donor_positions[0][1], ds_positions[0][1]) +
            _euclidean_distance(donor_positions[1][1], ds_positions[1][1])
        )
        # Pairing B: donor[0]→ds[1], donor[1]→ds[0]
        dist_b = (
            _euclidean_distance(donor_positions[0][1], ds_positions[1][1]) +
            _euclidean_distance(donor_positions[1][1], ds_positions[0][1])
        )

        if dist_a <= dist_b:
            pairs = [(0, 0), (1, 1)]
        else:
            pairs = [(0, 1), (1, 0)]

        for di, dsi in pairs:
            rows.append([
                donor_positions[di][0],
                ds_positions[dsi][0],
                {"isExhaust": "mainEngine"},
            ])
    else:
        # Fallback for unexpected counts: connect first to first
        rows.append([
            donor_nodes[0].name,
            ds_positions[0][0],
            {"isExhaust": "mainEngine"},
        ])

    return rows


def generate_mismatch_isExhaust_beams(
    donor_nodes: List[IsExhaustNode],
    downstream_nodes: List[Dict[str, Any]],
) -> List[List[Any]]:
    """Generate isExhaust beams for mismatch strategy (Y-pipe / splitter).

    All donor isExhaust nodes connect to ALL adapted nodes.
    Each beam gets {"isExhaust":"mainEngine"}.

    Returns:
        List of jbeam beam rows for Y-pipe wiring.
    """
    rows: List[List[Any]] = []

    for donor_node in donor_nodes:
        for ds_node in downstream_nodes:
            rows.append([
                donor_node.name,
                ds_node['name'],
                {"isExhaust": "mainEngine"},
            ])

    return rows


def generate_slot_entry(
    vehicle_name: str,
    exhaust_slot_type: str,
) -> List[Any]:
    """Generate the slot entry to inject into the adapted engine's slots array.

    Returns:
        Legacy slots format entry:
        ["<vehicle>_exhaust_adapter", "<vehicle>_exhaust_adapter",
         "Exhaust Adapter", {"coreSlot": true}]
    """
    slot_name = f"{vehicle_name}_exhaust_adapter"
    return [
        slot_name,
        slot_name,
        "Exhaust Adapter",
        {"coreSlot": True},
    ]


def generate_adapted_exhaust_component(
    vehicle_name: str,
    strategy: str,
    donor_nodes: List[IsExhaustNode],
    candidate_profile: EngineExhaustProfile,
    merged_data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[List[Any]], List[str]]:
    """Generate the complete adapted_exhaust_component jbeam part.

    Orchestrates node copying, beam generation, and slot creation based on
    the selected strategy (matching/mismatch).

    Args:
        vehicle_name: Target vehicle name (e.g. "pickup").
        strategy: "matching" or "mismatch".
        donor_nodes: Donor engine isExhaust nodes (post-TMS, with BeamNG names).
        candidate_profile: Selected target engine profile.
        merged_data: Cross-file merged vehicle parsed data.

    Returns:
        (adapted_part_dict, slot_entry, warnings)
        - adapted_part_dict: Complete jbeam part dict, or None on failure.
        - slot_entry: Slot array entry for engine injection, or None on failure.
        - warnings: Any warnings generated during component creation.
    """
    warnings: List[str] = []

    # Find the best ExhaustSlotInfo from the candidate profile
    slot_info = _get_best_exhaust_slot_info(candidate_profile)
    if not slot_info:
        warnings.append("No exhaust slot chain found on candidate engine")
        return None, None, warnings

    exhaust_slot_type = slot_info.exhaust_slot_type

    # --- Determine downstream component and extract its data ---
    ds_component_name = slot_info.downstream_component_name

    # For Pattern A' — engine sibling exhaust slot, the downstream component
    # is actually a header (leaf) which may have nodes from a separate chain.
    # Use the first chain with nodes if available.
    if ds_component_name == "(engine sibling)":
        # A' pattern — look for a header chain that has nodes
        for chain in candidate_profile.exhaust_slots:
            if chain.node_names and chain.downstream_component_name != "(engine sibling)":
                ds_component_name = chain.downstream_component_name
                break

    # Extract downstream component nodes with full properties
    downstream_nodes = _extract_part_nodes_full(merged_data, ds_component_name)

    if not downstream_nodes:
        # A' Direct fallback — bridge nodes may be in intake/turbo sub-parts
        bridge_nodes, eco_beam_props, eco_part = (
            _find_bridge_nodes_in_engine_ecosystem(
                merged_data, candidate_profile.engine_name,
            )
        )
        if bridge_nodes:
            downstream_nodes = bridge_nodes
            ds_component_name = eco_part
        else:
            warnings.append(
                f"No nodes found in downstream component "
                f"'{ds_component_name}' or engine ecosystem -- "
                f"exhaust_adapter will have no bridge nodes"
            )
            return None, None, warnings

    # Extract beam properties from downstream component
    beam_props = _extract_beam_properties_from_part(merged_data, ds_component_name)

    # --- Generate nodes ---
    adapted_nodes = generate_adapted_nodes(downstream_nodes)

    # --- Generate structural beams ---
    structural_beams = generate_structural_beams(
        downstream_nodes, donor_nodes, beam_props,
    )

    # --- Generate isExhaust beams ---
    if strategy == "matching":
        is_exhaust_beams = generate_matching_isExhaust_beams(
            donor_nodes, downstream_nodes,
        )
    elif strategy == "mismatch":
        is_exhaust_beams = generate_mismatch_isExhaust_beams(
            donor_nodes, downstream_nodes,
        )
    else:
        warnings.append(f"Unsupported strategy '{strategy}' for beam generation")
        is_exhaust_beams = []

    if not is_exhaust_beams:
        warnings.append("No isExhaust beams generated")

    # --- Combine beams: structural + isExhaust + trailing reset ---
    all_beams = list(structural_beams)  # includes header + modifiers
    # Add isExhaust beams (these get their own implicit property from inline dict)
    all_beams.extend(is_exhaust_beams)
    # Trailing beam property reset — after ALL beams (structural + isExhaust)
    all_beams.append({
        "beamPrecompression": 1,
        "beamType": "|NORMAL",
        "beamLongBound": 1.0,
        "beamShortBound": 1.0,
    })

    # --- Build exhaust slot for the adapted component to host ---
    # This is the child slot that loads the target vehicle's exhaust pipes
    child_exhaust_slot = [
        exhaust_slot_type,
        exhaust_slot_type,
        "Exhaust",
    ]

    # --- Build the complete part dict ---
    part_name = f"{vehicle_name}_exhaust_adapter"
    part_dict = {
        "information": {
            "authors": "BeamNGCommunity",
            "name": "Exhaust Adapter",
            "value": 200,
        },
        "slotType": f"{vehicle_name}_exhaust_adapter",
        "slots": [
            ["type", "default", "description"],
            child_exhaust_slot,
        ],
        "nodes": adapted_nodes,
        "beams": all_beams,
    }

    # --- Generate the slot entry for injection into engine ---
    slot_entry = generate_slot_entry(vehicle_name, exhaust_slot_type)

    logger.info(
        f"  [EXH] Generated {part_name}: "
        f"{len(downstream_nodes)} nodes, "
        f"{len(structural_beams) - 5} structural beams, "  # -5 for header+4 modifiers
        f"{len(is_exhaust_beams)} isExhaust beams, "
        f"hosts slot '{exhaust_slot_type}'"
    )

    return {part_name: part_dict}, slot_entry, warnings


def select_strategy(
    base_path: Path,
    vehicle_name: str,
    donor_isExhaust_count: int,
    donor_isExhaust_nodes: Optional[List[IsExhaustNode]] = None,
    family_prefix: Optional[str] = None,
) -> ExhaustSolverResult:
    """Run the full exhaust solver pipeline: strategy selection + component generation.

    Steps:
    1. Profile all target vehicle engines
    2. Classify into matching/mismatch candidates
    3. Select best candidate and strategy
    4. Generate adapted_exhaust_component (if donor nodes provided)

    Args:
        base_path: Path to SteamLibrary_content_vehicles/
        vehicle_name: Target vehicle name (e.g., "pickup")
        donor_isExhaust_count: Number of isExhaust nodes in adapted Camso engine
        donor_isExhaust_nodes: Donor isExhaust nodes (with BeamNG names, post-TMS).
            Required for Phase 2 component generation. If None, returns strategy
            selection only (Phase 1 behavior).
        family_prefix: Optional family prefix for family-shared architectures
            (e.g., 'etk' for etk800). When provided, file discovery also searches
            common/vehicles/common/{family_prefix}/.

    Returns:
        ExhaustSolverResult with strategy, candidate info, and generated component.
    """
    warnings: List[str] = []

    # Step 1: Profile target vehicle
    profiles = profile_vehicle_exhausts(base_path, vehicle_name, family_prefix)

    if not profiles:
        warnings.append(f"No engine profiles found for {vehicle_name}")
        return ExhaustSolverResult(
            strategy="no_exhaust",
            adapted_part=None,
            exhaust_slot_entry=None,
            target_exhaust_slot_type=None,
            candidate_engine=None,
            candidate_profile=None,
            donor_isExhaust_count=donor_isExhaust_count,
            target_isExhaust_count=0,
            pattern="no_exhaust",
            warnings=warnings,
        )

    # Step 2: Classify
    matching, mismatch = classify_candidates(profiles, donor_isExhaust_count)

    # Step 3: Select strategy
    if matching:
        strategy = "matching"
        candidate = _select_best_candidate(matching)
    elif mismatch:
        strategy = "mismatch"
        candidate = _select_best_candidate(mismatch)
    else:
        # All engines either have 0 isExhaust or >2 or no_exhaust
        strategy = "no_exhaust"
        warnings.append("No viable exhaust candidates found")
        return ExhaustSolverResult(
            strategy="no_exhaust",
            adapted_part=None,
            exhaust_slot_entry=None,
            target_exhaust_slot_type=None,
            candidate_engine=None,
            candidate_profile=None,
            donor_isExhaust_count=donor_isExhaust_count,
            target_isExhaust_count=0,
            pattern="no_exhaust",
            warnings=warnings,
        )

    exhaust_slot_type = _get_exhaust_slot_type(candidate)

    logger.info(
        f"  [EXH] Strategy: {strategy} | "
        f"Candidate: {candidate.engine_name} | "
        f"Pattern: {candidate.pattern} | "
        f"Donor: {donor_isExhaust_count}, Target: {candidate.is_exhaust_count} | "
        f"Exhaust slot: {exhaust_slot_type}"
    )

    # Step 4: Generate adapted_exhaust_component (Phase 2)
    adapted_part = None
    exhaust_slot_entry = None

    if donor_isExhaust_nodes and strategy in ("matching", "mismatch"):
        # Rebuild merged data for component generation
        engine_files = find_engine_files(base_path, vehicle_name, family_prefix)
        exhaust_files = find_exhaust_files(base_path, vehicle_name, family_prefix)
        merged_data = build_merged_vehicle_data(
            base_path, vehicle_name, engine_files, exhaust_files, family_prefix,
        )

        adapted_part, exhaust_slot_entry, gen_warnings = (
            generate_adapted_exhaust_component(
                vehicle_name=vehicle_name,
                strategy=strategy,
                donor_nodes=donor_isExhaust_nodes,
                candidate_profile=candidate,
                merged_data=merged_data,
            )
        )
        warnings.extend(gen_warnings)

    return ExhaustSolverResult(
        strategy=strategy,
        adapted_part=adapted_part,
        exhaust_slot_entry=exhaust_slot_entry,
        target_exhaust_slot_type=exhaust_slot_type,
        candidate_engine=candidate.engine_name,
        candidate_profile=candidate,
        donor_isExhaust_count=donor_isExhaust_count,
        target_isExhaust_count=candidate.is_exhaust_count,
        pattern=candidate.pattern,
        warnings=warnings,
    )


# =========================================================================
# Module availability flag for engineswap.py
# =========================================================================
# Use a property-like check: parser is available once _get_parser() succeeds.
# At import time PARSER_AVAILABLE may still be False (lazy); callers should
# invoke _get_parser() or check PARSER_AVAILABLE after first use.
EXHAUST_SOLVER_AVAILABLE = True  # import itself succeeded; parser resolved lazily
