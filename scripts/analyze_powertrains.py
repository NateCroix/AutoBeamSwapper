#!/usr/bin/env python3
"""
BeamNG Powertrain Array Extraction & Analysis Tool

Comprehensive extraction of "powertrain": arrays from all BeamNG original vehicle
assets (transmission, transfercase, and transaxle files), producing structured
data for programmatic lookup and manipulation.

Resolves complete drivetrain chains from transmission to wheels by following
slot references across vehicle-specific and common folders, including
driveshaft, differential, halfshaft, and transfer case connections.

Uses the project's proven JBeamParser for reliable .jbeam parsing (98.6% success rate).

Outputs:
  - powertrain_report.json    : Full structured data with property lookup
  - powertrain_report.md      : Human-readable report
  - powertrain_table.csv      : Flat CSV for tabular analysis
  - powertrain_properties.json: Property {} objects for each asset (for lookup)
  - non_transfercase_chains.md: Analysis of vehicles without transfer cases
  - architecture_diagrams.md  : Mermaid diagrams of drivetrain architectures

Usage:
  python analyze_powertrains.py              # Full analysis of all vehicles
  python analyze_powertrains.py -v burnside  # Targeted single-vehicle analysis
  python analyze_powertrains.py -o simple_traffic # Output summary table for simple_traffic vehicle assets only


Author: BeamNG Modding Project
"""

import json
import re
import sys
import csv
import io
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Set
from collections import defaultdict, Counter
from dataclasses import dataclass, field
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# JBeam Parser (from engineswap.py - proven 98.6% success rate)
# =============================================================================

class JBeamParser:
    """
    Parser for BeamNG .jbeam files with lenient JSON parsing.
    Uses URL-safe placeholder protection strategy.
    """

    # Class-level cache for parsed files to avoid re-parsing
    _cache: Dict[str, Optional[Dict[str, Any]]] = {}

    @staticmethod
    def strip_comments(content: str) -> str:
        """Remove comments while preserving URL schemes."""
        content = content.replace('https://', '<<<HTTPS_SCHEME>>>')
        content = content.replace('http://', '<<<HTTP_SCHEME>>>')
        content = content.replace('file://', '<<<FILE_SCHEME>>>')
        content = content.replace('local://', '<<<LOCAL_SCHEME>>>')
        # Negative lookbehind prevents //** from being treated as block comment start
        content = re.sub(r'(?<!/)/\*[\s\S]*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = content.replace('<<<HTTPS_SCHEME>>>', 'https://')
        content = content.replace('<<<HTTP_SCHEME>>>', 'http://')
        content = content.replace('<<<FILE_SCHEME>>>', 'file://')
        content = content.replace('<<<LOCAL_SCHEME>>>', 'local://')
        return content

    @staticmethod
    def add_missing_commas(content: str) -> str:
        """Add missing commas between JSON elements."""
        content = re.sub(r'(\]|})\s*?(\{|\[)', r'\1,\2', content)
        content = re.sub(r'(}|])\s*"', r'\1,"', content)
        content = re.sub(r'"{', r'", {', content)
        content = re.sub(r'"\s+("|\{)', r'",\1', content)
        content = re.sub(r'(false|true)\s+"', r'\1,"', content)
        content = re.sub(r',\s*,', r',', content)
        content = re.sub(r'("[a-zA-Z0-9_]*")\s(-?[0-9\[])', r'\1, \2', content)
        content = re.sub(r'(\d\.*\d*)\s*{', r'\1, {', content)
        content = re.sub(r'([0-9])\n', r'\1,\n', content)
        content = re.sub(r'(-?[0-9])\s+(-?[0-9])', r'\1,\2', content)
        content = re.sub(r'([0-9])\s*("[a-zA-Z0-9_]*")', r'\1, \2', content)
        content = re.sub(r'("[a-zA-Z0-9_$.]*")\s*("[a-zA-Z0-9_$.]*")', r'\1, \2', content)
        content = re.sub(
            r'("[a-zA-Z0-9_]+"):(\s*"[a-zA-Z0-9_]+:)(\n\s*"[a-zA-Z]+")',
            r'\1:\2",\n\3', content)
        content = re.sub(r':(false|true)("[a-zA-Z_]+")', r':\1, \2', content)
        content = re.sub(r'(["[a-zA-Z_0-9.?]+")\s(\["[a-zA-Z_]+"\]])', r'\1, \2', content)
        content = re.sub(r'("[a-zA-Z0-9]+"):(-?[0-9])\.,\s?"', r'\1:\2.0,"', content)
        content = re.sub(r':0+([0-9])', r':\1', content)
        content = re.sub(r'([,\[])0+([1-9])', r'\1\2', content)
        # Pattern 18: Strip explicit positive signs (+9 -> 9, +10.5 -> 10.5)
        # JSON does not allow leading '+' on numbers
        content = re.sub(r'([,\[:\s])\+(\d)', r'\1\2', content)
        return content

    @staticmethod
    def remove_trailing_commas(content: str) -> str:
        """Remove trailing commas before closing brackets/braces."""
        lines = content.split('\n')
        result_lines = []
        for line in lines:
            if ',,' in line: line = line.replace(',,', ',')
            if '[,' in line: line = line.replace('[,', '[')
            if '{,' in line: line = line.replace('{,', '{')
            if ',:' in line: line = line.replace(',:', ':')
            if ',}' in line: line = line.replace(',}', '}')
            if ',]' in line: line = line.replace(',]', ']')
            result_lines.append(line)
        content = '\n'.join(result_lines)
        content = re.sub(r',\s*?(]|})', r'\1', content)
        if content.rstrip().endswith(','):
            content = content.rstrip()[:-1]
        if content.count('{') != content.count('}'):
            if content.rstrip().endswith('}'):
                content = content.rstrip()[:-1]
        return content

    @classmethod
    def parse_jbeam(cls, file_path: Path, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Parse a .jbeam file and return its contents as a dictionary."""
        cache_key = str(file_path)
        if use_cache and cache_key in cls._cache:
            return cls._cache[cache_key]

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            content = cls.strip_comments(content)
            content = cls.add_missing_commas(content)
            content = cls.remove_trailing_commas(content)
            data = json.loads(content)
            if use_cache:
                cls._cache[cache_key] = data
            return data
        except json.JSONDecodeError as e:
            logger.debug(f"Parse error in {file_path.name}: {e}")
            if use_cache:
                cls._cache[cache_key] = None
            return None
        except Exception as e:
            logger.debug(f"Error reading {file_path.name}: {e}")
            if use_cache:
                cls._cache[cache_key] = None
            return None

    @classmethod
    def clear_cache(cls):
        """Clear the parse cache."""
        cls._cache.clear()


# =============================================================================
# Raw Comment Extractor
# =============================================================================

def extract_raw_powertrain_section(file_path: Path) -> Optional[str]:
    """
    Extract the raw text of the "powertrain" section from a .jbeam file,
    preserving comments. Uses bracket-matching to find section boundaries.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return None

    # Find all "powertrain" sections (there may be multiple parts in one file)
    sections = []
    search_start = 0
    while True:
        idx = content.find('"powertrain"', search_start)
        if idx == -1:
            break

        # Find the opening bracket
        bracket_start = content.find('[', idx)
        if bracket_start == -1:
            search_start = idx + 1
            continue

        # Match brackets
        depth = 0
        pos = bracket_start
        while pos < len(content):
            if content[pos] == '[':
                depth += 1
            elif content[pos] == ']':
                depth -= 1
                if depth == 0:
                    break
            pos += 1

        if depth == 0:
            raw_section = content[idx:pos + 1]
            sections.append(raw_section)

        search_start = pos + 1

    return '\n\n---\n\n'.join(sections) if sections else None


def extract_comments_from_section(raw_section: str) -> List[Dict[str, Any]]:
    """Extract comments from a raw powertrain section."""
    comments = []
    if not raw_section:
        return comments

    lines = raw_section.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Block comments
        if '/*' in stripped or '*/' in stripped:
            comments.append({
                "line_offset": i,
                "type": "block",
                "text": stripped
            })
            continue

        # Line comments
        comment_match = re.search(r'//(.*)$', stripped)
        if comment_match:
            comment_text = comment_match.group(1).strip()
            # Determine if this is a standalone comment or inline
            code_before = stripped[:stripped.find('//')].strip()
            comments.append({
                "line_offset": i,
                "type": "inline" if code_before else "standalone",
                "text": comment_text,
                "context": code_before if code_before else None
            })

    return comments


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class PowertrainDevice:
    """A single device in a powertrain chain."""
    type: str
    name: str
    inputName: str
    inputIndex: int
    properties: Dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    source_part: str = ""

    def to_summary(self) -> List:
        """Return array format without properties (truncated view)."""
        return [self.type, self.name, self.inputName, self.inputIndex]

    def to_full(self) -> List:
        """Return array format with properties."""
        result = [self.type, self.name, self.inputName, self.inputIndex]
        if self.properties:
            result.append(self.properties)
        return result


@dataclass
class DrivetrainComponent:
    """A resolved drivetrain component in the slot chain."""
    slot_type: str
    part_name: str
    source_file: str
    devices: List[PowertrainDevice] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "part_name": self.part_name,
            "source_file": self.source_file,
            "devices": [d.to_summary() for d in self.devices],
        }


@dataclass
class DrivetrainChain:
    """Complete resolved drivetrain chain from transmission to wheels."""
    components: List[DrivetrainComponent] = field(default_factory=list)
    full_torque_path: List[PowertrainDevice] = field(default_factory=list)
    split_points: List[str] = field(default_factory=list)

    def get_chain_string(self, max_branches: int = 2) -> str:
        """Format the full chain as type(name) -> type(name) -> ...
        Truncates after a power split device with a [SPLIT] marker."""
        if not self.full_torque_path:
            return ""

        # Build adjacency: device name -> list of downstream devices
        downstream_map: Dict[str, List[PowertrainDevice]] = defaultdict(list)
        for d in self.full_torque_path:
            downstream_map[d.inputName].append(d)

        # Walk the chain from mainEngine, linearizing with split detection
        parts: List[str] = []
        # Find root devices (input from mainEngine or from outside the chain)
        known_names = {d.name for d in self.full_torque_path}
        roots = [d for d in self.full_torque_path if d.inputName not in known_names]
        if not roots:
            roots = [d for d in self.full_torque_path if d.inputName == 'mainEngine']
        if not roots and self.full_torque_path:
            roots = [self.full_torque_path[0]]

        visited: Set[str] = set()
        queue = list(roots)
        while queue:
            current = queue.pop(0)
            if current.name in visited:
                continue
            visited.add(current.name)
            parts.append(f"{current.type}({current.name})")

            children = downstream_map.get(current.name, [])
            if len(children) > 1 and current.name in self.split_points:
                # Check if this is a terminal split (diff -> wheel axles)
                # Terminal splits are leaf-level: all children are wheel axles or halfshafts
                terminal_keywords = ('wheelaxle', 'halfshaft')
                is_terminal = all(
                    any(kw in child.name.lower() for kw in terminal_keywords)
                    for child in children
                )
                if is_terminal:
                    # Don't show terminal splits - chain ends at the differential
                    break
                else:
                    # Mid-chain power split (transfer case etc.) - show [SPLIT] marker
                    branch_labels = []
                    for child in children[:max_branches]:
                        branch_labels.append(f"{child.type}({child.name})")
                    parts.append(f"[SPLIT: {'/'.join(branch_labels)}]")
                    break
            elif children:
                queue.extend(children)

        return " -> ".join(parts)

    def get_full_chain_string(self) -> str:
        """Format the full chain without truncation, showing all branches."""
        if not self.full_torque_path:
            return ""

        downstream_map: Dict[str, List[PowertrainDevice]] = defaultdict(list)
        for d in self.full_torque_path:
            downstream_map[d.inputName].append(d)

        known_names = {d.name for d in self.full_torque_path}
        roots = [d for d in self.full_torque_path if d.inputName not in known_names]
        if not roots:
            roots = [self.full_torque_path[:1]]

        lines = []
        visited: Set[str] = set()

        def _walk(device: PowertrainDevice, indent: int = 0):
            if device.name in visited:
                return
            visited.add(device.name)
            prefix = "  " * indent
            lines.append(f"{prefix}{device.type}({device.name})")
            children = downstream_map.get(device.name, [])
            for child in children:
                _walk(child, indent + (1 if len(children) > 1 else 0))

        for root in roots:
            _walk(root)

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": [c.to_dict() for c in self.components],
            "full_torque_path": [d.to_summary() for d in self.full_torque_path],
            "full_chain_string": self.get_chain_string(),
            "split_points": self.split_points,
        }


