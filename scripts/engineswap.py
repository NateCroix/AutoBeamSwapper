#!/usr/bin/env python3
"""
BeamNG Engine Transplant Utility

Automated tool for adapting engine .jbeam files from Automation or donor vehicles
to work with BeamNG original content vehicles.

This utility analyzes engine characteristics, identifies vehicle architecture patterns,
and generates adapted engine configurations with proper slotType matching and
component dependencies.

Author: NateCroix + BeamNG Modding Community
License: MIT
Python: 3.11+
"""

"""
Usage:

python scripts/engineswap.py <mode> <engine_jbeam_path> <target_vehicle> [options]
modes: plan, visualize, generate
options: --show-files --show-transforms --package
Examples:
python scripts/engineswap.py plan "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/eng_3813e/camso_engine_3813e.jbeam" pickup
python scripts/engineswap.py generate "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/eng_3813e/camso_engine_3813e.jbeam" pickup --show-files --show-transforms
python scripts/engineswap.py generate "mods/unpacked/persh_crayenne_moracc/vehicles/persh_crayenne_moracc/eng_3813e/camso_engine_3813e.jbeam" pickup --show-files --show-transforms --package
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

# Import TMS (Transplant Mounting Solver)
try:
    from mount_solver import (
        solve_engine_mount, 
        generate_engine_beams, 
        generate_mount_beams, 
        generate_transmission_beams,
        EngineCube,
        TransmissionNode,
        TransmissionStructure,
        TargetVehicleExtractor,
        DonorDriveTypeExtractor,
        DriveType,
        Vec3
    )
    TMS_AVAILABLE = True
    # Single source of truth for node mapping
    CAMSO_TO_BEAMNG_NODE_MAP = EngineCube.CAMSO_TO_BEAMNG_MAP
except ImportError:
    TMS_AVAILABLE = False
    logging.warning("mount_solver.py not available - mounting solver disabled")
    # Fallback map if mount_solver not available
    CAMSO_TO_BEAMNG_NODE_MAP = {
        "engine0": "e2r", "engine1": "e2l", "engine2": "e1l", "engine3": "e1r",
        "engine4": "e4r", "engine5": "e4l", "engine6": "e3l", "engine7": "e3r",
    }

# Import Slot Graph (unified slot dependency management)
try:
    from slot_graph import (
        SlotGraph,
        SlotGraphBuilder,
        SlotDispositionRules,
        SlotTransformationPlanner,
        SlotTransformationExecutor,
        SlotAwareJBeamWriter,
        SlotAwareManifestGenerator,
        SlotDisposition,
        SlotState,
        AssetRole,
        build_slot_graph,
        plan_and_execute_transformations,
        extract_slot_suffix,
        apply_slot_suffix,
        match_slot_base,
    )
    SLOT_GRAPH_AVAILABLE = True
except ImportError:
    SLOT_GRAPH_AVAILABLE = False
    logging.warning("slot_graph.py not available - slot graph features disabled")

# Import Exhaust Solver (exhaust bridge component generation)
try:
    from exhaust_solver import (
        select_strategy as exhaust_select_strategy,
        extract_isExhaust_nodes as exhaust_extract_isExhaust_nodes,
        IsExhaustNode,
        ExhaustSolverResult,
    )
    EXHAUST_SOLVER_AVAILABLE = True
except ImportError:
    EXHAUST_SOLVER_AVAILABLE = False
    logging.warning("exhaust_solver.py not available - exhaust solver disabled")

# Import Powertrain Property Tweaks (post-processing module)
try:
    from powertrain_tweaks import apply_tweaks, TweakContext, format_results_summary
    POWERTRAIN_TWEAKS_AVAILABLE = True
except ImportError:
    POWERTRAIN_TWEAKS_AVAILABLE = False
    logging.warning("powertrain_tweaks.py not available - powertrain tweaks disabled")

# Import Powertrain Analysis (target vehicle TC catalog & drive type classification)
try:
    from analyze_powertrains import (
        SlotRegistry,
        DrivetrainChainBuilder,
        PowertrainExtractor,
        PowertrainEntry,
        DrivetrainChain,
        DrivetrainComponent,
        PowertrainDevice as APowertrainDevice,
        get_search_folders,
    )
    POWERTRAIN_ANALYSIS_AVAILABLE = True
except ImportError:
    POWERTRAIN_ANALYSIS_AVAILABLE = False
    logging.warning("analyze_powertrains.py not available - target powertrain analysis disabled")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Drivetrain Swap Strategy Constants (Phase 3)
# =============================================================================

# Strategy lookup: (camso_drive_type, beamng_drive_type) -> strategy
# See DrivetrainSwapLogic_DevelopmentPhases.md for full decision table rationale.
SWAP_STRATEGY: Dict[Tuple[str, str], str] = {
    ('RWD', 'RWD'): 'DIRECT',
    ('RWD', 'FWD'): 'REFUSE',
    ('RWD', 'AWD'): 'MAKE_RWD',
    ('RWD', '4WD'): 'MAKE_RWD',
    ('RWD', 'NO_TC_RWD'): 'SYNTH_TC',
    ('RWD', 'NO_TC_FWD'): 'REFUSE',
    ('FWD', 'RWD'): 'REFUSE',
    ('FWD', 'FWD'): 'DIRECT',
    ('FWD', 'AWD'): 'MAKE_FWD',
    ('FWD', '4WD'): 'MAKE_FWD',
    ('FWD', 'NO_TC_RWD'): 'REFUSE',
    ('FWD', 'NO_TC_FWD'): 'SYNTH_TC',
    ('AWD', 'RWD'): 'REFUSE',
    ('AWD', 'FWD'): 'REFUSE',
    ('AWD', 'AWD'): 'DIRECT_AWD',
    ('AWD', '4WD'): 'MAKE_AWD',
    ('AWD', 'NO_TC_RWD'): 'REFUSE',
    ('AWD', 'NO_TC_FWD'): 'REFUSE',
    ('4WD', 'RWD'): 'REFUSE',
    ('4WD', 'FWD'): 'REFUSE',
    ('4WD', 'AWD'): 'REFUSE',    # MAKE_4WD deferred (cost=99)
    ('4WD', '4WD'): 'DIRECT',
    ('4WD', 'NO_TC_RWD'): 'REFUSE',
    ('4WD', 'NO_TC_FWD'): 'REFUSE',
}

# Cost of each strategy — lower is better, >=99 means REFUSE.
ADAPTATION_COST: Dict[str, int] = {
    'DIRECT': 0,
    'DIRECT_AWD': 0,
    'MAKE_AWD': 1,
    'MAKE_RWD': 3,
    'MAKE_FWD': 4,
    'SYNTH_TC': 5,
    'REFUSE': 99,
}


class VehicleArchitecture(Enum):
    """BeamNG vehicle engine integration architecture types."""
    DIRECT = "direct"  # Vehicle-specific engines in vehicle folder
    COMMON = "common"  # Shared engines in vehicles/common/{family}/
    SUBMODEL = "submodel"  # Cross-model references via .pc files
    UNKNOWN = "unknown"


@dataclass
class EngineCharacteristics:
    """Core engine performance and physical characteristics."""
    name: str
    slot_type: str
    torque_curve: List[Tuple[float, float]] = field(default_factory=list)  # [(rpm, torque)]
    idle_rpm: float = 0.0
    max_rpm: float = 0.0
    redline_rpm: float = 0.0
    inertia: float = 0.0
    friction: float = 0.0
    dynamic_friction: float = 0.0
    radiator_area: float = 0.0
    radiator_effectiveness: float = 0.0
    coolant_volume: float = 0.0
    required_slots: List[str] = field(default_factory=list)
    node_positions: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)
    torque_reaction_nodes: List[str] = field(default_factory=list)
    sound_config: Dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        return (f"EngineCharacteristics(name='{self.name}', "
                f"slot_type='{self.slot_type}', "
                f"max_rpm={self.max_rpm})")


@dataclass
class EngineMeshInfo:
    """
    Engine mesh flexbody information extracted from Camso engine_structure.
    
    Contains mesh name and transform (position, rotation, scale) that can be
    adjusted by TMS translation for proper positioning in target vehicle.
    
    Attributes:
        mesh_name: Name of the mesh asset (e.g., "ec8ba_engine0")
        groups: Node groups the mesh attaches to (e.g., ["engine"])
        non_flex_materials: Materials that don't flex
        pos: Position offset {x, y, z}
        rot: Rotation {x, y, z} in degrees
        scale: Scale {x, y, z}
        part_name: Original part name (e.g., "Camso_engine_mesh_ec8ba")
        slot_type: Slot type (e.g., "Camso_engine_mesh")
        info: Information section from original part
    """
    mesh_name: str
    groups: List[str] = field(default_factory=list)
    non_flex_materials: List[str] = field(default_factory=list)
    pos: Dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})
    rot: Dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})
    scale: Dict[str, float] = field(default_factory=lambda: {"x": 1, "y": 1, "z": 1})
    part_name: str = ""
    slot_type: str = ""
    info: Dict[str, Any] = field(default_factory=dict)
    
    def with_translation(self, translation_x: float, translation_y: float, translation_z: float) -> 'EngineMeshInfo':
        """
        Create a new EngineMeshInfo with translation applied to position.
        
        Args:
            translation_x: X offset to add
            translation_y: Y offset to add
            translation_z: Z offset to add
            
        Returns:
            New EngineMeshInfo with translated position
        """
        new_pos = {
            "x": self.pos.get("x", 0) + translation_x,
            "y": self.pos.get("y", 0) + translation_y,
            "z": self.pos.get("z", 0) + translation_z
        }
        return EngineMeshInfo(
            mesh_name=self.mesh_name,
            groups=self.groups.copy(),
            non_flex_materials=self.non_flex_materials.copy(),
            pos=new_pos,
            rot=self.rot.copy(),
            scale=self.scale.copy(),
            part_name=self.part_name,
            slot_type=self.slot_type,
            info=self.info.copy()
        )
    
    def to_flexbody_row(self) -> List[Any]:
        """
        Convert to JBeam flexbodies row format.
        
        Returns:
            List in format: [mesh_name, [groups], [materials], {pos, rot, scale}]
        """
        transform = {
            "pos": self.pos,
            "rot": self.rot,
            "scale": self.scale
        }
        return [
            self.mesh_name,
            self.groups,
            self.non_flex_materials,
            transform
        ]


@dataclass
class VehicleInfo:
    """Information about a target or donor vehicle."""
    name: str
    architecture: VehicleArchitecture
    base_path: Path
    engine_slot_type: Optional[str] = None
    mount_slot_type: Optional[str] = None
    available_slots: List[str] = field(default_factory=list)
    existing_engines: List[str] = field(default_factory=list)
    pc_config: Optional[Dict[str, Any]] = None
    
    def __repr__(self) -> str:
        return (f"VehicleInfo(name='{self.name}', "
                f"architecture={self.architecture.value}, "
                f"slot_type='{self.engine_slot_type}', "
                f"mount_type='{self.mount_slot_type}')")



class JBeamWriter:
    """
    Writer for BeamNG .jbeam files with proper formatting.
    
    Consolidates all formatting logic for consistent output across:
    - Engine adaptation
    - Transmission adaptation
    - Future modules (exhaust, drivetrain, etc.)
    
    Formatting Conventions:
    - Tabs for indentation (BeamNG convention)
    - Aligned node coordinates (10 chars, 6 decimal places)
    - Compact numeric tables (each row on single line)
    - Property modifiers emitted once, nodes inherit
    
    Usage:
        writer = JBeamWriter()
        writer.write(file_path, jbeam_data)
    """
    
    @staticmethod
    def format_node_row(node_row: List) -> str:
        """
        Format a node row with aligned columns.
        
        Output format: ["name", x, y, z, {props}] or ["name", x, y, z]
        Coordinates aligned to fixed widths for vertical selection editing.
        """
        if not isinstance(node_row, list) or len(node_row) < 4:
            return json.dumps(node_row)
        
        name = node_row[0]
        x, y, z = node_row[1], node_row[2], node_row[3]
        props = node_row[4] if len(node_row) > 4 else None
        
        # Check if this is a header row (all string values)
        if isinstance(x, str) and isinstance(y, str) and isinstance(z, str):
            return json.dumps(node_row)
        
        # Format coordinates with fixed width (10 chars, 6 decimal places)
        x_str = f"{x:>10.6f}" if isinstance(x, (int, float)) else str(x)
        y_str = f"{y:>10.6f}" if isinstance(y, (int, float)) else str(y)
        z_str = f"{z:>10.6f}" if isinstance(z, (int, float)) else str(z)
        
        name_str = f'"{name}"'
        
        if props:
            props_str = json.dumps(props, separators=(',', ':'))
            return f'[{name_str}, {x_str}, {y_str}, {z_str}, {props_str}]'
        else:
            return f'[{name_str}, {x_str}, {y_str}, {z_str}]'
    
    @staticmethod
    def format_beam_row(beam_row: List) -> str:
        """
        Format a beam row with aligned columns.
        
        Output format: ["id1", "id2", {props}] or ["id1", "id2"]
        """
        if not isinstance(beam_row, list) or len(beam_row) < 2:
            return json.dumps(beam_row)
        
        id1 = beam_row[0]
        id2 = beam_row[1]
        props = beam_row[2] if len(beam_row) > 2 else None
        
        id1_str = f'"{id1}"'
        id2_str = f'"{id2}"'
        
        if props:
            props_str = json.dumps(props, separators=(',', ':'))
            return f'[{id1_str}, {id2_str}, {props_str}]'
        else:
            return f'[{id1_str}, {id2_str}]'
    
    @staticmethod
    def is_simple_value(value: Any) -> bool:
        """Check if value can be formatted on single line (no nesting)."""
        if isinstance(value, (str, int, float, bool, type(None))):
            return True
        if isinstance(value, list):
            return all(isinstance(v, (str, int, float, bool, type(None))) for v in value)
        return False
    
    @staticmethod
    def is_numeric_table(value: Any) -> bool:
        """Check if value is an array of numeric arrays (like torque curves)."""
        if not isinstance(value, list) or len(value) == 0:
            return False
        for item in value:
            if not isinstance(item, list):
                return False
            for v in item:
                if not isinstance(v, (int, float)):
                    return False
        return True
    
    @classmethod
    def format_compact_value(cls, value: Any, indent: str = "") -> str:
        """
        Format a value compactly - simple values inline, complex values indented.
        Uses tabs for indentation per BeamNG convention.
        """
        if isinstance(value, (str, int, float, bool, type(None))):
            return json.dumps(value)
        
        if isinstance(value, list):
            # Numeric table (torque curves, pressurePSI)
            if cls.is_numeric_table(value):
                lines = ["["]
                for i, row in enumerate(value):
                    comma = "," if i < len(value) - 1 else ""
                    row_str = json.dumps(row, separators=(', ', ':'))
                    lines.append(f"{indent}\t{row_str}{comma}")
                lines.append(f"{indent}]")
                return '\n'.join(lines)
            
            # Simple list (all primitives)
            if cls.is_simple_value(value):
                return json.dumps(value, separators=(', ', ':'))
            
            # Mixed/complex list
            lines = ["["]
            for i, item in enumerate(value):
                comma = "," if i < len(value) - 1 else ""
                if cls.is_simple_value(item):
                    item_str = json.dumps(item, separators=(', ', ':'))
                    lines.append(f"{indent}\t{item_str}{comma}")
                else:
                    item_str = cls.format_compact_value(item, indent + "\t")
                    lines.append(f"{indent}\t{item_str}{comma}")
            lines.append(f"{indent}]")
            return '\n'.join(lines)
        
        if isinstance(value, dict):
            # Simple dict fits on one line
            if all(cls.is_simple_value(v) for v in value.values()) and len(value) <= 3:
                return json.dumps(value, separators=(',', ':'))
            
            # Multi-line dict
            lines = ["{"]
            items = list(value.items())
            for i, (k, v) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                if cls.is_simple_value(v):
                    v_str = json.dumps(v, separators=(',', ':'))
                    lines.append(f'{indent}\t"{k}": {v_str}{comma}')
                else:
                    v_str = cls.format_compact_value(v, indent + "\t")
                    if '\n' in v_str:
                        v_lines = v_str.split('\n')
                        lines.append(f'{indent}\t"{k}": {v_lines[0]}')
                        for vl in v_lines[1:]:
                            lines.append(f'{indent}\t{vl}')
                        if comma:
                            lines[-1] = lines[-1] + comma
                    else:
                        lines.append(f'{indent}\t"{k}": {v_str}{comma}')
            lines.append(f"{indent}}}")
            return '\n'.join(lines)
        
        return json.dumps(value)
    
    @classmethod
    def format_slot_row(cls, slot_row: List) -> str:
        """
        Format a slot row as single line.
        
        Output: ["type", "default", "description", {options}] on one line
        """
        if not isinstance(slot_row, list):
            return json.dumps(slot_row, separators=(',', ':'))
        return json.dumps(slot_row, separators=(',', ':'))
    
    @classmethod
    def format_section(cls, section_name: str, section_data: Any, indent: str = "\t") -> Optional[str]:
        """
        Format a JBeam section with special handling for nodes, beams, and slots.
        Returns None if no special handling needed.
        """
        if section_name == "slots" and isinstance(section_data, list):
            lines = [f'{indent}"{section_name}": [']
            for i, row in enumerate(section_data):
                comma = "," if i < len(section_data) - 1 else ""
                lines.append(f'{indent}\t{cls.format_slot_row(row)}{comma}')
            lines.append(f'{indent}]')
            return '\n'.join(lines)
        
        elif section_name == "nodes" and isinstance(section_data, list):
            lines = [f'{indent}"{section_name}": [']
            for i, row in enumerate(section_data):
                comma = "," if i < len(section_data) - 1 else ""
                if isinstance(row, list) and len(row) >= 4 and isinstance(row[0], str):
                    lines.append(f'{indent}\t{cls.format_node_row(row)}{comma}')
                elif isinstance(row, dict):
                    # Property modifier row - use compact separators
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
                elif isinstance(row, list) and len(row) > 0 and row[0] == "id":
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
                else:
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
            lines.append(f'{indent}]')
            return '\n'.join(lines)
        
        elif section_name == "beams" and isinstance(section_data, list):
            lines = [f'{indent}"{section_name}": [']
            for i, row in enumerate(section_data):
                comma = "," if i < len(section_data) - 1 else ""
                if isinstance(row, list) and len(row) >= 2 and isinstance(row[0], str):
                    lines.append(f'{indent}\t{cls.format_beam_row(row)}{comma}')
                elif isinstance(row, dict):
                    # Property modifier row - use compact separators
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
                elif isinstance(row, list) and len(row) > 0 and row[0] == "id1:":
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
                else:
                    lines.append(f'{indent}\t{json.dumps(row, separators=(",", ":"))}{comma}')
            lines.append(f'{indent}]')
            return '\n'.join(lines)
        
        return None
    
    @classmethod
    def write(cls, file_path: Path, jbeam_data: Dict[str, Any]) -> None:
        """
        Write JBeam data to file with proper formatting.
        
        Args:
            file_path: Output file path
            jbeam_data: Dictionary of part_name -> part_data
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('{\n')
            
            for part_idx, (part_name, part_data) in enumerate(jbeam_data.items()):
                f.write(f'"{part_name}": {{\n')
                
                part_items = list(part_data.items())
                for i, (key, value) in enumerate(part_items):
                    is_last = (i == len(part_items) - 1)
                    comma = "" if is_last else ","
                    
                    # Try special formatting for nodes/beams
                    special_format = cls.format_section(key, value, "\t")
                    
                    if special_format:
                        f.write(special_format + comma + '\n')
                    else:
                        # Use compact formatting
                        value_str = cls.format_compact_value(value, "\t")
                        
                        if '\n' in value_str:
                            v_lines = value_str.split('\n')
                            f.write(f'\t"{key}": {v_lines[0]}\n')
                            for vl in v_lines[1:-1]:
                                f.write(f'\t{vl}\n')
                            f.write(f'\t{v_lines[-1]}{comma}\n')
                        else:
                            f.write(f'\t"{key}": {value_str}{comma}\n')
                
                if part_idx < len(jbeam_data) - 1:
                    f.write('},\n')
                else:
                    f.write('}\n')
            
            f.write('}\n')