@dataclass
class PowertrainEntry:
    """A complete powertrain entry from one part in a .jbeam file."""
    vehicle: str
    filename: str
    filepath: str
    is_common: bool
    part_name: str
    slot_type: str
    info_name: str
    info_value: Any
    info_authors: str
    parent_slot_name: str  # The slotType this part fills
    devices: List[PowertrainDevice] = field(default_factory=list)
    slots: List[Any] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)
    raw_section: Optional[str] = None
    drivetrain_chain: Optional[DrivetrainChain] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "vehicle": self.vehicle,
            "filename": self.filename,
            "filepath": self.filepath,
            "is_common": self.is_common,
            "part_name": self.part_name,
            "slot_type": self.slot_type,
            "info_name": self.info_name,
            "info_value": self.info_value,
            "info_authors": self.info_authors,
            "parent_slot_name": self.parent_slot_name,
            "powertrain_summary": [d.to_summary() for d in self.devices],
            "powertrain_full": [d.to_full() for d in self.devices],
            "slots": self.slots,
            "comments": self.comments,
        }
        if self.drivetrain_chain and self.drivetrain_chain.full_torque_path:
            result["drivetrain_chain"] = self.drivetrain_chain.to_dict()
        return result


# =============================================================================
# Slot Registry - Indexes all parts accessible to a vehicle
# =============================================================================

class SlotRegistry:
    """
    Indexes all .jbeam parts across search folders for a vehicle.
    Maps slotTypes to providers and tracks child slot relationships.
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        # slotType -> list of (part_name, part_data, file_path)
        self.slot_providers: Dict[str, List[Tuple[str, dict, Path]]] = defaultdict(list)
        # part_name -> list of (slot_type, default_part_name)
        self.part_child_slots: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        # part_name -> raw part_data dict
        self.part_data: Dict[str, dict] = {}
        # part_name -> file_path
        self.part_file: Dict[str, Path] = {}
        # All parts with powertrain arrays: part_name -> part_data
        self.powertrain_parts: Dict[str, dict] = {}
        # Track indexed folders to avoid duplicates
        self._indexed_folders: Set[str] = set()

    def index_folder(self, folder: Path):
        """Index all .jbeam files in a folder recursively."""
        folder_key = str(folder)
        if folder_key in self._indexed_folders:
            return
        self._indexed_folders.add(folder_key)

        for jbeam_file in folder.rglob('*.jbeam'):
            self._index_file(jbeam_file)

    def _index_file(self, jbeam_file: Path):
        """Index a single .jbeam file."""
        data = JBeamParser.parse_jbeam(jbeam_file)
        if data is None:
            return

        for part_name, part_data in data.items():
            if not isinstance(part_data, dict):
                continue

            # Register slot provider
            slot_type = part_data.get('slotType', '')
            if isinstance(slot_type, str) and slot_type:
                self.slot_providers[slot_type].append(
                    (part_name, part_data, jbeam_file))

            self.part_data[part_name] = part_data
            self.part_file[part_name] = jbeam_file

            # Parse child slots
            child_slots = self._parse_child_slots(part_data)
            if child_slots:
                self.part_child_slots[part_name] = child_slots

            # Index powertrain arrays
            powertrain = part_data.get('powertrain')
            if isinstance(powertrain, list) and len(powertrain) >= 2:
                self.powertrain_parts[part_name] = part_data

    def _parse_child_slots(self, part_data: dict) -> List[Tuple[str, str]]:
        """Parse both 'slots' and 'slots2' formats.
        Returns list of (slot_type, default_part_name) pairs."""
        results = []

        # Handle 'slots' format: [["type","default","description",...], ...]
        slots = part_data.get('slots', [])
        if isinstance(slots, list):
            header_found = False
            for row in slots:
                if not isinstance(row, list):
                    continue
                if not header_found:
                    if 'type' in row:
                        header_found = True
                    continue
                # Data row: [type, default, description, {options}]
                if len(row) >= 2 and isinstance(row[0], str) and row[0]:
                    results.append((row[0], row[1] if isinstance(row[1], str) else ''))

        # Handle 'slots2' format: [["name","allowTypes","denyTypes","default","desc"], ...]
        slots2 = part_data.get('slots2', [])
        if isinstance(slots2, list):
            header_found = False
            for row in slots2:
                if not isinstance(row, list):
                    continue
                if not header_found:
                    if 'name' in row or 'allowTypes' in row:
                        header_found = True
                    continue
                # Data row: [name, allowTypes, denyTypes, default, description, {options}]
                if len(row) >= 4 and isinstance(row[0], str) and row[0]:
                    default = row[3] if isinstance(row[3], str) else ''
                    results.append((row[0], default))

        return results

    def resolve_default_part(self, slot_type: str, preferred_name: str = ''
                             ) -> Optional[Tuple[str, dict, Path]]:
        """Find the default part for a given slot type.
        If preferred_name is given, try to match it first."""
        providers = self.slot_providers.get(slot_type, [])
        if not providers:
            return None

        # Try to match preferred name first
        if preferred_name:
            for prov in providers:
                if prov[0] == preferred_name:
                    return prov

        return providers[0]

    def get_child_slots(self, part_name: str) -> List[Tuple[str, str]]:
        """Get child slots (slot_type, default_name) for a part."""
        return self.part_child_slots.get(part_name, [])


# =============================================================================
# Folder Resolution - Determines search scope for a vehicle
# =============================================================================

def get_search_folders(base_path: Path, vehicle_name: str) -> List[Path]:
    """Determine which folders to search for a vehicle's complete components.

    Handles:
    - Vehicle's own folder
    - Common folder matching vehicle name (direct: common/<name>)
    - Common engine subfolders (nested: common/engines/<name>)
    - Cross-vehicle/cross-common references via slotType prefix scanning
      (e.g., etk800 using etk_engine from common/etk, roamer using pickup_*)
    """
    folders: Set[Path] = set()
    common_base = base_path / 'common' / 'vehicles' / 'common'

    # Known vehicle directories for validation
    all_vehicle_dirs = set()
    for d in base_path.iterdir():
        if d.is_dir():
            all_vehicle_dirs.add(d.name)

    # Known common subfolder names (for cross-folder prefix matching)
    all_common_dirs = set()
    if common_base.exists():
        for d in common_base.iterdir():
            if d.is_dir():
                all_common_dirs.add(d.name)
        # Also include nested engine subfolders (e.g., engines/bastion)
        engines_dir = common_base / 'engines'
        if engines_dir.exists():
            for d in engines_dir.iterdir():
                if d.is_dir():
                    all_common_dirs.add(d.name)

    # 1. Vehicle's own folder
    vehicle_folder = base_path / vehicle_name / 'vehicles' / vehicle_name
    if vehicle_folder.exists():
        folders.add(vehicle_folder)
    else:
        # Try finding it as a subfolder pattern
        for candidate in base_path.rglob(f'vehicles/{vehicle_name}'):
            if candidate.is_dir():
                folders.add(candidate)

    # 2. Common folder matching vehicle name
    common_folder = common_base / vehicle_name
    if common_folder.exists():
        folders.add(common_folder)
    # Also check nested engines/<vehicle_name>
    engines_folder = common_base / 'engines' / vehicle_name
    if engines_folder.exists():
        folders.add(engines_folder)

    # 3. Detect cross-vehicle / cross-common slot references
    cross_prefixes = _detect_cross_vehicle_prefixes(
        vehicle_folder if vehicle_folder.exists() else None,
        vehicle_name, all_vehicle_dirs, all_common_dirs)

    for prefix in cross_prefixes:
        # Check as a vehicle folder
        other_folder = base_path / prefix / 'vehicles' / prefix
        if other_folder.exists():
            folders.add(other_folder)
        # Check as a direct common subfolder
        other_common = common_base / prefix
        if other_common.exists():
            folders.add(other_common)
        # Check as a nested common/engines/ subfolder
        other_engines = common_base / 'engines' / prefix
        if other_engines.exists():
            folders.add(other_engines)

    return list(folders)


def _detect_cross_vehicle_prefixes(vehicle_folder: Optional[Path],
                                    vehicle_name: str,
                                    all_vehicle_dirs: Set[str],
                                    all_common_dirs: Optional[Set[str]] = None,
                                    ) -> Set[str]:
    """Scan a vehicle's jbeam files to find slot type prefixes from other
    vehicles or common subfolders.

    Matches prefixes against both top-level vehicle directory names AND
    common/vehicles/common/ subfolder names, enabling cross-folder
    resolution (e.g., etk800 -> common/etk via 'etk_engine' slotType).
    """
    prefixes: Set[str] = set()
    if vehicle_folder is None or not vehicle_folder.exists():
        return prefixes

    # Combine vehicle dirs and common dirs for prefix matching
    valid_prefixes = set(all_vehicle_dirs)
    if all_common_dirs:
        valid_prefixes |= all_common_dirs

    # Prefixes to always ignore (keywords, not vehicle/common names)
    IGNORE_PREFIXES = frozenset({
        'type', 'name', 'linelock', 'main', 'slot', 'mod',
    })

    for jbeam_file in vehicle_folder.glob('*.jbeam'):
        data = JBeamParser.parse_jbeam(jbeam_file)
        if data is None:
            continue
        for part_name, part_data in data.items():
            if not isinstance(part_data, dict):
                continue
            for key in ('slots', 'slots2'):
                slot_list = part_data.get(key, [])
                if not isinstance(slot_list, list):
                    continue
                header_found = False
                for row in slot_list:
                    if not isinstance(row, list) or len(row) < 1:
                        continue
                    if not header_found:
                        if isinstance(row[0], str) and row[0] in ('type', 'name'):
                            header_found = True
                        continue
                    slot_type_val = row[0] if isinstance(row[0], str) else ''
                    if '_' in slot_type_val:
                        prefix = slot_type_val.split('_')[0]
                        if (prefix != vehicle_name and
                                prefix in valid_prefixes and
                                prefix not in IGNORE_PREFIXES):
                            prefixes.add(prefix)
    return prefixes


def _build_common_to_vehicles_map(base_path: Path) -> Dict[str, List[str]]:
    """Build a mapping from common powertrain slotTypes to the vehicles they serve.

    Three-phase approach with slot-chain following:
      1. Parse common subfolders that contain powertrain parts, collecting:
         a) Parts with ``powertrain`` arrays → slotType + common prefix.
         b) ALL parts' ``slots`` arrays → directed parent→child slot graph.
         c) ALL slotTypes from powertrain-relevant subdirs (for bridge searching).
      2. Text-search each vehicle's ``.jbeam`` files for any common slotType
         from powertrain-relevant subdirs to find entry points.
      3. BFS through the slot-chain graph from each vehicle's entry points
         to find transitively reachable powertrain slotTypes.  Only downstream
         slot-chain connections are followed, preventing false positives
         (e.g. pigeon referencing ``pickup_differential_R`` does NOT inherit
         ``pickup_engine`` or ``pickup_transmission``).

    Returns ``{slotType: [vehicle1, vehicle2, ...]}``.
    """
    common_base = base_path / 'common' / 'vehicles' / 'common'

    # -- Phase 1 -- Parse common subdirs for powertrain slotTypes + slot chain.
    slottype_to_prefix: Dict[str, str] = {}  # powertrain slotType -> prefix
    prefix_to_slottypes: Dict[str, Set[str]] = defaultdict(set)  # prefix -> {PT slotTypes}
    # All slotTypes per prefix (including non-powertrain, for bridge searching)
    prefix_all_slottypes: Dict[str, Set[str]] = defaultdict(set)
    # Slot chain: parent slotType -> {child slotTypes from slots arrays}
    slot_chain: Dict[str, Set[str]] = defaultdict(set)

    for parent_dir in (common_base, common_base / 'engines'):
        if not parent_dir.exists():
            continue
        for d in parent_dir.iterdir():
            if not d.is_dir() or d.name == 'engines':
                continue
            prefix = d.name
            for jbeam_file in d.glob('*.jbeam'):
                data = JBeamParser.parse_jbeam(jbeam_file)
                if data is None:
                    continue
                for part_name, part_data in data.items():
                    if not isinstance(part_data, dict):
                        continue
                    st = part_data.get('slotType', '')
                    if isinstance(st, list):
                        st = st[0] if st else ''
                    if not isinstance(st, str) or not st:
                        continue

                    prefix_all_slottypes[prefix].add(st)

                    # Phase 1a: Track powertrain slotTypes
                    powertrain = part_data.get('powertrain')
                    if powertrain and isinstance(powertrain, list):
                        slottype_to_prefix[st] = prefix
                        prefix_to_slottypes[prefix].add(st)

                    # Phase 1b: Build slot chain graph from ALL parts
                    for slots_key in ('slots', 'slots2'):
                        slots = part_data.get(slots_key, [])
                        if not isinstance(slots, list):
                            continue
                        for row in slots:
                            if not isinstance(row, list) or len(row) < 2:
                                continue
                            child_st = row[0]
                            if (isinstance(child_st, str) and child_st
                                    and child_st not in ('type', 'default')):
                                slot_chain[st].add(child_st)

    if not slottype_to_prefix:
        return {}

    # Only search for slotTypes from prefixes that have powertrain parts
    powertrain_prefixes = set(slottype_to_prefix.values())
    searchable_slottypes: Set[str] = set()
    for pfx in powertrain_prefixes:
        searchable_slottypes |= prefix_all_slottypes[pfx]

    logger.debug(
        f"Common powertrain slotTypes ({len(slottype_to_prefix)}), "
        f"searchable bridge slotTypes ({len(searchable_slottypes)}), "
        f"slot chain edges ({sum(len(v) for v in slot_chain.values())})")

    # -- Phase 2 -- Find which common slotTypes each vehicle references.
    # Scans for ALL slotTypes from powertrain-relevant prefixes (including
    # non-powertrain ones) so BFS can follow through bridge slotTypes like
    # pickup_suspension_R -> pickup_differential_R.
    vehicle_direct_refs: Dict[str, Set[str]] = defaultdict(set)

    for d in sorted(base_path.iterdir()):
        if not d.is_dir() or d.name in ('common', 'simple_traffic', 'engine_props'):
            continue
        veh_folder = d / 'vehicles' / d.name
        if not veh_folder.exists():
            continue

        veh_name = d.name

        # Self-reference: vehicle name matches a powertrain common prefix
        if veh_name in powertrain_prefixes:
            for st in prefix_to_slottypes[veh_name]:
                vehicle_direct_refs[veh_name].add(st)

        # Scan jbeam files for exact slotType references
        for jbeam in veh_folder.glob('*.jbeam'):
            try:
                content = jbeam.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for st in searchable_slottypes:
                if f'"{st}"' in content:
                    vehicle_direct_refs[veh_name].add(st)

    # -- Phase 3 -- BFS through slot chain from each vehicle's entry points.
    # Follow downstream slot-chain edges to find transitively reachable
    # powertrain slotTypes.  Non-powertrain slotTypes serve as bridges
    # (e.g. pickup_suspension_R connects to pickup_differential_R).

    def _follow_slot_chain(start_sts: Set[str]) -> Set[str]:
        """BFS through slot chain to find reachable powertrain slotTypes."""
        visited: Set[str] = set()
        queue = list(start_sts)
        reachable: Set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if current in slottype_to_prefix:
                reachable.add(current)
            for child in slot_chain.get(current, set()):
                if child not in visited:
                    queue.append(child)
        return reachable

    mapping: Dict[str, Set[str]] = defaultdict(set)
    for veh_name, direct_refs in vehicle_direct_refs.items():
        reachable = _follow_slot_chain(direct_refs)
        for st in reachable:
            mapping[st].add(veh_name)

    result = {k: sorted(v) for k, v in mapping.items() if v}
    if result:
        logger.debug("Slot-chain vehicle mapping:")
        veh_to_sts: Dict[str, Set[str]] = defaultdict(set)
        for st, vehicles in result.items():
            for v in vehicles:
                veh_to_sts[v].add(st)
        for v in sorted(veh_to_sts):
            logger.debug(f"  {v} ({len(veh_to_sts[v])} slotTypes) -> "
                         f"{sorted(veh_to_sts[v])}")
    return result


# =============================================================================
# Drivetrain Chain Builder
# =============================================================================

# Slot type keywords that indicate drivetrain-related components
DRIVETRAIN_KEYWORDS = frozenset([
    'driveshaft', 'differential', 'transfercase', 'transfer_case',
    'tranfercase',  # BeamNG typo
    'halfshaft', 'finaldrive', 'final_drive', 'axle', 'transaxle',
])


def _is_drivetrain_slot(slot_type: str) -> bool:
    """Check if a slot type name indicates a drivetrain component."""
    lower = slot_type.lower()
    return any(kw in lower for kw in DRIVETRAIN_KEYWORDS)


class DrivetrainChainBuilder:
    """Builds complete drivetrain chains using hybrid slot-chain + device-name linking."""

    def __init__(self, registry: SlotRegistry,
                 allowed_common_slottypes: Optional[Set[str]] = None):
        self.registry = registry
        # When set, parts from common/ folders are only included if their
        # slotType is in this set.  None = no filtering (full-mode default).
        self._allowed_common_slottypes = allowed_common_slottypes

    def _is_allowed_part(self, part_name: str, slot_type: str,
                         source_file: Path) -> bool:
        """Check if a part passes the common-folder reachability filter."""
        if self._allowed_common_slottypes is None:
            return True
        if 'common' not in str(source_file).lower():
            return True
        if not slot_type:
            return True  # Can't filter without slotType
        return slot_type in self._allowed_common_slottypes

    def build_chain(self, entry: PowertrainEntry) -> DrivetrainChain:
        """Build a complete drivetrain chain starting from a transmission entry."""
        chain = DrivetrainChain()

        # Collect all devices: name -> PowertrainDevice
        all_devices: Dict[str, PowertrainDevice] = {}
        resolved_parts: Set[str] = set()

        # Step 1: Seed with the transmission entry's own devices
        resolved_parts.add(entry.part_name)
        for d in entry.devices:
            dev_copy = PowertrainDevice(
                type=d.type, name=d.name,
                inputName=d.inputName, inputIndex=d.inputIndex,
                properties=d.properties,
                source_file=entry.filename, source_part=entry.part_name,
            )
            all_devices[d.name] = dev_copy

        # Step 2: Follow child slots recursively from the transmission
        self._resolve_child_slots(
            entry.part_name, chain, all_devices, resolved_parts, depth=0)

        # Step 3: Device-name linking fallback
        # Catches components not in the transmission's slot tree (e.g. RWD
        # driveshafts/differentials owned by the frame or suspension)
        self._device_name_linking(all_devices, chain, resolved_parts)

        # Step 4: Build ordered torque path via BFS from mainEngine
        chain.full_torque_path = self._build_ordered_path(all_devices)

        # Step 5: Detect power split points
        chain.split_points = self._find_split_points(all_devices)

        return chain

    def _resolve_child_slots(self, part_name: str, chain: DrivetrainChain,
                              all_devices: Dict[str, PowertrainDevice],
                              resolved: Set[str], depth: int):
        """Follow slot chains from a part, collecting powertrain devices."""
        if depth > 10:
            return

        child_slots = self.registry.get_child_slots(part_name)

        for slot_type, default_name in child_slots:
            if not _is_drivetrain_slot(slot_type):
                continue

            resolved_part = self.registry.resolve_default_part(slot_type, default_name)
            if resolved_part is None:
                continue

            res_name, res_data, res_file = resolved_part
            if res_name in resolved:
                continue

            # Skip unreachable common-folder parts in targeted mode
            if not self._is_allowed_part(res_name, slot_type, res_file):
                continue

            resolved.add(res_name)

            # Extract devices
            powertrain = res_data.get('powertrain')
            if isinstance(powertrain, list):
                devices = _extract_powertrain_devices(powertrain)
                if devices:
                    for d in devices:
                        d.source_file = res_file.name
                        d.source_part = res_name
                        all_devices[d.name] = d

                    component = DrivetrainComponent(
                        slot_type=slot_type,
                        part_name=res_name,
                        source_file=res_file.name,
                        devices=devices,
                    )
                    chain.components.append(component)

            # Recurse into this part's children
            self._resolve_child_slots(
                res_name, chain, all_devices, resolved, depth + 1)

    def _device_name_linking(self, all_devices: Dict[str, PowertrainDevice],
                              chain: DrivetrainChain, resolved: Set[str]):
        """Find additional parts by looking for device-name matches across all
        powertrain parts in the registry.

        Only links parts where:
        - At least one device's inputName matches a known device name (forward link)
        - The part doesn't redefine device names already in the chain (avoids variants)
        - Only one part per slot type is linked (avoids multiple variants)
        """
        linked_slot_types: Set[str] = set()
        changed = True
        iterations = 0
        while changed and iterations < 20:
            changed = False
            iterations += 1
            known_names = set(all_devices.keys())

            for part_name, part_data in self.registry.powertrain_parts.items():
                if part_name in resolved:
                    continue

                slot_type = part_data.get('slotType', '')
                if not isinstance(slot_type, str):
                    slot_type = slot_type[0] if isinstance(slot_type, list) and slot_type else ''

                # Skip if we already linked a part for this slot type
                if slot_type and slot_type in linked_slot_types:
                    continue

                # Skip unreachable common-folder parts in targeted mode
                source_file_lnk = self.registry.part_file.get(part_name, Path('unknown'))
                if not self._is_allowed_part(part_name, slot_type, source_file_lnk):
                    continue

                powertrain = part_data.get('powertrain')
                if not isinstance(powertrain, list):
                    continue

                devices = _extract_powertrain_devices(powertrain)

                # Skip parts that would redefine device names already in the chain
                # (this avoids pulling in alternate variants of the same component)
                new_device_names = {d.name for d in devices}
                if new_device_names & known_names:
                    continue

                # Forward link only: the candidate takes input FROM the chain
                has_link = any(d.inputName in known_names for d in devices)

                if has_link:
                    resolved.add(part_name)
                    if slot_type:
                        linked_slot_types.add(slot_type)
                    source_file = self.registry.part_file.get(part_name, Path('unknown'))

                    for d in devices:
                        d.source_file = source_file.name if isinstance(source_file, Path) else str(source_file)
                        d.source_part = part_name
                        all_devices[d.name] = d

                    component = DrivetrainComponent(
                        slot_type=slot_type,
                        part_name=part_name,
                        source_file=source_file.name if isinstance(source_file, Path) else str(source_file),
                        devices=devices,
                    )
                    chain.components.append(component)
                    changed = True

    def _build_ordered_path(self, all_devices: Dict[str, PowertrainDevice]
                             ) -> List[PowertrainDevice]:
        """Build a BFS-ordered torque path from engine to wheels."""
        if not all_devices:
            return []

        # Find root devices (input from mainEngine or from outside the chain)
        known_names = set(all_devices.keys())
        roots = [d for d in all_devices.values() if d.inputName == 'mainEngine']
        if not roots:
            # Fall back to devices whose input is not in our chain
            roots = [d for d in all_devices.values()
                     if d.inputName not in known_names]
        if not roots:
            return list(all_devices.values())

        # BFS
        ordered = []
        visited: Set[str] = set()
        queue = sorted(roots, key=lambda d: d.inputIndex)

        while queue:
            current = queue.pop(0)
            if current.name in visited:
                continue
            visited.add(current.name)
            ordered.append(current)

            # Find downstream devices
            downstream = [d for d in all_devices.values()
                         if d.inputName == current.name and d.name not in visited]
            downstream.sort(key=lambda d: d.inputIndex)
            queue.extend(downstream)

        return ordered

    def _find_split_points(self, all_devices: Dict[str, PowertrainDevice]
                            ) -> List[str]:
        """Find device names that have multiple downstream consumers."""
        output_counts: Dict[str, int] = defaultdict(int)
        for d in all_devices.values():
            if d.inputName in all_devices:
                output_counts[d.inputName] += 1
        return [name for name, count in output_counts.items() if count > 1]


# =============================================================================
# Standalone device extraction (used by both PowertrainExtractor and ChainBuilder)
# =============================================================================

def _extract_powertrain_devices(powertrain: List) -> List[PowertrainDevice]:
    """Extract device information from a powertrain table array."""
    devices = []

    if not isinstance(powertrain, list) or len(powertrain) < 2:
        return devices

    # Find header row
    header_idx = -1
    for i, row in enumerate(powertrain):
        if isinstance(row, list) and 'type' in row:
            header_idx = i
            break

    if header_idx == -1:
        return devices

    header = powertrain[header_idx]

    # Process subsequent rows
    for row in powertrain[header_idx + 1:]:
        if not isinstance(row, list):
            continue

        values = {}
        properties = {}
        for j, value in enumerate(row):
            if isinstance(value, dict):
                properties = value
            elif j < len(header):
                key = header[j]
                values[key] = value

        if 'type' in values:
            device = PowertrainDevice(
                type=values.get('type', ''),
                name=values.get('name', ''),
                inputName=values.get('inputName', ''),
                inputIndex=values.get('inputIndex', 0),
                properties=properties,
            )
            devices.append(device)

    return devices


# =============================================================================
# Powertrain Extractor
# =============================================================================

class PowertrainExtractor:
    """Extracts powertrain arrays from .jbeam files with full metadata."""

    def __init__(self, base_path: Path, include_simple_traffic: bool = False):
        self.base_path = base_path
        self.include_simple_traffic = include_simple_traffic
        self.entries: List[PowertrainEntry] = []
        self.parse_failures: List[str] = []
        self.property_lookup: Dict[str, Dict[str, Any]] = {}
        # Mapping: common subfolder prefix -> [vehicles that use it]
        self._common_to_vehicles = _build_common_to_vehicles_map(base_path)

    def _classify_path(self, file_path: Path) -> Tuple[str, bool]:
        """Determine vehicle name and whether this is a common asset."""
        parts = file_path.parts
        path_str = str(file_path)

        # Check if in common folder
        is_common = 'common' in parts

        # Check if in simple_traffic folder
        is_simple_traffic = 'simple_traffic' in parts

        # Extract vehicle name
        vehicle = "unknown"

        if is_common:
            # Pattern: common/vehicles/common/<vehicle_family>/
            for i, p in enumerate(parts):
                if p == 'common' and i + 1 < len(parts):
                    # Skip 'vehicles' and 'common' hierarchy
                    if parts[i+1] == 'vehicles':
                        if i + 3 < len(parts):
                            vehicle = parts[i + 3]
                    else:
                        vehicle = parts[i + 1]
                    break
            # Specifically for common/vehicles/common/<name>/
            try:
                common_idx = list(parts).index('common')
                # Walk forward to find the actual vehicle name
                remaining = parts[common_idx:]
                for j, rp in enumerate(remaining):
                    if rp not in ('common', 'vehicles', 'engines'):
                        vehicle = rp
                        break
            except (ValueError, IndexError):
                pass
        elif is_simple_traffic:
            # Pattern: simple_traffic/vehicles/simple_traffic/<vehicle>/
            try:
                st_indices = [i for i, p in enumerate(parts) if p == 'simple_traffic']
                if len(st_indices) >= 2:
                    vehicle = f"simple_traffic/{parts[st_indices[1] + 1]}"
                elif st_indices:
                    vehicle = f"simple_traffic/{parts[st_indices[0] + 2] if st_indices[0] + 2 < len(parts) else 'unknown'}"
            except (IndexError):
                pass
        else:
            # Standard: <vehicle_folder>/vehicles/<vehicle>/
            for i, p in enumerate(parts):
                if p == 'vehicles' and i + 1 < len(parts):
                    vehicle = parts[i + 1]
                    break

        return vehicle, is_common

    def _extract_slots(self, part_data: Dict) -> List[Any]:
        """Extract slot information from a part."""
        slots = part_data.get('slots', [])
        if not slots:
            slots = part_data.get('slots2', [])
        return slots

    def process_file(self, file_path: Path):
        """Process a single .jbeam file, extracting all powertrain entries."""
        # Skip engine_props folder entirely (animated visual elements, not powertrain)
        if 'engine_props' in file_path.parts:
            return

        data = JBeamParser.parse_jbeam(file_path)
        if data is None:
            self.parse_failures.append(str(file_path))
            return

        vehicle, is_common = self._classify_path(file_path)
        raw_section = extract_raw_powertrain_section(file_path)
        comments = extract_comments_from_section(raw_section) if raw_section else []

        # Relative path from base
        try:
            rel_path = file_path.relative_to(self.base_path)
        except ValueError:
            rel_path = file_path

        for part_name, part_data in data.items():
            if not isinstance(part_data, dict):
                continue

            powertrain = part_data.get('powertrain', None)
            if powertrain is None or not isinstance(powertrain, list):
                continue

            # Extract metadata
            info = part_data.get('information', {})
            if not isinstance(info, dict):
                info = {}

            slot_type = part_data.get('slotType', '')
            if not isinstance(slot_type, str):
                slot_type = slot_type[0] if isinstance(slot_type, list) and slot_type else ''

            # Expand common entries to the vehicles that reference this slotType
            if is_common and slot_type and slot_type in self._common_to_vehicles:
                target_vehicles = self._common_to_vehicles[slot_type]
            else:
                target_vehicles = [vehicle]

            info_name = info.get('name', '')
            info_value = info.get('value', '')
            info_authors = info.get('authors', '')
            slots = self._extract_slots(part_data)

            # Extract devices
            devices = _extract_powertrain_devices(powertrain)
            for d in devices:
                d.source_file = file_path.name
                d.source_part = part_name

            for target_vehicle in target_vehicles:
                # Deep-copy devices so each entry owns its own list
                entry_devices = [
                    PowertrainDevice(
                        type=d.type, name=d.name,
                        inputName=d.inputName, inputIndex=d.inputIndex,
                        properties=dict(d.properties) if d.properties else {},
                        source_file=d.source_file, source_part=d.source_part,
                    ) for d in devices
                ]

                entry = PowertrainEntry(
                    vehicle=target_vehicle,
                    filename=file_path.name,
                    filepath=str(rel_path),
                    is_common=is_common,
                    part_name=part_name,
                    slot_type=slot_type,
                    info_name=info_name,
                    info_value=info_value,
                    info_authors=info_authors,
                    parent_slot_name=slot_type,
                    devices=entry_devices,
                    slots=slots,
                    comments=comments,
                    raw_section=raw_section,
                )

                self.entries.append(entry)

            # Store property lookup indexed by part_name
            if devices:
                self.property_lookup[part_name] = {
                    "filename": file_path.name,
                    "filepath": str(rel_path),
                    "vehicle": target_vehicles[0],
                    "devices": {d.name: d.properties for d in devices if d.properties},
                }

    def find_target_files(self) -> List[Path]:
        """Find all transmission, transfercase, and transaxle files."""
        patterns = [
            '*transmission*.jbeam',
            '*transfercase*.jbeam',
            '*tranfercase*.jbeam',   # BeamNG typo in some files
            '*transaxle*.jbeam',
        ]

        files = set()
        for pattern in patterns:
            for f in self.base_path.rglob(pattern):
                if 'engine_props' in f.parts:
                    continue
                if not self.include_simple_traffic and 'simple_traffic' in f.parts:
                    continue
                files.add(f)

        return sorted(files)

    def find_all_powertrain_files(self) -> List[Path]:
        """Find ALL files containing powertrain arrays (for chain analysis)."""
        all_jbeam = list(self.base_path.rglob('*.jbeam'))
        powertrain_files = []
        for f in all_jbeam:
            if 'engine_props' in f.parts:
                continue
            if not self.include_simple_traffic and 'simple_traffic' in f.parts:
                continue
            try:
                with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
                if '"powertrain"' in content:
                    powertrain_files.append(f)
            except Exception:
                pass
        return sorted(powertrain_files)

    def run_primary(self):
        """Run primary extraction on transmission/transfercase/transaxle files."""
        target_files = self.find_target_files()
        logger.info(f"Found {len(target_files)} target files (transmission/transfercase/transaxle)")

        for f in target_files:
            self.process_file(f)

        logger.info(f"Extracted {len(self.entries)} powertrain entries")
        if self.parse_failures:
            logger.warning(f"Failed to parse {len(self.parse_failures)} files:")
            for pf in self.parse_failures:
                logger.warning(f"  - {pf}")

    def run_full_scan(self) -> List[PowertrainEntry]:
        """
        Run full scan of ALL files with powertrain arrays.
        Returns entries from non-primary files (for chain analysis).
        """
        all_files = self.find_all_powertrain_files()
        primary_filenames = {e.filepath for e in self.entries}

        supplemental_entries = []
        for f in all_files:
            try:
                rel = str(f.relative_to(self.base_path))
            except ValueError:
                rel = str(f)
            if rel in primary_filenames:
                continue

            data = JBeamParser.parse_jbeam(f)
            if data is None:
                continue

            vehicle, is_common = self._classify_path(f)

            for part_name, part_data in data.items():
                if not isinstance(part_data, dict):
                    continue
                powertrain = part_data.get('powertrain', None)
                if powertrain is None or not isinstance(powertrain, list):
                    continue

                info = part_data.get('information', {})
                if not isinstance(info, dict):
                    info = {}

                slot_type = part_data.get('slotType', '')
                if not isinstance(slot_type, str):
                    slot_type = slot_type[0] if isinstance(slot_type, list) and slot_type else ''

                # Expand common entries to vehicles that reference this slotType
                if is_common and slot_type and slot_type in self._common_to_vehicles:
                    target_vehicles = self._common_to_vehicles[slot_type]
                else:
                    target_vehicles = [vehicle]

                devices = _extract_powertrain_devices(powertrain)
                for d in devices:
                    d.source_file = f.name
                    d.source_part = part_name

                for target_vehicle in target_vehicles:
                    entry_devices = [
                        PowertrainDevice(
                            type=d.type, name=d.name,
                            inputName=d.inputName, inputIndex=d.inputIndex,
                            properties=dict(d.properties) if d.properties else {},
                            source_file=d.source_file, source_part=d.source_part,
                        ) for d in devices
                    ]

                    entry = PowertrainEntry(
                        vehicle=target_vehicle,
                        filename=f.name,
                        filepath=rel,
                        is_common=is_common,
                        part_name=part_name,
                        slot_type=slot_type,
                        info_name=info.get('name', ''),
                        info_value=info.get('value', ''),
                        info_authors=info.get('authors', ''),
                        parent_slot_name=slot_type,
                        devices=entry_devices,
                        slots=self._extract_slots(part_data),
                    )
                    supplemental_entries.append(entry)

        logger.info(f"Full scan found {len(supplemental_entries)} additional powertrain entries from other file types")
        return supplemental_entries


# =============================================================================
# Drivetrain Chain Resolution Phase
# =============================================================================

def resolve_drivetrain_chains(base_path: Path,
                               entries: List[PowertrainEntry]) -> int:
    """Resolve drivetrain chains for all entries.
    Returns count of entries that got chain resolution."""
    entries_by_vehicle: Dict[str, List[PowertrainEntry]] = defaultdict(list)
    for e in entries:
        entries_by_vehicle[e.vehicle].append(e)

    resolved_count = 0
    for vehicle, v_entries in entries_by_vehicle.items():
        # Skip simple_traffic, engine_props, and unknown
        if vehicle.startswith('simple_traffic/') or vehicle in ('unknown', 'engine_props'):
            continue

        folders = get_search_folders(base_path, vehicle)
        if not folders:
            logger.debug(f"  No search folders for {vehicle}, skipping chain resolution")
            continue

        registry = SlotRegistry(base_path)
        for folder in folders:
            registry.index_folder(folder)

        chain_builder = DrivetrainChainBuilder(registry)

        for entry in v_entries:
            try:
                chain = chain_builder.build_chain(entry)
                entry.drivetrain_chain = chain
                if chain.components:
                    resolved_count += 1
                    logger.debug(
                        f"  {entry.part_name}: +{len(chain.components)} components, "
                        f"{len(chain.full_torque_path)} total devices")
            except Exception as ex:
                logger.warning(f"  Chain resolution failed for {entry.part_name}: {ex}")

    return resolved_count


# =============================================================================
# Report Generators
# =============================================================================

def generate_json_report(entries: List[PowertrainEntry], property_lookup: Dict) -> Dict:
    """Generate full JSON report structure."""
    # Group by vehicle
    by_vehicle = defaultdict(list)
    for e in entries:
        by_vehicle[e.vehicle].append(e.to_dict())

    # Chain resolution stats
    chain_resolved = sum(1 for e in entries
                         if e.drivetrain_chain and e.drivetrain_chain.components)
    chain_total_components = sum(
        len(e.drivetrain_chain.components)
        for e in entries
        if e.drivetrain_chain and e.drivetrain_chain.components)

    return {
        "metadata": {
            "description": "BeamNG Powertrain Array Report",
            "source": "SteamLibrary_content_vehicles",
            "total_entries": len(entries),
            "total_vehicles": len(by_vehicle),
            "file_types": dict(Counter(
                e.filename.split('_')[-1].replace('.jbeam', '') for e in entries)),
            "chain_resolution": {
                "entries_with_full_chain": chain_resolved,
                "entries_without_chain": len(entries) - chain_resolved,
                "total_resolved_components": chain_total_components,
            },
        },
        "entries_by_vehicle": dict(by_vehicle),
        "all_entries": [e.to_dict() for e in entries],
        "property_lookup": property_lookup,
    }


def generate_csv(entries: List[PowertrainEntry]) -> str:
    """Generate CSV table."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Vehicle', 'IsCommon', 'Filename', 'PartName', 'SlotType',
        'InfoName', 'DeviceType', 'DeviceName', 'InputName', 'InputIndex',
        'HasProperties', 'SourceFile', 'ChainResolved'
    ])

    for e in entries:
        chain_resolved = 'Yes' if (e.drivetrain_chain and
                                    e.drivetrain_chain.components) else 'No'
        # Transmission's own devices
        for d in e.devices:
            writer.writerow([
                e.vehicle,
                'COMMON' if e.is_common else 'INDIVIDUAL',
                e.filename,
                e.part_name,
                e.slot_type,
                e.info_name,
                d.type,
                d.name,
                d.inputName,
                d.inputIndex,
                'Yes' if d.properties else 'No',
                d.source_file or e.filename,
                chain_resolved,
            ])
        # Resolved chain devices
        if e.drivetrain_chain:
            for comp in e.drivetrain_chain.components:
                for d in comp.devices:
                    writer.writerow([
                        e.vehicle,
                        'COMMON' if e.is_common else 'INDIVIDUAL',
                        comp.source_file,
                        comp.part_name,
                        comp.slot_type,
                        f"(chain from {e.part_name})",
                        d.type,
                        d.name,
                        d.inputName,
                        d.inputIndex,
                        'Yes' if d.properties else 'No',
                        d.source_file or comp.source_file,
                        'Chain',
                    ])

    return output.getvalue()