class JBeamParser:
    """
    Parser for BeamNG .jbeam files with lenient JSON parsing.
    
    Handles BeamNG's relaxed JSON format:
    - Comments (// and /* */)
    - Optional commas (ALL commas are optional in JBeam)
    - Trailing commas before ] or }
    
    Pattern strategy derived from JBeamToJson (github.com/bhowiebkr).
    The key insight is matching COMPLETE quoted strings as atomic units
    to prevent corruption of string contents like "engine0".
    
    See docs/jBeam_syntax.md for authoritative JBeam format documentation.
    """
    
    @staticmethod
    def strip_comments(content: str) -> str:
        """Remove JavaScript-style comments from content.
        
        Uses a placeholder-protection strategy to safely remove comments
        while preserving URL schemes (http://, https://, file://) that
        contain // but are NOT comments.
        
        Strategy:
        1. Protect known URL schemes by replacing with placeholders
        2. Remove all // line comments (now safe)
        3. Remove /* */ block comments
        4. Restore URL schemes from placeholders
        """
        # Step 1: Protect URL schemes by replacing with placeholders
        content = content.replace('https://', '<<<HTTPS_SCHEME>>>')
        content = content.replace('http://', '<<<HTTP_SCHEME>>>')
        content = content.replace('file://', '<<<FILE_SCHEME>>>')
        content = content.replace('local://', '<<<LOCAL_SCHEME>>>')
        
        # Step 2: Remove block comments (/* ... */)
        # Negative lookbehind prevents //** (decorated line comments) from
        # being treated as block comment starts.
        content = re.sub(r'(?<!/)/\*[\s\S]*?\*/', '', content, flags=re.DOTALL)
        
        # Step 3: Remove line comments (// to end of line)
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        
        # Step 4: Restore URL schemes
        content = content.replace('<<<HTTPS_SCHEME>>>', 'https://')
        content = content.replace('<<<HTTP_SCHEME>>>', 'http://')
        content = content.replace('<<<FILE_SCHEME>>>', 'file://')
        content = content.replace('<<<LOCAL_SCHEME>>>', 'local://')
        
        return content
    
    @staticmethod
    def add_missing_commas(content: str) -> str:
        """Add missing commas between JSON elements.
        
        JBeam allows ALL commas to be optional. This method adds them back
        for JSON parsing. The patterns are derived from the battle-tested
        JBeamToJson project and match COMPLETE structural units to avoid
        corrupting string contents.
        
        Pattern order matters - later patterns may depend on earlier fixes.
        """
        # Pattern 1: ] or } followed by { or [
        content = re.sub(r'(\]|})\s*?(\{|\[)', r'\1,\2', content)
        
        # Pattern 2: } or ] followed by "
        content = re.sub(r'(}|])\s*"', r'\1,"', content)
        
        # Pattern 3: " followed by { (value string then object)
        content = re.sub(r'"{', r'", {', content)
        
        # Pattern 4: " followed by whitespace then " or {
        content = re.sub(r'"\s+("|\{)', r'",\1', content)
        
        # Pattern 5: false or true followed by "
        content = re.sub(r'(false|true)\s+"', r'\1,"', content)
        
        # Pattern 6: Clean up any double commas introduced
        content = re.sub(r',\s*,', r',', content)
        
        # Pattern 7: Complete quoted string followed by [ or number (including negative)
        # This matches the ENTIRE quoted string to avoid mid-string corruption
        content = re.sub(r'("[a-zA-Z0-9_]*")\s(-?[0-9\[])', r'\1, \2', content)
        
        # Pattern 8: Number followed by {
        content = re.sub(r'(\d\.*\d*)\s*{', r'\1, {', content)
        
        # Pattern 9: Number at end of line (add comma for next line)
        content = re.sub(r'([0-9])\n', r'\1,\n', content)
        
        # Pattern 10: Two adjacent numbers separated by whitespace
        content = re.sub(r'(-?[0-9])\s+(-?[0-9])', r'\1,\2', content)
        
        # Pattern 11: Number followed by complete quoted string
        content = re.sub(r'([0-9])\s*("[a-zA-Z0-9_]*")', r'\1, \2', content)
        
        # Pattern 12: Two adjacent complete quoted strings (with optional whitespace)
        # Handles both "str""str" and "str" "str"
        content = re.sub(r'("[a-zA-Z0-9_$.]*")\s*("[a-zA-Z0-9_$.]*")', r'\1, \2', content)
        
        # Pattern 13: Handle key:value where value is incomplete (ends with :)
        content = re.sub(
            r'("[a-zA-Z0-9_]+"):(\s*"[a-zA-Z0-9_]+:)(\n\s*"[a-zA-Z]+")', 
            r'\1:\2",\n\3', content)
        
        # Pattern 14: false/true followed by quoted string key
        content = re.sub(r':(false|true)("[a-zA-Z_]+")', r':\1, \2', content)
        
        # Pattern 15: Quoted string followed by array notation
        content = re.sub(r'(["[a-zA-Z_0-9.?]+")\s(\["[a-zA-Z_]+"\]])', r'\1, \2', content)
        
        # Pattern 16: Fix malformed decimal numbers (missing zero after decimal)
        content = re.sub(r'("[a-zA-Z0-9]+"):(-?[0-9])\.,\s?"', r'\1:\2.0,"', content)
        
        # Pattern 17: Fix leading zeros in numbers (00 -> 0, 007 -> 7)
        # Handles both key:value (":0n") and array element (",0n" / "[0n") contexts
        content = re.sub(r':0+([0-9])', r':\1', content)
        content = re.sub(r'([,\[])0+([1-9])', r'\1\2', content)
        
        # Pattern 18: Strip explicit positive signs (+9 -> 9, +10.5 -> 10.5)
        # JSON does not allow leading '+' on numbers
        content = re.sub(r'([,\[:\s])\+(\d)', r'\1\2', content)
        
        return content
    
    @staticmethod
    def remove_trailing_commas(content: str) -> str:
        """Remove trailing commas before closing brackets/braces.
        
        Also performs final cleanup of any malformed comma sequences.
        """
        # Split into lines for line-by-line processing
        lines = content.split('\n')
        result_lines = []
        
        for i, line in enumerate(lines):
            # Fix various comma issues
            if ',,' in line:
                line = line.replace(',,', ',')
            if '[,' in line:
                line = line.replace('[,', '[')
            if '{,' in line:
                line = line.replace('{,', '{')
            if ',:' in line:
                line = line.replace(',:', ':')
            if ',}' in line:
                line = line.replace(',}', '}')
            if ',]' in line:
                line = line.replace(',]', ']')
            
            result_lines.append(line)
        
        content = '\n'.join(result_lines)
        
        # Final regex cleanup for any remaining trailing commas
        content = re.sub(r',\s*?(]|})', r'\1', content)
        
        # Handle trailing content issues at end of file
        if content.rstrip().endswith(','):
            content = content.rstrip()[:-1]
        
        # Balance braces if needed
        if content.count('{') != content.count('}'):
            # Try removing last character if it's causing imbalance
            if content.rstrip().endswith('}'):
                content = content.rstrip()[:-1]
        
        return content
    
    @classmethod
    def parse_jbeam(cls, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse a .jbeam file and return its contents as a dictionary.
        
        Args:
            file_path: Path to the .jbeam file
            
        Returns:
            Parsed JSON data as dictionary, or None if parsing fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Clean up content
            content = cls.strip_comments(content)
            content = cls.add_missing_commas(content)
            content = cls.remove_trailing_commas(content)
            
            # Debug: save preprocessed content
            if logger.isEnabledFor(logging.DEBUG):
                debug_path = file_path.with_suffix('.jbeam.debug')
                debug_path.write_text(content, encoding='utf-8')
            
            # Parse JSON
            data = json.loads(content)
            logger.debug(f"Successfully parsed {file_path.name}")
            return data
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error in {file_path.name}: {e}")
            logger.debug(f"  Full path: {file_path}")
            return None
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            return None
        except Exception as e:
            logger.warning(f"Error parsing {file_path.name}: {e}")
            return None
    
    @classmethod
    def extract_slot_type(cls, jbeam_data: Dict[str, Any]) -> Optional[str]:
        """Extract slotType from parsed jbeam data."""
        for part_name, part_data in jbeam_data.items():
            if isinstance(part_data, dict) and 'slotType' in part_data:
                return part_data['slotType']
        return None
    
    @classmethod
    def extract_engine_characteristics(cls, jbeam_data: Dict[str, Any]) -> Optional[EngineCharacteristics]:
        """
        Extract engine characteristics from parsed jbeam data.
        
        Args:
            jbeam_data: Parsed .jbeam file contents
            
        Returns:
            EngineCharacteristics object or None if not an engine part
        """
        # Find the main engine part
        for part_name, part_data in jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            slot_type = part_data.get('slotType', '')
            
            # Check if this is an engine part
            if 'engine' not in slot_type.lower() and 'mainEngine' not in part_data:
                continue
            
            # Extract information section
            info = part_data.get('information', {})
            name = info.get('name', part_name)
            
            # Extract main engine data
            main_engine = part_data.get('mainEngine', {})
            
            # Extract torque curve
            torque_curve = []
            if 'torque' in main_engine and isinstance(main_engine['torque'], list):
                for entry in main_engine['torque']:
                    if isinstance(entry, list) and len(entry) >= 2:
                        try:
                            rpm = float(entry[0])
                            torque = float(entry[1])
                            torque_curve.append((rpm, torque))
                        except (ValueError, TypeError):
                            continue
            
            # Extract required slots
            required_slots = []
            if 'slots' in part_data and isinstance(part_data['slots'], list):
                for slot in part_data['slots']:
                    if isinstance(slot, list) and len(slot) > 0:
                        required_slots.append(slot[0])
            
            # Extract node positions
            node_positions = {}
            if 'nodes' in part_data and isinstance(part_data['nodes'], list):
                for node in part_data['nodes']:
                    if isinstance(node, list) and len(node) >= 4:
                        node_id = str(node[0])
                        try:
                            x, y, z = float(node[1]), float(node[2]), float(node[3])
                            node_positions[node_id] = (x, y, z)
                        except (ValueError, TypeError):
                            continue
            
            # Extract torque reaction nodes
            torque_reaction = main_engine.get('torqueReactionNodes:', [])
            if isinstance(torque_reaction, list):
                torque_reaction = [str(n) for n in torque_reaction]
            
            # Build characteristics object
            characteristics = EngineCharacteristics(
                name=name,
                slot_type=slot_type,
                torque_curve=torque_curve,
                idle_rpm=main_engine.get('idleRPM', 0.0),
                max_rpm=main_engine.get('maxRPM', 0.0),
                redline_rpm=main_engine.get('revLimitRPM', main_engine.get('maxRPM', 0.0)),
                inertia=main_engine.get('inertia', 0.0),
                friction=main_engine.get('friction', 0.0),
                dynamic_friction=main_engine.get('dynamicFriction', 0.0),
                radiator_area=main_engine.get('radiatorArea', 0.0),
                radiator_effectiveness=main_engine.get('radiatorEffectiveness', 0.0),
                coolant_volume=main_engine.get('coolantVolume', 0.0),
                required_slots=required_slots,
                node_positions=node_positions,
                torque_reaction_nodes=torque_reaction,
                sound_config=part_data.get('soundConfig', {})
            )
            
            logger.info(f"Extracted characteristics for engine: {name}")
            return characteristics
        
        logger.warning("No engine characteristics found in jbeam data")
        return None


class VehicleAnalyzer:
    """
    Analyzer for BeamNG vehicle structures to determine architecture type
    and compatibility requirements.
    """
    
    def __init__(self, base_vehicles_path: Path):
        """
        Initialize vehicle analyzer.
        
        Args:
            base_vehicles_path: Path to SteamLibrary_content_vehicles or equivalent
        """
        self.base_vehicles_path = Path(base_vehicles_path)
        
    def detect_architecture(self, vehicle_name: str) -> VehicleArchitecture:
        """
        Detect which architecture pattern a vehicle uses.
        
        Args:
            vehicle_name: Name of the vehicle (e.g., 'pickup', 'etk800')
            
        Returns:
            VehicleArchitecture enum value
        """
        vehicle_path = self.base_vehicles_path / vehicle_name / "vehicles" / vehicle_name
        
        if not vehicle_path.exists():
            logger.warning(f"Vehicle path not found: {vehicle_path}")
            return VehicleArchitecture.UNKNOWN
        
        # Check for .pc files (submodel architecture)
        pc_files = list(vehicle_path.glob("*.pc"))
        if pc_files:
            logger.info(f"{vehicle_name} uses SUBMODEL architecture (.pc files found)")
            return VehicleArchitecture.SUBMODEL
        
        # Check for common folder usage
        common_path = self.base_vehicles_path / "common" / "vehicles" / "common"
        if common_path.exists():
            # Check if vehicle references common engines
            jbeam_files = list(vehicle_path.glob("*.jbeam"))
            for jbeam_file in jbeam_files:
                content = jbeam_file.read_text(encoding='utf-8', errors='ignore')
                if f"common/{vehicle_name}" in content or "vehicles/common" in content:
                    logger.info(f"{vehicle_name} uses COMMON architecture")
                    return VehicleArchitecture.COMMON
        
        # Check for direct engine files in vehicle folder
        engine_files = list(vehicle_path.glob("*engine*.jbeam"))
        if engine_files:
            logger.info(f"{vehicle_name} uses DIRECT architecture (engine files in vehicle folder)")
            return VehicleArchitecture.DIRECT
        
        logger.warning(f"Could not determine architecture for {vehicle_name}")
        return VehicleArchitecture.UNKNOWN
    
    def find_engine_slot_type(self, vehicle_name: str) -> Optional[str]:
        """
        Find the expected engine slotType for a vehicle.
        
        Args:
            vehicle_name: Name of the vehicle
            
        Returns:
            Expected engine slotType string, or None if not found
        """
        vehicle_path = self.base_vehicles_path / vehicle_name / "vehicles" / vehicle_name
        
        if not vehicle_path.exists():
            return None
        
        # Search through jbeam files for engine slot references
        jbeam_files = list(vehicle_path.glob("*.jbeam"))
        
        for jbeam_file in jbeam_files:
            data = JBeamParser.parse_jbeam(jbeam_file)
            if not data:
                continue
            
            # Look for slot definitions that reference engines
            for part_name, part_data in data.items():
                if not isinstance(part_data, dict):
                    continue
                
                slots = part_data.get('slots', [])
                for slot in slots:
                    if isinstance(slot, list) and len(slot) > 0:
                        slot_type = str(slot[0])
                        if 'engine' in slot_type.lower():
                            logger.info(f"Found engine slot type for {vehicle_name}: {slot_type}")
                            return slot_type
        
        # Fallback: assume standard naming pattern
        fallback = f"{vehicle_name}_engine"
        logger.info(f"Using fallback engine slot type: {fallback}")
        return fallback
    
    def find_mount_slot_type(self, vehicle_name: str,
                             engine_slot_type: Optional[str] = None) -> Optional[str]:
        """
        Dynamically discover the enginemounts slot type from target engine files.
        
        Reads actual slot entries in target engine .jbeam files rather than
        synthesizing a name. Handles family-shared architectures (e.g., etk800
        uses etk_enginemounts defined in common/vehicles/common/etk/).
        
        Args:
            vehicle_name: Name of the vehicle (e.g., 'etk800')
            engine_slot_type: Already-discovered engine slot type (e.g., 'etk_engine').
                Used to derive family prefix for common-folder search paths.
            
        Returns:
            Actual enginemounts slot type string, or None if not found
        """
        # Build search paths: vehicle-specific, common/vehicle, common/family
        search_paths = []
        
        vehicle_path = self.base_vehicles_path / vehicle_name / "vehicles" / vehicle_name
        if vehicle_path.exists():
            search_paths.append((vehicle_path, vehicle_name))
        
        common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / vehicle_name
        if common_path.exists():
            search_paths.append((common_path, vehicle_name))
        
        # Derive family prefix from engine_slot_type for shared architectures
        # e.g., engine_slot_type="etk_engine" -> family_prefix="etk"
        family_prefix = None
        if engine_slot_type:
            prefix = engine_slot_type.replace('_engine', '')
            if prefix != vehicle_name:
                family_prefix = prefix
                family_common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / prefix
                if family_common_path.exists():
                    search_paths.append((family_common_path, prefix))
        
        # Search engine files for enginemounts slot entries
        for search_dir, prefix in search_paths:
            engine_files = list(search_dir.glob(f"{prefix}_engine*.jbeam"))
            # Exclude subcomponent files that wouldn't define mount slots
            _exclude_kw = ('management', 'ecu', 'internals', 'speedlimit', 'logo')
            engine_files = [f for f in engine_files
                           if not any(kw in f.stem.lower() for kw in _exclude_kw)]
            
            for engine_file in engine_files:
                data = JBeamParser.parse_jbeam(engine_file)
                if not data:
                    continue
                
                for part_name, part_data in data.items():
                    if not isinstance(part_data, dict):
                        continue
                    
                    slots = part_data.get('slots', [])
                    for slot in slots:
                        if isinstance(slot, list) and len(slot) > 0:
                            slot_type = str(slot[0])
                            if 'enginemounts' in slot_type.lower():
                                logger.info(f"Found mount slot type for {vehicle_name}: {slot_type} (from {engine_file.name})")
                                return slot_type
        
        # Fallback: use family prefix if available, otherwise vehicle name
        fallback_prefix = family_prefix or vehicle_name
        fallback = f"{fallback_prefix}_enginemounts"
        logger.warning(f"Mount slot type not found in engine files, using fallback: {fallback}")
        return fallback
    
    def analyze_vehicle(self, vehicle_name: str) -> VehicleInfo:
        """
        Perform complete analysis of a vehicle.
        
        Args:
            vehicle_name: Name of the vehicle
            
        Returns:
            VehicleInfo object with analysis results
        """
        architecture = self.detect_architecture(vehicle_name)
        engine_slot_type = self.find_engine_slot_type(vehicle_name)
        mount_slot_type = self.find_mount_slot_type(vehicle_name, engine_slot_type)
        vehicle_path = self.base_vehicles_path / vehicle_name / "vehicles" / vehicle_name
        
        vehicle_info = VehicleInfo(
            name=vehicle_name,
            architecture=architecture,
            base_path=vehicle_path,
            engine_slot_type=engine_slot_type,
            mount_slot_type=mount_slot_type
        )
        
        logger.info(f"Vehicle analysis complete: {vehicle_info}")
        return vehicle_info


class EngineTransplantUtility:
    """
    Main utility class for engine transplant operations.
    
    Coordinates parsing, analysis, adaptation, and validation of engine swaps.
    """
    
    def __init__(self, 
                 base_vehicles_path: Path,
                 output_path: Path,
                 workspace_subfolder: str = "temp",
                 target_engine_file: Optional[str] = None,
                 swap_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the engine transplant utility.
        
        Args:
            base_vehicles_path: Path to BeamNG base game vehicles
            output_path: Path for output files (e.g., mods/unpacked/engineswaps/vehicles/)
            workspace_subfolder: Subfolder name for current workspace (default: "temp", or vehicle name)
            target_engine_file: Optional override for target engine selection (filename only, e.g., "pickup_engine_v8_5.5.jbeam")
            swap_config: Optional swap configuration dict (for slot_rules, etc.)
        """
        self.base_vehicles_path = Path(base_vehicles_path)
        self.output_path = Path(output_path)
        self.workspace_subfolder = workspace_subfolder
        self.temp_path = self.output_path / workspace_subfolder
        self.vehicle_analyzer = VehicleAnalyzer(base_vehicles_path)
        
        # Store target engine override (filename only)
        self._target_engine_override = target_engine_file
        
        # Store swap configuration for slot graph rules
        self._swap_config = swap_config or {}
        
        # Store last solver result for use by transmission adaptation
        self._last_solver_result = None
        
        # Store last donor drive type for use by transfer case adaptation
        self._last_donor_drive_type = None
        
        # Store last mesh info and translation for mesh part generation
        self._last_mesh_info = None
        self._last_translation = None
        
        # Store last TC adaptation summary for manifest generation (Phase 6)
        self._last_tc_adaptation_summary = None
        self._last_swap_decision = None
        
        # Store donor engine torque table and idle RPM for powertrain tweaks
        # Raw table cached as-is (supports both Camso 5-col and BeamNG 2-col formats)
        self._last_donor_torque_table = None  # List[List[number]] — raw rows from mainEngine.torque
        self._last_donor_idle_rpm = None      # float — mainEngine.idleRPM
        
        # Store last exhaust solver result for manifest generation
        self._last_exhaust_result = None
        
        # Slot Graph for unified slot dependency management
        # Built per-swap via _build_slot_graph(), stores mappings for consistent naming
        self._slot_graph: Optional['SlotGraph'] = None
        
        # Ensure output directories exist
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized EngineTransplantUtility")
        logger.info(f"  Base vehicles: {self.base_vehicles_path}")
        logger.info(f"  Output path: {self.output_path}")
        logger.info(f"  Workspace: {self.temp_path} (subfolder: {workspace_subfolder})")
        if SLOT_GRAPH_AVAILABLE:
            logger.info(f"  Slot Graph: ENABLED")
    
    def load_donor_engine(self, engine_file_path: Path) -> Optional[EngineCharacteristics]:
        """
        Load and parse a donor engine from a .jbeam file.
        
        Args:
            engine_file_path: Path to donor engine .jbeam file
            
        Returns:
            EngineCharacteristics object or None if parsing fails
        """
        logger.info(f"Loading donor engine from: {engine_file_path}")
        
        jbeam_data = JBeamParser.parse_jbeam(engine_file_path)
        if not jbeam_data:
            logger.error("Failed to parse donor engine file")
            return None
        
        characteristics = JBeamParser.extract_engine_characteristics(jbeam_data)
        if not characteristics:
            logger.error("Could not extract engine characteristics from file")
            return None
        
        return characteristics
    
    def analyze_target_vehicle(self, vehicle_name: str) -> Optional[VehicleInfo]:
        """
        Analyze a target vehicle for compatibility.
        
        Args:
            vehicle_name: Name of target vehicle
            
        Returns:
            VehicleInfo object or None if analysis fails
        """
        logger.info(f"Analyzing target vehicle: {vehicle_name}")
        
        try:
            vehicle_info = self.vehicle_analyzer.analyze_vehicle(vehicle_name)
            return vehicle_info
        except Exception as e:
            logger.error(f"Failed to analyze vehicle {vehicle_name}: {e}")
            return None
    
    def generate_adaptation_plan(self,
                                  donor_engine: EngineCharacteristics,
                                  target_vehicle: VehicleInfo) -> Dict[str, Any]:
        """
        Generate an adaptation plan for transplanting an engine to a vehicle.
        
        Args:
            donor_engine: Characteristics of the donor engine
            target_vehicle: Information about target vehicle
            
        Returns:
            Dictionary containing adaptation plan details
        """
        logger.info(f"Generating adaptation plan: {donor_engine.name} -> {target_vehicle.name}")
        
        plan = {
            'donor_engine': {
                'name': donor_engine.name,
                'original_slot_type': donor_engine.slot_type,
            },
            'target_vehicle': {
                'name': target_vehicle.name,
                'architecture': target_vehicle.architecture.value,
                'expected_slot_type': target_vehicle.engine_slot_type,
            },
            'adaptations_required': [],
            'compatibility_notes': [],
        }
        
        # Check if slotType needs to be changed
        if donor_engine.slot_type != target_vehicle.engine_slot_type:
            plan['adaptations_required'].append({
                'type': 'slot_type_change',
                'from': donor_engine.slot_type,
                'to': target_vehicle.engine_slot_type,
                'description': 'Create vehicle-specific slotType wrapper'
            })
        
        # Check thermal balance
        if donor_engine.max_rpm > 0:
            # Estimate required cooling (simplified)
            power_factor = donor_engine.max_rpm / 6000.0  # Rough approximation
            if donor_engine.radiator_area < power_factor * 0.3:
                plan['adaptations_required'].append({
                    'type': 'cooling_upgrade',
                    'current_radiator_area': donor_engine.radiator_area,
                    'description': 'May require upgraded radiator for thermal balance'
                })
        
        # Architecture-specific notes
        if target_vehicle.architecture == VehicleArchitecture.SUBMODEL:
            plan['compatibility_notes'].append(
                'Target uses SUBMODEL architecture - may require .pc configuration'
            )
        elif target_vehicle.architecture == VehicleArchitecture.COMMON:
            plan['compatibility_notes'].append(
                'Target uses COMMON architecture - place adapted engine in common folder'
            )
        
        logger.info(f"Adaptation plan generated with {len(plan['adaptations_required'])} required adaptations")
        return plan
    
    # =========================================================================
    # Target Vehicle Powertrain Analysis (Phase 1)
    # =========================================================================
    
    def analyze_target_powertrain(self, vehicle_name: str) -> Optional[Dict[str, Any]]:
        """
        Analyze a target vehicle's transfer case inventory using analyze_powertrains.
        
        Builds a structured catalog of all transfer case variants available for
        the target vehicle, classifies their drive type (RWD, FWD, AWD, 4WD),
        and extracts downstream axle slot references (front/rear driveshaft slotTypes).
        
        This catalog becomes the input to the Phase 3 swap decision engine, which
        selects the best-match BeamNG TC for a given Camso donor drive type.
        
        Args:
            vehicle_name: BeamNG vehicle folder name (e.g., "pickup", "etki")
            
        Returns:
            Dict with:
                vehicle: str - vehicle name
                transfer_cases: List[Dict] - one entry per TC variant with:
                    part_name: str - e.g., "pickup_transfer_case_4WD"
                    slot_type: str - e.g., "pickup_transfer_case"
                    info_name: str - display name
                    drive_type: str - "RWD" | "FWD" | "AWD" | "4WD"
                    devices: List[Dict] - powertrain device summaries
                    child_slots: List[Dict] - downstream slot refs with:
                        slot_type: str
                        default_part: str
                    chain_string: str - formatted torque path
                    chain_components: List[Dict] - resolved downstream components
            Or None if analysis unavailable or failed.
        """
        if not POWERTRAIN_ANALYSIS_AVAILABLE:
            logger.warning("analyze_powertrains module not available - "
                           "skipping target powertrain analysis")
            return None
        
        logger.info(f"Analyzing target vehicle powertrain: {vehicle_name}")
        
        try:
            # Step 1: Determine search folders (handles cross-vehicle refs)
            # base_vehicles_path points to the folder containing vehicle dirs
            # (e.g., SteamLibrary_content_vehicles/ which has pickup/, etki/, common/)
            base_path = self.base_vehicles_path
            folders = get_search_folders(base_path, vehicle_name)
            
            if not folders:
                logger.warning(f"No component folders found for vehicle '{vehicle_name}'")
                return None
            
            logger.info(f"  Search folders: {len(folders)}")
            for f in folders:
                logger.debug(f"    - {f}")
            
            # Step 2: Build slot registry for target vehicle
            registry = SlotRegistry(base_path)
            for folder in folders:
                registry.index_folder(folder)
            
            logger.info(f"  Indexed {len(registry.part_data)} parts, "
                        f"{len(registry.slot_providers)} slot types, "
                        f"{len(registry.powertrain_parts)} powertrain parts")
            
            # Step 3: Extract powertrain entries from transfercase files
            # TC parts may live in their own files (*transfercase*.jbeam) OR
            # inside transmission files (*transmission*.jbeam) — pickup does
            # the latter. Search all powertrain-related file patterns.
            extractor = PowertrainExtractor(base_path)
            patterns = ['*transmission*.jbeam', '*transfercase*.jbeam',
                        '*tranfercase*.jbeam', '*transaxle*.jbeam']
            processed_files = set()
            
            for folder in folders:
                for pattern in patterns:
                    for f in folder.rglob(pattern):
                        fkey = str(f)
                        if fkey not in processed_files:
                            processed_files.add(fkey)
                            extractor.process_file(f)
            
            if not extractor.entries:
                logger.warning(f"No powertrain entries found for '{vehicle_name}'")
                return None
            
            # Filter to only transfer case entries (skip transmissions/transaxles)
            # TC parts typically have "transfer_case" or "transfercase" in their
            # slotType or part_name
            tc_keywords = ('transfer_case', 'transfercase', 'tranfercase')
            tc_entries_raw = [
                e for e in extractor.entries
                if any(kw in e.part_name.lower() for kw in tc_keywords)
                or any(kw in e.slot_type.lower() for kw in tc_keywords)
            ]
            
            if not tc_entries_raw:
                logger.warning(f"No transfer case entries found for '{vehicle_name}' "
                             f"(found {len(extractor.entries)} total powertrain entries)")
                return None
            
            # Filter to this vehicle's reachable slotTypes
            reachable_slottypes = set()
            for st, vehicles in extractor._common_to_vehicles.items():
                if vehicle_name in vehicles:
                    reachable_slottypes.add(st)
            
            filtered_entries = []
            for entry in tc_entries_raw:
                if entry.is_common:
                    if entry.slot_type and entry.slot_type not in reachable_slottypes:
                        continue
                    entry.vehicle = vehicle_name
                filtered_entries.append(entry)
            
            logger.info(f"  Found {len(filtered_entries)} transfer case entries")
            
            if not filtered_entries:
                logger.info(f"  No reachable transfer case entries for '{vehicle_name}' "
                            f"(vehicle does not use a transfer case slotType)")
                return None
            
            # Step 4: Resolve drivetrain chains for each TC entry
            # Deduplicate entries by part_name (can appear from multiple patterns)
            seen_parts = set()
            chain_builder = DrivetrainChainBuilder(
                registry, allowed_common_slottypes=reachable_slottypes
            )
            
            tc_catalog = []
            for entry in filtered_entries:
                if entry.part_name in seen_parts:
                    continue
                seen_parts.add(entry.part_name)
                try:
                    chain = chain_builder.build_chain(entry)
                    entry.drivetrain_chain = chain
                except Exception as ex:
                    logger.warning(f"  Chain resolution failed for {entry.part_name}: {ex}")
                    chain = DrivetrainChain()
                
                # Step 5: Classify drive type from devices
                drive_type = self._classify_tc_drive_type(entry, chain)
                
                # Step 6: Extract downstream axle slot references
                child_slots, direct_child_count = self._extract_tc_child_slots(
                    entry, registry, chain
                )
                
                tc_entry = {
                    "part_name": entry.part_name,
                    "slot_type": entry.slot_type,
                    "info_name": entry.info_name or entry.part_name,
                    "drive_type": drive_type,
                    "devices": [
                        {
                            "type": d.type,
                            "name": d.name,
                            "inputName": d.inputName,
                            "inputIndex": d.inputIndex,
                            "properties": d.properties if d.properties else {},
                        }
                        for d in entry.devices
                    ],
                    "child_slots": child_slots,
                    "direct_child_count": direct_child_count,
                    "chain_string": chain.get_chain_string() if chain else "",
                    "chain_components": [
                        c.to_dict() for c in chain.components
                    ] if chain else [],
                }
                tc_catalog.append(tc_entry)
                
                logger.info(f"  {entry.part_name}: drive_type={drive_type}, "
                           f"child_slots={len(child_slots)}, "
                           f"chain={chain.get_chain_string()[:60] if chain else 'none'}")
            
            result = {
                "vehicle": vehicle_name,
                "transfer_cases": tc_catalog,
            }
            
            logger.info(f"  Target powertrain analysis complete: "
                        f"{len(tc_catalog)} TC variants cataloged")
            return result
            
        except Exception as e:
            logger.error(f"Failed to analyze target powertrain for {vehicle_name}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _classify_tc_drive_type(self, entry: PowertrainEntry,
                                 chain: DrivetrainChain) -> str:
        """
        Classify a BeamNG transfer case entry's drive type.
        
        Classification Rules (matching analyze_powertrains report conventions):
        - RWD: Has rear driveshaft output only (shaft passthrough)
        - FWD: Has front driveshaft output only
        - AWD: Has both front and rear outputs via a center diff or split
        - 4WD: Has both outputs plus a rangeBox device (hi/lo)
        
        Relies primarily on the TC's OWN devices and child slot declarations,
        NOT on chain_components (which may contain false positives from
        device-name linking across the registry).
        
        Args:
            entry: PowertrainEntry for the transfer case part
            chain: Resolved DrivetrainChain from the chain builder
            
        Returns:
            Drive type string: "RWD", "FWD", "AWD", "4WD", or "UNKNOWN"
        """
        # Only use the TC's own devices for classification (not chain components)
        tc_devices = list(entry.devices)
        device_types = {d.type.lower() for d in tc_devices}
        
        # Check for rangeBox → 4WD indicator
        has_rangebox = 'rangebox' in device_types
        
        # Detect front/rear presence from TC's own device name suffixes
        has_front = False
        has_rear = False
        
        for d in tc_devices:
            name_lower = d.name.lower()
            # Match suffixes like _F, _front, frontDriveShaft
            if any(kw in name_lower for kw in ('_f', 'front', '_sfa')):
                has_front = True
            # Match suffixes like _R, _rear
            # Be careful not to match words that happen to contain 'r'
            if '_r' in name_lower or 'rear' in name_lower:
                has_rear = True
            
            # Check outputPortOverride in device properties.
            # BeamNG convention: port 1 = rear axle, port 2 = front axle.
            # FWD transfer cases use outputPortOverride:[2] on a shaft device
            # to lock output to the front axle only.
            port_override = d.properties.get('outputPortOverride', [])
            if isinstance(port_override, list):
                if 2 in port_override and 1 not in port_override:
                    has_front = True
                elif 1 in port_override and 2 not in port_override:
                    has_rear = True
                elif 1 in port_override and 2 in port_override:
                    has_front = True
                    has_rear = True
        
        # Check child slot declarations in TC's own slots array
        for slot in entry.slots:
            if isinstance(slot, (list, tuple)) and len(slot) >= 2:
                slot_type_str = str(slot[0]).lower() if slot else ""
                if any(kw in slot_type_str for kw in ('front', '_f', '_sfa')):
                    has_front = True
                if any(kw in slot_type_str for kw in ('rear', '_r')):
                    has_rear = True
        
        # Check for split points on differential/splitShaft devices
        # A central diff/splitShaft that splits implies AWD
        if chain and chain.split_points:
            for d in tc_devices:
                if d.type.lower() in ('differential', 'splitshaft'):
                    if d.name in chain.split_points:
                        # Central split device — implies both front and rear
                        has_front = True
                        has_rear = True
        
        # Classification logic
        # A rangeBox alone does NOT imply 4WD — it's a hi/lo range selector.
        # 4WD requires rangebox AND both front+rear outputs.
        # A RWD vehicle with a rangebox (e.g., Camso exports) is still RWD.
        if has_rangebox and has_front and has_rear:
            return "4WD"
        elif has_front and has_rear:
            return "AWD"
        elif has_front and not has_rear:
            return "FWD"
        elif has_rear and not has_front:
            return "RWD"
        else:
            # Fallback: a simple shaft with no front/rear suffix is typically RWD
            if any(d.type.lower() == 'shaft' for d in tc_devices) and len(tc_devices) <= 2:
                return "RWD"
            return "UNKNOWN"
    
    def _extract_tc_child_slots(self, entry: PowertrainEntry,
                                 registry: SlotRegistry,
                                 chain: Optional[DrivetrainChain] = None,
                                 ) -> Tuple[List[Dict[str, str]], int]:
        """
        Extract downstream child slot references from a transfer case entry.
        
        Returns the slotType + default part for each child slot declared
        in the TC part's slots array. If the registry doesn't have explicit
        child slots, falls back to chain_components' slot_types (resolved
        via device-name linking).
        
        Most BeamNG transfer case parts have ZERO direct child slots — the
        downstream driveshaft/differential slots are declared by the vehicle's
        frame. The connection between TC and driveshafts is purely through
        powertrain device naming (e.g., torsionReactorR inputName:"transfercase").
        
        Args:
            entry: PowertrainEntry for the transfer case part
            registry: SlotRegistry with indexed parts
            chain: Optional resolved DrivetrainChain
            
        Returns:
            Tuple of:
              - List of dicts with "slot_type" and "default_part" keys
              - int: count of direct child slots from the TC part itself
                     (0 = driveshafts are provided externally, e.g., by frame)
        """
        child_slots = []
        seen_slot_types = set()
        direct_child_count = 0
        
        # Use the registry's get_child_slots for definitive resolution
        reg_child_slots = registry.get_child_slots(entry.part_name)
        for slot_type, default_name in reg_child_slots:
            if slot_type not in seen_slot_types:
                seen_slot_types.add(slot_type)
                child_slots.append({
                    "slot_type": slot_type,
                    "default_part": default_name,
                })
                direct_child_count += 1
        
        # If registry didn't find any, fall back to entry's raw slots
        if not child_slots and entry.slots:
            for slot in entry.slots:
                if isinstance(slot, (list, tuple)) and len(slot) >= 3:
                    # slots format: [slotType, defaultPart, displayName, ...]
                    st = str(slot[0]) if slot[0] else ""
                    dp = str(slot[1]) if len(slot) > 1 else ""
                    if st and st not in ('type', 'name') and st not in seen_slot_types:
                        seen_slot_types.add(st)
                        child_slots.append({
                            "slot_type": st,
                            "default_part": dp,
                        })
                        direct_child_count += 1
        
        # Also extract from chain_components (device-name linked downstream)
        # These are the driveshaft/differential slots the TC feeds into
        if chain:
            for component in chain.components:
                if component.slot_type and component.slot_type not in seen_slot_types:
                    seen_slot_types.add(component.slot_type)
                    child_slots.append({
                        "slot_type": component.slot_type,
                        "default_part": component.part_name,
                    })
        
        return child_slots, direct_child_count
    
    # =========================================================================
    # Camso Donor Drive Type Classification (Phase 2)
    # =========================================================================
    
    def analyze_donor_powertrain(self, donor_engine_path: Path) -> Optional[Dict[str, Any]]:
        """
        Analyze a Camso donor vehicle's transfer case to classify its drive type.
        
        Mirrors the output format of analyze_target_powertrain() so that Phase 3's
        swap decision engine receives symmetrical inputs. Parses the Camso TC file,
        classifies the primary drive type (RWD/FWD/AWD/4WD), and for AWD further
        classifies the sub-variant (on_demand/viscous/helical/advanced).
        
        Phase 2 of DrivetrainSwapLogic_DevelopmentPhases.md.
        
        Args:
            donor_engine_path: Path to the donor engine .jbeam file
            
        Returns:
            Dict with:
                drive_type: str - "RWD" | "FWD" | "AWD" | "4WD" | "UNKNOWN"
                awd_subvariant: Optional[str] - "on_demand" | "viscous" | "helical" | "advanced"
                parts: List[Dict] - one entry per TC part with:
                    part_name: str
                    slot_type: str
                    drive_type: str
                    devices: List[Dict]
                    child_slots: List[str] (slot types)
                    properties: Dict - notable powertrain properties
                center_diff: Optional[Dict] - center diff part details (AWD only)
            Or None if TC file not found or parse failed.
        """
        logger.info("Analyzing Camso donor powertrain...")
        
        # Find the transfer case file
        tc_file = self._find_donor_transfercase_file(donor_engine_path)
        if not tc_file:
            logger.warning("No Camso transfer case file found for donor")
            return None
        
        logger.info(f"  Parsing: {tc_file.name}")
        
        # Parse with JBeamParser (handles JBeam quirks)
        tc_data = JBeamParser.parse_jbeam(tc_file)
        if not tc_data:
            logger.warning(f"Failed to parse transfer case file: {tc_file}")
            return None
        
        # Separate parts by slotType
        tc_parts = []       # slotType == Camso_TransferCase
        center_diff = None   # slotType == Camso_differential_center
        
        for part_name, part_data in tc_data.items():
            if not isinstance(part_data, dict):
                continue
            
            slot_type = part_data.get("slotType", "")
            
            if slot_type == "Camso_differential_center":
                center_diff = self._extract_camso_part_summary(part_name, part_data)
                logger.info(f"  Found center diff part: {part_name}")
            elif slot_type == "Camso_TransferCase":
                tc_parts.append(self._extract_camso_part_summary(part_name, part_data))
                logger.info(f"  Found TC part: {part_name}")
            else:
                # Catch parts that may use variant slotTypes
                logger.debug(f"  Skipping non-TC part: {part_name} (slotType={slot_type})")
        
        if not tc_parts:
            logger.warning(f"No Camso_TransferCase parts found in {tc_file.name}")
            return None
        
        # Classify each TC part
        for part in tc_parts:
            part["drive_type"] = self._classify_camso_part_drive_type(part, center_diff)
        
        # Determine overall donor drive type from the primary (non-rangebox) part.
        # Rangebox variants are identified by "_rangebox_" in their part name.
        primary_parts = [p for p in tc_parts if "_rangebox_" not in p["part_name"].lower()]
        if primary_parts:
            overall_drive_type = primary_parts[0]["drive_type"]
        else:
            # All parts are rangebox variants — use first one
            overall_drive_type = tc_parts[0]["drive_type"]
        
        # AWD sub-variant classification
        awd_subvariant = None
        if overall_drive_type == "AWD" and center_diff:
            awd_subvariant = self._classify_camso_awd_subvariant(center_diff)
            logger.info(f"  AWD sub-variant: {awd_subvariant}")
        
        result = {
            "drive_type": overall_drive_type,
            "awd_subvariant": awd_subvariant,
            "parts": tc_parts,
            "center_diff": center_diff,
            "tc_file": str(tc_file),
        }
        
        logger.info(f"  Donor powertrain classification: {overall_drive_type}"
                    f"{f' ({awd_subvariant})' if awd_subvariant else ''}")
        return result
    
    def _extract_camso_part_summary(self, part_name: str,
                                     part_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract a structured summary from a Camso transfercase or center diff part.
        
        Args:
            part_name: JBeam part name (e.g., "Camso_TransferCase_RWD_79971")
            part_data: Parsed part definition dict
            
        Returns:
            Dict with part_name, slot_type, devices, child_slots, properties
        """
        slot_type = part_data.get("slotType", "")
        
        # Extract powertrain devices
        devices = []
        powertrain = part_data.get("powertrain", [])
        if isinstance(powertrain, list):
            for item in powertrain:
                if isinstance(item, list) and len(item) >= 4:
                    device = {
                        "type": item[0],       # e.g., "shaft", "differential", "splitShaft", "rangeBox"
                        "name": item[1],       # e.g., "transferCase", "frontDriveShaft"
                        "inputName": item[2],  # e.g., "gearbox", "rangebox"
                        "inputIndex": item[3], # typically 1
                    }
                    # Extract notable properties from the optional 5th element
                    if len(item) >= 5 and isinstance(item[4], dict):
                        device["properties"] = item[4]
                    else:
                        device["properties"] = {}
                    devices.append(device)
        
        # Extract child slot types
        child_slots = []
        slots = part_data.get("slots", [])
        if isinstance(slots, list):
            for item in slots:
                if isinstance(item, list) and len(item) >= 2:
                    st = str(item[0])
                    # Skip the header row
                    if st.lower() in ("type", "default", "description"):
                        continue
                    child_slots.append(st)
        
        # Extract controller references
        controllers = []
        controller = part_data.get("controller", [])
        if isinstance(controller, list):
            for item in controller:
                if isinstance(item, list) and len(item) >= 1:
                    ctrl_entry = {}
                    for element in item:
                        if isinstance(element, dict):
                            ctrl_entry.update(element)
                        elif isinstance(element, str) and "fileName" not in element.lower():
                            ctrl_entry["name"] = element
                    if ctrl_entry:
                        controllers.append(ctrl_entry)
        
        # Collect notable properties across all devices
        notable_props = {}
        for d in devices:
            props = d.get("properties", {})
            for key in ("diffType", "splitType", "canDisconnect", "lockTorque",
                        "viscousCoef", "viscousTorque", "lsdLockCoef",
                        "lsdRevLockCoef", "lsdPreload", "defaultClutchRatio",
                        "gearRatios"):
                if key in props:
                    notable_props[key] = props[key]
        
        return {
            "part_name": part_name,
            "slot_type": slot_type,
            "devices": devices,
            "child_slots": child_slots,
            "controllers": controllers,
            "notable_properties": notable_props,
        }
    
    def _classify_camso_part_drive_type(self, part_summary: Dict[str, Any],
                                         center_diff: Optional[Dict[str, Any]]) -> str:
        """
        Classify a Camso transfercase part's drive type.
        
        Uses a tiered approach:
        1. Part name prefix pattern (reliable: Camso embeds drive type in name)
        2. Structural analysis fallback (child slots + powertrain devices)
        
        Classification heuristic (from DrivetrainSwapLogic Phase 2.2):
        - Camso_differential_center child slot → AWD (two-tier pattern)
        - Camso_4wd_controller child slot → 4WD
        - rangeBox + locked differential → 4WD (structural)
        - frontDriveShaft device name → FWD
        - transferCase shaft device → RWD

        Args:
            part_summary: Output of _extract_camso_part_summary()
            center_diff: Center diff summary if found in same file, else None
            
        Returns:
            Drive type string: "RWD", "FWD", "AWD", "4WD", or "UNKNOWN"
        """
        part_name = part_summary["part_name"]
        child_slots = part_summary["child_slots"]
        devices = part_summary["devices"]
        
        # === Tier 1: Part name pattern (Camso convention) ===
        # Camso embeds drive type in part names:
        #   Camso_TransferCase_RWD_<hash>
        #   Camso_TransferCase_FWD_<hash>
        #   Camso_TransferCase_AWD_<hash>
        #   Camso_TransferCase_4x4_<hash>
        name_upper = part_name.upper()
        if "_RWD_" in name_upper:
            return "RWD"
        if "_FWD_" in name_upper:
            return "FWD"
        if "_AWD_" in name_upper:
            return "AWD"
        if "_4X4_" in name_upper:
            return "4WD"
        
        # === Tier 2: Structural analysis fallback ===
        logger.debug(f"  Part {part_name}: no name-based classification, "
                     "falling back to structural analysis")
        
        # Check child slot declarations
        child_slot_set = set(s.lower() for s in child_slots)
        
        if any("camso_differential_center" in s for s in child_slot_set):
            return "AWD"
        if any("camso_4wd_controller" in s for s in child_slot_set):
            return "4WD"
        
        # Check powertrain device types and names
        device_types = {d["type"].lower() for d in devices}
        device_names = {d["name"].lower() for d in devices}
        notable = part_summary.get("notable_properties", {})
        
        # rangeBox + locked differential without center diff → 4WD
        if "rangebox" in device_types and "differential" in device_types:
            if notable.get("diffType") == "locked":
                return "4WD"
        
        # Check output shaft naming
        if "frontdriveshaft" in device_names:
            return "FWD"
        if "transfercase" in device_names:
            # Simple shaft passthrough to rear → RWD
            # (For AWD/4WD, transferCase is a differential/splitShaft, not a shaft)
            tc_devices = [d for d in devices if d["name"].lower() == "transfercase"]
            if tc_devices and tc_devices[0]["type"].lower() == "shaft":
                return "RWD"
        
        # If we have a center diff in the same file, it's AWD
        if center_diff is not None:
            return "AWD"
        
        # Conservative default
        logger.warning(f"  Could not classify Camso part {part_name}, defaulting to UNKNOWN")
        return "UNKNOWN"
    
    def _classify_camso_awd_subvariant(self, center_diff: Dict[str, Any]) -> str:
        """
        Classify an AWD center differential's sub-variant.
        
        AWD sub-variant decision tree (from Camso_Drivetrain_Notes.md):
        
        | Device Type   | diffType/splitType | Controller       | Sub-variant |
        |---------------|-------------------|------------------|-------------|
        | splitShaft    | splitType:"locked" | electronicSplit* | on_demand   |
        | differential  | diffType:"viscous" | (none)           | viscous     |
        | differential  | diffType:"lsd"     | (none)           | helical     |
        | differential  | diffType:"lsd"     | camso_advawd     | advanced    |
        
        This classification is informational but may be needed for future utility — all AWD subtypes use the same
        DIRECT_AWD swap strategy in Phase 3, although there may be variations in implementation.
        
        Args:
            center_diff: Part summary dict for the Camso_differential_center part
            
        Returns:
            Sub-variant string: "on_demand", "viscous", "helical", "advanced"
        """
        devices = center_diff.get("devices", [])
        controllers = center_diff.get("controllers", [])
        notable = center_diff.get("notable_properties", {})
        
        # Check device types
        device_types = {d["type"].lower() for d in devices}
        
        # splitShaft → On-Demand AWD
        if "splitshaft" in device_types:
            return "on_demand"
        
        # differential → check diffType
        diff_type = notable.get("diffType", "")
        
        if diff_type == "viscous":
            return "viscous"
        
        if diff_type == "lsd":
            # LSD with active controller → Advanced; without → Helical
            has_advawd_controller = any(
                "advawd" in str(ctrl).lower() or
                "camso_advawd" in str(ctrl.get("fileName", "")).lower()
                for ctrl in controllers
            )
            if has_advawd_controller:
                return "advanced"
            return "helical"
        
        # Fallback
        logger.warning(f"  Could not classify AWD sub-variant from center diff, "
                      f"devices={[d['type'] for d in devices]}, diffType={diff_type}")
        return "unknown"
    
    # =========================================================================
    # Swap Decision Engine (Phase 3)
    # =========================================================================
    
    def select_swap_strategy(self,
                              donor_catalog: Dict[str, Any],
                              tc_catalog: Optional[Dict[str, Any]],
                              vehicle_name: str) -> Dict[str, Any]:
        """
        Select the optimal transfercase swap strategy.
        
        Combines Phase 1 (target TC catalog), Phase 2 (donor classification),
        and the swap_parameters config to determine which swap strategy to use
        and which BeamNG transfer case to target.
        
        Supports two modes:
        - Auto mode (transfercase_to_adapt="auto"): finds the lowest-cost match
          across all target vehicle TC variants.
        - Specified mode (transfercase_to_adapt="<part_name>"): validates and
          evaluates a user-specified BeamNG TC part.
        
        Phase 3 of DrivetrainSwapLogic_DevelopmentPhases.md.
        
        Args:
            donor_catalog: Output of analyze_donor_powertrain() (must not be None)
            tc_catalog: Output of analyze_target_powertrain() (None if non-TC vehicle)
            vehicle_name: Target vehicle name for logging
            
        Returns:
            Dict with:
                strategy: str - "DIRECT", "DIRECT_AWD", "MAKE_RWD", etc.
                cost: int - adaptation cost (0=best, 99=REFUSE)
                donor_drive_type: str - "RWD", "FWD", "AWD", "4WD"
                donor_awd_subvariant: Optional[str]
                target_drive_type: str - BeamNG TC drive type or "NO_TC_RWD"/"NO_TC_FWD"
                selected_tc: Optional[Dict] - selected BeamNG TC entry (None for SYNTH_TC/REFUSE)
                all_candidates: List[Dict] - all evaluated candidates with cost/strategy
                mode: str - "auto" or "specified"
                refused: bool - True if strategy is REFUSE
                refuse_reason: Optional[str] - explanation if refused
        """
        camso_type = donor_catalog["drive_type"]
        awd_sub = donor_catalog.get("awd_subvariant")
        tc_adapt_option = self._swap_config.get("transfercase_to_adapt", "auto")
        
        logger.info(f"[DRIVETRAIN] Selecting swap strategy for {vehicle_name}")
        logger.info(f"  Camso donor: {camso_type}"
                    f"{f' ({awd_sub})' if awd_sub else ''}")
        
        # Determine target architecture
        if tc_catalog is None or not tc_catalog.get("transfer_cases"):
            # Non-TC vehicle — stub classification (Phase 1.5 deferred)
            # Nearly all non-TC vehicles are RWD; FWD transaxle detection deferred.
            target_arch = "NO_TC_RWD"
            logger.info(f"  Target '{vehicle_name}': no transfer case (classified as {target_arch})")
            return self._evaluate_no_tc_strategy(camso_type, awd_sub, target_arch,
                                                  vehicle_name)
        
        # TC-equipped vehicle — evaluate all TC variants
        beamng_tcs = tc_catalog["transfer_cases"]
        logger.info(f"  Target '{vehicle_name}': {len(beamng_tcs)} TC variant(s)")
        
        # Check mode
        if tc_adapt_option not in ("auto", "single", "all"):
            # Specified mode — user named a specific BeamNG TC part
            return self._evaluate_specified_strategy(camso_type, awd_sub,
                                                      tc_adapt_option, beamng_tcs,
                                                      vehicle_name)
        
        # Auto mode — find lowest-cost match
        return self._evaluate_auto_strategy(camso_type, awd_sub, beamng_tcs,
                                             vehicle_name)
    
    def _evaluate_auto_strategy(self,
                                 camso_type: str,
                                 awd_sub: Optional[str],
                                 beamng_tcs: List[Dict[str, Any]],
                                 vehicle_name: str) -> Dict[str, Any]:
        """
        Auto-selection: find the lowest-cost BeamNG TC match.
        
        Evaluates every target vehicle TC variant against the donor drive type,
        sorts by adaptation cost, and returns the best candidate.
        """
        candidates = []
        
        for tc in beamng_tcs:
            beamng_type = tc["drive_type"]
            strategy = SWAP_STRATEGY.get((camso_type, beamng_type), 'REFUSE')
            cost = ADAPTATION_COST.get(strategy, 99)
            
            candidate = {
                "part_name": tc["part_name"],
                "target_drive_type": beamng_type,
                "strategy": strategy,
                "cost": cost,
            }
            candidates.append(candidate)
            
            marker = ""
            if cost < 99:
                marker = "  <-- viable"
            logger.info(f"    {tc['part_name']:<40s} {beamng_type:<5s} "
                       f"-> {strategy:<12s} (cost: {cost}){marker}")
        
        # Sort by cost (lowest first), then by strategy name for determinism
        viable = [c for c in candidates if c["cost"] < 99]
        viable.sort(key=lambda c: (c["cost"], c["strategy"]))
        
        if not viable:
            # All candidates are REFUSE
            logger.warning(f"  [DRIVETRAIN] No compatible TC found for "
                          f"{camso_type} -> {vehicle_name}")
            return {
                "strategy": "REFUSE",
                "cost": 99,
                "donor_drive_type": camso_type,
                "donor_awd_subvariant": awd_sub,
                "target_drive_type": "NONE",
                "selected_tc": None,
                "all_candidates": candidates,
                "mode": "auto",
                "refused": True,
                "refuse_reason": (f"No compatible transfer case found: "
                                  f"Camso {camso_type} has no viable match "
                                  f"among {len(beamng_tcs)} target TC variants"),
            }
        
        best = viable[0]
        selected_tc = next(
            tc for tc in beamng_tcs if tc["part_name"] == best["part_name"]
        )
        
        logger.info(f"  [DRIVETRAIN] Selected: {best['part_name']} "
                   f"via {best['strategy']} (cost: {best['cost']})")
        
        return {
            "strategy": best["strategy"],
            "cost": best["cost"],
            "donor_drive_type": camso_type,
            "donor_awd_subvariant": awd_sub,
            "target_drive_type": best["target_drive_type"],
            "selected_tc": selected_tc,
            "all_candidates": candidates,
            "mode": "auto",
            "refused": False,
            "refuse_reason": None,
        }
    
    def _evaluate_specified_strategy(self,
                                      camso_type: str,
                                      awd_sub: Optional[str],
                                      specified_part: str,
                                      beamng_tcs: List[Dict[str, Any]],
                                      vehicle_name: str) -> Dict[str, Any]:
        """
        Specified mode: evaluate a user-named BeamNG TC part.
        
        Validates that the part exists in the target vehicle's catalog,
        computes strategy and cost, and refuses if incompatible.
        """
        logger.info(f"  [DRIVETRAIN] Specified mode: '{specified_part}'")
        
        # Also evaluate all candidates for the log
        all_candidates = []
        for tc in beamng_tcs:
            beamng_type = tc["drive_type"]
            strategy = SWAP_STRATEGY.get((camso_type, beamng_type), 'REFUSE')
            cost = ADAPTATION_COST.get(strategy, 99)
            all_candidates.append({
                "part_name": tc["part_name"],
                "target_drive_type": beamng_type,
                "strategy": strategy,
                "cost": cost,
            })
        
        # Find the specified part
        matched_tc = None
        for tc in beamng_tcs:
            if tc["part_name"] == specified_part:
                matched_tc = tc
                break
        
        if matched_tc is None:
            # Part not found in target vehicle's catalog
            available = ", ".join(tc["part_name"] for tc in beamng_tcs)
            reason = (f"Specified transfer case '{specified_part}' not found "
                      f"in {vehicle_name}'s catalog. "
                      f"Available: [{available}]")
            logger.error(f"  [DRIVETRAIN] {reason}")
            return {
                "strategy": "REFUSE",
                "cost": 99,
                "donor_drive_type": camso_type,
                "donor_awd_subvariant": awd_sub,
                "target_drive_type": "UNKNOWN",
                "selected_tc": None,
                "all_candidates": all_candidates,
                "mode": "specified",
                "refused": True,
                "refuse_reason": reason,
            }
        
        # Evaluate the specified part
        beamng_type = matched_tc["drive_type"]
        strategy = SWAP_STRATEGY.get((camso_type, beamng_type), 'REFUSE')
        cost = ADAPTATION_COST.get(strategy, 99)
        
        if cost >= 99:
            reason = (f"Incompatible: Camso {camso_type} -> "
                      f"{specified_part} ({beamng_type}) = {strategy}")
            logger.warning(f"  [DRIVETRAIN] {reason}")
            return {
                "strategy": strategy,
                "cost": cost,
                "donor_drive_type": camso_type,
                "donor_awd_subvariant": awd_sub,
                "target_drive_type": beamng_type,
                "selected_tc": matched_tc,
                "all_candidates": all_candidates,
                "mode": "specified",
                "refused": True,
                "refuse_reason": reason,
            }
        
        logger.info(f"  [DRIVETRAIN] Specified: {specified_part} "
                   f"via {strategy} (cost: {cost})")
        
        return {
            "strategy": strategy,
            "cost": cost,
            "donor_drive_type": camso_type,
            "donor_awd_subvariant": awd_sub,
            "target_drive_type": beamng_type,
            "selected_tc": matched_tc,
            "all_candidates": all_candidates,
            "mode": "specified",
            "refused": False,
            "refuse_reason": None,
        }
    
    def _evaluate_no_tc_strategy(self,
                                  camso_type: str,
                                  awd_sub: Optional[str],
                                  target_arch: str,
                                  vehicle_name: str) -> Dict[str, Any]:
        """
        Evaluate swap strategy for a non-TC target vehicle.
        
        Uses SYNTH_TC lookup. Currently stubs the non-TC classification
        as NO_TC_RWD (Phase 1.5 deferred — nearly all non-TC vehicles are RWD).
        """
        strategy = SWAP_STRATEGY.get((camso_type, target_arch), 'REFUSE')
        cost = ADAPTATION_COST.get(strategy, 99)
        
        if cost >= 99:
            reason = (f"Incompatible: Camso {camso_type} cannot target "
                      f"non-TC vehicle '{vehicle_name}' ({target_arch})")
            logger.warning(f"  [DRIVETRAIN] {reason}")
            return {
                "strategy": strategy,
                "cost": cost,
                "donor_drive_type": camso_type,
                "donor_awd_subvariant": awd_sub,
                "target_drive_type": target_arch,
                "selected_tc": None,
                "all_candidates": [],
                "mode": "auto",
                "refused": True,
                "refuse_reason": reason,
            }
        
        logger.info(f"  [DRIVETRAIN] Non-TC target: {strategy} (cost: {cost})")
        
        return {
            "strategy": strategy,
            "cost": cost,
            "donor_drive_type": camso_type,
            "donor_awd_subvariant": awd_sub,
            "target_drive_type": target_arch,
            "selected_tc": None,  # No BeamNG TC part for SYNTH_TC
            "all_candidates": [],
            "mode": "auto",
            "refused": False,
            "refuse_reason": None,
        }
    
    # =========================================================================
    # Axle Slot Extraction (Phase 4)
    # =========================================================================
    
    def extract_injection_targets(self,
                                   swap_decision: Dict[str, Any],
                                   ) -> Optional[Dict[str, Any]]:
        """
        Extract BeamNG axle slot references for TC adaptation.
        
        Analyzes the selected BeamNG transfer case's resolved chain to identify:
        1. Rear driveshaft components (via torsionReactorR device presence)
        2. Front driveshaft components (via driveshaft_F device presence)
        3. Whether the TC declares direct child slots (rare — most BeamNG TCs
           have zero, with driveshafts provided externally by the vehicle frame)
        4. Powertrain device details for device name mapping in Phase 5
        
        Architecture note: Most BeamNG TCs (pickup, van, roamer, etc.) have
        no direct child slots. The downstream driveshaft/axle slots are declared
        by the vehicle's frame via ``slots2``. The TC connects to driveshafts
        purely through powertrain device naming (e.g., ``torsionReactorR``
        takes ``inputName: "transfercase"``). Phase 5 handles this by pruning
        the Camso driveshaft child slots rather than injecting replacements,
        unless the target TC explicitly declares its own child slots.
        
        Only valid for strategies with a selected BeamNG TC (not SYNTH_TC/REFUSE).
        
        Args:
            swap_decision: Output of select_swap_strategy() — must have
                           ``selected_tc`` with ``chain_components`` data
            
        Returns:
            Dict with:
                rear_slots: List[Dict] - rear driveshaft slot targets
                    each: {slot_type, default_part, position, devices}
                front_slots: List[Dict] - front driveshaft slot targets
                    each: {slot_type, default_part, position, devices}
                tc_has_direct_child_slots: bool - True if TC declares its own
                    driveshaft child slots (rare, changes Phase 5 approach)
                direct_child_count: int - number of TC-declared child slots
                tc_devices: List[Dict] - TC part's own powertrain devices
                    (for device name mapping in Phase 5)
                strategy: str - the swap strategy for context
                selected_tc: str - the selected TC part name
            None if strategy is REFUSE, SYNTH_TC, or no selected TC
        """
        strategy = swap_decision["strategy"]
        
        # No injection targets for REFUSE or SYNTH_TC strategies
        if swap_decision["refused"] or strategy in ("REFUSE", "SYNTH_TC"):
            logger.info(f"  [AXLE] No injection targets for {strategy} strategy")
            return None
        
        selected_tc = swap_decision.get("selected_tc")
        if not selected_tc:
            logger.warning("  [AXLE] No selected TC in swap decision")
            return None
        
        tc_name = selected_tc["part_name"]
        chain_components = selected_tc.get("chain_components", [])
        tc_devices = selected_tc.get("devices", [])
        direct_child_count = selected_tc.get("direct_child_count", 0)
        
        logger.info(f"  [AXLE] Extracting injection targets from {tc_name}")
        logger.info(f"    TC declares {direct_child_count} direct child slot(s)")
        
        rear_slots = []
        front_slots = []
        skipped = 0
        
        for comp in chain_components:
            slot_type = comp.get("slot_type", "")
            part_name = comp.get("part_name", "")
            devices = comp.get("devices", [])
            
            # Classify by device name presence
            # devices format: [[type, name, inputName, inputIndex], ...]
            device_names = set()
            for d in devices:
                if isinstance(d, (list, tuple)) and len(d) >= 2:
                    device_names.add(d[1])
            
            position = self._classify_chain_component_position(device_names)
            
            if position == "rear":
                rear_slots.append({
                    "slot_type": slot_type,
                    "default_part": part_name,
                    "position": "rear",
                    "devices": [d[1] for d in devices
                                if isinstance(d, (list, tuple)) and len(d) >= 2],
                })
            elif position == "front":
                front_slots.append({
                    "slot_type": slot_type,
                    "default_part": part_name,
                    "position": "front",
                    "devices": [d[1] for d in devices
                                if isinstance(d, (list, tuple)) and len(d) >= 2],
                })
            else:
                skipped += 1
        
        logger.info(f"    Rear driveshaft slots: {len(rear_slots)}")
        logger.info(f"    Front driveshaft slots: {len(front_slots)}")
        logger.info(f"    Deeper components skipped: {skipped}")
        
        result = {
            "rear_slots": rear_slots,
            "front_slots": front_slots,
            "tc_has_direct_child_slots": direct_child_count > 0,
            "direct_child_count": direct_child_count,
            "tc_devices": tc_devices,
            "strategy": strategy,
            "selected_tc": tc_name,
        }
        
        return result
    
    @staticmethod
    def _classify_chain_component_position(device_names: set) -> Optional[str]:
        """
        Classify a chain component as 'rear', 'front', or None (deeper component).
        
        Uses powertrain device name conventions to identify which components
        are the immediate driveshaft-level connections from the transfer case:
        
        - **Rear driveshaft**: Contains ``torsionReactorR`` — the rear torsion
          reactor that takes ``inputName: "transfercase"`` (output 1).
        - **Front driveshaft**: Contains ``driveshaft_F`` — the front driveshaft
          that connects via the TC's ``transfercase_F`` intermediate shaft.
          Includes both IFS variants (``driveshaft_F`` only) and SFA variants
          (``torsionReactorF`` + ``driveshaft_F``).
        - **Deeper components**: Differentials (``differential_R``, ``differential_F``),
          wheeldatas (``wheelaxle*``), halfshafts (``halfshaft*``), hubs — skipped
          because they are loaded through their own slot hierarchy.
        
        Args:
            device_names: Set of device name strings from the component
            
        Returns:
            'rear', 'front', or None
        """
        if 'torsionReactorR' in device_names:
            return 'rear'
        if 'driveshaft_F' in device_names:
            return 'front'
        return None
    
    def generate_adapted_jbeam(self,
                               donor_file: Path,
                               target_vehicle: VehicleInfo,
                               adaptation_plan: Dict[str, Any]) -> Optional[Path]:
        """
        Generate an adapted .jbeam file for target vehicle.
        Following Cummins mod pattern: adapt main slotTypes, preserve internal ecosystem.
        
        Args:
            donor_file: Path to donor engine .jbeam file
            target_vehicle: Target vehicle information
            adaptation_plan: Adaptation plan from generate_adaptation_plan()
            
        Returns:
            Path to generated temp file, or None if generation fails
        """
        logger.info(f"Generating adapted JBeam: {donor_file.name} -> {target_vehicle.name}")
        
        # Parse donor file
        donor_data = JBeamParser.parse_jbeam(donor_file)
        if not donor_data:
            logger.error(f"Failed to parse donor file: {donor_file}")
            return None
        
        # === SLOT GRAPH INTEGRATION ===
        # Build slot graph as single source of truth for slot/part mappings
        if SLOT_GRAPH_AVAILABLE and not self._slot_graph:
            self._build_slot_graph(donor_file, target_vehicle.name,
                                   engine_slot_type=target_vehicle.engine_slot_type,
                                   mount_slot_type=target_vehicle.mount_slot_type)
        
        # Load target vehicle engine for TMS
        target_engine_data = None
        donor_structure_data = None  # Camso-style separate structure file
        donor_drive_type = None  # Drive configuration of donor vehicle
        if TMS_AVAILABLE:
            target_engine_path = self._find_target_engine_file(target_vehicle)
            if target_engine_path:
                target_engine_data = JBeamParser.parse_jbeam(target_engine_path)
                if target_engine_data:
                    logger.info(f"  Loaded target engine for TMS: {target_engine_path.name}")
            
            # Check if donor uses separate engine structure file (Camso pattern)
            donor_structure_data = self._find_donor_structure_file(donor_file)
            donor_mesh_info = None  # Extracted mesh info for TMS transformation
            if donor_structure_data:
                logger.info(f"  Loaded donor engine structure for TMS")
                # Extract mesh info from structure file for later transformation
                donor_mesh_info = self._extract_engine_mesh_from_structure(donor_structure_data)
            
            # Determine donor vehicle drive type for transfer case handling
            donor_drive_type = self._determine_donor_drive_type(donor_file)
            self._last_donor_drive_type = donor_drive_type
        
        # Create adapted data structure
        adapted_data = {}
        exhaust_result = None  # Populated by exhaust solver inside loop, used after loop
        
        # Process each part in donor file
        for part_name, part_data in donor_data.items():
            if not isinstance(part_data, dict):
                continue
            
            # Get donor slotType
            donor_slot_type = part_data.get('slotType', '')
            
            # Determine if this is a PRIMARY part that needs vehicle-specific slotType
            is_primary_engine = donor_slot_type and 'engine' in donor_slot_type.lower() and 'management' not in donor_slot_type.lower() and 'internals' not in donor_slot_type.lower()
            
            # Cache donor engine torque table for downstream tweak modules
            if is_primary_engine:
                main_engine = part_data.get('mainEngine', {})
                raw_torque = main_engine.get('torque')
                if isinstance(raw_torque, list) and raw_torque:
                    self._last_donor_torque_table = raw_torque
                    self._last_donor_idle_rpm = main_engine.get('idleRPM')
                    logger.info(f"  Cached donor torque table: {len(raw_torque)} rows")

            # Check if this needs slotType adaptation
            if 'slot_type_change' in [a['type'] for a in adaptation_plan['adaptations_required']] and is_primary_engine:
                # Deep copy part data to preserve ALL donor attributes
                adapted_part_data = self._deep_copy_part_data(part_data)
                
                # CRITICAL: Add vehicle-specific engine mount slot for physical attachment
                self._inject_engine_mount_slot(adapted_part_data, target_vehicle.mount_slot_type)
                
                # === TMS INTEGRATION: Solve mounting geometry ===
                if TMS_AVAILABLE and target_engine_data:
                    logger.info("  [TMS] Running Transplant Mounting Solver...")
                    try:
                        # Load swap parameters
                        params_file = Path("../configs/swap_parameters.json")
                        
                        # Use structure file if available, otherwise use main donor data
                        donor_for_tms = donor_structure_data if donor_structure_data else donor_data
                        
                        # Solve mounting
                        solver_result = solve_engine_mount(
                            donor_jbeam=donor_for_tms,
                            target_jbeam=target_engine_data,
                            params_file=params_file if params_file.exists() else None
                        )
                        
                        if solver_result.success:
                            logger.info(f"  [TMS] OK - Solver succeeded")
                            logger.info(f"  [TMS]   Translation: {solver_result.translation}")
                            logger.info(f"  [TMS]   Scale: {solver_result.scale_applied:.4f}")
                            
                            # Store for use by transmission adaptation
                            self._last_solver_result = solver_result
                            
                            if solver_result.warnings:
                                for warning in solver_result.warnings:
                                    logger.warning(f"  [TMS]   {warning}")
                            
                            # Inject translated nodes and beams
                            self._inject_tms_geometry(adapted_part_data, solver_result)
                            logger.info(f"  [TMS]   Injected {len(solver_result.engine_cube.nodes) if solver_result.engine_cube else 0} translated nodes")
                            
                            # Log mount node and beam injection
                            if solver_result.mount_nodes:
                                logger.info(f"  [TMS]   Injected {len(solver_result.mount_nodes)} mount nodes: {[m.name for m in solver_result.mount_nodes]}")
                                if solver_result.engine_cube:
                                    beam_count = len(solver_result.mount_nodes) * len(solver_result.engine_cube.nodes)
                                    logger.info(f"  [TMS]   Injected {beam_count} mount-to-engine beams")
                            
                            # Translate torqueReactionNodes to BeamNG naming
                            self._translate_torque_reaction_nodes(adapted_part_data)
                            
                            # Handle engine structure slot:
                            # - If mesh info available: replace structure slot with mesh slot
                            # - Otherwise: neutralize structure slot to prevent duplicate nodes
                            if donor_mesh_info:
                                self._replace_structure_slot_with_mesh(adapted_part_data, donor_mesh_info)
                                # Store mesh info and translation for generating adapted mesh part later
                                self._last_mesh_info = donor_mesh_info
                                self._last_translation = solver_result.translation
                            else:
                                self._neutralize_structure_slot(adapted_part_data)
                        else:
                            logger.error(f"  [TMS] FAILED - Solver error: {solver_result.errors}")
                    except Exception as e:
                        logger.error(f"  [TMS] Exception during mounting solve: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    if not TMS_AVAILABLE:
                        logger.warning("  [TMS] Mounting solver not available - nodes will not be translated")
                    else:
                        logger.warning("  [TMS] Target engine data not found - nodes will not be translated")
                
                # CUMMINS PATTERN: Create vehicle-specific part name for PRIMARY engine only
                adapted_part_name = self._create_adapted_part_name(part_name, target_vehicle.name)
                
                # Adapt PRIMARY slotType to target vehicle
                adapted_part_data['slotType'] = target_vehicle.engine_slot_type
                logger.info(f"  Adapted PRIMARY engine slotType: {donor_slot_type} -> {target_vehicle.engine_slot_type}")
                logger.info(f"  Part name: {part_name} -> {adapted_part_name}")
                
                # Update part name in information section
                if 'information' in adapted_part_data:
                    info = adapted_part_data['information']
                    if 'name' in info:
                        info['name'] = f"{info['name']} ({target_vehicle.name.title()} Swap)"
                
                # === EXHAUST SOLVER INTEGRATION ===
                # Run after TMS geometry injection so isExhaust nodes have BeamNG names
                exhaust_result = None
                if EXHAUST_SOLVER_AVAILABLE:
                    exh_count, exh_nodes = self._extract_isExhaust_from_adapted(
                        adapted_part_data, adapted_part_name
                    )
                    if exh_count > 0:
                        try:
                            # Derive family prefix for family-shared architectures
                            # (e.g. etk800 uses etk_engine -> family_prefix='etk')
                            exh_family_prefix = None
                            if target_vehicle.engine_slot_type:
                                prefix = target_vehicle.engine_slot_type.replace('_engine', '')
                                if prefix != target_vehicle.name:
                                    exh_family_prefix = prefix
                            exhaust_result = exhaust_select_strategy(
                                base_path=self.base_vehicles_path,
                                vehicle_name=target_vehicle.name,
                                donor_isExhaust_count=exh_count,
                                donor_isExhaust_nodes=exh_nodes,
                                family_prefix=exh_family_prefix,
                            )
                            self._last_exhaust_result = exhaust_result
                            logger.info(
                                f"  [EXH] Strategy: {exhaust_result.strategy}, "
                                f"Pattern: {exhaust_result.pattern}, "
                                f"Donor: {exh_count}, Target: {exhaust_result.target_isExhaust_count}"
                            )
                            if exhaust_result.warnings:
                                for w in exhaust_result.warnings:
                                    logger.warning(f"  [EXH] {w}")
                        except Exception as e:
                            logger.error(f"  [EXH] Exception during exhaust solve: {e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        logger.info("  [EXH] No isExhaust nodes in adapted engine - skipping")
                
                # === SLOT GRAPH INTEGRATION ===
                # Transform slots using slot graph mappings (replaces "preserve all" approach)
                if 'slots' in adapted_part_data:
                    original_slot_count = len(adapted_part_data['slots'])
                    adapted_part_data['slots'] = self._transform_slots_with_graph(
                        adapted_part_data['slots'],
                        adapted_part_name,
                        target_vehicle.name
                    )
                    logger.info(f"  Slots: {original_slot_count} original -> {len(adapted_part_data['slots'])} transformed")
                
                # Inject exhaust slot entry (after slot graph to avoid interference)
                if exhaust_result and exhaust_result.exhaust_slot_entry:
                    if 'slots' not in adapted_part_data:
                        adapted_part_data['slots'] = [['type', 'default', 'description']]
                    adapted_part_data['slots'].append(exhaust_result.exhaust_slot_entry)
                    logger.info(f"  [EXH] Injected exhaust slot: {exhaust_result.exhaust_slot_entry[0]}")
                
                adapted_data[adapted_part_name] = adapted_part_data
            else:
                # CUMMINS PATTERN: Keep child parts as-is with original names
                # These form the shared ecosystem (intake, management, internals, etc.)
                adapted_data[part_name] = self._deep_copy_part_data(part_data)
                logger.info(f"  Preserved ecosystem part: {part_name} (slotType: {donor_slot_type})")
        
        # Inject exhaust adapted part if generated
        if exhaust_result and exhaust_result.adapted_part:
            for exh_part_name, exh_part_data in exhaust_result.adapted_part.items():
                adapted_data[exh_part_name] = exh_part_data
                logger.info(f"  [EXH] Injected exhaust adapter: {exh_part_name}")
        
        # Generate adapted engine mesh part if mesh info was extracted
        if self._last_mesh_info and self._last_translation:
            mesh_part = self._generate_adapted_mesh_part(
                self._last_mesh_info,
                self._last_translation
            )
            # Add mesh part to adapted data using original part name
            adapted_data[self._last_mesh_info.part_name] = mesh_part
            logger.info(f"  [TMS] Generated adapted mesh part: {self._last_mesh_info.part_name}")
        
        # Post-process: powertrain property tweaks
        adapted_data = self._apply_powertrain_tweaks(adapted_data, "engine", target_vehicle.name)
        
        # Write to temp file
        temp_file = self.temp_path / f"{target_vehicle.name}_{donor_file.stem}_adapted.jbeam"
        try:
            self._write_jbeam_file(temp_file, adapted_data)
            logger.info(f"  Generated temp file: {temp_file}")
            # Register with slot graph for manifest tracking
            if self._slot_graph:
                self._slot_graph.add_generated_file(temp_file)
            return temp_file
        except Exception as e:
            logger.error(f"Failed to write adapted file: {e}")
            return None
    
    def _find_donor_structure_file(self, donor_file: Path) -> Optional[Dict]:
        """
        Find and load donor engine structure file (Camso pattern).
        Camso engines use separate *_engine_structure_*.jbeam files for nodes.
        """
        donor_folder = donor_file.parent
        
        # Look for engine_structure file
        structure_files = list(donor_folder.parent.glob("*/camso_engine_structure*.jbeam"))
        if not structure_files:
            structure_files = list(donor_folder.glob("*_engine_structure*.jbeam"))
        
        if structure_files:
            structure_data = JBeamParser.parse_jbeam(structure_files[0])
            if structure_data:
                logger.info(f"  Found donor structure file: {structure_files[0].name}")
                return structure_data
        
        return None
    
    def _extract_engine_mesh_from_structure(self, structure_data: Dict[str, Any]) -> Optional[EngineMeshInfo]:
        """
        Extract engine mesh information from Camso engine_structure file.
        
        Camso structure files contain a separate Camso_engine_mesh part with
        flexbodies that define the visual mesh and its transform.
        
        Args:
            structure_data: Parsed engine_structure jbeam data
            
        Returns:
            EngineMeshInfo with mesh details, or None if not found
        """
        # Look for Camso_engine_mesh part
        for part_name, part_data in structure_data.items():
            if not isinstance(part_data, dict):
                continue
            
            slot_type = part_data.get('slotType', '')
            if 'engine_mesh' not in slot_type.lower():
                continue
            
            # Found mesh part - extract flexbodies
            flexbodies = part_data.get('flexbodies', [])
            if not flexbodies or not isinstance(flexbodies, list):
                logger.warning(f"  No flexbodies found in mesh part: {part_name}")
                continue
            
            # Find the mesh row (skip header row)
            for row in flexbodies:
                if isinstance(row, list) and len(row) >= 4:
                    # Skip header row
                    if row[0] == "mesh":
                        continue
                    
                    mesh_name = row[0]
                    groups = row[1] if len(row) > 1 and isinstance(row[1], list) else []
                    non_flex_materials = row[2] if len(row) > 2 and isinstance(row[2], list) else []
                    transform = row[3] if len(row) > 3 and isinstance(row[3], dict) else {}
                    
                    # Extract transform components
                    pos = transform.get('pos', {"x": 0, "y": 0, "z": 0})
                    rot = transform.get('rot', {"x": 0, "y": 0, "z": 0})
                    scale = transform.get('scale', {"x": 1, "y": 1, "z": 1})
                    
                    mesh_info = EngineMeshInfo(
                        mesh_name=mesh_name,
                        groups=groups,
                        non_flex_materials=non_flex_materials,
                        pos=pos,
                        rot=rot,
                        scale=scale,
                        part_name=part_name,
                        slot_type=slot_type,
                        info=part_data.get('information', {})
                    )
                    
                    logger.info(f"  [TMS] Extracted engine mesh: {mesh_name}")
                    logger.info(f"    Original pos: ({pos.get('x', 0):.4f}, {pos.get('y', 0):.4f}, {pos.get('z', 0):.4f})")
                    logger.info(f"    Rotation: ({rot.get('x', 0):.4f}, {rot.get('y', 0):.4f}, {rot.get('z', 0):.4f})")
                    logger.info(f"    Scale: ({scale.get('x', 1):.4f}, {scale.get('y', 1):.4f}, {scale.get('z', 1):.4f})")
                    
                    return mesh_info
        
        logger.warning("  No engine mesh part found in structure file")
        return None
    
    def _replace_structure_slot_with_mesh(self, 
                                           part_data: Dict[str, Any],
                                           mesh_info: EngineMeshInfo) -> None:
        """
        Replace Camso_engine_structure slot with Camso_engine_mesh slot.
        
        Instead of neutralizing the structure slot (setting default to ""),
        we replace it entirely with an engine mesh slot that points to our
        TMS-transformed mesh part.
        
        Args:
            part_data: Engine part data to modify
            mesh_info: Extracted mesh info with original part name
        """
        if 'slots' not in part_data:
            return
        
        slots = part_data['slots']
        
        for i, slot in enumerate(slots):
            if isinstance(slot, list) and len(slot) >= 2:
                slot_type = slot[0]
                # Check for Camso_engine_structure slot
                if 'engine_structure' in str(slot_type).lower():
                    # Replace with engine_mesh slot
                    # Original: ["Camso_engine_structure", "Camso_engine_structure_ec8ba", ...]
                    # New: ["Camso_engine_mesh", "Camso_engine_mesh_ec8ba", "Engine Mesh", {"coreSlot": true}]
                    new_slot = [
                        mesh_info.slot_type,  # "Camso_engine_mesh"
                        mesh_info.part_name,  # "Camso_engine_mesh_ec8ba"
                        "Engine Mesh",
                        {"coreSlot": True}
                    ]
                    slots[i] = new_slot
                    logger.info(f"  [TMS] Replaced structure slot with mesh slot: {slot_type} -> {mesh_info.slot_type}")
                    return
    
    def _generate_adapted_mesh_part(self,
                                     mesh_info: EngineMeshInfo,
                                     translation: 'Vec3') -> Dict[str, Any]:
        """
        Generate an adapted engine mesh part with TMS translation applied.
        
        Takes the original mesh info and applies the same translation used for
        engine nodes to the mesh position coordinates.
        
        Args:
            mesh_info: Original mesh info from structure file
            translation: TMS translation vector (same as used for nodes)
            
        Returns:
            Dictionary with adapted mesh part data ready for jbeam output
        """
        # Apply translation to mesh position
        translated_mesh = mesh_info.with_translation(
            translation.x,
            translation.y,
            translation.z
        )
        
        logger.info(f"  [TMS] Transformed mesh position:")
        logger.info(f"    Original: ({mesh_info.pos.get('x', 0):.4f}, {mesh_info.pos.get('y', 0):.4f}, {mesh_info.pos.get('z', 0):.4f})")
        logger.info(f"    Translation: ({translation.x:.4f}, {translation.y:.4f}, {translation.z:.4f})")
        logger.info(f"    Final: ({translated_mesh.pos.get('x', 0):.4f}, {translated_mesh.pos.get('y', 0):.4f}, {translated_mesh.pos.get('z', 0):.4f})")
        
        # Build the mesh part
        mesh_part = {
            "information": {
                "authors": mesh_info.info.get("authors", "Camshaft Software"),
                "name": mesh_info.info.get("name", "Engine Mesh"),
                "value": mesh_info.info.get("value", 1)
            },
            "slotType": mesh_info.slot_type,
            "flexbodies": [
                ["mesh", "[group]:", "nonFlexMaterials"],
                translated_mesh.to_flexbody_row()
            ]
        }
        
        return mesh_part
    
    def _find_target_engine_file(self, target_vehicle: VehicleInfo) -> Optional[Path]:
        """Find the target vehicle's stock engine jbeam file for TMS.
        
        Checks for user override first (from swap_parameters.json target_engine_file),
        then falls back to automatic selection.
        
        Handles family-shared architectures (e.g. etk800 uses etk_engine slot type
        with files in common/vehicles/common/etk/) by deriving a family prefix from
        the detected engine_slot_type.
        """
        # Check vehicle-specific folder first (direct architecture)
        vehicle_path = self.base_vehicles_path / target_vehicle.name / "vehicles" / target_vehicle.name
        
        # Check common folder (most common pattern)
        common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / target_vehicle.name
        
        # Derive family prefix from engine_slot_type if different from vehicle name
        # e.g. engine_slot_type="etk_engine" -> family_prefix="etk"
        family_prefix = None
        family_common_path = None
        if target_vehicle.engine_slot_type:
            prefix = target_vehicle.engine_slot_type.replace('_engine', '')
            if prefix != target_vehicle.name:
                family_prefix = prefix
                family_common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / prefix
                logger.debug(f"  Family prefix derived: {family_prefix} (from {target_vehicle.engine_slot_type})")
        
        # Build search paths list (vehicle-specific, common/vehicle, common/family)
        search_paths = []
        if family_common_path and family_common_path.exists():
            search_paths.append((family_common_path, family_prefix))
        if common_path.exists():
            search_paths.append((common_path, target_vehicle.name))
        if vehicle_path.exists():
            search_paths.append((vehicle_path, target_vehicle.name))
        
        # === Check for user override first ===
        if self._target_engine_override:
            logger.info(f"  [Override] Looking for specified engine file: {self._target_engine_override}")
            for search_dir, _ in search_paths:
                override_path = search_dir / self._target_engine_override
                if override_path.exists():
                    logger.info(f"  [Override] Found target engine: {override_path}")
                    return override_path
            # Override specified but not found - warn and fall back
            logger.warning(f"  [Override] Specified engine file '{self._target_engine_override}' not found in standard paths")
            for search_dir, _ in search_paths:
                logger.warning(f"    Searched: {search_dir}")
            logger.warning(f"  [Override] Falling back to automatic selection...")
        
        # === Automatic selection ===
        # Subcomponent keywords to exclude — these are child parts, not main engine files
        _exclude_keywords = ('enginemounts', 'management', 'ecu', 'internals', 'speedlimit', 'logo')
        for search_dir, prefix in search_paths:
            engine_files = list(search_dir.glob(f"{prefix}_engine*.jbeam"))
            # Filter out subcomponent files
            engine_files = [f for f in engine_files 
                           if not any(kw in f.stem.lower() for kw in _exclude_keywords)]
            if engine_files:
                # Prefer main engine file (not variants like "race" or "diesel")
                for match in engine_files:
                    if "race" not in match.stem.lower():
                        logger.info(f"  Found target engine: {match}")
                        return match
                # Fallback to first match
                logger.info(f"  Found target engine: {engine_files[0]}")
                return engine_files[0]
        
        logger.warning(f"Could not find target engine file for {target_vehicle.name}")
        for search_dir, _ in search_paths:
            logger.warning(f"  Searched: {search_dir}")
        return None
    
    def _find_target_transmission_file(self, target_vehicle: VehicleInfo) -> Optional[Path]:
        """Find the target vehicle's stock transmission jbeam file for TMS.
        
        Handles family-shared architectures by deriving a family prefix from
        the detected engine_slot_type (e.g. etk_engine -> etk prefix).
        """
        # Check vehicle-specific folder first (direct architecture)
        vehicle_path = self.base_vehicles_path / target_vehicle.name / "vehicles" / target_vehicle.name
        
        # Check common folder (most common pattern)
        common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / target_vehicle.name
        
        # Derive family prefix from engine_slot_type if different from vehicle name
        family_prefix = None
        family_common_path = None
        if target_vehicle.engine_slot_type:
            prefix = target_vehicle.engine_slot_type.replace('_engine', '')
            if prefix != target_vehicle.name:
                family_prefix = prefix
                family_common_path = self.base_vehicles_path / "common" / "vehicles" / "common" / prefix
        
        # Build search paths list (family first for priority)
        search_paths = []
        if family_common_path and family_common_path.exists():
            search_paths.append((family_common_path, family_prefix))
        if common_path.exists():
            search_paths.append((common_path, target_vehicle.name))
        if vehicle_path.exists():
            search_paths.append((vehicle_path, target_vehicle.name))
        
        for search_dir, prefix in search_paths:
            trans_files = list(search_dir.glob(f"{prefix}_transmission*.jbeam"))
            if trans_files:
                logger.info(f"  Found target transmission: {trans_files[0]}")
                return trans_files[0]
        
        logger.warning(f"Could not find target transmission file for {target_vehicle.name}")
        return None
    
    def _identify_default_transmission(self, 
                                        donor_engine_path: Path,
                                        trans_files: List[Path]) -> Optional[Path]:
        """
        Identify which transmission file contains the engine's default transmission.
        
        Used by the 'transmissions_to_adapt: single' config option to filter out
        vestigial transmission files (e.g., Camso sequential/race variants) that
        are not the engine's declared default.
        
        Approach: parse the engine file to find the Camso_Transmission child slot's
        default_part name, then find which of the discovered trans_files defines
        that part.
        
        Args:
            donor_engine_path: Path to the donor engine .jbeam file
            trans_files: List of discovered transmission file paths
            
        Returns:
            Path to the file containing the default transmission part,
            or None if it cannot be determined
        """
        # Parse engine file to find default transmission part name
        engine_data = JBeamParser.parse_jbeam(donor_engine_path)
        if not engine_data:
            logger.warning("  [transmissions_to_adapt] Cannot parse engine file — "
                           "falling back to 'all'")
            return None
        
        # Find the transmission child slot in the engine part
        default_trans_part = None
        for part_name, part_data in engine_data.items():
            if not isinstance(part_data, dict):
                continue
            slots = part_data.get('slots', [])
            for slot in slots:
                if not isinstance(slot, list) or len(slot) < 2:
                    continue
                slot_type = str(slot[0]) if slot[0] else ""
                if 'transmission' in slot_type.lower() and 'transfer' not in slot_type.lower():
                    default_trans_part = str(slot[1]) if len(slot) > 1 and slot[1] else ""
                    if default_trans_part:
                        logger.info(f"  [transmissions_to_adapt] Engine declares default "
                                    f"transmission: '{default_trans_part}'")
                        break
            if default_trans_part:
                break
        
        if not default_trans_part:
            logger.warning("  [transmissions_to_adapt] No transmission slot found in "
                           "engine — falling back to 'all'")
            return None
        
        # Find which trans_file defines this part
        for tf in trans_files:
            try:
                tf_data = JBeamParser.parse_jbeam(tf)
                if tf_data and default_trans_part in tf_data:
                    logger.info(f"  [transmissions_to_adapt] Default transmission found in: "
                                f"{tf.name}")
                    return tf
            except Exception as e:
                logger.warning(f"  [transmissions_to_adapt] Error parsing {tf.name}: {e}")
                continue
        
        logger.warning(f"  [transmissions_to_adapt] Default part '{default_trans_part}' "
                       f"not found in any transmission file — falling back to 'all'")
        return None
    
    def _find_donor_transfercase_file(self, donor_file: Path) -> Optional[Path]:
        """
        Find the Camso transfer case jbeam file for a donor engine.
        
        Camso engines store transfer case definitions in a separate file
        following the pattern: camso_transfercase_<variant>.jbeam
        
        Args:
            donor_file: Path to donor engine jbeam file
            
        Returns:
            Path to transfer case file, or None if not found
        """
        donor_folder = donor_file.parent
        
        # Try same folder as engine
        tc_files = list(donor_folder.glob("camso_transfercase*.jbeam"))
        if tc_files:
            logger.info(f"  Found donor transfer case: {tc_files[0].name}")
            return tc_files[0]
        
        # Try sibling folders (common Camso structure)
        parent_folder = donor_folder.parent
        tc_files = list(parent_folder.glob("*/camso_transfercase*.jbeam"))
        if tc_files:
            logger.info(f"  Found donor transfer case: {tc_files[0].name}")
            return tc_files[0]
        
        # Try searching recursively under parent folder
        tc_files = list(parent_folder.glob("**/camso_transfercase*.jbeam"))
        if tc_files:
            logger.info(f"  Found donor transfer case: {tc_files[0].name}")
            return tc_files[0]
        
        # Try grandparent folder (for deep Camso structures)
        grandparent = parent_folder.parent
        tc_files = list(grandparent.glob("**/camso_transfercase*.jbeam"))
        if tc_files:
            logger.info(f"  Found donor transfer case: {tc_files[0].name}")
            return tc_files[0]
        
        logger.warning("Could not find donor transfer case file")
        return None
    
    def _determine_donor_drive_type(self, donor_file: Path) -> Optional['DriveType']:
        """
        Determine the drive type of a Camso donor vehicle.
        
        Finds and analyzes the transfer case file to identify whether
        the donor is RWD, FWD, AWD, or 4WD based on driveshaft slots.
        
        Args:
            donor_file: Path to donor engine jbeam file
            
        Returns:
            DriveType enum value, or None if unable to determine
        """
        if not TMS_AVAILABLE:
            logger.warning("TMS not available - cannot determine drive type")
            return None
        
        # Find transfer case file
        tc_file = self._find_donor_transfercase_file(donor_file)
        if not tc_file:
            return None
        
        # Parse and analyze
        tc_data = JBeamParser.parse_jbeam(tc_file)
        if not tc_data:
            logger.warning(f"Failed to parse transfer case file: {tc_file}")
            return None
        
        # Extract drive type
        extractor = DonorDriveTypeExtractor(tc_data)
        drive_type = extractor.extract_drive_type()
        
        # Log detailed info
        drive_info = extractor.get_drive_info()
        logger.info(f"  Donor drive configuration:")
        logger.info(f"    - Drive type: {drive_type.value.upper()}")
        logger.info(f"    - Front driveshaft: {'YES' if drive_info['has_front_driveshaft'] else 'NO'}")
        logger.info(f"    - Rear driveshaft: {'YES' if drive_info['has_rear_driveshaft'] else 'NO'}")
        
        return drive_type
    
    # =========================================================================
    # Slot Graph Integration (Phase 2)
    # =========================================================================
    
    def _discover_donor_files(self, donor_engine_path: Path) -> List[Path]:
        """
        Discover all related donor jbeam files for slot graph construction.
        
        Finds engine, transmission, transfer case, structure, intake, and other
        related files following Camso/Automation mod patterns.
        
        Args:
            donor_engine_path: Path to primary donor engine .jbeam file
            
        Returns:
            List of Paths to all discovered jbeam files
        """
        files = [donor_engine_path]
        donor_folder = donor_engine_path.parent
        parent_folder = donor_folder.parent
        
        # Look for related files in same folder and sibling folders
        search_patterns = [
            "camso_transmission*.jbeam",
            "camso_transfercase*.jbeam",
            "camso_4x4_controllers*.jbeam",
            "camso_engine_structure*.jbeam",
            "camso_intakes*.jbeam",
            "camso_turbo*.jbeam",
            "camso_supercharger*.jbeam",
            "camso_management*.jbeam",
            "camso_internals*.jbeam",
            "camso_exhaust*.jbeam",
        ]
        
        # Search in donor folder and sibling folders
        for pattern in search_patterns:
            # Same folder
            for f in donor_folder.glob(pattern):
                if f not in files:
                    files.append(f)
            
            # Sibling folders (common Camso structure: eng_xxx/, ec8ba/, etc.)
            for f in parent_folder.glob(f"*/{pattern}"):
                if f not in files:
                    files.append(f)
        
        logger.info(f"  [SlotGraph] Discovered {len(files)} donor files:")
        for f in files:
            logger.debug(f"    - {f.name}")
        
        return files
    
    def _build_slot_graph(self, 
                          donor_engine_path: Path, 
                          target_vehicle: str,
                          engine_slot_type: Optional[str] = None,
                          mount_slot_type: Optional[str] = None) -> Optional['SlotGraph']:
        """
        Build a slot graph from donor files for the given target vehicle.
        
        The slot graph becomes the single source of truth for:
        - Slot type mappings (donor -> target)
        - Part name mappings (donor -> adapted)
        - Slot dispositions (adapt, preserve, prune, inject)
        - Asset roles (source vs target vs preserve)
        - Required file manifest
        
        Args:
            donor_engine_path: Path to primary donor engine .jbeam file
            target_vehicle: Target vehicle name (e.g., "pickup")
            engine_slot_type: Detected engine slot type (e.g., "etk_engine").
                Used to derive family prefix for vehicles with shared drivetrain 
                slot types (e.g., etk800 uses "etk_" prefix, not "etk800_").
            mount_slot_type: Dynamically discovered enginemounts slot type
                from target engine files (e.g., "etk_enginemounts").
            
        Returns:
            SlotGraph instance, or None if slot_graph module not available
        """
        if not SLOT_GRAPH_AVAILABLE:
            logger.warning("  [SlotGraph] Module not available - skipping graph construction")
            return None
        
        logger.info(f"  [SlotGraph] Building slot graph for {target_vehicle}...")
        
        try:
            # Discover all related donor files
            donor_files = self._discover_donor_files(donor_engine_path)
            
            # Build graph using JBeamParser (injected via protocol)
            graph = build_slot_graph(
                target_vehicle=target_vehicle,
                donor_files=donor_files,
                jbeam_parser=JBeamParser
            )
            
            # Build rules for disposition determination and replacement lookup
            rules = SlotDispositionRules(self._swap_config)
            
            # Derive family prefix from engine_slot_type for shared drivetrain architectures
            # e.g. engine_slot_type="etk_engine" -> slot_type_prefix="etk"
            # For direct architectures (pickup_engine), prefix matches vehicle name (no-op)
            slot_type_prefix = None
            if engine_slot_type:
                prefix = engine_slot_type.replace('_engine', '')
                if prefix != target_vehicle:
                    slot_type_prefix = prefix
                    logger.info(f"  [SlotGraph] Using family prefix '{slot_type_prefix}' for slot types (from {engine_slot_type})")
            
            # Apply transformation rules from config
            graph = plan_and_execute_transformations(
                graph=graph,
                target_vehicle=target_vehicle,
                config=self._swap_config,
                validate=True,
                slot_type_prefix=slot_type_prefix,
                target_mount_slot_type=mount_slot_type
            )
            
            # === MARK ASSET ROLES ===
            # Mark engine_structure-related slots as SOURCE (extraction only, not exported)
            # Pass rules to enable replacement injection for SOURCE slots
            self._mark_asset_roles(graph, rules)
            
            # Log summary
            logger.info(f"  [SlotGraph] Graph built successfully:")
            logger.info(f"    - Total slots: {len(graph.by_slot_type)}")
            logger.info(f"    - Active slots: {len(graph.get_active_slots())}")
            logger.info(f"    - Transformations: {len(graph.transformations)}")
            logger.info(f"    - Slot type mappings: {len(graph.slot_type_map)}")
            logger.info(f"    - Part name mappings: {len(graph.part_name_map)}")
            
            # Log asset roles
            if SLOT_GRAPH_AVAILABLE:
                source_count = len(graph.get_source_slots())
                export_count = len(graph.get_exportable_slots())
                logger.info(f"    - SOURCE (extraction only): {source_count}")
                logger.info(f"    - Exportable (TARGET/PRESERVE): {export_count}")
            
            # Store for use by other methods
            self._slot_graph = graph
            
            return graph
            
        except Exception as e:
            logger.error(f"  [SlotGraph] Failed to build graph: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _mark_asset_roles(self, graph: 'SlotGraph', rules: Optional['SlotDispositionRules'] = None) -> None:
        """
        Mark slots with appropriate asset roles based on their source and purpose.
        
        Asset Roles:
        - SOURCE: Extraction-only files (engine_structure) - NOT exported
        - TARGET: Generated/adapted files - IS exported  
        - PRESERVE: Original mod files copied as-is
        - INTERNAL: Processing artifacts, never exported
        
        Replacement Injection:
        When a slot is marked SOURCE, check for replacement rules.
        If a replacement exists, inject a new slot that calls the extracted assets.
        This maintains the convention: extracted assets need a slot to call them.
        
        Args:
            graph: SlotGraph to update with asset roles
            rules: Optional SlotDispositionRules for replacement lookup
        """
        if not SLOT_GRAPH_AVAILABLE:
            return
        
        # Build rules if not provided (for replacement lookup)
        if rules is None:
            rules = SlotDispositionRules()
        
        # Track SOURCE slots that need replacements
        source_slots_needing_replacement = []
        
        for node in graph.by_slot_type.values():
            # Determine role based on source file and slot characteristics
            
            # 1. Engine structure files are SOURCE (extraction only)
            if node.source_file:
                filename = node.source_file.name.lower()
                if 'engine_structure' in filename:
                    node.asset_role = AssetRole.SOURCE
                    logger.debug(f"  [AssetRole] {node.slot_type} -> SOURCE (engine_structure)")
                    # Check for replacement rule
                    if rules.has_replacement(node.slot_type):
                        source_slots_needing_replacement.append(node)
                    continue
            
            # 2. Slots from engine_structure slots are also SOURCE
            if node.original_slot_type:
                slot_lower = node.original_slot_type.lower()
                if 'engine_structure' in slot_lower:
                    node.asset_role = AssetRole.SOURCE
                    logger.debug(f"  [AssetRole] {node.slot_type} -> SOURCE (structure slot)")
                    # Check for replacement rule
                    if rules.has_replacement(node.slot_type):
                        source_slots_needing_replacement.append(node)
                    continue
            
            # 3. Injected slots (e.g., enginemounts) are TARGET
            if node.disposition == SlotDisposition.INJECT:
                node.asset_role = AssetRole.TARGET
                logger.debug(f"  [AssetRole] {node.slot_type} -> TARGET (injected)")
                continue
            
            # 4. Adapted slots are TARGET (we generate these)
            if node.disposition == SlotDisposition.ADAPT:
                node.asset_role = AssetRole.TARGET
                logger.debug(f"  [AssetRole] {node.slot_type} -> TARGET (adapted)")
                continue
            
            # 5. Everything else defaults to PRESERVE (original mod files)
            node.asset_role = AssetRole.PRESERVE
            logger.debug(f"  [AssetRole] {node.slot_type} -> PRESERVE (default)")
        
        # Inject replacement slots for SOURCE slots
        for source_node in source_slots_needing_replacement:
            replacement_config = rules.get_replacement_for_slot(source_node.slot_type)
            if replacement_config:
                replacement_node = graph.inject_replacement_slot(
                    source_slot_type=source_node.slot_type,
                    replacement_type=replacement_config.get('replacement_type', ''),
                    description=replacement_config.get('description', ''),
                    options=replacement_config.get('options')
                )
                if replacement_node:
                    logger.info(f"  [AssetRole] Injected replacement: {source_node.slot_type} -> {replacement_node.slot_type}")
    
    def _get_adapted_slot_type(self, donor_slot_type: str, target_vehicle: str) -> str:
        """
        Get adapted slot type using slot graph mappings if available.
        
        Falls back to pattern-based derivation if slot graph not built.
        
        Args:
            donor_slot_type: Original donor slot type
            target_vehicle: Target vehicle name
            
        Returns:
            Adapted slot type for target vehicle
        """
        # Use slot graph mapping if available
        if self._slot_graph and donor_slot_type in self._slot_graph.slot_type_map:
            return self._slot_graph.slot_type_map[donor_slot_type]
        
        # Fallback: derive from pattern (existing logic)
        slot_lower = donor_slot_type.lower()
        if 'engine' in slot_lower and 'management' not in slot_lower and 'internals' not in slot_lower:
            return f"{target_vehicle}_engine"
        elif 'transmission' in slot_lower:
            return f"{target_vehicle}_transmission"
        elif 'transfer' in slot_lower:
            return f"{target_vehicle}_transfer_case"
        
        return donor_slot_type  # Preserve as-is
    
    def _get_adapted_part_name_from_graph(self, donor_part_name: str, target_vehicle: str) -> str:
        """
        Get adapted part name using slot graph mappings if available.
        
        Falls back to prefix-based naming if slot graph not built.
        
        Args:
            donor_part_name: Original donor part name
            target_vehicle: Target vehicle name
            
        Returns:
            Adapted part name for target vehicle
        """
        # Use slot graph mapping if available
        if self._slot_graph and donor_part_name in self._slot_graph.part_name_map:
            return self._slot_graph.part_name_map[donor_part_name]
        
        # Fallback: prefix with vehicle name (existing logic)
        return f"{target_vehicle}_{donor_part_name}"
    
    def _transform_slots_with_graph(self, 
                                     slots_array: List[Any], 
                                     adapted_part_name: str,
                                     target_vehicle: str) -> List[Any]:
        """
        Transform slots array using SlotAwareJBeamWriter if slot graph available.
        
        This applies the slot graph's planned transformations to produce correct:
        - Slot type mappings (Camso_Transmission -> pickup_transmission)
        - Default part name mappings (Camso_Transmission_ec8ba -> pickup_Camso_Transmission_ec8ba)
        - coreSlot attributes for structural dependencies
        
        Args:
            slots_array: Original slots array from donor part
            adapted_part_name: Name of the adapted part (e.g., "pickup_Camso_Engine_3813e")
            target_vehicle: Target vehicle name (e.g., "pickup")
            
        Returns:
            Transformed slots array, or original if slot graph not available
        """
        if not SLOT_GRAPH_AVAILABLE or not self._slot_graph:
            logger.debug("  [SlotGraph] Not available - preserving original slots")
            return slots_array
        
        logger.info(f"  [SlotGraph] Transforming slots for {adapted_part_name}")
        
        try:
            # Use SlotAwareJBeamWriter to generate transformed slots
            writer = SlotAwareJBeamWriter(self._slot_graph)
            transformed_slots = writer.generate_slots_section(adapted_part_name)
            
            if transformed_slots:
                logger.info(f"  [SlotGraph] Generated {len(transformed_slots) - 1} transformed slots (+ header)")
                
                # Log key transformations
                for slot in transformed_slots[1:]:  # Skip header
                    if isinstance(slot, list) and len(slot) >= 2:
                        slot_type = slot[0]
                        default = slot[1] if len(slot) > 1 else ""
                        # Check if this was transformed
                        if slot_type in self._slot_graph.slot_type_map.values():
                            logger.info(f"    [ADAPTED] {slot_type} -> {default}")
                
                return transformed_slots
            else:
                logger.warning(f"  [SlotGraph] Writer returned empty slots - using original")
                return slots_array
                
        except Exception as e:
            logger.error(f"  [SlotGraph] Failed to transform slots: {e}")
            import traceback
            traceback.print_exc()
            return slots_array
    
    def _inject_tms_geometry(self, part_data: Dict[str, Any], solver_result) -> None:
        """
        Inject TMS-solved geometry (nodes and beams) into adapted part.
        
        Follows BeamNG convention: property modifiers are emitted ONCE as dictionary rows,
        then subsequent node rows inherit those properties. This matches the source
        Camso/Automation pattern and produces cleaner, more maintainable output.
        
        Property Preservation Strategy:
            1. Extract common properties from first translated node
            2. Emit property modifier rows (nodeWeight, group, engineGroup, etc.)
            3. Emit node rows WITHOUT individual properties (they inherit from modifiers)
        
        Mount Node Injection:
            After engine cube nodes, inject:
            - {"engineGroup":""}  (reset engineGroup)
            - {"group":""}        (reset group)
            - Mount nodes from target vehicle (em1l, em1r, etc.)
        
        Mount Beam Injection:
            After engine cube beams, inject:
            - Mount beam property modifiers (spring, damp, deform, strength from target)
            - Mount-to-engine beams (each mount to all 8 engine nodes)
        """
        if not solver_result.engine_cube:
            return
        
        # Extract common properties from translated nodes
        # These will be emitted as property modifier rows instead of per-node
        common_properties = self._extract_common_node_properties(solver_result.engine_cube)
        
        # Generate clean node arrays (without per-node properties)
        translated_nodes = self._generate_clean_node_arrays(solver_result.engine_cube)
        
        # Inject or update nodes section
        if 'nodes' in part_data:
            # Append to existing nodes
            existing_nodes = part_data['nodes']
            if isinstance(existing_nodes, list):
                # Find header row
                header_idx = -1
                for i, row in enumerate(existing_nodes):
                    if isinstance(row, list) and len(row) > 0 and row[0] == 'id':
                        header_idx = i
                        break
                
                if header_idx >= 0:
                    # Insert after header and any property rows
                    insert_idx = header_idx + 1
                    while insert_idx < len(existing_nodes) and isinstance(existing_nodes[insert_idx], dict):
                        insert_idx += 1
                    
                    # Remove old engine block nodes if they exist
                    beamng_node_names = ['e1l', 'e1r', 'e2l', 'e2r', 'e3l', 'e3r', 'e4l', 'e4r']
                    mount_node_names = [m.name for m in solver_result.mount_nodes] if solver_result.mount_nodes else []
                    nodes_to_remove = set(beamng_node_names + mount_node_names)
                    existing_nodes[:] = [row for row in existing_nodes 
                                        if not (isinstance(row, list) and len(row) > 0 and row[0] in nodes_to_remove)]
                    
                    # Recalculate insert position after removal
                    insert_idx = header_idx + 1
                    while insert_idx < len(existing_nodes) and isinstance(existing_nodes[insert_idx], dict):
                        insert_idx += 1
                    
                    # Insert property modifier rows FIRST (BeamNG convention)
                    for prop_row in common_properties:
                        existing_nodes.insert(insert_idx, prop_row)
                        insert_idx += 1
                    
                    # Insert clean node arrays (without individual properties)
                    for node_array in translated_nodes:
                        existing_nodes.insert(insert_idx, node_array)
                        insert_idx += 1
                    
                    # Insert mount nodes after engine cube (BeamNG convention)
                    if solver_result.mount_nodes:
                        # Reset engineGroup and group before mount nodes
                        existing_nodes.insert(insert_idx, {"engineGroup": ""})
                        insert_idx += 1
                        existing_nodes.insert(insert_idx, {"group": ""})
                        insert_idx += 1
                        
                        # Insert mount nodes
                        for mount in solver_result.mount_nodes:
                            mount_row = [mount.name, mount.position.x, mount.position.y, mount.position.z, {"nodeWeight": 3}]
                            existing_nodes.insert(insert_idx, mount_row)
                            insert_idx += 1
                        
                        logger.info(f"  [TMS]   Injected {len(solver_result.mount_nodes)} mount nodes")
                else:
                    # No header found, just append with properties
                    for prop_row in common_properties:
                        part_data['nodes'].append(prop_row)
                    part_data['nodes'].extend(translated_nodes)
                    
                    # Append mount nodes
                    if solver_result.mount_nodes:
                        part_data['nodes'].append({"engineGroup": ""})
                        part_data['nodes'].append({"group": ""})
                        for mount in solver_result.mount_nodes:
                            part_data['nodes'].append([mount.name, mount.position.x, mount.position.y, mount.position.z, {"nodeWeight": 3}])
        else:
            # Create new nodes section with full property context
            nodes_section = [
                ['id', 'posX', 'posY', 'posZ'],
            ] + common_properties + translated_nodes
            
            # Add mount nodes
            if solver_result.mount_nodes:
                nodes_section.append({"engineGroup": ""})
                nodes_section.append({"group": ""})
                for mount in solver_result.mount_nodes:
                    nodes_section.append([mount.name, mount.position.x, mount.position.y, mount.position.z, {"nodeWeight": 3}])
            
            part_data['nodes'] = nodes_section
        
        # Generate and inject engine cube beams
        engine_beams = generate_engine_beams(solver_result.engine_cube)
        
        if 'beams' in part_data:
            existing_beams = part_data['beams']
            if isinstance(existing_beams, list):
                # Append engine beams with property row from source engine
                if solver_result.source_engine_beam_properties:
                    props = solver_result.source_engine_beam_properties
                    existing_beams.append({
                        'beamSpring': props.beam_spring,
                        'beamDamp': props.beam_damp,
                        'beamDeform': props.beam_deform,
                        'beamStrength': props.beam_strength
                    })
                else:
                    # Fallback to Camso defaults
                    existing_beams.append({'beamSpring': 3.30439e+07, 'beamDamp': 1650.54, 'beamDeform': 330109, 'beamStrength': 8.25272e+06})
                
                existing_beams.extend(engine_beams[1:])  # Skip header
                
                # Inject mount beams after engine cube beams
                if solver_result.mount_nodes and solver_result.engine_cube:
                    # Add mount beam properties from target vehicle
                    if solver_result.mount_beam_properties:
                        props = solver_result.mount_beam_properties
                        existing_beams.append({
                            'beamSpring': props.beam_spring,
                            'beamDamp': props.beam_damp,
                            'beamDeform': props.beam_deform,
                            'beamStrength': props.beam_strength
                        })
                    else:
                        # Fallback to pickup defaults
                        existing_beams.append({'beamSpring': 2956300, 'beamDamp': 130.43, 'beamDeform': 63000, 'beamStrength': 'FLT_MAX'})
                    
                    # Generate and append mount beams
                    mount_beams = generate_mount_beams(solver_result.mount_nodes, solver_result.engine_cube)
                    existing_beams.extend(mount_beams)
                    
                    # Close mount beam section
                    existing_beams.append({"deformGroup": ""})
                    
                    logger.info(f"  [TMS]   Injected {len(mount_beams)} mount-to-engine beams")
        else:
            # Create new beams section with source engine beam properties
            beams_section = [["id1:", "id2:"]]  # Header
            
            # Add source engine beam properties
            if solver_result.source_engine_beam_properties:
                props = solver_result.source_engine_beam_properties
                beams_section.append({
                    'beamSpring': props.beam_spring,
                    'beamDamp': props.beam_damp,
                    'beamDeform': props.beam_deform,
                    'beamStrength': props.beam_strength
                })
            else:
                beams_section.append({'beamSpring': 3.30439e+07, 'beamDamp': 1650.54, 'beamDeform': 330109, 'beamStrength': 8.25272e+06})
            
            # Add engine cube beams
            beams_section.extend(engine_beams[1:])  # Skip header
            
            # Add mount beams
            if solver_result.mount_nodes and solver_result.engine_cube:
                if solver_result.mount_beam_properties:
                    props = solver_result.mount_beam_properties
                    beams_section.append({
                        'beamSpring': props.beam_spring,
                        'beamDamp': props.beam_damp,
                        'beamDeform': props.beam_deform,
                        'beamStrength': props.beam_strength
                    })
                else:
                    beams_section.append({'beamSpring': 2956300, 'beamDamp': 130.43, 'beamDeform': 63000, 'beamStrength': 'FLT_MAX'})
                
                mount_beams = generate_mount_beams(solver_result.mount_nodes, solver_result.engine_cube)
                beams_section.extend(mount_beams)
                beams_section.append({"deformGroup": ""})
            
            part_data['beams'] = beams_section
    
    def _extract_isExhaust_from_adapted(
        self,
        adapted_part_data: Dict[str, Any],
        part_name: str,
    ) -> 'Tuple[int, list]':
        """
        Extract isExhaust nodes from adapted engine part data (in-memory, post-TMS).
        
        Uses exhaust_solver's extract_isExhaust_nodes() to walk the nodes section
        with group/nodeGroup modifier tracking, then filters to engine_block group.
        
        Args:
            adapted_part_data: The adapted engine part dict (with TMS-injected nodes)
            part_name: Adapted part name for wrapping
            
        Returns:
            (count, list_of_IsExhaustNode) — typically 1 or 2 for Camso engines.
        """
        if not EXHAUST_SOLVER_AVAILABLE:
            return 0, []
        
        # Wrap in parsed-data format for exhaust_solver's extraction function
        wrapped = {part_name: adapted_part_data}
        results = exhaust_extract_isExhaust_nodes(wrapped, "adapted_engine")
        
        # Flatten across all parts
        flat = []
        for nodes in results.values():
            flat.extend(nodes)
        
        # Filter to engine group (same logic as count_donor_isExhaust_nodes)
        engine_nodes = [
            n for n in flat
            if 'engine' in n.group.lower() or 'block' in n.group.lower() or n.group == ''
        ]
        
        return len(engine_nodes), engine_nodes
    
    def _extract_common_node_properties(self, engine_cube) -> List[Dict[str, Any]]:
        """
        Extract common properties from engine cube nodes to emit as property modifier rows.
        
        BeamNG Convention:
            Property modifier rows (dicts) apply to ALL subsequent nodes until overridden.
            This produces cleaner output matching the source Camso/Automation pattern.
        
        Returns:
            List of property modifier dictionaries in order:
            - {"frictionCoef": 0.5}
            - {"nodeMaterial": "|NM_METAL"}
            - {"collision": true}
            - {"group": "engine"}
            - {"selfCollision": false}
            - {"nodeWeight": <weight>}
        
        Note:
            engineGroup is handled differently - it varies per node so stays inline.
        """
        property_rows = []
        
        # Get a sample node to extract common properties
        sample_node = None
        sample_props = {}
        for node in engine_cube.nodes.values():
            if node.node_properties:
                sample_node = node
                sample_props = node.node_properties.copy()
                break
        
        # Standard BeamNG engine node property order (from Camso reference)
        # These are emitted as separate rows for clarity and maintainability
        
        # 1. Friction coefficient
        if 'frictionCoef' in sample_props:
            property_rows.append({"frictionCoef": sample_props['frictionCoef']})
        else:
            property_rows.append({"frictionCoef": 0.5})  # BeamNG default for engine
        
        # 2. Node material
        if 'nodeMaterial' in sample_props:
            property_rows.append({"nodeMaterial": sample_props['nodeMaterial']})
        else:
            property_rows.append({"nodeMaterial": "|NM_METAL"})
        
        # 3. Collision enabled
        if 'collision' in sample_props:
            property_rows.append({"collision": sample_props['collision']})
        else:
            property_rows.append({"collision": True})
        
        # 4. Group assignment
        property_rows.append({"group": "engine"})
        
        # 5. Self-collision disabled (engines shouldn't self-collide)
        if 'selfCollision' in sample_props:
            property_rows.append({"selfCollision": sample_props['selfCollision']})
        else:
            property_rows.append({"selfCollision": False})
        
        # 6. Node weight (critical for physics)
        node_weight = None
        if 'nodeWeight' in sample_props:
            node_weight = sample_props['nodeWeight']
        else:
            # Try to find nodeWeight in any node
            for node in engine_cube.nodes.values():
                if 'nodeWeight' in node.node_properties:
                    node_weight = node.node_properties['nodeWeight']
                    break
        
        if node_weight is not None:
            property_rows.append({"nodeWeight": node_weight})
        else:
            # Default weight for engine nodes (from Camso reference)
            property_rows.append({"nodeWeight": 33.0109})
            logger.warning("  [TMS] No nodeWeight found in donor, using default 33.0109")
        
        logger.info(f"  [TMS]   Extracted {len(property_rows)} property modifier rows")
        return property_rows
    
    def _generate_clean_node_arrays(self, engine_cube) -> List[List[Any]]:
        """
        Generate node arrays WITHOUT per-node properties (except engineGroup).
        
        BeamNG Convention:
            - Common properties (nodeWeight, collision, etc.) are inherited from modifier rows
            - Only node-specific properties (engineGroup, isExhaust) are inline
        
        Args:
            engine_cube: EngineCube with translated nodes
            
        Returns:
            List of node arrays: ["name", x, y, z] or ["name", x, y, z, {inline_props}]
        """
        nodes = []
        
        # Properties that should remain inline (vary per node)
        INLINE_PROPERTIES = {'engineGroup', 'isExhaust', 'tag'}
        
        # Properties that are emitted as modifier rows (common to all)
        MODIFIER_PROPERTIES = {'nodeWeight', 'frictionCoef', 'nodeMaterial', 
                               'collision', 'selfCollision', 'group'}
        
        for node in engine_cube.nodes.values():
            # Extract only inline properties
            inline_props = {}
            for key, value in node.node_properties.items():
                if key in INLINE_PROPERTIES:
                    inline_props[key] = value
            
            # Build node array
            if inline_props:
                nodes.append([
                    node.name,
                    node.position.x,
                    node.position.y,
                    node.position.z,
                    inline_props
                ])
            else:
                nodes.append([
                    node.name,
                    node.position.x,
                    node.position.y,
                    node.position.z
                ])
        
        return nodes

    def _translate_torque_reaction_nodes(self, part_data: Dict[str, Any]) -> None:
        """
        Translate torqueReactionNodes from Camso naming to BeamNG naming.
        
        Camso engines use engine0-7 names, but TMS translates to BeamNG e1l-e4r names.
        The torqueReactionNodes must reference the translated names.
        """
        # Check mainEngine section for torqueReactionNodes
        main_engine = part_data.get('mainEngine', {})
        if not main_engine:
            return
        
        # Look for torqueReactionNodes (may have trailing colon in key)
        trn_key = None
        trn_value = None
        for key in list(main_engine.keys()):
            if 'torqueReactionNodes' in key:
                trn_key = key
                trn_value = main_engine[key]
                break
        
        if not trn_value:
            return
        
        # Handle both list and string formats (use module-level constant)
        if isinstance(trn_value, list):
            translated = []
            for node_name in trn_value:
                # Clean up node name (may have trailing comma/space from parser)
                clean_name = str(node_name).strip().rstrip(',').strip()
                if clean_name in CAMSO_TO_BEAMNG_NODE_MAP:
                    translated.append(CAMSO_TO_BEAMNG_NODE_MAP[clean_name])
                else:
                    translated.append(clean_name)  # Keep as-is if not in map
            main_engine[trn_key] = translated
            logger.info(f"  [TMS]   Translated torqueReactionNodes: {trn_value} -> {translated}")
        elif isinstance(trn_value, str):
            # Single node as string
            clean_name = trn_value.strip().rstrip(',').strip()
            if clean_name in CAMSO_TO_BEAMNG_NODE_MAP:
                main_engine[trn_key] = CAMSO_TO_BEAMNG_NODE_MAP[clean_name]
                logger.info(f"  [TMS]   Translated torqueReactionNodes: {clean_name} -> {main_engine[trn_key]}")
    
    def _neutralize_structure_slot(self, part_data: Dict[str, Any]) -> None:
        """
        Neutralize the Camso_engine_structure slot to prevent duplicate node loading.
        
        Since TMS has embedded translated nodes (e1l-e4r) directly into the engine part,
        we must prevent the original Camso structure file (with engine0-7) from loading.
        Setting the slot default to "" keeps the slot available but loads nothing.
        
        Args:
            part_data: Engine part data to modify
        """
        if 'slots' not in part_data:
            return
        
        slots = part_data['slots']
        
        for i, slot in enumerate(slots):
            if isinstance(slot, list) and len(slot) >= 2:
                slot_type = slot[0]
                # Check for Camso_engine_structure or similar structure slot
                if 'engine_structure' in str(slot_type).lower() or 'Camso_engine_structure' in str(slot_type):
                    original_default = slot[1] if len(slot) > 1 else ""
                    # Neutralize by setting default to empty string
                    slot[1] = ""
                    logger.info(f"  [TMS]   Neutralized structure slot: {slot_type} (was: {original_default})")
                    return
    
    def _create_adapted_part_name(self, donor_part_name: str, vehicle_name: str) -> str:
        """
        Create vehicle-specific part name.
        
        Uses slot graph mappings if available for consistent naming across
        all parts in the ecosystem.
        """
        # Use slot graph mapping if available (single source of truth)
        return self._get_adapted_part_name_from_graph(donor_part_name, vehicle_name)
    
    def _deep_copy_part_data(self, part_data: Dict[str, Any]) -> Dict[str, Any]:
        """Deep copy part data preserving all attributes."""
        import copy
        return copy.deepcopy(part_data)
    
    def _inject_engine_mount_slot(self, part_data: Dict[str, Any], mount_slot_type: Optional[str] = None) -> None:
        """
        Inject vehicle-specific engine mount slot into adapted engine.
        
        This is CRITICAL for proper physical attachment to chassis.
        Following Cummins mod pattern: use target vehicle's enginemounts slot.
        
        Args:
            part_data: Engine part data to modify
            mount_slot_type: Dynamically discovered enginemounts slot type
                (e.g., 'etk_enginemounts'). Read from target engine file slots.
        """
        if not mount_slot_type:
            logger.warning("  No mount slot type provided for engine mount injection")
            return
        
        if 'slots' not in part_data:
            part_data['slots'] = []
        
        slots = part_data['slots']
        
        # Find header row (usually first entry)
        header_idx = -1
        for i, slot in enumerate(slots):
            if isinstance(slot, list) and len(slot) >= 2:
                if slot[0] == "type" and slot[1] == "default":
                    header_idx = i
                    break
        
        # If no header, add one
        if header_idx == -1:
            slots.insert(0, ["type", "default", "description"])
            header_idx = 0
        
        # Check if mount slot already exists
        has_mount_slot = False
        for slot in slots[header_idx+1:]:
            if isinstance(slot, list) and len(slot) > 0:
                if mount_slot_type in str(slot[0]):
                    has_mount_slot = True
                    break
        
        # Add mount slot if missing (insert right after header)
        if not has_mount_slot:
            # Pattern from engine files:
            # ["etk_enginemounts","etk_enginemounts", "Engine Mounts", {"coreSlot":true}]
            mount_slot = [
                mount_slot_type,
                mount_slot_type,  # Default to stock mounts
                "Engine Mounts",
                {"coreSlot": True}
            ]
            slots.insert(header_idx + 1, mount_slot)
            logger.info(f"  Injected engine mount slot: {mount_slot_type}")
    
    def generate_adapted_transmission(self,
                                     donor_file: Path,
                                     target_vehicle: VehicleInfo) -> Optional[Path]:
        """
        Adapt transmission file for target vehicle.
        Follows Cummins pattern: change slotType to target vehicle's transmission slot.
        
        Also injects transmission nodes with redistributed Camso gearbox weight,
        and beams connecting to engine nodes.
        
        Args:
            donor_file: Path to donor transmission .jbeam file
            target_vehicle: Target vehicle information
            
        Returns:
            Path to generated temp file, or None if generation fails
        """
        logger.info(f"Adapting transmission: {donor_file.name} -> {target_vehicle.name}")
        
        # Parse donor file
        donor_data = JBeamParser.parse_jbeam(donor_file)
        if not donor_data:
            logger.error(f"Failed to parse transmission file: {donor_file}")
            return None
        
        # Get Camso gearbox weight from solver result
        camso_gearbox_weight = 0.0
        if self._last_solver_result:
            camso_gearbox_weight = self._last_solver_result.camso_gearbox_weight
        
        # Find and load target vehicle's transmission file for structure extraction
        trans_structure = None
        if TMS_AVAILABLE:
            target_trans_file = self._find_target_transmission_file(target_vehicle)
            if target_trans_file:
                target_trans_jbeam = JBeamParser.parse_jbeam(target_trans_file)
                if target_trans_jbeam:
                    target_extractor = TargetVehicleExtractor(target_trans_jbeam)
                    # Filter for transmission parts only (exclude transfer_case)
                    raw_trans_structure = target_extractor.extract_transmission_structure(
                        slot_type_filter="transmission"
                    )
                    if raw_trans_structure and raw_trans_structure.nodes:
                        # Deduplicate nodes by name (keep first occurrence)
                        unique_nodes = {}
                        for node in raw_trans_structure.nodes:
                            if node.name not in unique_nodes:
                                unique_nodes[node.name] = node
                        
                        # Create new structure with deduplicated nodes
                        trans_structure = TransmissionStructure(
                            nodes=list(unique_nodes.values()),
                            beam_properties=raw_trans_structure.beam_properties,
                            connected_engine_nodes=raw_trans_structure.connected_engine_nodes
                        )
                        
                        logger.info(f"  [TMS] Target transmission structure: {len(trans_structure.nodes)} unique nodes")
                        logger.info(f"  [TMS] Camso gearbox weight: {camso_gearbox_weight:.2f} kg")
                        for node in trans_structure.nodes:
                            logger.info(f"    - {node.name}: pos=({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
                    else:
                        logger.warning("  [TMS] No transmission nodes (tra*) found in target transmission file")
                else:
                    logger.warning(f"  Failed to parse target transmission file: {target_trans_file}")
            else:
                logger.warning(f"  Could not find target transmission file for {target_vehicle.name}")
        
        adapted_data = {}
        
        # Process each part
        for part_name, part_data in donor_data.items():
            if not isinstance(part_data, dict):
                continue
            
            donor_slot_type = part_data.get('slotType', '')
            
            # Check if this is a primary transmission part
            if donor_slot_type and 'transmission' in donor_slot_type.lower():
                # Create vehicle-specific name
                adapted_part_name = f"{target_vehicle.name}_{part_name}"
                adapted_part_data = self._deep_copy_part_data(part_data)
                
                # Adapt slotType to target vehicle transmission slot
                # Use slot graph mapping if available, fall back to family prefix derivation
                if self._slot_graph and donor_slot_type in self._slot_graph.slot_type_map:
                    target_trans_slot = self._slot_graph.slot_type_map[donor_slot_type]
                else:
                    # Derive prefix from engine_slot_type for family vehicles
                    prefix = target_vehicle.name
                    if target_vehicle.engine_slot_type:
                        derived = target_vehicle.engine_slot_type.replace('_engine', '')
                        if derived != target_vehicle.name:
                            prefix = derived
                    target_trans_slot = f"{prefix}_transmission"
                adapted_part_data['slotType'] = target_trans_slot
                
                logger.info(f"  Adapted transmission slotType: {donor_slot_type} -> {target_trans_slot}")
                logger.info(f"  Part name: {part_name} -> {adapted_part_name}")
                
                # Update information
                if 'information' in adapted_part_data:
                    info = adapted_part_data['information']
                    if 'name' in info:
                        info['name'] = f"{info['name']} ({target_vehicle.name.title()} Swap)"
                
                # === SLOT GRAPH INTEGRATION ===
                # Transform slots using slot graph mappings (e.g., Camso_TransferCase -> pickup_transfer_case)
                if 'slots' in adapted_part_data:
                    original_slot_count = len(adapted_part_data['slots'])
                    adapted_part_data['slots'] = self._transform_slots_with_graph(
                        adapted_part_data['slots'],
                        adapted_part_name,
                        target_vehicle.name
                    )
                    logger.info(f"  Slots: {original_slot_count} original -> {len(adapted_part_data['slots'])} transformed")
                
                # === Inject transmission nodes and beams ===
                if trans_structure and trans_structure.nodes and camso_gearbox_weight > 0:
                    self._inject_transmission_geometry(
                        adapted_part_data, 
                        trans_structure, 
                        camso_gearbox_weight
                    )
                
                # Update gearboxNode: reference from Camso engine0 to BeamNG tra1
                self._update_gearbox_node_reference(adapted_part_data, trans_structure)
                
                adapted_data[adapted_part_name] = adapted_part_data
            else:
                # Keep child parts as-is
                adapted_data[part_name] = self._deep_copy_part_data(part_data)
        
        # Post-process: powertrain property tweaks
        adapted_data = self._apply_powertrain_tweaks(adapted_data, "transmission", target_vehicle.name)
        
        # Write to temp file
        temp_file = self.temp_path / f"{target_vehicle.name}_{donor_file.stem}_adapted.jbeam"
        try:
            self._write_jbeam_file(temp_file, adapted_data)
            logger.info(f"  Generated transmission file: {temp_file}")
            return temp_file
        except Exception as e:
            logger.error(f"Failed to write transmission file: {e}")
            return None
    
    def _inject_transmission_geometry(self,
                                       part_data: Dict[str, Any],
                                       trans_structure: TransmissionStructure,
                                       camso_total_weight: float) -> None:
        """
        Inject transmission nodes and beams into adapted part.
        
        Uses BeamNG target vehicle node positions and beam properties,
        with Camso gearbox weight redistributed across nodes.
        
        Args:
            part_data: Part data dict to modify
            trans_structure: Target vehicle transmission structure
            camso_total_weight: Total weight of Camso gearbox nodes (to redistribute)
        """
        if not trans_structure.nodes:
            return
        
        # Calculate redistributed weight per node
        node_count = len(trans_structure.nodes)
        weight_per_node = camso_total_weight / node_count
        
        logger.info(f"  [TMS] Injecting transmission: {node_count} nodes at {weight_per_node:.2f} kg each")
        
        # Build nodes section
        nodes_section = [
            ["id", "posX", "posY", "posZ"],
            {"selfCollision": False},
            {"collision": True},
            {"frictionCoef": 0.5},
            {"nodeMaterial": "|NM_METAL"},
            {"nodeWeight": weight_per_node},
            {"group": trans_structure.nodes[0].group if trans_structure.nodes[0].group else f"pickup_transmission"}
        ]
        
        # Add transmission nodes
        for trans_node in trans_structure.nodes:
            nodes_section.append([
                trans_node.name, 
                trans_node.position.x, 
                trans_node.position.y, 
                trans_node.position.z
            ])
        
        nodes_section.append({"group": ""})
        
        part_data['nodes'] = nodes_section
        
        # Build beams section
        if trans_structure.beam_properties and trans_structure.connected_engine_nodes:
            beams_section = [["id1:", "id2:"]]
            
            # Add beam properties
            props = trans_structure.beam_properties
            beams_section.append({
                "beamPrecompression": 1,
                "beamType": "|NORMAL",
                "beamLongBound": 1.0,
                "beamShortBound": 1.0
            })
            beams_section.append({
                "beamSpring": props.beam_spring,
                "beamDamp": props.beam_damp,
                "beamDeform": props.beam_deform,
                "beamStrength": props.beam_strength
            })
            
            # Generate transmission-to-engine beams
            trans_beams = generate_transmission_beams(
                trans_structure.nodes,
                trans_structure.connected_engine_nodes
            )
            beams_section.extend(trans_beams)
            
            # Reset beam properties
            beams_section.append({
                "beamPrecompression": 1,
                "beamType": "|NORMAL",
                "beamLongBound": 1.0,
                "beamShortBound": 1.0
            })
            
            part_data['beams'] = beams_section
            logger.info(f"  [TMS] Injected {len(trans_beams)} transmission-to-engine beams")
    
    def _update_gearbox_node_reference(self,
                                        part_data: Dict[str, Any],
                                        trans_structure: Optional[TransmissionStructure]) -> None:
        """
        Update gearboxNode: reference from Camso engine naming to BeamNG tra1.
        
        Camso uses "engine0" or similar as the gearbox reference node.
        BeamNG uses "tra1" as the transmission output shaft node.
        
        Args:
            part_data: Part data dict to modify
            trans_structure: Transmission structure with node names
        """
        # Determine the primary transmission node (tra1)
        primary_node = "tra1"  # Default BeamNG convention
        if trans_structure and trans_structure.nodes:
            # Use the first node from structure (typically tra1)
            primary_node = trans_structure.nodes[0].name
        
        # Update gearboxNode: in gearbox section
        if 'gearbox' in part_data:
            gearbox = part_data['gearbox']
            old_ref = gearbox.get('gearboxNode:', None)
            if old_ref:
                gearbox['gearboxNode:'] = primary_node
                logger.info(f"  [TMS] Updated gearboxNode: {old_ref} -> {primary_node}")
            else:
                # Try without colon
                old_ref = gearbox.get('gearboxNode', None)
                if old_ref:
                    # Replace with colon version
                    del gearbox['gearboxNode']
                    gearbox['gearboxNode:'] = primary_node
                    logger.info(f"  [TMS] Updated gearboxNode: {old_ref} -> {primary_node}")
    
    # =========================================================================
    # Phase 5: Strategy-Specific TC Adaptation Helpers
    # =========================================================================
    
    @staticmethod
    def _prune_driveshaft_slots(part_data: Dict[str, Any],
                                slot_types_to_prune: List[str]) -> List[str]:
        """
        Remove specific child slot entries from a part's slots/slots2 arrays.
        
        Searches both 'slots' and 'slots2' arrays in part_data and removes
        any slot entry whose slotType matches one of the pruning targets.
        
        Args:
            part_data: The part's data dict (modified in place)
            slot_types_to_prune: List of slotType strings to remove
                (e.g., ['Camso_driveshaft_front', 'Camso_driveshaft_rear'])
        
        Returns:
            List of slotType strings that were actually removed
        """
        pruned = []
        prune_set = set(slot_types_to_prune)
        
        for slots_key in ('slots', 'slots2'):
            if slots_key not in part_data:
                continue
            
            slots_array = part_data[slots_key]
            if not isinstance(slots_array, list) or len(slots_array) < 2:
                continue
            
            # slots format: [header_row, entry1, entry2, ...]
            # Each entry is a list like: ["slotType", "default", "description", ...]
            # or a dict (property row like {"coreSlot": true})
            kept = [slots_array[0]]  # Keep header
            for entry in slots_array[1:]:
                if isinstance(entry, list) and len(entry) >= 1:
                    entry_slot_type = entry[0]
                    if entry_slot_type in prune_set:
                        pruned.append(entry_slot_type)
                        continue  # Skip (prune) this entry
                # Keep non-matching entries and property dicts
                kept.append(entry)
            
            part_data[slots_key] = kept
        
        return pruned
    
    @staticmethod
    def _normalize_powertrain_device_names(part_data: Dict[str, Any],
                                           renames: Dict[str, str]) -> int:
        """
        Rename powertrain device names and inputName references in a part.
        
        Handles three locations where device names appear:
        1. Powertrain array: device 'name' field (index 1) and 'inputName' field (index 2)
        2. Config override sections: top-level keys matching old device names
        3. Controller entries: 'deviceName' or 'splitShaftName' fields in properties dicts
        
        Args:
            part_data: The part's data dict (modified in place)
            renames: Mapping of old_name → new_name
                (e.g., {'transferCase': 'transfercase'})
        
        Returns:
            Count of renames applied
        """
        count = 0
        
        # 1. Powertrain array: [type, name, inputName, inputIndex, {props}]
        if 'powertrain' in part_data:
            pt = part_data['powertrain']
            if isinstance(pt, list):
                for entry in pt:
                    if isinstance(entry, list) and len(entry) >= 3:
                        # Device name (index 1)
                        if entry[1] in renames:
                            old = entry[1]
                            entry[1] = renames[old]
                            count += 1
                        # InputName (index 2)
                        if entry[2] in renames:
                            old = entry[2]
                            entry[2] = renames[old]
                            count += 1
        
        # 2. Config override sections: {"transferCase": {...}} → {"transfercase": {...}}
        for old_name, new_name in renames.items():
            if old_name in part_data and old_name != new_name:
                part_data[new_name] = part_data.pop(old_name)
                count += 1
        
        # 3. Controller entries — search for deviceName/splitShaftName/differentialName references
        if 'controller' in part_data:
            ctrl = part_data['controller']
            if isinstance(ctrl, list):
                for entry in ctrl:
                    if isinstance(entry, list):
                        for item in entry:
                            if isinstance(item, dict):
                                for key in ('deviceName', 'splitShaftName', 'differentialName'):
                                    if key in item and item[key] in renames:
                                        item[key] = renames[item[key]]
                                        count += 1
        
        return count
    
    @staticmethod
    def _derive_device_name_mapping(adapted_data: Dict[str, Any],
                                    swap_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Derive powertrain device name mapping from analysis data.
        
        Instead of hardcoding rename targets (e.g., 'transferCase' → 'transfercase'),
        this method reads:
        - TARGET device names from swap_decision["selected_tc"]["devices"]
        - DONOR device names from adapted_data parts' powertrain arrays
        
        and builds a rename mapping with full provenance for traceability.
        
        Matching strategy (structural positional matching):
        - Build a target lookup keyed by (device_type, inputName) → target device name
        - Walk each donor powertrain entry and look up the target name by matching
          the device's structural role (type + what it connects to)
        - inputName references are resolved transitively: if device A was renamed,
          any device whose inputName references A's old name gets its inputName
          updated via the same mapping
        
        This follows the same "analyze → populate mapping → consume mapping" pattern
        used by the slot graph system for slot type adaptation.
        
        Args:
            adapted_data: Dict of {part_name: part_data} for the adapted TC parts
            swap_decision: Phase 3 swap decision dict containing selected_tc with devices
        
        Returns:
            Dict with:
                'renames': {donor_name: target_name} mapping
                'provenance': list of {donor_name, target_name, source, reason} records
        """
        renames = {}
        provenance = []
        
        # --- Extract target device topology from Phase 1 analysis ---
        selected_tc = swap_decision.get("selected_tc")
        if not selected_tc or not isinstance(selected_tc, dict):
            logger.warning("  [Phase5] Cannot derive device name mapping — "
                           "selected_tc not available. Skipping.")
            return {"renames": {}, "provenance": []}
        
        target_devices = selected_tc.get("devices", [])
        if not target_devices:
            logger.warning("  [Phase5] Cannot derive device name mapping — "
                           "selected_tc has no devices. Skipping.")
            return {"renames": {}, "provenance": []}
        
        # Build target lookup: (type, inputName) → device name
        # This captures each device's STRUCTURAL ROLE in the chain
        target_by_role = {}
        for dev in target_devices:
            role_key = (dev["type"], dev.get("inputName", ""))
            target_by_role[role_key] = dev["name"]
        
        tc_part_name = selected_tc.get("part_name", "?")
        logger.info(f"  [Phase5] Target TC topology ({tc_part_name}): "
                    f"{len(target_devices)} device(s)")
        for dev in target_devices:
            logger.info(f"    {dev['type']}('{dev['name']}') ← {dev.get('inputName', '?')}")
        
        # --- Scan donor parts and structurally match devices ---
        donor_type = swap_decision.get("donor_drive_type", "UNKNOWN")
        
        for part_name, part_data in adapted_data.items():
            if not isinstance(part_data, dict):
                continue
            
            powertrain = part_data.get("powertrain", [])
            if not isinstance(powertrain, list):
                continue
            
            for entry in powertrain:
                if not isinstance(entry, list) or len(entry) < 4:
                    continue
                
                dev_type = entry[0]     # e.g., "shaft", "differential", "rangeBox"
                dev_name = entry[1]     # e.g., "transferCase"
                input_name = entry[2]   # e.g., "gearbox", "rangebox"
                
                # Skip header rows
                if dev_name in ("name", "type") or dev_type in ("name", "type"):
                    continue
                
                # Resolve inputName through any already-mapped renames
                # (e.g., if "transferCase" was renamed to "transfercase",
                #  a downstream device referencing "transferCase" should match
                #  against the target's "transfercase" input)
                resolved_input = renames.get(input_name, input_name)
                
                # Look up target device by structural role (type + resolved inputName)
                role_key = (dev_type, resolved_input)
                target_name = target_by_role.get(role_key)
                
                if target_name and dev_name != target_name and dev_name not in renames:
                    renames[dev_name] = target_name
                    provenance.append({
                        "donor_name": dev_name,
                        "target_name": target_name,
                        "source_part": part_name,
                        "target_part": tc_part_name,
                        "reason": (f"structural match: {dev_type}(inputName='{input_name}') "
                                   f"-> target {dev_type}('{target_name}')"),
                    })
                
                # FWD edge case: donor uses frontDriveShaft as primary output.
                # FWD topology is fundamentally different — a single shaft from
                # gearbox, vs the target's multi-device chain (rangebox → differential → shaft).
                # Map to the target's DIFFERENTIAL device (not the root rangeBox),
                # since the FWD shaft serves the same torque-routing role as the
                # target's central TC differential.
                # Note: This FWD adaptation path is segmented from conventional
                # structural matching — Camso native rangebox variant parts
                # (Camso_TransferCase_FWD_rangebox_*) are unaffected as their
                # rangeBox device structurally matches the target's rangeBox.
                if (donor_type == "FWD"
                        and dev_name == "frontDriveShaft"
                        and dev_name not in renames
                        and target_name is None):
                    # Find the target's differential device (the central TC device)
                    target_tc_diff = None
                    for role_key, tname in target_by_role.items():
                        if role_key[0] == "differential":
                            target_tc_diff = tname
                            break
                    # Fallback: target's root device if no differential found
                    if target_tc_diff is None:
                        for role_key, tname in target_by_role.items():
                            if role_key[1] == "gearbox":
                                target_tc_diff = tname
                                break
                    if target_tc_diff and dev_name != target_tc_diff:
                        renames[dev_name] = target_tc_diff
                        provenance.append({
                            "donor_name": dev_name,
                            "target_name": target_tc_diff,
                            "source_part": part_name,
                            "target_part": tc_part_name,
                            "reason": ("FWD primary output -> target TC differential "
                                       "(segmented FWD adaptation)"),
                        })
        
        # --- Detect unmatched target roles (devices the target expects but donor lacks) ---
        # Track which target device names were consumed by the donor scan
        matched_target_names = set(renames.values())
        
        # Also track which device TYPES the donor has (for type-only fallback matching)
        donor_device_types = set()
        for part_name, part_data in adapted_data.items():
            if not isinstance(part_data, dict):
                continue
            powertrain = part_data.get("powertrain", [])
            if not isinstance(powertrain, list):
                continue
            for entry in powertrain:
                if not isinstance(entry, list) or len(entry) < 4:
                    continue
                dev_name = entry[1]
                dev_type = entry[0]
                if dev_name in ("name", "type") or dev_type in ("name", "type"):
                    continue
                donor_device_types.add(dev_type)
                # If this donor device name IS a target device name, it's already matched
                for role_key, tname in target_by_role.items():
                    if tname == dev_name:
                        matched_target_names.add(tname)
        
        # For MAKE_AWD and similar cross-topology strategies, the donor may have
        # devices of the same TYPE but at different chain positions (different inputName).
        # Example: AWD donor has differential(transferCase, inputName=gearbox), but
        # 4WD target has differential(transfercase, inputName=rangebox). The strict
        # structural match fails, but the donor DOES have a differential — the rename
        # should still happen via type-only fallback.
        #
        # Apply type-only fallback: if a target device hasn't been matched yet and
        # the donor has exactly ONE device of that type that also hasn't been renamed,
        # infer the rename.
        if donor_type in ("AWD", "4WD"):  # Only for cross-topology strategies
            for dev in target_devices:
                if dev["name"] in matched_target_names:
                    continue
                dev_type = dev["type"]
                # Find unrenamed donor devices of this type
                donor_candidates = []
                for pn, pd in adapted_data.items():
                    if not isinstance(pd, dict):
                        continue
                    for entry in pd.get("powertrain", []):
                        if not isinstance(entry, list) or len(entry) < 4:
                            continue
                        if entry[0] == dev_type and entry[1] not in ("name", "type"):
                            if entry[1] not in renames:
                                donor_candidates.append((pn, entry[1]))
                
                if len(donor_candidates) == 1:
                    d_part, d_name = donor_candidates[0]
                    if d_name != dev["name"]:
                        renames[d_name] = dev["name"]
                        matched_target_names.add(dev["name"])
                        provenance.append({
                            "donor_name": d_name,
                            "target_name": dev["name"],
                            "source_part": d_part,
                            "target_part": tc_part_name,
                            "reason": (f"type-only fallback: donor {dev_type}('{d_name}') "
                                       f"-> target {dev_type}('{dev['name']}') "
                                       f"[cross-topology, same device type]"),
                        })
                    else:
                        matched_target_names.add(dev["name"])
        
        # Cross-type inputName fallback for DIRECT_AWD strategy.
        # Camso and BeamNG may implement AWD center coupling with different
        # device types (e.g. Camso differential(lsd) vs BeamNG splitShaft).
        # The Camso device type is preserved (design principle), but the device
        # NAME must match the target's convention so downstream driveshaft
        # devices (which reference inputName: "transfercase") can connect.
        #
        # Match by inputName: if target and donor each have exactly one
        # unmatched device sharing the same inputName, map the donor's name
        # to the target's name regardless of device type.
        if donor_type == "AWD":
            unmatched_target = [d for d in target_devices
                                if d["name"] not in matched_target_names]
            if unmatched_target:
                # Build donor device inventory (unrenamed, with inputName)
                donor_devices_by_input = {}  # inputName -> [(part, name, type)]
                for pn, pd in adapted_data.items():
                    if not isinstance(pd, dict):
                        continue
                    for entry in pd.get("powertrain", []):
                        if not isinstance(entry, list) or len(entry) < 4:
                            continue
                        if entry[1] in ("name", "type") or entry[0] in ("name", "type"):
                            continue
                        if entry[1] not in renames:
                            inp = entry[2]
                            donor_devices_by_input.setdefault(inp, []).append(
                                (pn, entry[1], entry[0]))
                
                for dev in unmatched_target:
                    if dev["name"] in matched_target_names:
                        continue
                    target_input = dev.get("inputName", "")
                    # Resolve through existing renames (e.g. if gearbox was renamed)
                    resolved_input = target_input
                    for old, new in renames.items():
                        if target_input == new:
                            # target references the post-rename name; look up
                            # donor devices by the original inputName too
                            resolved_input = old
                            break
                    
                    candidates = donor_devices_by_input.get(target_input, [])
                    if not candidates:
                        candidates = donor_devices_by_input.get(resolved_input, [])
                    
                    if len(candidates) == 1:
                        d_part, d_name, d_type = candidates[0]
                        if d_name != dev["name"] and d_name not in renames:
                            renames[d_name] = dev["name"]
                            matched_target_names.add(dev["name"])
                            provenance.append({
                                "donor_name": d_name,
                                "target_name": dev["name"],
                                "source_part": d_part,
                                "target_part": tc_part_name,
                                "reason": (f"cross-type inputName fallback: "
                                           f"donor {d_type}('{d_name}') -> "
                                           f"target {dev['type']}('{dev['name']}') "
                                           f"[shared inputName='{target_input}', "
                                           f"Camso device type preserved]"),
                            })
                        elif d_name == dev["name"]:
                            matched_target_names.add(dev["name"])
        
        # Build list of truly missing devices: target expects them but donor has
        # NO device of that type (not just a different chain position)
        missing_devices = []
        for dev in target_devices:
            if dev["name"] not in matched_target_names:
                # Only consider truly missing if donor lacks this device type entirely
                if dev["type"] not in donor_device_types:
                    missing_devices.append(dev)
                else:
                    logger.info(f"  [Phase5] Target device '{dev['name']}' ({dev['type']}) "
                                f"has donor equivalent — skipping injection")
        
        if renames:
            logger.info(f"  [Phase5] Derived {len(renames)} device name mapping(s):")
            for p in provenance:
                logger.info(f"    '{p['donor_name']}' -> '{p['target_name']}' "
                            f"({p['reason']})")
        else:
            logger.info(f"  [Phase5] No device name remapping needed "
                        f"(donor names already match target)")
        
        if missing_devices:
            logger.info(f"  [Phase5] Detected {len(missing_devices)} unmatched target device(s):")
            for md in missing_devices:
                logger.info(f"    {md['type']}('{md['name']}') ← {md.get('inputName', '?')} "
                            f"[not present in donor]")
        
        return {"renames": renames, "provenance": provenance, "missing_devices": missing_devices}

    def _apply_tc_strategy_adaptations(self,
                                       adapted_data: Dict[str, Any],
                                       swap_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply Phase 5 strategy-specific slot pruning and device name adaptation
        to all parts in the adapted transfercase data.
        
        Device name adaptation uses the "analyze → populate mapping → consume mapping"
        pattern: the rename targets are DERIVED from the target vehicle's actual TC
        powertrain devices (via swap_decision["selected_tc"]), not hardcoded.
        
        Called after the existing part iteration in generate_adapted_transfercase().
        
        Args:
            adapted_data: Dict of {part_name: part_data} for all parts in the TC file
            swap_decision: Phase 3 swap decision dict with 'strategy', 'selected_tc', etc.
        
        Returns:
            Dict with pruning/normalization summary for logging and traceability
        """
        strategy = swap_decision.get("strategy", "")
        donor_type = swap_decision.get("donor_drive_type", "UNKNOWN")
        
        summary = {
            "strategy": strategy,
            "slots_pruned": [],
            "device_renames": 0,
            "device_name_mapping": {},
            "device_name_provenance": [],
            "parts_modified": [],
        }
        
        if strategy == "REFUSE":
            logger.warning(f"  [Phase5] Strategy is REFUSE — skipping TC adaptation")
            return summary
        
        if strategy == "SYNTH_TC":
            logger.warning(f"  [Phase5] SYNTH_TC strategy — deferred (not yet implemented)")
            return summary
        
        # --- Determine which slots to prune based on strategy ---
        # RWD donors (DIRECT RWD, MAKE_RWD): prune rear only (no front slot exists)
        # FWD donors (DIRECT FWD, MAKE_FWD): no slots to prune (all commented out)
        # AWD donors (DIRECT_AWD, MAKE_AWD): prune both front + rear (on center diff)
        # 4WD donors (DIRECT 4WD): prune rear only (front is powertrain device, not slot)
        
        slots_to_prune = []
        if donor_type in ("RWD", "4WD"):
            slots_to_prune = ["Camso_driveshaft_rear"]
        elif donor_type == "AWD":
            slots_to_prune = ["Camso_driveshaft_front", "Camso_driveshaft_rear"]
        elif donor_type == "FWD":
            slots_to_prune = []  # FWD has no active driveshaft child slots
        
        # --- Derive device name mapping from analysis data ---
        mapping_result = self._derive_device_name_mapping(adapted_data, swap_decision)
        device_renames = mapping_result["renames"]
        summary["device_name_mapping"] = device_renames
        summary["device_name_provenance"] = mapping_result["provenance"]
        
        # --- Determine if missing devices should be injected ---
        # AWD donors (DIRECT_AWD, MAKE_AWD) may lack target powertrain devices
        # that BeamNG expects (e.g., front output shaft). The target TC defines
        # these devices in its powertrain array but the Camso AWD center diff
        # routes front/rear torque via child slots instead. After pruning those
        # child slots, we must inject the missing powertrain entry so the
        # BeamNG frame's front driveshaft chain receives torque.
        #
        # This does NOT apply to 4WD donors (they already have frontDriveShaft
        # as a powertrain device) or RWD/FWD donors (no front output expected).
        missing_devices = mapping_result.get("missing_devices", [])
        inject_missing = (donor_type == "AWD" and len(missing_devices) > 0)
        summary["devices_injected"] = []
        
        # --- Apply to all parts ---
        for part_name, part_data in adapted_data.items():
            if not isinstance(part_data, dict):
                continue
            
            part_modified = False
            
            # Prune driveshaft slots
            if slots_to_prune:
                pruned = self._prune_driveshaft_slots(part_data, slots_to_prune)
                if pruned:
                    summary["slots_pruned"].extend(pruned)
                    part_modified = True
                    logger.info(f"  [Phase5] Pruned {len(pruned)} driveshaft slot(s) from '{part_name}': {pruned}")
            
            # Apply derived device name adaptation
            if device_renames:
                rename_count = self._normalize_powertrain_device_names(part_data, device_renames)
                if rename_count > 0:
                    summary["device_renames"] += rename_count
                    part_modified = True
                    logger.info(f"  [Phase5] Adapted {rename_count} device name(s) in '{part_name}'")
            
            # Inject missing target powertrain devices (AWD donors only)
            # The injection target is the part that had device renames applied
            # (i.e., the center diff part that owns the powertrain array)
            if inject_missing and part_modified and "powertrain" in part_data:
                powertrain = part_data["powertrain"]
                if isinstance(powertrain, list):
                    # Collect device names currently defined in this part's
                    # powertrain (post-rename). Used to verify connectivity:
                    # only inject a device whose inputName references a device
                    # that actually exists in this part.
                    defined_device_names = set()
                    for entry in powertrain:
                        if isinstance(entry, list) and len(entry) >= 4:
                            if entry[1] not in ("name", "type"):
                                defined_device_names.add(entry[1])
                    
                    for md in missing_devices:
                        # Connectivity check: only inject if the device's input
                        # source is defined in THIS part. This prevents injecting
                        # devices that belong to a different chain position (e.g.,
                        # rangebox feeds from gearbox — not defined here).
                        if md.get("inputName") not in defined_device_names:
                            logger.info(f"  [Phase5] Skipping injection of '{md['name']}' "
                                        f"({md['type']}): inputName '{md.get('inputName')}' "
                                        f"not defined in '{part_name}' powertrain")
                            continue
                        
                        # Build powertrain entry from target analysis data
                        # inputName references the POST-rename device name, which
                        # should already match since the target device references
                        # target naming (e.g., inputName="transfercase")
                        new_entry = [
                            md["type"],
                            md["name"],
                            md["inputName"],
                            md["inputIndex"],
                        ]
                        props = md.get("properties", {})
                        if props:
                            new_entry.append(props)
                        
                        powertrain.append(new_entry)
                        summary["devices_injected"].append(md["name"])
                        summary["device_name_provenance"].append({
                            "donor_name": None,
                            "target_name": md["name"],
                            "source_part": part_name,
                            "target_part": (swap_decision.get("selected_tc") or {}).get("part_name", "?"),
                            "reason": (f"injected from target TC: {md['type']}('{md['name']}') "
                                       f"<- {md['inputName']} [AWD donor lacks powertrain-level "
                                       f"front output; target defines it as device]"),
                        })
                        logger.info(f"  [Phase5] Injected missing device '{md['name']}' "
                                    f"({md['type']}) into '{part_name}' powertrain")
                    inject_missing = False  # Only inject once (into the first matching part)
            
            if part_modified:
                summary["parts_modified"].append(part_name)
        
        # --- Log summary ---
        logger.info(f"  [Phase5] Strategy '{strategy}' applied:")
        logger.info(f"    Slots pruned: {summary['slots_pruned'] if summary['slots_pruned'] else '(none)'}")
        logger.info(f"    Device name renames: {summary['device_renames']}")
        if device_renames:
            for old, new in device_renames.items():
                logger.info(f"      '{old}' -> '{new}'")
        if summary["devices_injected"]:
            logger.info(f"    Devices injected: {summary['devices_injected']}")
        logger.info(f"    Parts modified: {len(summary['parts_modified'])}")
        
        return summary

    def generate_adapted_transfercase(self,
                                      donor_file: Path,
                                      target_vehicle: VehicleInfo,
                                      swap_decision: Optional[Dict[str, Any]] = None,
                                      injection_targets: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        """
        Adapt transfer case file for target vehicle.
        
        Phase 5 integration: When swap_decision is provided, applies strategy-specific
        slot pruning (removing Camso driveshaft child slots) and device name normalization
        (transferCase → transfercase) to ensure compatibility with the target vehicle's
        native powertrain chain.
        
        Decision Logic (BeamNG convention):
        - RWD/FWD donors: Skip node injection entirely (transfer case has no physical nodes)
        - AWD/4WD donors: Inject target vehicle's transfer case nodes (tra2, tra3)
        
        Args:
            donor_file: Path to donor transfer case .jbeam file
            target_vehicle: Target vehicle information
            swap_decision: Phase 3 swap decision dict (strategy, donor_drive_type, etc.)
                If None, falls back to legacy behavior (no pruning/normalization).
            injection_targets: Phase 4 axle slot extraction results (informational,
                used for logging/validation only — pruning doesn't inject these slots)
            
        Returns:
            Path to generated temp file, or None if generation fails
        """
        logger.info(f"Adapting transfer case: {donor_file.name} -> {target_vehicle.name}")
        
        # Check donor drive type first
        donor_drive_type = self._last_donor_drive_type
        if donor_drive_type is None:
            # Attempt to determine if not already cached
            donor_drive_type = self._determine_donor_drive_type(donor_file.parent.parent)
        
        # Decision: Skip node injection for RWD/FWD donors
        should_inject_nodes = donor_drive_type in (DriveType.AWD, DriveType.FOUR_WD)
        
        logger.info(f"  Donor drive type: {donor_drive_type.value.upper()}")
        logger.info(f"  Transfer case node injection: {'YES' if should_inject_nodes else 'SKIP (RWD/FWD donor)'}")
        
        # Parse donor file
        donor_data = JBeamParser.parse_jbeam(donor_file)
        if not donor_data:
            logger.error(f"Failed to parse transfer case file: {donor_file}")
            return None
        
        # Extract target vehicle's transfer case structure (only for AWD/4WD donors)
        tc_structure = None
        if should_inject_nodes and TMS_AVAILABLE:
            target_trans_file = self._find_target_transmission_file(target_vehicle)
            if target_trans_file:
                target_trans_jbeam = JBeamParser.parse_jbeam(target_trans_file)
                if target_trans_jbeam:
                    target_extractor = TargetVehicleExtractor(target_trans_jbeam)
                    # Filter for transfer_case parts only (tra2, tra3 nodes)
                    raw_tc_structure = target_extractor.extract_transmission_structure(
                        slot_type_filter="transfer_case"
                    )
                    if raw_tc_structure and raw_tc_structure.nodes:
                        # Deduplicate nodes by name (keep first occurrence)
                        unique_nodes = {}
                        for node in raw_tc_structure.nodes:
                            if node.name not in unique_nodes:
                                unique_nodes[node.name] = node
                        
                        # Create new structure with deduplicated nodes
                        tc_structure = TransmissionStructure(
                            nodes=list(unique_nodes.values()),
                            beam_properties=raw_tc_structure.beam_properties,
                            connected_engine_nodes=raw_tc_structure.connected_engine_nodes
                        )
                        
                        logger.info(f"  [TMS] Target transfer case structure: {len(tc_structure.nodes)} unique nodes")
                        for node in tc_structure.nodes:
                            logger.info(f"    - {node.name}: pos=({node.position.x:.4f}, {node.position.y:.4f}, {node.position.z:.4f})")
                    else:
                        logger.info("  [TMS] No transfer case nodes (tra2/tra3) found in target - RWD/FWD-only target vehicle")
                else:
                    logger.warning(f"  Failed to parse target transmission file: {target_trans_file}")
            else:
                logger.warning(f"  Could not find target transmission file for {target_vehicle.name}")
        
        adapted_data = {}
        
        # === discard_aux_transfercase: filter rangebox TC variants ===
        discard_aux_tc = self._swap_config.get("discard_aux_transfercase", True)
        discarded_rangebox_parts = []
        primary_tc_part = None
        
        if discard_aux_tc:
            # Identify the primary TC part from the donor transmission's slot declaration.
            # This part is immune from pruning — only auxiliary rangebox siblings are pruned.
            primary_tc_part = self._identify_default_transfercase(donor_file)
            if primary_tc_part:
                logger.info(f"  [discard_aux_transfercase] Primary TC (immune): {primary_tc_part}")
            else:
                logger.warning("  [discard_aux_transfercase] Could not identify primary TC — "
                               "disabling rangebox pruning to avoid false positives")
                discard_aux_tc = False
        
        # Rangebox pattern: FWD or RWD variants with '_rangebox_' in name
        _rangebox_pattern = re.compile(r'_(?:FWD|RWD)_rangebox_', re.IGNORECASE)
        
        # Process each part
        for part_name, part_data in donor_data.items():
            if not isinstance(part_data, dict):
                continue
            
            # Filter rangebox variants when enabled
            if discard_aux_tc and _rangebox_pattern.search(part_name):
                if part_name == primary_tc_part:
                    logger.info(f"  [discard_aux_transfercase] Keeping primary TC despite "
                                f"rangebox match: {part_name}")
                else:
                    discarded_rangebox_parts.append(part_name)
                    logger.info(f"  [discard_aux_transfercase] Pruning rangebox variant: {part_name}")
                    continue
            
            donor_slot_type = part_data.get('slotType', '')
            
            # Check if this is a transfer case part
            if donor_slot_type and 'transfer' in donor_slot_type.lower():
                # Create vehicle-specific name
                adapted_part_name = f"{target_vehicle.name}_{part_name}"
                adapted_part_data = self._deep_copy_part_data(part_data)
                
                # Adapt slotType to target vehicle transfer case slot
                # Use slot graph mapping if available, fall back to family prefix derivation
                if self._slot_graph and donor_slot_type in self._slot_graph.slot_type_map:
                    target_tc_slot = self._slot_graph.slot_type_map[donor_slot_type]
                else:
                    prefix = target_vehicle.name
                    if target_vehicle.engine_slot_type:
                        derived = target_vehicle.engine_slot_type.replace('_engine', '')
                        if derived != target_vehicle.name:
                            prefix = derived
                    target_tc_slot = f"{prefix}_transfer_case"
                adapted_part_data['slotType'] = target_tc_slot
                
                logger.info(f"  Adapted transfer case slotType: {donor_slot_type} -> {target_tc_slot}")
                logger.info(f"  Part name: {part_name} -> {adapted_part_name}")
                
                # Update information section with drive-type-specific naming (Phase 6.4)
                if 'information' in adapted_part_data:
                    info = adapted_part_data['information']
                    if 'name' in info:
                        # Derive descriptive name from swap decision if available
                        if swap_decision and not swap_decision.get('refused'):
                            d_type = swap_decision.get('donor_drive_type', '')
                            d_sub = swap_decision.get('donor_awd_subvariant', '')
                            strategy = swap_decision.get('strategy', '')
                            
                            # Build drive type label
                            if d_sub:
                                type_label = f"{d_sub.title()} {d_type}"  # e.g., "Helical AWD"
                            else:
                                type_label = d_type  # e.g., "RWD"
                            
                            # Add strategy suffix for cross-type swaps
                            if strategy.startswith('MAKE_'):
                                swap_suffix = f" ({strategy.replace('MAKE_', '')} Swap)"
                            else:
                                swap_suffix = ""
                            
                            info['name'] = f"Camso {type_label} Transfer Case{swap_suffix}"
                            logger.info(f"  Info name: {info['name']}")
                        else:
                            info['name'] = f"{info['name']} ({target_vehicle.name.title()} Swap)"
                
                # === Inject transfer case nodes and beams (AWD/4WD donors only) ===
                if tc_structure and tc_structure.nodes:
                    self._inject_transfercase_geometry(
                        adapted_part_data, 
                        tc_structure
                    )
                elif should_inject_nodes:
                    logger.info("  [TMS] Skipping node injection - target has no transfer case nodes")
                
                # === SLOT GRAPH INTEGRATION (Phase 6.3) ===
                # Transform slots using slot graph mappings
                # This must happen AFTER geometry injection but BEFORE Phase 5 pruning
                if 'slots' in adapted_part_data:
                    original_slot_count = len(adapted_part_data['slots'])
                    adapted_part_data['slots'] = self._transform_slots_with_graph(
                        adapted_part_data['slots'],
                        adapted_part_name,
                        target_vehicle.name
                    )
                    logger.info(f"  Slots: {original_slot_count} original -> {len(adapted_part_data['slots'])} transformed")
                
                adapted_data[adapted_part_name] = adapted_part_data
            else:
                # Keep child parts as-is (e.g., Camso_differential_center for AWD)
                adapted_data[part_name] = self._deep_copy_part_data(part_data)
        
        # Post-process: fix stale TC defaults in adapted transmission when rangebox discarded
        if discarded_rangebox_parts:
            logger.info(f"  [discard_aux_transfercase] Discarded {len(discarded_rangebox_parts)} "
                        f"rangebox variant(s): {discarded_rangebox_parts}")
            # The slot graph may have set the adapted transmission's TC default to the rangebox
            # part (last-seen overwrites default_part). Fix by replacing with the primary TC.
            kept_tc_parts = [name for name in adapted_data.keys()
                             if isinstance(adapted_data.get(name), dict)
                             and 'transfer' in adapted_data[name].get('slotType', '').lower()]
            if kept_tc_parts:
                primary_adapted_name = kept_tc_parts[0]
                discarded_adapted_names = [f"{target_vehicle.name}_{p}" for p in discarded_rangebox_parts]
                self._fix_transmission_tc_default(
                    target_vehicle.name, primary_adapted_name, discarded_adapted_names)
        
        # === Phase 5: Strategy-specific slot pruning and device name adaptation ===
        phase5_summary = None
        if swap_decision and swap_decision.get("strategy") not in (None, "REFUSE"):
            phase5_summary = self._apply_tc_strategy_adaptations(adapted_data, swap_decision)
            
            # Log injection targets context (informational — not injecting, just validating)
            if injection_targets:
                rear_count = len(injection_targets.get("rear_slots", []))
                front_count = len(injection_targets.get("front_slots", []))
                logger.info(f"  [Phase5] Target vehicle chain context: {rear_count} rear, {front_count} front driveshaft slots")
                logger.info(f"    TC declares {injection_targets.get('direct_child_count', '?')} direct child slots")
        
        # Store Phase 5 summary and swap decision for manifest generation (Phase 6.5)
        self._last_tc_adaptation_summary = phase5_summary
        self._last_swap_decision = swap_decision
        
        # Post-process: powertrain property tweaks
        adapted_data = self._apply_powertrain_tweaks(adapted_data, "transfercase", target_vehicle.name)
        
        # Write to temp file
        temp_file = self.temp_path / f"{target_vehicle.name}_{donor_file.stem}_adapted.jbeam"
        try:
            self._write_jbeam_file(temp_file, adapted_data)
            logger.info(f"  Generated transfer case file: {temp_file}")
            return temp_file
        except Exception as e:
            logger.error(f"Failed to write transfer case file: {e}")
            return None
    
    def _identify_default_transfercase(self, donor_tc_path: Path) -> Optional[str]:
        """
        Identify the primary (default) transfer case part from the donor transmission.
        
        The donor transmission's slot declaration for slotType 'Camso_TransferCase'
        names the default TC part. This part is the primary variant and should be
        immune from aux-TC pruning.
        
        Args:
            donor_tc_path: Path to the donor transfer case .jbeam file.
                Used to locate the sibling transmission file.
                
        Returns:
            Part name of the default TC, or None if not determinable.
        """
        # Find transmission files in the same vehicle folder
        vehicle_folder = donor_tc_path.parent
        trans_files = list(vehicle_folder.glob("*transmission*.jbeam")) + \
                      list(vehicle_folder.glob("*Transmission*.jbeam"))
        
        for tf in trans_files:
            try:
                tf_data = JBeamParser.parse_jbeam(tf)
                if not tf_data:
                    continue
                for part_name, part_data in tf_data.items():
                    if not isinstance(part_data, dict):
                        continue
                    for slot in part_data.get('slots', []):
                        if not isinstance(slot, list) or len(slot) < 2:
                            continue
                        slot_type = str(slot[0]) if slot[0] else ""
                        if 'transfercase' in slot_type.lower() or 'transfer_case' in slot_type.lower():
                            default_part = str(slot[1]) if len(slot) > 1 and slot[1] else ""
                            if default_part:
                                return default_part
            except Exception as e:
                logger.debug(f"  [discard_aux_transfercase] Parse error in {tf.name}: {e}")
                continue
        
        return None
    
    def _fix_transmission_tc_default(self, target_name: str,
                                      primary_tc_name: str,
                                      discarded_names: List[str]) -> None:
        """
        Post-fix the adapted transmission file's TC slot default when rangebox
        parts have been discarded.
        
        The slot graph stores one default_part per slotType. When multiple TC parts
        share the same slotType (e.g., RWD + rangebox), the last-seen part becomes
        the graph default. If that part was discarded, the adapted transmission would
        reference a non-existent part.
        
        Args:
            target_name: Target vehicle name (e.g., 'pickup')
            primary_tc_name: Adapted name of the kept primary TC part
            discarded_names: List of adapted names of discarded rangebox TC parts
        """
        for trans_file in self.temp_path.glob(f"{target_name}_*transmission*_adapted.jbeam"):
            try:
                content = trans_file.read_text(encoding='utf-8')
                modified = False
                for discarded in discarded_names:
                    if discarded in content:
                        content = content.replace(discarded, primary_tc_name)
                        modified = True
                        logger.info(f"  [discard_aux_transfercase] Fixed TC default in "
                                    f"{trans_file.name}: {discarded} -> {primary_tc_name}")
                if modified:
                    trans_file.write_text(content, encoding='utf-8')
            except Exception as e:
                logger.warning(f"  [discard_aux_transfercase] Could not fix "
                               f"TC default in {trans_file.name}: {e}")
    
    def _inject_transfercase_geometry(self,
                                       part_data: Dict[str, Any],
                                       tc_structure: TransmissionStructure) -> None:
        """
        Inject transfer case nodes and beams into adapted part.
        
        Uses BeamNG target vehicle node positions and beam properties.
        Transfer case nodes are typically lightweight (18kg each for pickup).
        
        Args:
            part_data: Part data dict to modify
            tc_structure: Target vehicle transfer case structure
        """
        if not tc_structure.nodes:
            return
        
        node_count = len(tc_structure.nodes)
        
        # Use typical transfer case node weight from BeamNG (18kg per node for pickup)
        weight_per_node = 18.0
        if tc_structure.nodes[0].weight:
            weight_per_node = tc_structure.nodes[0].weight
        
        logger.info(f"  [TMS] Injecting transfer case: {node_count} nodes at {weight_per_node:.2f} kg each")
        
        # Build nodes section
        nodes_section = [
            ["id", "posX", "posY", "posZ"],
            {"selfCollision": False},
            {"collision": True},
            {"frictionCoef": 0.5},
            {"nodeMaterial": "|NM_METAL"},
            {"nodeWeight": weight_per_node},
            {"group": tc_structure.nodes[0].group if tc_structure.nodes[0].group else "pickup_transmission"}
        ]
        
        # Add transfer case nodes (tra2, tra3)
        for tc_node in tc_structure.nodes:
            nodes_section.append([
                tc_node.name, 
                tc_node.position.x, 
                tc_node.position.y, 
                tc_node.position.z
            ])
        
        nodes_section.append({"group": ""})
        
        part_data['nodes'] = nodes_section
        
        # Build beams section
        if tc_structure.beam_properties and tc_structure.connected_engine_nodes:
            beams_section = [["id1:", "id2:"]]
            
            # Add beam properties
            props = tc_structure.beam_properties
            beams_section.append({
                "beamPrecompression": 1,
                "beamType": "|NORMAL",
                "beamLongBound": 1.0,
                "beamShortBound": 1.0
            })
            beams_section.append({
                "beamSpring": props.beam_spring,
                "beamDamp": props.beam_damp,
                "beamDeform": props.beam_deform,
                "beamStrength": props.beam_strength
            })
            
            # Generate transfer case beams (tc nodes to engine nodes and tra1)
            # BeamNG pattern: tra2/tra3 connect to tra1 AND engine nodes (e1l, e1r, e3l, e3r)
            tc_beams = generate_transmission_beams(
                tc_structure.nodes,
                tc_structure.connected_engine_nodes
            )
            beams_section.extend(tc_beams)
            
            # Reset beam properties
            beams_section.append({
                "beamPrecompression": 1,
                "beamType": "|NORMAL",
                "beamLongBound": 1.0,
                "beamShortBound": 1.0
            })
            
            part_data['beams'] = beams_section
            logger.info(f"  [TMS] Injected {len(tc_beams)} transfer case beams")
    
    def generate_mod_manifest(self, 
                              donor_engine_path: Path,
                              target_vehicle: VehicleInfo) -> Dict[str, Any]:
        """
        Generate a manifest of all files required to port the mod in-game.
        
        When slot graph is available (Phase 2+), generates a slot-centric manifest
        with complete dependency tracking and minimum necessary files.
        
        Falls back to pattern-based file scanning for legacy compatibility.
        
        Args:
            donor_engine_path: Path to donor engine .jbeam file
            target_vehicle: Target vehicle information
            
        Returns:
            Dictionary with categorized file lists and copy instructions
        """
        # Get donor mod root (parent of vehicles folder)
        donor_dir = donor_engine_path.parent
        mod_root = donor_dir
        while mod_root.parent.name != "unpacked" and mod_root.parent != mod_root:
            mod_root = mod_root.parent
        
        # === SLOT GRAPH MANIFEST (Primary path when available) ===
        if SLOT_GRAPH_AVAILABLE and self._slot_graph:
            logger.info("  [SlotGraph] Generating slot-aware manifest...")
            
            # Create generator with parser for asset extraction and output path
            generator = SlotAwareManifestGenerator(
                graph=self._slot_graph,
                jbeam_parser=JBeamParser,
                output_base_path=self.temp_path  # For computing generated file paths
            )
            slot_manifest = generator.generate()
            
            # Resolve physical asset files using post-transform mesh/sound references
            # This ensures only assets needed for generated output are included
            asset_files = generator.resolve_physical_assets(mod_root, slot_manifest["copy_plan"])
            
            # Build final manifest combining slot graph + physical files
            manifest = {
                "version": "3.0",
                "donor_engine": str(donor_engine_path),
                "target_vehicle": target_vehicle.name,
                "mod_root": str(mod_root),
                
                # Extra assets config (from swap_parameters.json)
                # Stored in manifest so packager is self-contained
                "extra_assets": self._swap_config.get("extra_assets", {}),
                
                # Slot-centric data from graph
                "required_slots": slot_manifest["required_slots"],
                "copy_plan": slot_manifest["copy_plan"],
                "mappings": slot_manifest["mappings"],
                
                # Physical asset files discovered in mod folder
                "asset_files": asset_files,
                
                # Generated files tracking
                "generated_files": [str(f) for f in self._slot_graph.generated_files],
                
                # Copy instructions
                "copy_instructions": self._generate_copy_instructions(
                    mod_root, target_vehicle, slot_manifest, asset_files
                ),
                
                # Statistics
                "statistics": {
                    **slot_manifest["statistics"],
                    "physical_mesh_files": len(asset_files.get("meshes", [])),
                    "physical_texture_files": len(asset_files.get("textures", [])),
                },
                
                # Validation
                "validation": slot_manifest["validation"],
            }
            
            # === Phase 6.5: Drivetrain section with provenance ===
            if self._last_swap_decision:
                sd = self._last_swap_decision
                drivetrain_section = {
                    "donor_drive_type": sd.get("donor_drive_type", "UNKNOWN"),
                    "swap_strategy": sd.get("strategy", "UNKNOWN"),
                    "adaptation_cost": sd.get("cost", -1),
                    "selected_beamng_tc": (sd.get("selected_tc") or {}).get("part_name"),
                }
                # Add AWD subvariant if present
                if sd.get("donor_awd_subvariant"):
                    drivetrain_section["donor_awd_subvariant"] = sd["donor_awd_subvariant"]
                
                # Add Phase 5 adaptation summary with provenance
                if self._last_tc_adaptation_summary:
                    p5 = self._last_tc_adaptation_summary
                    drivetrain_section["slots_pruned"] = p5.get("slots_pruned", [])
                    drivetrain_section["device_name_mapping"] = p5.get("device_name_mapping", {})
                    drivetrain_section["device_name_provenance"] = p5.get("device_name_provenance", [])
                    drivetrain_section["devices_injected"] = p5.get("devices_injected", [])
                    drivetrain_section["parts_modified"] = p5.get("parts_modified", [])
                    drivetrain_section["device_renames_count"] = p5.get("device_renames", 0)
                
                manifest["drivetrain"] = drivetrain_section
                logger.info(f"  [Phase6] Drivetrain section added to manifest: "
                           f"strategy={drivetrain_section['swap_strategy']}, "
                           f"cost={drivetrain_section['adaptation_cost']}")
            
            logger.info(f"  [SlotGraph] Manifest complete: "
                       f"{slot_manifest['statistics']['total_slots']} slots, "
                       f"{slot_manifest['statistics']['original_jbeam_files']} original files, "
                       f"{slot_manifest['statistics']['generated_jbeam_files']} generated files")
            
            return manifest
        
        # === LEGACY FILE-SCAN MANIFEST (Fallback) ===
        logger.info("  [Legacy] Generating pattern-based manifest...")
        return self._generate_legacy_manifest(donor_engine_path, target_vehicle, mod_root)
    
    def _discover_asset_files(self, mod_root: Path) -> Dict[str, List[Dict]]:
        """
        Discover physical asset files (meshes, textures, sounds) in mod folder.
        
        Args:
            mod_root: Root path of the mod folder
            
        Returns:
            Dict with categorized asset file lists
        """
        assets = {
            "meshes": [],
            "textures": [],
            "sounds": [],
        }
        
        # Mesh files
        for pattern in ["**/*.dae", "**/*.cdae"]:
            for f in mod_root.glob(pattern):
                rel_path = f.relative_to(mod_root)
                assets["meshes"].append({
                    "name": f.stem,
                    "path": str(rel_path),
                    "full_path": str(f),
                })
        
        # Texture files
        for pattern in ["**/*.dds", "**/*.png"]:
            for f in mod_root.glob(pattern):
                rel_path = f.relative_to(mod_root)
                assets["textures"].append({
                    "path": str(rel_path),
                    "full_path": str(f),
                })
        
        # Sound files
        for pattern in ["**/*.ogg", "**/*.wav"]:
            for f in mod_root.glob(pattern):
                rel_path = f.relative_to(mod_root)
                assets["sounds"].append({
                    "path": str(rel_path),
                    "full_path": str(f),
                })
        
        return assets
    
    def _generate_copy_instructions(self, 
                                    mod_root: Path, 
                                    target_vehicle: VehicleInfo,
                                    slot_manifest: Dict,
                                    resolved_assets: Dict = None) -> List[str]:
        """
        Generate human-readable copy instructions based on slot manifest.
        
        Args:
            mod_root: Root path of the mod folder
            target_vehicle: Target vehicle info
            slot_manifest: Generated slot manifest
            resolved_assets: Optional dict of resolved physical asset files
            
        Returns:
            List of instruction strings
        """
        copy_plan = slot_manifest.get("copy_plan", {})
        original_count = len(copy_plan.get("original_jbeam", []))
        generated_count = len(copy_plan.get("generated_jbeam", []))
        excluded_count = len(copy_plan.get("excluded_files", []))
        
        instructions = [
            f"=== Mod Packaging Instructions ===",
            f"",
            f"1. ORIGINAL FILES ({original_count} files):",
            f"   Copy from '{mod_root.name}' to your mod folder:",
        ]
        
        # List original files needed
        for f in copy_plan.get("original_jbeam", [])[:5]:  # Show first 5
            slots = ", ".join(f.get("provides_slots", [])[:2])
            instructions.append(f"   - {Path(f['path']).name} (provides: {slots})")
        if original_count > 5:
            instructions.append(f"   ... and {original_count - 5} more")
        
        instructions.extend([
            f"",
            f"2. GENERATED FILES ({generated_count} files):",
            f"   Already created in: mods/unpacked/engineswaps/vehicles/{target_vehicle.name}/",
        ])
        
        # List generated files - use output_filename if available, else fallback to source path
        for f in copy_plan.get("generated_jbeam", []):
            filename = f.get("output_filename") or Path(f['path']).name
            instructions.append(f"   - {filename}")
        
        if excluded_count > 0:
            instructions.extend([
                f"",
                f"3. EXCLUDED FILES ({excluded_count} files):",
                f"   These can be omitted (pruned slots):",
            ])
            for f in copy_plan.get("excluded_files", [])[:3]:
                instructions.append(f"   - {Path(f['path']).name} ({f.get('reason', 'pruned')})")
        
        # Section 4: Asset files - show specific resolved files if available
        if resolved_assets:
            mesh_count = len(resolved_assets.get("meshes", []))
            texture_count = len(resolved_assets.get("textures", []))
            
            instructions.extend([
                f"",
                f"4. ASSET FILES ({mesh_count} meshes, {texture_count} textures):",
                f"   Copy these specific files from '{mod_root.name}':",
            ])
            
            # List mesh files with what they provide
            for mesh in resolved_assets.get("meshes", [])[:5]:
                provides = mesh.get("provides_meshes", [])
                provides_str = f" (provides: {', '.join(provides[:2])})" if provides else ""
                instructions.append(f"   - {Path(mesh['path']).name}{provides_str}")
            if mesh_count > 5:
                instructions.append(f"   ... and {mesh_count - 5} more meshes")
            
            # Note about textures
            if texture_count > 0:
                instructions.append(f"   - Plus {texture_count} texture files matching mesh prefixes")
        else:
            instructions.extend([
                f"",
                f"4. ASSET FILES:",
                f"   Copy mesh (.dae) and texture (.dds) files from mod folder",
            ])
        
        instructions.extend([
            f"",
            f"5. The engine will appear in {target_vehicle.name}'s parts selector",
        ])
        
        return instructions
    
    def _generate_legacy_manifest(self, 
                                   donor_engine_path: Path,
                                   target_vehicle: VehicleInfo,
                                   mod_root: Path) -> Dict[str, Any]:
        """
        Generate legacy pattern-based manifest (fallback when slot graph unavailable).
        
        Args:
            donor_engine_path: Path to donor engine .jbeam file
            target_vehicle: Target vehicle information
            mod_root: Root path of the mod folder
            
        Returns:
            Legacy manifest dictionary
        """
        manifest = {
            "version": "1.0",
            "donor_engine": str(donor_engine_path),
            "target_vehicle": target_vehicle.name,
            "generated_files": [],
            "required_files": {
                "engine": [],
                "structure": [],
                "intake": [],
                "turbo": [],
                "supercharger": [],
                "management": [],
                "internals": [],
                "transmission": [],
                "transfercase": [],
                "sound": [],
                "mesh": [],
                "texture": [],
                "other": []
            },
            "copy_instructions": []
        }
        
        manifest["mod_root"] = str(mod_root)
        
        # Scan for all jbeam files
        jbeam_files = list(mod_root.glob("**/*.jbeam"))
        
        # Categorize files by pattern matching
        for jbeam_file in jbeam_files:
            rel_path = jbeam_file.relative_to(mod_root)
            file_info = {"path": str(rel_path), "full_path": str(jbeam_file)}
            
            stem_lower = jbeam_file.stem.lower()
            
            if "engine_structure" in stem_lower:
                manifest["required_files"]["structure"].append(file_info)
            elif "engine" in stem_lower and "management" not in stem_lower:
                manifest["required_files"]["engine"].append(file_info)
            elif "intake" in stem_lower:
                manifest["required_files"]["intake"].append(file_info)
            elif "turbo" in stem_lower:
                manifest["required_files"]["turbo"].append(file_info)
            elif "supercharger" in stem_lower:
                manifest["required_files"]["supercharger"].append(file_info)
            elif "management" in stem_lower:
                manifest["required_files"]["management"].append(file_info)
            elif "internals" in stem_lower:
                manifest["required_files"]["internals"].append(file_info)
            elif "transmission" in stem_lower:
                manifest["required_files"]["transmission"].append(file_info)
            elif "transfercase" in stem_lower:
                manifest["required_files"]["transfercase"].append(file_info)
            elif "sound" in stem_lower:
                manifest["required_files"]["sound"].append(file_info)
            else:
                manifest["required_files"]["other"].append(file_info)
        
        # Scan for mesh files
        mesh_files = list(mod_root.glob("**/*.dae")) + list(mod_root.glob("**/*.cdae"))
        for mesh_file in mesh_files:
            rel_path = mesh_file.relative_to(mod_root)
            manifest["required_files"]["mesh"].append({
                "path": str(rel_path),
                "full_path": str(mesh_file)
            })
        
        # Scan for texture files
        texture_files = list(mod_root.glob("**/*.dds")) + list(mod_root.glob("**/*.png"))
        for tex_file in texture_files:
            rel_path = tex_file.relative_to(mod_root)
            manifest["required_files"]["texture"].append({
                "path": str(rel_path),
                "full_path": str(tex_file)
            })
        
        # Generate copy instructions
        manifest["copy_instructions"] = [
            f"1. Copy entire '{mod_root.name}' folder to mods/unpacked/",
            f"2. Place adapted engine file in mods/unpacked/{mod_root.name}/vehicles/{target_vehicle.name}/",
            f"3. Place adapted transmission files in same folder",
            f"4. The engine will appear in {target_vehicle.name}'s parts selector",
        ]
        
        # Summary statistics
        manifest["summary"] = {
            "total_jbeam_files": len(jbeam_files),
            "total_mesh_files": len(mesh_files),
            "total_texture_files": len(texture_files),
            "categories_with_files": sum(1 for v in manifest["required_files"].values() if v)
        }
        
        return manifest
    
    def _apply_powertrain_tweaks(
        self,
        adapted_data: Dict[str, Any],
        component_type: str,
        target_vehicle_name: str
    ) -> Dict[str, Any]:
        """
        Apply powertrain property tweaks as a post-processing step.
        
        Delegates to the standalone powertrain_tweaks module. No-ops gracefully
        if the module is unavailable or no tweaks are configured.
        
        Args:
            adapted_data: Fully-adapted jbeam data dict (mutated in place).
            component_type: "engine", "transmission", or "transfercase".
            target_vehicle_name: For logging context.
            
        Returns:
            The (possibly mutated) adapted_data dict.
        """
        if not POWERTRAIN_TWEAKS_AVAILABLE:
            return adapted_data
        
        tweak_config = self._swap_config.get("powertrain_tweaks")
        if not tweak_config or not tweak_config.get("enabled", True):
            return adapted_data
        
        # Build context from already-extracted upstream data
        ctx = TweakContext(
            component_type=component_type,
            donor_drive_type=self._last_donor_drive_type,
            target_vehicle_name=target_vehicle_name,
            donor_torque_table=self._last_donor_torque_table,
            donor_idle_rpm=self._last_donor_idle_rpm,
        )
        
        results = apply_tweaks(adapted_data, tweak_config, ctx)
        
        if not results:
            return adapted_data
        
        # Log results
        applied = [r for r in results if r.applied]
        skipped = [r for r in results if not r.applied]
        
        if applied:
            summary = format_results_summary(results)
            for line in summary.split('\n'):
                logger.info(line)
                # Safe print: avoid UnicodeEncodeError on Windows cp1252 consoles
                try:
                    print(line)
                except UnicodeEncodeError:
                    print(line.encode('ascii', errors='replace').decode('ascii'))
        elif skipped:
            reasons = "; ".join(f"{r.tweak_name}: {r.reason}" for r in skipped)
            logger.info(f"  Powertrain tweaks ({component_type}): all skipped — {reasons}")
        
        return adapted_data
    
    # Delegate formatting to JBeamWriter for consistency
    def _write_jbeam_file(self, file_path: Path, jbeam_data: Dict[str, Any]) -> None:
        """Write JBeam file using consolidated JBeamWriter class."""
        JBeamWriter.write(file_path, jbeam_data)


def load_swap_parameters(config_path: Path = None) -> Dict[str, Any]:
    """
    Load swap parameters from JSON config file.
    
    Args:
        config_path: Path to swap_parameters.json (default: ../configs/swap_parameters.json)
        
    Returns:
        Dictionary with configuration parameters
    """
    if config_path is None:
        # Default to configs folder relative to script
        script_dir = Path(__file__).resolve().parent
        config_path = script_dir.parent / "configs" / "swap_parameters.json"
    else:
        config_path = Path(config_path).resolve()
    
    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"Loaded swap parameters from {config_path}")
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='BeamNG Engine Transplant Utility',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a donor engine file
  python engineswap.py analyze-engine path/to/engine.jbeam
  
  # Analyze a target vehicle
  python engineswap.py analyze-vehicle pickup
  
  # Generate adaptation plan
  python engineswap.py plan path/to/engine.jbeam pickup
  
  # Generate adapted JBeam file (to temp folder)
  python engineswap.py generate path/to/engine.jbeam pickup
  
  # Visualize slot graph for debugging
  python engineswap.py visualize path/to/engine.jbeam pickup
  python engineswap.py visualize path/to/engine.jbeam pickup --show-files --show-transforms

  # Do your first swap and output a fully packaged mod to default mods/unpacked/engineswaps/ folder 
  python engineswap.py generate path/to/engine.jbeam pickup --show-files --show-transforms --package
        """
    )
    
    parser.add_argument(
        'command',
        choices=['analyze-engine', 'analyze-vehicle', 'plan', 'generate', 'visualize'],
        help='Command to execute'
    )
    
    parser.add_argument(
        'input',
        help='Input file path (for analyze-engine/plan) or vehicle name (for analyze-vehicle)'
    )
    
    parser.add_argument(
        'target',
        nargs='?',
        help='Target vehicle name (required for plan/generate/visualize commands)'
    )
    
    parser.add_argument(
        '--base-path',
        default=None,
        help='Path to BeamNG base vehicles folder (overrides config file setting)'
    )
    
    parser.add_argument(
        '--output',
        default=None,
        help='Output directory for generated files (overrides config)'
    )
    
    parser.add_argument(
        '--config',
        default=None,
        help='Path to swap_parameters.json config file'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    # Visualize command options
    parser.add_argument(
        '--show-files',
        action='store_true',
        help='Show source file paths in visualization'
    )
    
    parser.add_argument(
        '--show-transforms',
        action='store_true',
        help='Show transformation history in visualization'
    )
    
    parser.add_argument(
        '--filter-role',
        choices=['source', 'target', 'preserve', 'internal'],
        help='Filter visualization to specific asset role'
    )
    
    parser.add_argument(
        '--markdown',
        action='store_true',
        help='Output visualization in markdown format'
    )
    
    # Packaging options
    parser.add_argument(
        '--package',
        action='store_true',
        help='Package assets after generation (copy required files to output folder)'
    )
    
    parser.add_argument(
        '--package-dry-run',
        action='store_true',
        help='Show what would be packaged without copying files'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load configuration
    config_path = Path(args.config) if args.config else None
    swap_config = load_swap_parameters(config_path)
    
    # Get mod name from config (default: engineswaps)
    mod_name = swap_config.get('mod_name', 'engineswaps')
    
    # Determine output path (CLI arg overrides config)
    if args.output:
        output_base = Path(args.output)
    elif 'base_output_path' in swap_config:
        # Build full path: {base_output_path}/mods/unpacked/{mod_name}/vehicles
        base = Path(swap_config['base_output_path'])
        output_base = base / "mods" / "unpacked" / mod_name / "vehicles"
    else:
        # Fallback default
        output_base = Path(f'../mods/unpacked/{mod_name}/vehicles')
    
    logger.info(f"Using output path: {output_base}")
    logger.info(f"Mod package name: {mod_name}")
    
    # Determine base vehicles path (CLI arg overrides config)
    if args.base_path:
        base_vehicles_path = Path(args.base_path)
    elif 'base_vehicles_path' in swap_config:
        base_vehicles_path = Path(swap_config['base_vehicles_path'])
    else:
        # Fallback default - will only work in dev environment
        base_vehicles_path = Path('SteamLibrary_content_vehicles')
        logger.warning(f"No base_vehicles_path in config - using fallback: {base_vehicles_path}")
    
    logger.info(f"Using base vehicles path: {base_vehicles_path}")
    
    # Determine workspace subfolder based on target vehicle (or "temp" for analysis)
    workspace_subfolder = "temp"
    if args.command in ['generate', 'plan'] and args.target:
        workspace_subfolder = args.target  # Use vehicle name as subfolder
    
    # Get optional target engine override from config
    target_engine_file = swap_config.get('target_engine_file', None)
    if target_engine_file:
        logger.info(f"Using target engine override: {target_engine_file}")
    
    # Initialize utility
    utility = EngineTransplantUtility(
        base_vehicles_path=base_vehicles_path,
        output_path=output_base,
        workspace_subfolder=workspace_subfolder,
        target_engine_file=target_engine_file,
        swap_config=swap_config
    )
    
    # Execute command
    if args.command == 'analyze-engine':
        engine_path = Path(args.input)
        engine = utility.load_donor_engine(engine_path)
        if engine:
            print(f"\n=== Engine Analysis ===")
            print(f"Name: {engine.name}")
            print(f"SlotType: {engine.slot_type}")
            print(f"Max RPM: {engine.max_rpm}")
            print(f"Idle RPM: {engine.idle_rpm}")
            print(f"Torque Curve Points: {len(engine.torque_curve)}")
            print(f"Required Slots: {', '.join(engine.required_slots)}")
            print(f"Node Positions: {len(engine.node_positions)} nodes")
    
    elif args.command == 'analyze-vehicle':
        vehicle_info = utility.analyze_target_vehicle(args.input)
        if vehicle_info:
            print(f"\n=== Vehicle Analysis ===")
            print(f"Name: {vehicle_info.name}")
            print(f"Architecture: {vehicle_info.architecture.value}")
            print(f"Engine SlotType: {vehicle_info.engine_slot_type}")
            print(f"Base Path: {vehicle_info.base_path}")
    
    elif args.command == 'plan':
        if not args.target:
            print("Error: plan command requires target vehicle name")
            return
        
        engine_path = Path(args.input)
        engine = utility.load_donor_engine(engine_path)
        vehicle = utility.analyze_target_vehicle(args.target)
        
        if engine and vehicle:
            plan = utility.generate_adaptation_plan(engine, vehicle)
            
            print(f"\n=== Adaptation Plan ===")
            print(f"Donor: {plan['donor_engine']['name']} ({plan['donor_engine']['original_slot_type']})")
            print(f"Target: {plan['target_vehicle']['name']} ({plan['target_vehicle']['architecture']})")
            print(f"\nRequired Adaptations: {len(plan['adaptations_required'])}")
            for i, adaptation in enumerate(plan['adaptations_required'], 1):
                print(f"  {i}. {adaptation['type']}: {adaptation['description']}")
            
            if plan['compatibility_notes']:
                print(f"\nCompatibility Notes:")
                for note in plan['compatibility_notes']:
                    print(f"  - {note}")
    
    elif args.command == 'generate':
        if not args.target:
            print("Error: generate command requires target vehicle name")
            return
        
        engine_path = Path(args.input)
        
        # Load donor engine to get characteristics
        engine = utility.load_donor_engine(engine_path)
        if not engine:
            print("Error: Failed to load donor engine")
            return
        
        # Analyze target vehicle
        vehicle = utility.analyze_target_vehicle(args.target)
        if not vehicle:
            print("Error: Failed to analyze target vehicle")
            return
        
        # Analyze target vehicle's transfer case inventory (Phase 1)
        tc_catalog = utility.analyze_target_powertrain(args.target)
        if tc_catalog:
            print(f"\n=== Target Vehicle Powertrain ===")
            tcs = tc_catalog.get("transfer_cases", [])
            print(f"Transfer case variants: {len(tcs)}")
            for tc in tcs:
                slots_desc = ", ".join(
                    s["slot_type"] for s in tc.get("child_slots", [])
                )
                print(f"  {tc['part_name']}: {tc['drive_type']}"
                      f"  [{slots_desc}]")
        else:
            print("\n  (Target powertrain analysis unavailable)")
        
        # Analyze donor vehicle's drive type (Phase 2)
        donor_catalog = utility.analyze_donor_powertrain(engine_path)
        if donor_catalog:
            print(f"\n=== Donor Powertrain Classification ===")
            print(f"Drive type: {donor_catalog['drive_type']}")
            if donor_catalog.get('awd_subvariant'):
                print(f"AWD sub-variant: {donor_catalog['awd_subvariant']}")
            parts = donor_catalog.get("parts", [])
            print(f"TC parts: {len(parts)}")
            for p in parts:
                slots_str = ", ".join(p.get("child_slots", []))
                dev_str = ", ".join(
                    f"{d['type']}:{d['name']}" for d in p.get("devices", [])
                )
                print(f"  {p['part_name']}: {p['drive_type']}")
                print(f"    devices: [{dev_str}]")
                if slots_str:
                    print(f"    child_slots: [{slots_str}]")
                if p.get("notable_properties"):
                    print(f"    properties: {p['notable_properties']}")
            if donor_catalog.get("center_diff"):
                cd = donor_catalog["center_diff"]
                cd_dev = ", ".join(
                    f"{d['type']}:{d['name']}" for d in cd.get("devices", [])
                )
                print(f"  Center diff: {cd['part_name']}")
                print(f"    devices: [{cd_dev}]")
                if cd.get("notable_properties"):
                    print(f"    properties: {cd['notable_properties']}")
        else:
            print("\n  (Donor powertrain analysis unavailable)")
        
        # Phase 3: Swap Decision Engine
        swap_decision = None
        if donor_catalog:
            swap_decision = utility.select_swap_strategy(
                donor_catalog, tc_catalog, args.target
            )
            # Decision logging (Phase 3.4)
            print(f"\n=== Swap Decision Engine ===")
            d_type = swap_decision["donor_drive_type"]
            d_sub = swap_decision.get("donor_awd_subvariant")
            print(f"Camso donor: {d_type}"
                  f"{f' ({d_sub} subtype)' if d_sub else ''}")
            
            candidates = swap_decision.get("all_candidates", [])
            if candidates:
                print(f"Target vehicle '{args.target}' transfer case catalog:")
                selected_part = (swap_decision.get("selected_tc") or {}).get("part_name")
                for c in candidates:
                    marker = ""
                    if c["part_name"] == selected_part:
                        marker = "  <-- SELECTED"
                    print(f"  {c['part_name']:<40s} {c['target_drive_type']:<8s} "
                          f"-> {c['strategy']:<12s} (cost: {c['cost']}){marker}")
            elif swap_decision["target_drive_type"].startswith("NO_TC"):
                print(f"Target '{args.target}': non-TC vehicle "
                      f"({swap_decision['target_drive_type']})")
            
            strat = swap_decision["strategy"]
            cost = swap_decision["cost"]
            if swap_decision["refused"]:
                print(f"\n  *** REFUSED: {swap_decision['refuse_reason']}")
            else:
                selected = swap_decision.get("selected_tc")
                tc_name = selected["part_name"] if selected else "(synthetic)"
                print(f"\nSelected: {tc_name} via {strat} strategy (cost: {cost})")
        else:
            print("\n  (Swap Decision Engine skipped — no donor catalog)")
        
        # Phase 4: Axle Slot Extraction
        injection_targets = None
        if swap_decision and not swap_decision["refused"]:
            injection_targets = utility.extract_injection_targets(swap_decision)
            if injection_targets:
                print(f"\n=== Axle Slot Extraction ===")
                direct = injection_targets["direct_child_count"]
                tc_direct = injection_targets["tc_has_direct_child_slots"]
                print(f"Selected TC: {injection_targets['selected_tc']}")
                print(f"TC declares own child slots: {'yes' if tc_direct else 'no'}"
                      f" ({direct} direct)")
                
                rear = injection_targets["rear_slots"]
                front = injection_targets["front_slots"]
                if rear:
                    print(f"Rear driveshaft targets ({len(rear)}):")
                    for r in rear[:5]:  # Show first 5
                        print(f"  {r['slot_type']:<45s} ({', '.join(r['devices'])})")
                    if len(rear) > 5:
                        print(f"  ... and {len(rear) - 5} more")
                if front:
                    print(f"Front driveshaft targets ({len(front)}):")
                    for f_ in front[:5]:  # Show first 5
                        print(f"  {f_['slot_type']:<45s} ({', '.join(f_['devices'])})")
                    if len(front) > 5:
                        print(f"  ... and {len(front) - 5} more")
                
                # Summary: which slots are relevant per strategy
                strat = injection_targets["strategy"]
                if strat in ("DIRECT", "MAKE_RWD"):
                    print(f"\nStrategy {strat}: rear slots relevant ({len(rear)} candidates)")
                elif strat == "MAKE_FWD":
                    print(f"\nStrategy {strat}: front slots relevant ({len(front)} candidates)")
                else:
                    print(f"\nStrategy {strat}: both rear ({len(rear)}) + front ({len(front)}) slots relevant")
            elif swap_decision["strategy"] == "SYNTH_TC":
                print(f"\n=== Axle Slot Extraction ===")
                print(f"SYNTH_TC strategy: no BeamNG TC to extract from")
                print(f"Adaptation will generate synthetic TC bridge for non-TC vehicle")
        
        # Generate adaptation plan
        plan = utility.generate_adaptation_plan(engine, vehicle)
        
        # Generate adapted JBeam file
        output_file = utility.generate_adapted_jbeam(engine_path, vehicle, plan)
        
        if output_file:
            print(f"\n=== Generation Complete ===")
            print(f"Adapted ENGINE file: {output_file}")
            
            # Look for transmission and transfercase files in same directory
            donor_dir = engine_path.parent.parent  # Go up to vehicle root
            print(f"\nSearching for powertrain components in: {donor_dir}")
            
            # Find transmission files
            trans_files = list(donor_dir.glob("**/camso_transmission*.jbeam"))
            transfer_files = list(donor_dir.glob("**/camso_transfercase*.jbeam"))
            
            # Apply transmissions_to_adapt filter
            trans_adapt_mode = swap_config.get("transmissions_to_adapt", "all")
            if trans_adapt_mode == "single" and trans_files:
                default_trans_file = utility._identify_default_transmission(
                    engine_path, trans_files
                )
                if default_trans_file:
                    skipped = [f for f in trans_files if f != default_trans_file]
                    if skipped:
                        print(f"\n  [transmissions_to_adapt: single] Skipping {len(skipped)} "
                              f"vestigial transmission file(s):")
                        for sf in skipped:
                            print(f"    - {sf.name} (not the engine's default)")
                    trans_files = [default_trans_file]
                else:
                    print(f"\n  [transmissions_to_adapt: single] Could not identify default "
                          f"— adapting all {len(trans_files)} transmission(s)")
            
            if trans_files:
                print(f"\nFound {len(trans_files)} transmission file(s):")
                for trans_file in trans_files:
                    print(f"  - {trans_file.name}")
                    trans_output = utility.generate_adapted_transmission(trans_file, vehicle)
                    if trans_output:
                        print(f"    -> Generated: {trans_output.name}")
                        # Register with slot graph for manifest tracking
                        if utility._slot_graph:
                            utility._slot_graph.add_generated_file(trans_output)
            
            if transfer_files:
                print(f"\nFound {len(transfer_files)} transfercase file(s):")
                for tc_file in transfer_files:
                    print(f"  - {tc_file.name}")
                    tc_output = utility.generate_adapted_transfercase(
                        tc_file, vehicle,
                        swap_decision=swap_decision,
                        injection_targets=injection_targets
                    )
                    if tc_output:
                        print(f"    -> Generated: {tc_output.name}")
                        # Register with slot graph for manifest tracking
                        if utility._slot_graph:
                            utility._slot_graph.add_generated_file(tc_output)
            
            print(f"\n=== Adaptations Applied ===")
            for adaptation in plan['adaptations_required']:
                print(f"  - {adaptation['type']}: {adaptation['description']}")
            
            # Generate mod manifest
            print(f"\n=== Mod Manifest ===")
            manifest = utility.generate_mod_manifest(engine_path, vehicle)
            
            # Write manifest to JSON file
            manifest_file = utility.temp_path / f"{vehicle.name}_swap_manifest.json"
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            print(f"  Manifest saved: {manifest_file}")
            
            # Print summary based on manifest version
            manifest_version = manifest.get("version", "1.0")
            
            if manifest_version.startswith("3."):
                # Slot-centric manifest (v3.0)
                print(f"\n  Slot-Centric Manifest (v{manifest_version}):")
                stats = manifest.get("statistics", {})
                print(f"    Total slots: {stats.get('total_slots', 0)}")
                print(f"    Original jbeam files: {stats.get('original_jbeam_files', 0)}")
                print(f"    Generated jbeam files: {stats.get('generated_jbeam_files', 0)}")
                
                asset_files = manifest.get("asset_files", {})
                print(f"    Physical mesh files: {len(asset_files.get('meshes', []))}")
                print(f"    Physical texture files: {len(asset_files.get('textures', []))}")
                
                # Show copy plan summary
                copy_plan = manifest.get("copy_plan", {})
                if copy_plan:
                    print(f"\n  Copy Plan:")
                    print(f"    Original files to copy: {len(copy_plan.get('original_jbeam', []))}")
                    print(f"    Generated files ready: {len(copy_plan.get('generated_jbeam', []))}")
                    excluded = copy_plan.get('excluded_files', [])
                    if excluded:
                        print(f"    Excluded (pruned): {len(excluded)}")
                        
            else:
                # Legacy manifest (v1.0/v2.0)
                print(f"\n  Required Files Summary:")
                for category, files in manifest.get("required_files", {}).items():
                    if files:
                        print(f"    {category}: {len(files)} file(s)")
            
            print(f"\n=== Copy Instructions ===")
            for instruction in manifest.get("copy_instructions", []):
                print(f"  {instruction}")
            
            # === Drivetrain Adaptation Summary (Phase 6) ===
            drivetrain = manifest.get("drivetrain")
            if drivetrain:
                print(f"\n=== Drivetrain Adaptation ===")
                d_type = drivetrain.get("donor_drive_type", "?")
                d_sub = drivetrain.get("donor_awd_subvariant")
                strat = drivetrain.get("swap_strategy", "?")
                cost = drivetrain.get("adaptation_cost", -1)
                tc_name = drivetrain.get("selected_beamng_tc", "(none)")
                print(f"  Donor: {d_type}{f' ({d_sub})' if d_sub else ''}")
                print(f"  Strategy: {strat} (cost: {cost})")
                print(f"  Target TC: {tc_name}")
                
                pruned = drivetrain.get("slots_pruned", [])
                if pruned:
                    print(f"  Slots pruned: {', '.join(pruned)}")
                
                mapping = drivetrain.get("device_name_mapping", {})
                if mapping:
                    print(f"  Device adaptations (derived):")
                    for old, new in mapping.items():
                        print(f"    '{old}' -> '{new}'")
                
                injected = drivetrain.get("devices_injected", [])
                if injected:
                    print(f"  Devices injected from target: {', '.join(injected)}")
                
                provenance = drivetrain.get("device_name_provenance", [])
                if provenance:
                    print(f"  Provenance ({len(provenance)} mapping(s)):")
                    for p in provenance:
                        print(f"    {p.get('donor_name')} -> {p.get('target_name')}: "
                              f"{p.get('reason', '?')}")
            
            print(f"\n=== Next Steps ===")
            print(f"  1. Review generated files in: {utility.temp_path}")
            print(f"  2. Review manifest: {manifest_file.name}")
            print(f"  3. Copy required files as specified in manifest")
            print(f"  4. Test in BeamNG")
            print(f"\n[Following Cummins Mod Pattern]")
            print(f"  - Main engine adapted to {vehicle.engine_slot_type or vehicle.name + '_engine'} slotType")
            print(f"  - All child slots preserved (intake, management, internals)")
            # Derive family prefix for display
            _disp_prefix = vehicle.name
            if vehicle.engine_slot_type:
                _derived = vehicle.engine_slot_type.replace('_engine', '')
                if _derived != vehicle.name:
                    _disp_prefix = _derived
            print(f"  - Transmission adapted to {_disp_prefix}_transmission slotType")
            print(f"  - TMS translated nodes + torqueReactionNodes to BeamNG convention")
            
            # === PACKAGING ===
            if args.package or args.package_dry_run:
                print(f"\n=== Packaging Assets ===")
                try:
                    from mod_packager import ModPackager
                    
                    packager = ModPackager(manifest_file)
                    packager.load_manifest()
                    
                    dry_run = args.package_dry_run
                    result = packager.execute(dry_run=dry_run, overwrite=False)
                    
                    mode = "[DRY RUN] " if dry_run else ""
                    status = "SUCCESS" if result.success else "FAILED"
                    print(f"{mode}Packaging {status}")
                    print(f"  Total files: {result.total_files}")
                    print(f"  Copied: {result.copied}")
                    print(f"  Skipped: {result.skipped}")
                    print(f"  Failed: {result.failed}")
                    
                    by_cat = result.get_by_category()
                    if by_cat:
                        print(f"\n  By category:")
                        for cat, count in sorted(by_cat.items()):
                            print(f"    {cat}: {count}")
                    
                    if not result.success:
                        print(f"\nPackaging had failures. Check output above.")
                        
                except ImportError as e:
                    print(f"Warning: Could not import mod_packager: {e}")
                except Exception as e:
                    print(f"Warning: Packaging failed: {e}")
        else:
            print("Error: Failed to generate adapted file")
    
    elif args.command == 'visualize':
        # Visualize slot graph for debugging
        if not args.target:
            print("Error: visualize command requires target vehicle name")
            return
        
        if not SLOT_GRAPH_AVAILABLE:
            print("Error: Slot graph module not available. Use Python 3.12+")
            return
        
        engine_path = Path(args.input)
        
        # Analyze target vehicle
        vehicle = utility.analyze_target_vehicle(args.target)
        if not vehicle:
            print("Error: Failed to analyze target vehicle")
            return
        
        # Build slot graph (the visualization target)
        print(f"Building slot graph for {args.target}...")
        graph = utility._build_slot_graph(engine_path, args.target,
                                          engine_slot_type=vehicle.engine_slot_type)
        
        if not graph:
            print("Error: Failed to build slot graph")
            return
        
        # Determine output format
        output_format = "markdown" if args.markdown else "text"
        
        # Map filter_role string to AssetRole enum
        filter_role = None
        if args.filter_role:
            role_map = {
                'source': AssetRole.SOURCE,
                'target': AssetRole.TARGET,
                'preserve': AssetRole.PRESERVE,
                'internal': AssetRole.INTERNAL,
            }
            filter_role = role_map.get(args.filter_role)
        
        # Generate visualization
        visualization = graph.visualize(
            show_source_files=args.show_files,
            show_transformations=args.show_transforms,
            filter_role=filter_role,
            output_format=output_format
        )
        
        # Handle Unicode characters that might not display in Windows console
        try:
            print(visualization)
        except UnicodeEncodeError:
            # Fallback: replace problematic characters
            safe_viz = visualization.encode('ascii', errors='replace').decode('ascii')
            print(safe_viz)
        
        # Also save to file if markdown requested
        if args.markdown:
            output_file = utility.temp_path / f"{args.target}_slot_graph.md"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(visualization)
            print(f"\nVisualization saved to: {output_file}")


if __name__ == '__main__':
    main()