def generate_markdown_report(entries: List[PowertrainEntry],
                              parse_failures: List[str]) -> str:
    """Generate human-readable markdown report with full drivetrain chains."""
    lines = []
    lines.append("# BeamNG Powertrain Array Report")
    lines.append("")
    lines.append("## Overview")
    lines.append("")

    # Stats
    total = len(entries)
    common_count = sum(1 for e in entries if e.is_common)
    individual_count = total - common_count
    vehicles = set(e.vehicle for e in entries)
    chain_resolved = sum(1 for e in entries
                         if e.drivetrain_chain and e.drivetrain_chain.components)
    device_types = Counter()
    for e in entries:
        for d in e.devices:
            device_types[d.type] += 1
        if e.drivetrain_chain:
            for comp in e.drivetrain_chain.components:
                for d in comp.devices:
                    device_types[d.type] += 1

    lines.append(f"- **Total powertrain entries:** {total}")
    lines.append(f"- **Common assets:** {common_count}")
    lines.append(f"- **Individual assets:** {individual_count}")
    lines.append(f"- **Unique vehicles/families:** {len(vehicles)}")
    lines.append(f"- **Entries with resolved drivetrain chain:** {chain_resolved}")
    lines.append(f"- **Parse failures:** {len(parse_failures)}")
    lines.append("")

    # Device type distribution
    lines.append("## Powertrain Device Types")
    lines.append("")
    lines.append("| Device Type | Count | Description |")
    lines.append("|-------------|-------|-------------|")

    type_descriptions = {
        'frictionClutch': 'Manual transmission clutch',
        'torqueConverter': 'Automatic transmission torque converter',
        'manualGearbox': 'Manual gearbox with discrete ratios',
        'automaticGearbox': 'Automatic gearbox with auto-shifting',
        'sequentialGearbox': 'Sequential gearbox (paddle/lever shift)',
        'dctGearbox': 'Dual-clutch transmission',
        'cvtGearbox': 'Continuously variable transmission',
        'rangeBox': 'High/Low range selector',
        'shaft': 'Driveshaft / output shaft',
        'differential': 'Differential (open/LSD/locked)',
        'splitShaft': 'Torque-splitting shaft (AWD)',
        'torsionReactor': 'Torque reaction element (engine mount bridge)',
        'electricMotor': 'Electric motor',
        'centrifugalClutch': 'Centrifugal (automatic) clutch',
    }

    for dtype, count in sorted(device_types.items(), key=lambda x: -x[1]):
        desc = type_descriptions.get(dtype, '')
        lines.append(f"| `{dtype}` | {count} | {desc} |")
    lines.append("")

    # Group by vehicle
    by_vehicle = defaultdict(list)
    for e in entries:
        by_vehicle[e.vehicle].append(e)

    lines.append("## Entries by Vehicle")
    lines.append("")

    for vehicle in sorted(by_vehicle.keys()):
        v_entries = by_vehicle[vehicle]
        lines.append(f"### {vehicle}")
        lines.append("")

        for e in v_entries:
            location_tag = "**[COMMON]**" if e.is_common else "[Individual]"
            lines.append(f"#### `{e.part_name}` {location_tag}")
            lines.append("")
            lines.append(f"- **File:** `{e.filepath}`")
            lines.append(f"- **SlotType:** `{e.slot_type}`")
            lines.append(f"- **Info Name:** {e.info_name}")
            if e.info_value:
                lines.append(f"- **Value:** {e.info_value}")
            lines.append("")

            # Powertrain chain with full resolved chain
            lines.append("**Powertrain Chain:**")
            lines.append("```")

            if e.drivetrain_chain and e.drivetrain_chain.full_torque_path:
                # Show full resolved chain with source annotations
                lines.append('["type", "name", "inputName", "inputIndex"]  <- source')
                for d in e.drivetrain_chain.full_torque_path:
                    src = d.source_file or e.filename
                    lines.append(
                        f'["{d.type}", "{d.name}", "{d.inputName}", {d.inputIndex}]'
                        f'    <- {src}')
            else:
                # Fallback: transmission-only devices
                lines.append('["type", "name", "inputName", "inputIndex"]')
                for d in e.devices:
                    lines.append(
                        f'["{d.type}", "{d.name}", "{d.inputName}", {d.inputIndex}]')

            lines.append("```")
            lines.append("")

            # Full torque path visualization
            if e.drivetrain_chain and e.drivetrain_chain.full_torque_path:
                chain_str = e.drivetrain_chain.get_chain_string(max_branches=2)
                if chain_str:
                    lines.append(f"**Full Torque Path:** `{chain_str}`")
                    lines.append("")

                # Show resolved components
                if e.drivetrain_chain.components:
                    lines.append("**Resolved Drivetrain Components:**")
                    for comp in e.drivetrain_chain.components:
                        dev_str = ", ".join(
                            f"{d.type}({d.name})" for d in comp.devices)
                        lines.append(
                            f"  - `{comp.part_name}` "
                            f"(slot: `{comp.slot_type}`, "
                            f"file: `{comp.source_file}`): {dev_str}")
                    lines.append("")

                # Power splits
                if e.drivetrain_chain.split_points:
                    lines.append("**Power Split Points:** " +
                                 ", ".join(f"`{s}`" for s in e.drivetrain_chain.split_points))
                    lines.append("")
            else:
                # Legacy flow visualization
                if e.devices:
                    chain_parts = []
                    for d in e.devices:
                        chain_parts.append(f"{d.inputName} -> [{d.type}]{d.name}")
                    lines.append("**Flow:** " + " | ".join(chain_parts))
                    lines.append("")

            # Comments if any
            if e.comments:
                standalone = [c for c in e.comments if c.get('type') == 'standalone']
                if standalone:
                    lines.append("**Comments found in section:**")
                    for c in standalone:
                        lines.append(f"  - `// {c['text']}`")
                    lines.append("")

            # Slots
            if e.slots and isinstance(e.slots, list) and len(e.slots) > 1:
                lines.append("**Slots provided:**")
                lines.append("```")
                for s in e.slots:
                    if isinstance(s, list):
                        lines.append(str(s))
                    elif isinstance(s, dict):
                        lines.append(str(s))
                lines.append("```")
                lines.append("")

    # Parse failures
    if parse_failures:
        lines.append("## Parse Failures")
        lines.append("")
        for pf in parse_failures:
            lines.append(f"- `{pf}`")
        lines.append("")

    return '\n'.join(lines)


# =============================================================================
# Column-Aligned Markdown Table Builder
# =============================================================================

def _build_aligned_component_table(device_map: Dict[str, Dict]) -> List[str]:
    """Build a markdown table with columns padded to the widest cell in each column.

    Returns a list of lines (header, separator, data rows) ready to append.
    """
    headers = ["Component Name", "Type", "Input From", "InPort", "Source File"]

    # Build raw cell values for each row
    rows = []
    for name in sorted(device_map.keys()):
        dm = device_map[name]
        rows.append([
            f"`{name}`",
            f"`{dm['type']}`",
            f"`{dm['inputName']}`",
            str(dm['inputIndex']),
            f"`{dm['file']}`",
        ])

    # Compute max width per column (considering header and all data rows)
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Format a row with padded cells
    def fmt_row(cells: List[str]) -> str:
        padded = [cell.ljust(col_widths[i]) for i, cell in enumerate(cells)]
        return "| " + " | ".join(padded) + " |"

    # Build separator row with dashes filling column width
    sep = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"

    result = [fmt_row(headers), sep]
    for row in rows:
        result.append(fmt_row(row))
    return result


# =============================================================================
# Non-Transfercase Chain Analysis (Secondary Task)
# =============================================================================

def analyze_non_transfercase_chains(
    primary_entries: List[PowertrainEntry],
    supplemental_entries: List[PowertrainEntry],
) -> str:
    """
    Analyze how vehicles without transfer cases transmit power
    from engine to wheels. Traces the complete powertrain chain.
    """
    lines = []
    lines.append("# Drivetrain Chains for Vehicles Without Transfer Cases")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append("This report traces how vehicles that lack a dedicated transfer case component")
    lines.append("transmit power from the engine to the wheels. These vehicles use a simpler")
    lines.append("drivetrain architecture, typically omitting the transfer case in favor of")
    lines.append("direct driveshaft connections via `torsionReactor` and `shaft` devices.")
    lines.append("")

    # Build full device map keyed by vehicle
    all_entries = primary_entries + supplemental_entries
    by_vehicle = defaultdict(list)
    for e in all_entries:
        # Normalize vehicle name (strip simple_traffic/ prefix for comparison)
        base_vehicle = e.vehicle.replace('simple_traffic/', '')
        by_vehicle[base_vehicle].append(e)

    # Identify vehicles that have transfercase entries
    vehicles_with_tcase = set()
    for e in all_entries:
        base_vehicle = e.vehicle.replace('simple_traffic/', '')
        for d in e.devices:
            if 'transfercase' in d.name.lower() or 'transfercase' in d.type.lower():
                vehicles_with_tcase.add(base_vehicle)
            if d.type == 'splitShaft' and 'transfercase' in d.name.lower():
                vehicles_with_tcase.add(base_vehicle)
        if 'transfer' in e.filename.lower():
            vehicles_with_tcase.add(base_vehicle)

    # Find vehicles WITHOUT transfer cases
    all_vehicles = set(by_vehicle.keys())
    vehicles_without_tcase = all_vehicles - vehicles_with_tcase

    # Filter to actual drivable vehicles (exclude props, trailers, etc.)
    drivable_indicators = ['transmission', 'transaxle', 'engine', 'gearbox', 'differential']
    truly_drivable = set()
    for v in vehicles_without_tcase:
        v_entries = by_vehicle[v]
        for e in v_entries:
            fn_lower = e.filename.lower()
            if any(ind in fn_lower for ind in drivable_indicators):
                truly_drivable.add(v)
                break
            for d in e.devices:
                if d.type in ('manualGearbox', 'automaticGearbox', 'sequentialGearbox',
                              'dctGearbox', 'cvtGearbox', 'electricMotor'):
                    truly_drivable.add(v)
                    break

    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"- **Total vehicles with powertrain data:** {len(all_vehicles)}")
    lines.append(f"- **Vehicles WITH transfer case:** {len(vehicles_with_tcase)}")
    lines.append(f"- **Vehicles WITHOUT transfer case:** {len(vehicles_without_tcase)}")
    lines.append(f"- **Drivable vehicles without transfer case:** {len(truly_drivable)}")
    lines.append("")

    # Analyze each drivable vehicle without tcase
    lines.append("## Vehicle Detail")
    lines.append("")

    for vehicle in sorted(truly_drivable):
        v_entries = by_vehicle[vehicle]

        lines.append(f"### {vehicle}")
        lines.append("")

        # Build device chain graph
        device_map = {}
        file_map = defaultdict(list)

        for e in v_entries:
            for d in e.devices:
                device_map[d.name] = {
                    'type': d.type,
                    'inputName': d.inputName,
                    'inputIndex': d.inputIndex,
                    'file': e.filename,
                    'part': e.part_name,
                    'slot_type': e.slot_type,
                }
                file_map[e.filename].append(d.name)

        # Trace chains from mainEngine
        lines.append("**Component Map:**")
        lines.append("")
        lines.extend(_build_aligned_component_table(device_map))
        lines.append("")

        # Trace power flow
        lines.append("**Power Flow Chain:**")
        lines.append("")

        starts = [name for name, dm in device_map.items() if dm['inputName'] == 'mainEngine']

        if starts:
            for start in starts:
                chain = _trace_chain(start, device_map)
                chain_str = " -> ".join([f"`{c}`({device_map[c]['type']})" for c in chain])
                lines.append(f"  `mainEngine` -> {chain_str}")
        else:
            lines.append("  *(No direct mainEngine input found in traced entries)*")
        lines.append("")

        # File distribution
        lines.append("**Files contributing powertrain devices:**")
        for fn, devices in sorted(file_map.items()):
            lines.append(f"  - `{fn}`: {', '.join(devices)}")
        lines.append("")

    # Architecture classification
    lines.append("## Architecture Patterns")
    lines.append("")
    lines.append("### Pattern 1: Simple RWD (no transfer case)")
    lines.append("```")
    lines.append("mainEngine -> clutch/torqueConverter -> gearbox")
    lines.append("  (from transmission file)")
    lines.append("gearbox -> torsionReactor -> driveshaft")
    lines.append("  (from driveshaft file)")
    lines.append("driveshaft -> differential_R")
    lines.append("  (from differential file)")
    lines.append("```")
    lines.append("Vehicles: moonhawk, barstow, bluebuck, burnside, etc.")
    lines.append("")

    lines.append("### Pattern 2: Simple FWD (transaxle)")
    lines.append("```")
    lines.append("mainEngine -> clutch -> gearbox -> differential_F")
    lines.append("  (often all in transaxle file)")
    lines.append("```")
    lines.append("Vehicles: autobello, pessima, covet, etc.")
    lines.append("")

    lines.append("### Pattern 3: RWD micro-vehicle (pigeon)")
    lines.append("```")
    lines.append("mainEngine -> clutch -> gearbox")
    lines.append("  (from transmission file in common folder)")
    lines.append("gearbox -> torsionReactor -> driveshaft")
    lines.append("  (from driveshaft file)")
    lines.append("driveshaft -> differential_R")
    lines.append("  (from differential file)")
    lines.append("```")
    lines.append("Key insight: Identical architecture to full-size RWD, just smaller components.")
    lines.append("")

    lines.append("### Pattern 4: Electric / Hybrid")
    lines.append("```")
    lines.append("electricMotor -> gearbox -> differential")
    lines.append("```")
    lines.append("Vehicles: sbr (electric), simple_traffic electric variants")
    lines.append("")

    return '\n'.join(lines)


def _trace_chain(start_name: str, device_map: Dict) -> List[str]:
    """Trace a powertrain chain from a starting device."""
    chain = [start_name]
    visited = {start_name}

    current_names = [start_name]
    while current_names:
        next_names = []
        for cn in current_names:
            for name, dm in device_map.items():
                if dm['inputName'] == cn and name not in visited:
                    chain.append(name)
                    visited.add(name)
                    next_names.append(name)
        current_names = next_names

    return chain


# =============================================================================
# Architecture Diagrams
# =============================================================================

def generate_architecture_diagrams(entries: List[PowertrainEntry]) -> str:
    """Generate Mermaid diagrams of the main powertrain architecture patterns."""
    lines = []
    lines.append("# BeamNG Drivetrain Architecture Diagrams")
    lines.append("")

    # Classify entries by architecture pattern
    # Use full chain data when available for better classification
    patterns = defaultdict(list)
    for e in entries:
        # Collect all device types/names across the full chain
        all_device_types = [d.type for d in e.devices]
        all_device_names = [d.name for d in e.devices]
        if e.drivetrain_chain:
            for comp in e.drivetrain_chain.components:
                all_device_types.extend(d.type for d in comp.devices)
                all_device_names.extend(d.name for d in comp.devices)

        combined_names = ' '.join(all_device_names).lower()

        # Check device names for FWD vs RWD distinction.
        # Device names like 'differential_F' / 'differential_R' reliably
        # indicate axle position, whereas checking device *types* for
        # 'differential' is always True in fully-resolved chains.
        has_diff_F = any('differential_f' in n.lower() for n in all_device_names)
        has_diff_R = any('differential_r' in n.lower() for n in all_device_names)

        if 'transfercase' in combined_names:
            if 'rangeBox' in all_device_types:
                patterns['4WD with Rangebox'].append(e)
            elif 'splitShaft' in all_device_types:
                patterns['AWD Clutch-based'].append(e)
            elif has_diff_F and has_diff_R:
                patterns['AWD Differential'].append(e)
            elif has_diff_F and not has_diff_R:
                patterns['FWD Transaxle'].append(e)
            else:
                patterns['Transfer Case (other)'].append(e)
        elif 'torqueConverter' in all_device_types:
            if has_diff_F and not has_diff_R:
                patterns['Automatic Transaxle (FWD)'].append(e)
            else:
                patterns['Automatic Transmission (RWD)'].append(e)
        elif 'frictionClutch' in all_device_types:
            if has_diff_F and not has_diff_R:
                patterns['Manual Transaxle (FWD)'].append(e)
            else:
                patterns['Manual Transmission (RWD)'].append(e)
        elif 'dctGearbox' in all_device_types:
            patterns['Dual Clutch (DCT)'].append(e)
        elif 'cvtGearbox' in all_device_types:
            patterns['CVT'].append(e)
        elif 'electricMotor' in all_device_types:
            patterns['Electric'].append(e)
        elif 'centrifugalClutch' in all_device_types:
            patterns['Centrifugal Clutch'].append(e)
        elif 'sequentialGearbox' in all_device_types:
            patterns['Sequential'].append(e)
        else:
            patterns['Other'].append(e)

    # Summary table
    lines.append("## Architecture Pattern Distribution")
    lines.append("")
    lines.append("| Pattern | Count | Example Vehicles |")
    lines.append("|---------|-------|-----------------|")
    for pattern, p_entries in sorted(patterns.items(), key=lambda x: -len(x[1])):
        vehicles = sorted(set(e.vehicle for e in p_entries))[:4]
        examples = ', '.join(vehicles)
        lines.append(f"| {pattern} | {len(p_entries)} | {examples} |")
    lines.append("")

    # Mermaid diagrams
    lines.append("## Architecture Flow Diagrams")
    lines.append("")

    lines.append("### Standard Manual RWD Chain")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> FC[frictionClutch<br/>clutch]")
    lines.append("    FC --> MG[manualGearbox<br/>gearbox]")
    lines.append("    MG -->|via driveshaft file| TR[torsionReactor]")
    lines.append("    TR --> SH[shaft<br/>driveshaft]")
    lines.append("    SH -->|via differential file| DIFF[differential<br/>differential_R]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style DIFF fill:#9cf")
    lines.append("```")
    lines.append("")

    lines.append("### Standard Automatic RWD Chain")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> TC[torqueConverter]")
    lines.append("    TC --> AG[automaticGearbox<br/>gearbox]")
    lines.append("    AG -->|via driveshaft file| TR[torsionReactor]")
    lines.append("    TR --> SH[shaft<br/>driveshaft]")
    lines.append("    SH -->|via differential file| DIFF[differential<br/>differential_R]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style DIFF fill:#9cf")
    lines.append("```")
    lines.append("")

    lines.append("### FWD Transaxle Chain")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> FC[frictionClutch<br/>clutch]")
    lines.append("    FC --> MG[manualGearbox<br/>gearbox]")
    lines.append("    MG --> TC[shaft<br/>transfercase<br/>outputPortOverride: 2]")
    lines.append("    TC -->|via differential file| TRF[torsionReactor<br/>torsionReactorF]")
    lines.append("    TRF --> DIFF[differential<br/>differential_F]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style DIFF fill:#9cf")
    lines.append("```")
    lines.append("")

    lines.append("### 4WD with Transfer Case and Rangebox")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> CC[clutch/converter] --> GB[gearbox]")
    lines.append("    GB --> RB[rangeBox<br/>rangebox]")
    lines.append("    RB --> TCASE[differential<br/>transfercase<br/>locked/LSD]")
    lines.append("    TCASE -->|output 1| RSHAFT[Rear Driveshaft]")
    lines.append("    TCASE -->|output 2| FSHAFT[shaft<br/>transfercase_F<br/>disconnectable]")
    lines.append("    RSHAFT --> RDIFF[differential_R]")
    lines.append("    RDIFF --> RWL[Rear Left]")
    lines.append("    RDIFF --> RWR[Rear Right]")
    lines.append("    FSHAFT --> FDIFF[differential_F]")
    lines.append("    FDIFF --> FWL[Front Left]")
    lines.append("    FDIFF --> FWR[Front Right]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style TCASE fill:#f9f")
    lines.append("```")
    lines.append("")

    lines.append("### AWD Clutch-based Transfer Case (splitShaft)")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> CC[clutch/converter] --> GB[gearbox]")
    lines.append("    GB --> SS[splitShaft<br/>transfercase<br/>torque splitter]")
    lines.append("    SS -->|primary output| FDIFF[differential_F]")
    lines.append("    SS -->|secondary output| RSHAFT[Rear Driveshaft]")
    lines.append("    FDIFF --> FWL[Front Left]")
    lines.append("    FDIFF --> FWR[Front Right]")
    lines.append("    RSHAFT --> RDIFF[differential_R]")
    lines.append("    RDIFF --> RWL[Rear Left]")
    lines.append("    RDIFF --> RWR[Rear Right]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style SS fill:#f9f")
    lines.append("```")
    lines.append("")

    lines.append("### AWD Center Differential")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> CC[clutch/converter] --> GB[gearbox]")
    lines.append("    GB --> CDIFF[differential<br/>transfercase<br/>center diff]")
    lines.append("    CDIFF -->|output 1| RDIFF[differential_R]")
    lines.append("    CDIFF -->|output 2| DS[shaft<br/>driveshaft] --> TRF[torsionReactorF] --> FDIFF[differential_F]")
    lines.append("    RDIFF --> RWL[Rear Left]")
    lines.append("    RDIFF --> RWR[Rear Right]")
    lines.append("    FDIFF --> FWL[Front Left]")
    lines.append("    FDIFF --> FWR[Front Right]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style CDIFF fill:#f9f")
    lines.append("```")
    lines.append("")

    lines.append("### Dual Clutch Transmission (DCT)")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> DCT[dctGearbox<br/>gearbox<br/>internal clutches]")
    lines.append("    DCT -->|via driveshaft file| TR[torsionReactor]")
    lines.append("    TR --> SH[shaft<br/>driveshaft]")
    lines.append("    SH -->|via differential file| DIFF[differential<br/>differential_R]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style DCT fill:#fcf")
    lines.append("```")
    lines.append("")

    lines.append("### Mid-Engine RWD (Direct Transaxle)")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    ME[mainEngine] --> FC[frictionClutch<br/>clutch]")
    lines.append("    FC --> MG[manualGearbox<br/>gearbox]")
    lines.append("    MG -->|direct, no driveshaft| DIFF[differential<br/>differential_R]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style ME fill:#ff9")
    lines.append("    style DIFF fill:#9cf")
    lines.append("```")
    lines.append("")

    lines.append("### Electric Motor Drive")
    lines.append("```mermaid")
    lines.append("graph LR")
    lines.append("    EM[electricMotor] --> GB[gearbox<br/>reduction gear]")
    lines.append("    GB --> DIFF[differential]")
    lines.append("    DIFF --> WL[Left Wheel]")
    lines.append("    DIFF --> WR[Right Wheel]")
    lines.append("    style EM fill:#afa")
    lines.append("```")
    lines.append("")

    # Per-pattern vehicle listing with full chain strings
    lines.append("## Vehicles by Architecture Pattern")
    lines.append("")
    for pattern, p_entries in sorted(patterns.items(), key=lambda x: -len(x[1])):
        lines.append(f"### {pattern}")
        lines.append("")
        for e in sorted(p_entries, key=lambda x: (x.vehicle, x.part_name)):
            loc = "[COMMON]" if e.is_common else ""
            # Use full chain string if available, truncating at splits
            if e.drivetrain_chain and e.drivetrain_chain.full_torque_path:
                chain = e.drivetrain_chain.get_chain_string(max_branches=2)
            else:
                chain = " -> ".join(
                    [f"{d.type}({d.name})" for d in e.devices])
            lines.append(
                f"- **{e.vehicle}** `{e.part_name}` {loc}: {chain}")
        lines.append("")

    return '\n'.join(lines)


# =============================================================================
# Targeted Single-Vehicle Mode
# =============================================================================

def run_targeted(base_path: Path, output_dir: Path, vehicle_name: str,
                 include_simple_traffic: bool = False):
    """Run analysis for a single specified vehicle."""
    logger.info(f"=" * 70)
    logger.info(f"TARGETED MODE: Analyzing vehicle '{vehicle_name}'")
    logger.info(f"=" * 70)

    # Determine search folders
    folders = get_search_folders(base_path, vehicle_name)
    if not folders:
        logger.error(f"No folders found for vehicle '{vehicle_name}'")
        logger.info("Available vehicles:")
        for d in sorted(base_path.iterdir()):
            if d.is_dir() and (d / 'vehicles').exists():
                logger.info(f"  - {d.name}")
        sys.exit(1)

    logger.info(f"Search folders:")
    for f in folders:
        logger.info(f"  - {f}")

    # Build slot registry
    logger.info("")
    logger.info("Building slot registry...")
    registry = SlotRegistry(base_path)
    for folder in folders:
        registry.index_folder(folder)
    logger.info(f"  Indexed {len(registry.part_data)} parts, "
                f"{len(registry.slot_providers)} slot types, "
                f"{len(registry.powertrain_parts)} powertrain parts")

    # Extract primary entries (transmission/transfercase/transaxle)
    logger.info("")
    logger.info("Extracting powertrain entries...")
    extractor = PowertrainExtractor(base_path)

    # Process target files from the search folders
    patterns = ['*transmission*.jbeam', '*transfercase*.jbeam',
                '*tranfercase*.jbeam', '*transaxle*.jbeam']
    processed_files: Set[str] = set()
    for folder in folders:
        for pattern in patterns:
            for f in folder.rglob(pattern):
                fkey = str(f)
                if fkey not in processed_files:
                    processed_files.add(fkey)
                    extractor.process_file(f)

    # In targeted mode, classify entries to the target vehicle name,
    # but only keep common entries whose slotType is reachable from this
    # vehicle via the slot-chain BFS mapping (prevents false positives
    # like pigeon inheriting pickup_transmission/pickup_transfer_case).
    reachable_slottypes: Set[str] = set()
    for st, vehicles in extractor._common_to_vehicles.items():
        if vehicle_name in vehicles:
            reachable_slottypes.add(st)

    filtered_entries = []
    dropped = 0
    for entry in extractor.entries:
        if entry.is_common:
            if entry.slot_type and entry.slot_type not in reachable_slottypes:
                dropped += 1
                continue
            entry.vehicle = vehicle_name
        filtered_entries.append(entry)
    extractor.entries = filtered_entries
    if dropped:
        logger.debug(f"  Filtered {dropped} unreachable common entries")

    # Also filter property_lookup to drop unreachable common parts
    kept_parts = {e.part_name for e in extractor.entries}
    filtered_lookup: Dict[str, Dict[str, Any]] = {}
    for pname, props in extractor.property_lookup.items():
        if pname in kept_parts:
            filtered_lookup[pname] = props
            continue
        filepath = props.get('filepath', '')
        if 'common' in filepath.lower():
            st = registry.part_data.get(pname, {}).get('slotType', '')
            if isinstance(st, list):
                st = st[0] if st else ''
            if st and st not in reachable_slottypes:
                continue  # Drop unreachable common part
        filtered_lookup[pname] = props
    prop_dropped = len(extractor.property_lookup) - len(filtered_lookup)
    extractor.property_lookup = filtered_lookup
    if prop_dropped:
        logger.debug(f"  Filtered {prop_dropped} unreachable property_lookup entries")

    logger.info(f"  Found {len(extractor.entries)} powertrain entries")

    # Resolve drivetrain chains
    logger.info("")
    logger.info("Resolving drivetrain chains...")
    chain_builder = DrivetrainChainBuilder(registry,
                                            allowed_common_slottypes=reachable_slottypes)
    for entry in extractor.entries:
        try:
            chain = chain_builder.build_chain(entry)
            entry.drivetrain_chain = chain
            if chain.components:
                logger.info(
                    f"  {entry.part_name}: "
                    f"+{len(chain.components)} downstream components, "
                    f"{len(chain.full_torque_path)} total devices")
                chain_str = chain.get_chain_string()
                if chain_str:
                    logger.info(f"    Chain: {chain_str}")
        except Exception as ex:
            logger.warning(f"  Chain resolution failed for {entry.part_name}: {ex}")

    # Full scan for supplemental entries
    logger.info("")
    logger.info("Scanning for supplemental powertrain entries...")
    supplemental_entries = []
    primary_parts = {e.part_name for e in extractor.entries}
    for part_name, part_data in registry.powertrain_parts.items():
        if part_name in primary_parts:
            continue
        slot_type = part_data.get('slotType', '')
        if not isinstance(slot_type, str):
            slot_type = slot_type[0] if isinstance(slot_type, list) and slot_type else ''

        # In targeted mode, skip common entries whose slotType is not
        # reachable from this vehicle via the slot-chain BFS mapping.
        source_file = registry.part_file.get(part_name, Path('unknown'))
        is_common = 'common' in str(source_file).lower()
        if is_common and slot_type and slot_type not in reachable_slottypes:
            continue

        info = part_data.get('information', {})
        if not isinstance(info, dict):
            info = {}
        devices = _extract_powertrain_devices(part_data.get('powertrain', []))
        source_file = registry.part_file.get(part_name, Path('unknown'))
        for d in devices:
            d.source_file = source_file.name if isinstance(source_file, Path) else str(source_file)
            d.source_part = part_name

        try:
            rel = str(source_file.relative_to(base_path))
        except (ValueError, AttributeError):
            rel = str(source_file)

        entry = PowertrainEntry(
            vehicle=vehicle_name,
            filename=source_file.name if isinstance(source_file, Path) else str(source_file),
            filepath=rel,
            is_common='common' in str(source_file).lower(),
            part_name=part_name,
            slot_type=slot_type,
            info_name=info.get('name', ''),
            info_value=info.get('value', ''),
            info_authors=info.get('authors', ''),
            parent_slot_name=slot_type,
            devices=devices,
            slots=extractor._extract_slots(part_data),
        )
        supplemental_entries.append(entry)

    logger.info(f"  Found {len(supplemental_entries)} supplemental entries")

    # Generate outputs
    logger.info("")
    logger.info("Generating reports...")

    # Create targeted subdirectory
    targeted_dir = output_dir / f"targeted_{vehicle_name}"
    targeted_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_report = generate_json_report(extractor.entries, extractor.property_lookup)
    json_path = targeted_dir / "powertrain_report.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info(f"  JSON report: {json_path}")

    # Properties lookup
    props_path = targeted_dir / "powertrain_properties.json"
    with open(props_path, 'w', encoding='utf-8') as f:
        json.dump(extractor.property_lookup, f, indent=2, default=str)
    logger.info(f"  Properties lookup: {props_path}")

    # CSV
    csv_data = generate_csv(extractor.entries)
    csv_path = targeted_dir / "powertrain_table.csv"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(csv_data)
    logger.info(f"  CSV table: {csv_path}")

    # Markdown report
    md_report = generate_markdown_report(extractor.entries, extractor.parse_failures)
    md_path = targeted_dir / "powertrain_report.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_report)
    logger.info(f"  Markdown report: {md_path}")

    # Architecture diagrams
    diagrams = generate_architecture_diagrams(extractor.entries)
    diagrams_path = targeted_dir / "architecture_diagrams.md"
    with open(diagrams_path, 'w', encoding='utf-8') as f:
        f.write(diagrams)
    logger.info(f"  Architecture diagrams: {diagrams_path}")

    # Non-transfercase chains
    chains_report = analyze_non_transfercase_chains(
        extractor.entries, supplemental_entries)
    chains_path = targeted_dir / "non_transfercase_chains.md"
    with open(chains_path, 'w', encoding='utf-8') as f:
        f.write(chains_report)
    logger.info(f"  Chain analysis: {chains_path}")

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"TARGETED MODE COMPLETE: {vehicle_name}")
    logger.info("=" * 70)
    logger.info(f"Primary entries: {len(extractor.entries)}")
    logger.info(f"Supplemental entries: {len(supplemental_entries)}")
    logger.info(f"Entries with resolved chain: "
                f"{sum(1 for e in extractor.entries if e.drivetrain_chain and e.drivetrain_chain.components)}")
    logger.info(f"Output directory: {targeted_dir}")
    logger.info("")
    logger.info("Generated files:")
    for f in sorted(targeted_dir.iterdir()):
        size_kb = f.stat().st_size / 1024
        logger.info(f"  {f.name:40s} ({size_kb:.1f} KB)")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeamNG Powertrain Array Extraction & Analysis Tool')
    parser.add_argument(
        '--vehicle', '-v', type=str, default=None,
        help='Generate report for a single vehicle (targeted mode)')
    parser.add_argument(
        '--options', '-o', type=str, nargs='*', default=[],
        help='Toggle options. Available: simple_traffic (include simple_traffic vehicles)')
    args = parser.parse_args()

    include_simple_traffic = 'simple_traffic' in args.options

    base_path = Path(__file__).parent.parent / "SteamLibrary_content_vehicles"
    output_dir = Path(__file__).parent.parent / "docs" / "DrivetrainReports"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not base_path.exists():
        logger.error(f"Base path not found: {base_path}")
        sys.exit(1)

    # Targeted mode
    if args.vehicle:
        run_targeted(base_path, output_dir, args.vehicle,
                     include_simple_traffic=include_simple_traffic)
        return

    # =========================================================================
    # FULL MODE
    # =========================================================================

    if include_simple_traffic:
        logger.info("Option enabled: including simple_traffic vehicles")

    # Primary extraction
    logger.info("=" * 70)
    logger.info("PHASE 1: Primary Powertrain Extraction")
    logger.info("  Targeting: transmission, transfercase, transaxle files")
    logger.info("=" * 70)

    extractor = PowertrainExtractor(base_path, include_simple_traffic=include_simple_traffic)
    extractor.run_primary()

    # Drivetrain chain resolution
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 2: Drivetrain Chain Resolution")
    logger.info("  Resolving driveshaft/differential/halfshaft connections")
    logger.info("=" * 70)

    resolved_count = resolve_drivetrain_chains(base_path, extractor.entries)
    logger.info(f"  Resolved chains for {resolved_count} entries")

    # Generate primary outputs
    logger.info("")
    logger.info("Generating reports...")

    # JSON
    json_report = generate_json_report(extractor.entries, extractor.property_lookup)
    json_path = output_dir / "powertrain_report.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info(f"  JSON report: {json_path}")

    # Properties lookup
    props_path = output_dir / "powertrain_properties.json"
    with open(props_path, 'w', encoding='utf-8') as f:
        json.dump(extractor.property_lookup, f, indent=2, default=str)
    logger.info(f"  Properties lookup: {props_path}")

    # CSV
    csv_data = generate_csv(extractor.entries)
    csv_path = output_dir / "powertrain_table.csv"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(csv_data)
    logger.info(f"  CSV table: {csv_path}")

    # Markdown report
    md_report = generate_markdown_report(extractor.entries, extractor.parse_failures)
    md_path = output_dir / "powertrain_report.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_report)
    logger.info(f"  Markdown report: {md_path}")

    # Architecture diagrams
    diagrams = generate_architecture_diagrams(extractor.entries)
    diagrams_path = output_dir / "architecture_diagrams.md"
    with open(diagrams_path, 'w', encoding='utf-8') as f:
        f.write(diagrams)
    logger.info(f"  Architecture diagrams: {diagrams_path}")

    # Secondary analysis: Full scan for non-transfercase chains
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 3: Full Powertrain Chain Analysis")
    logger.info("  Scanning ALL files with powertrain arrays for chain tracing")
    logger.info("=" * 70)

    supplemental_entries = extractor.run_full_scan()

    chains_report = analyze_non_transfercase_chains(extractor.entries, supplemental_entries)
    chains_path = output_dir / "non_transfercase_chains.md"
    with open(chains_path, 'w', encoding='utf-8') as f:
        f.write(chains_report)
    logger.info(f"  Chain analysis: {chains_path}")

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Primary entries: {len(extractor.entries)}")
    logger.info(f"Entries with resolved chain: {resolved_count}")
    logger.info(f"Supplemental entries: {len(supplemental_entries)}")
    logger.info(f"Parse failures: {len(extractor.parse_failures)}")
    logger.info(f"Output directory: {output_dir}")
    logger.info("")
    logger.info("Generated files:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            size_kb = f.stat().st_size / 1024
            logger.info(f"  {f.name:40s} ({size_kb:.1f} KB)")


if __name__ == '__main__':
    main()
