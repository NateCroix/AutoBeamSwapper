"""
Transplant Mounting Solver (TMS) - Engine Mount Adaptation Module

This module solves the geometric problem of positioning a donor engine (e.g., Camso/Automation)
within a target vehicle's (BeamNG) engine bay such that:
1. The flywheel planes align for proper transmission interface
2. The floor planes align for proper vertical positioning
3. Mount nodes (em1l, em1r, tra1) remain outside the engine bounding box
4. User offsets are applied for fine-tuning

ARCHITECTURE:
    This module is imported by engineswap.py and called during generate_adapted_jbeam()
    to produce translated node positions and beam connections.

NODE NAMING CONVENTIONS:
    Camso/Automation:
        engine0-7: Engine block bounding box (8 corners)
        engine_Gearbox8-11: Transmission mounting points (4 nodes)
    
    BeamNG:
        e1l, e1r, e2l, e2r, e3l, e3r, e4l, e4r: Engine block (8 corners)
        em1l, em1r: Engine mount nodes (left/right)
        tra1: Transmission mount node (rear center)

COORDINATE SYSTEM:
    BeamNG uses a right-handed coordinate system:
    - X: Lateral (+right from driver's perspective)
    - Y: Longitudinal (+rearward toward trunk)
    - Z: Vertical (+upward)

ALGORITHM OVERVIEW:
    Phase 1: Extract donor engine nodes (Camso pattern)
    Phase 2: Extract target vehicle mount structure (BeamNG pattern)
    Phase 3: Compute flywheel plane centroids, align on Y-axis
    Phase 4: Compute floor plane centroids, align on Z-axis
    Phase 5: Apply user offsets (ForeAft, UpDown, LeftRight)
    Phase 6: Check interference, apply resolution if needed
    
Author: BeamNG Engine Swap Utility
Version: 1.0.0
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any, Union
from pathlib import Path
from enum import Enum
import json
import logging
import math
import re

# Configure logging for this module
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class InterferenceResolution(Enum):
    """How to handle mount node interference with engine cube."""
    NONE = "none"
    SHRINK_ENGINE_BLOCK = "shrink_engine_block"
    EXPAND_ENGINE_MOUNTS = "expand_engine_mounts"


class OutputFormat(Enum):
    """Where to write translated nodes."""
    EMBEDDED = "embedded"      # Into engine .jbeam (Cummins pattern)
    SEPARATE = "separate"      # Separate engine_structure.jbeam file


class DriveType(Enum):
    """
    Donor vehicle drive configuration.
    
    Determined by analyzing Camso transfer case driveshaft slots:
    - RWD: Only Camso_driveshaft_rear slot present
    - FWD: Only Camso_driveshaft_front slot present
    - AWD: Both front and rear, with center differential (continuous power)
    - FOUR_WD: Both front and rear, with selectable modes (part-time 4WD)
    - UNKNOWN: Could not determine drive type
    """
    RWD = "rwd"
    FWD = "fwd"
    AWD = "awd"
    FOUR_WD = "4wd"
    UNKNOWN = "unknown"


# ============================================================================
# CORE DATA STRUCTURES
# ============================================================================

@dataclass
class Vec3:
    """
    3D vector for node positions using BeamNG coordinate convention.
    
    Coordinate System:
        x: Lateral (+right from driver's perspective)
        y: Longitudinal (+rearward toward trunk)
        z: Vertical (+upward)
    """
    x: float
    y: float
    z: float
    
    def __add__(self, other: Vec3) -> Vec3:
        """Vector addition."""
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __sub__(self, other: Vec3) -> Vec3:
        """Vector subtraction."""
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)
    
    def __mul__(self, scalar: float) -> Vec3:
        """Scalar multiplication."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def __truediv__(self, scalar: float) -> Vec3:
        """Scalar division."""
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)
    
    def magnitude(self) -> float:
        """Euclidean magnitude."""
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)
    
    def normalized(self) -> Vec3:
        """Return unit vector in same direction."""
        mag = self.magnitude()
        if mag < 1e-10:
            return Vec3(0, 0, 0)
        return self / mag
    
    def dot(self, other: Vec3) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z
    
    def cross(self, other: Vec3) -> Vec3:
        """Cross product."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x
        )
    
    def to_tuple(self) -> Tuple[float, float, float]:
        """Convert to tuple for serialization."""
        return (self.x, self.y, self.z)
    
    def to_list(self) -> List[float]:
        """Convert to list for jbeam output."""
        return [self.x, self.y, self.z]
    
    @classmethod
    def from_list(cls, coords: List[float]) -> Vec3:
        """Create from [x, y, z] list."""
        return cls(coords[0], coords[1], coords[2])
    
    def __repr__(self) -> str:
        return f"Vec3({self.x:.4f}, {self.y:.4f}, {self.z:.4f})"


@dataclass
class EngineNode:
    """
    A single physics node in the engine assembly.
    
    Attributes:
        name: Node identifier (e.g., "engine0", "e1l", "em1r")
        position: 3D position in vehicle coordinate space
        original_name: Name from source file (before any renaming)
        node_properties: Additional jbeam node properties (mass, collision, etc.)
    """
    name: str
    position: Vec3
    original_name: Optional[str] = None
    node_properties: Dict[str, Any] = field(default_factory=dict)
    
    def translated(self, offset: Vec3) -> EngineNode:
        """Return new node with position translated by offset."""
        return EngineNode(
            name=self.name,
            position=self.position + offset,
            original_name=self.original_name or self.name,
            node_properties=self.node_properties.copy()
        )
    
    def renamed(self, new_name: str) -> EngineNode:
        """Return new node with different name."""
        return EngineNode(
            name=new_name,
            position=self.position,
            original_name=self.original_name or self.name,
            node_properties=self.node_properties.copy()
        )
    
    def to_jbeam(self) -> List[Any]:
        """
        Convert to jbeam node array format.
        
        Format: ["name", x, y, z, {properties}] or ["name", x, y, z]
        """
        base = [self.name, self.position.x, self.position.y, self.position.z]
        if self.node_properties:
            base.append(self.node_properties)
        return base


@dataclass
class EngineCube:
    """
    The 8-corner bounding box of an engine block for physics simulation.
    
    Node naming conventions (validated Feb 2026):
    
    Camso Pattern (engine0-7):
        engine0: front-right-bottom  → e2r
        engine1: front-left-bottom   → e2l
        engine2: rear-left-bottom    → e1l
        engine3: rear-right-bottom   → e1r
        engine4: front-right-top     → e4r
        engine5: front-left-top      → e4l
        engine6: rear-left-top       → e3l
        engine7: rear-right-top      → e3r
    
    BeamNG Pattern (e1l-e4r, in numeric order):
        e1l: rear-left-bottom      e1r: rear-right-bottom
        e2l: front-left-bottom     e2r: front-right-bottom
        e3l: rear-left-top         e3r: rear-right-top
        e4l: front-left-top        e4r: front-right-top
    
    Attributes:
        nodes: Dictionary mapping node name to EngineNode
        source_pattern: "camso" or "beamng" indicating naming convention
    """
    nodes: Dict[str, EngineNode]
    source_pattern: str = "unknown"
    
    # Node mapping from Camso to BeamNG (validated Feb 2026)
    # Arranged by BeamNG numeric order for clarity
    CAMSO_TO_BEAMNG_MAP = {
        "engine2": "e1l",   # rear-left-bottom
        "engine3": "e1r",   # rear-right-bottom
        "engine1": "e2l",   # front-left-bottom
        "engine0": "e2r",   # front-right-bottom
        "engine6": "e3l",   # rear-left-top
        "engine7": "e3r",   # rear-right-top
        "engine5": "e4l",   # front-left-top
        "engine4": "e4r",   # front-right-top
    }
    
    @property
    def centroid(self) -> Vec3:
        """Calculate geometric center of the engine cube."""
        if not self.nodes:
            return Vec3(0, 0, 0)
        
        total = Vec3(0, 0, 0)
        for node in self.nodes.values():
            total = total + node.position
        return total / len(self.nodes)
    
    def get_flywheel_plane_nodes(self) -> List[EngineNode]:
        """
        Return the 4 rear nodes that define the flywheel plane.
        
        These are the rearmost nodes where the transmission interfaces.
        Camso: engine2, engine3, engine6, engine7
        BeamNG: e1l, e1r, e3l, e3r
        """
        if self.source_pattern == "camso":
            rear_names = ["engine2", "engine3", "engine6", "engine7"]
        else:  # beamng
            rear_names = ["e1l", "e1r", "e3l", "e3r"]
        
        return [self.nodes[n] for n in rear_names if n in self.nodes]
    
    def get_floor_plane_nodes(self) -> List[EngineNode]:
        """
        Return the 4 bottom nodes that define the floor plane.
        
        These are the lowest nodes that constrain vertical position.
        Camso: engine0, engine1, engine4, engine5
        BeamNG: e2l, e2r, e4l, e4r
        """
        if self.source_pattern == "camso":
            bottom_names = ["engine2", "engine3", "engine1", "engine0"]
        else:  # beamng
            bottom_names = ["e1l", "e1r", "e2l", "e2r"]
        
        return [self.nodes[n] for n in bottom_names if n in self.nodes]
    
    def get_plane_centroid(self, nodes: List[EngineNode]) -> Vec3:
        """Calculate centroid of a set of nodes (for plane alignment)."""
        if not nodes:
            return Vec3(0, 0, 0)
        
        total = Vec3(0, 0, 0)
        for node in nodes:
            total = total + node.position
        return total / len(nodes)
    
    def get_aabb(self) -> Tuple[Vec3, Vec3]:
        """
        Get axis-aligned bounding box of the engine cube.
        
        Returns:
            Tuple of (min_corner, max_corner) Vec3 positions
        """
        if not self.nodes:
            return (Vec3(0, 0, 0), Vec3(0, 0, 0))
        
        positions = [n.position for n in self.nodes.values()]
        min_corner = Vec3(
            min(p.x for p in positions),
            min(p.y for p in positions),
            min(p.z for p in positions)
        )
        max_corner = Vec3(
            max(p.x for p in positions),
            max(p.y for p in positions),
            max(p.z for p in positions)
        )
        return (min_corner, max_corner)
    
    def contains_point(self, point: Vec3, margin: float = 0.0) -> bool:
        """
        Check if a point is inside the engine cube AABB.
        
        Args:
            point: Position to check
            margin: Positive shrinks check region, negative expands
            
        Returns:
            True if point is inside (accounting for margin)
        """
        min_c, max_c = self.get_aabb()
        return (
            min_c.x + margin <= point.x <= max_c.x - margin and
            min_c.y + margin <= point.y <= max_c.y - margin and
            min_c.z + margin <= point.z <= max_c.z - margin
        )
    
    def translated(self, offset: Vec3) -> EngineCube:
        """Return new EngineCube with all nodes translated."""
        new_nodes = {
            name: node.translated(offset)
            for name, node in self.nodes.items()
        }
        return EngineCube(nodes=new_nodes, source_pattern=self.source_pattern)
    
    def scaled_from_centroid(self, scale: float) -> EngineCube:
        """
        Return new EngineCube with nodes scaled toward/away from centroid.
        
        Args:
            scale: < 1.0 shrinks, > 1.0 expands
        """
        center = self.centroid
        new_nodes = {}
        for name, node in self.nodes.items():
            direction = node.position - center
            new_pos = center + (direction * scale)
            new_nodes[name] = EngineNode(
                name=node.name,
                position=new_pos,
                original_name=node.original_name,
                node_properties=node.node_properties.copy()
            )
        return EngineCube(nodes=new_nodes, source_pattern=self.source_pattern)
    
    def with_beamng_names(self) -> EngineCube:
        """
        Return new EngineCube with nodes renamed to BeamNG convention.
        
        Only applies if source_pattern is "camso".
        """
        if self.source_pattern != "camso":
            logger.warning("with_beamng_names() called on non-camso cube")
            return self
        
        new_nodes = {}
        for old_name, node in self.nodes.items():
            if old_name in self.CAMSO_TO_BEAMNG_MAP:
                new_name = self.CAMSO_TO_BEAMNG_MAP[old_name]
                new_nodes[new_name] = node.renamed(new_name)
            else:
                # Keep non-standard nodes as-is
                new_nodes[old_name] = node
        
        return EngineCube(nodes=new_nodes, source_pattern="beamng")


@dataclass
class MountNode:
    """
    Engine mount attachment point on the chassis/subframe.
    
    These are the nodes where the engine connects to the vehicle structure.
    
    BeamNG Convention:
        em1l: Left engine mount
        em1r: Right engine mount  
        tra1: Transmission mount (rear center)
    
    Attributes:
        name: Node identifier (e.g., "em1l")
        position: 3D position in vehicle coordinate space
        mount_type: "engine_left", "engine_right", or "transmission"
    """
    name: str
    position: Vec3
    mount_type: str = "unknown"
    
    def translated(self, offset: Vec3) -> MountNode:
        """Return new MountNode with position translated."""
        return MountNode(
            name=self.name,
            position=self.position + offset,
            mount_type=self.mount_type
        )
    
    def to_jbeam(self) -> List[Any]:
        """Convert to jbeam node format."""
        return [self.name, self.position.x, self.position.y, self.position.z]


@dataclass
class TransmissionNode:
    """
    Transmission/gearbox physics node.
    
    BeamNG Convention:
        tra1: Primary transmission output (all transmissions)
        tra2, tra3: Transfer case nodes (4WD/AWD only)
    
    Attributes:
        name: Node identifier (e.g., "tra1")
        position: 3D position in vehicle coordinate space
        weight: Node mass in kg
        group: Node group (typically "pickup_transmission" or similar)
    """
    name: str
    position: Vec3
    weight: float = 32.9
    group: str = ""
    
    def to_jbeam(self) -> List[Any]:
        """Convert to jbeam node format."""
        return [self.name, self.position.x, self.position.y, self.position.z]


@dataclass 
class TransmissionStructure:
    """
    Complete transmission node/beam structure from a BeamNG target vehicle.
    
    Attributes:
        nodes: List of TransmissionNode (tra1, tra2, tra3, etc.)
        beam_properties: BeamProperties for transmission-to-engine beams
        connected_engine_nodes: List of engine node names the transmission connects to
    """
    nodes: List[TransmissionNode] = field(default_factory=list)
    beam_properties: Optional[BeamProperties] = None
    connected_engine_nodes: List[str] = field(default_factory=list)
    
    def get_total_weight(self) -> float:
        """Sum of all transmission node weights."""
        return sum(n.weight for n in self.nodes)
    
    def get_node_names(self) -> List[str]:
        """List of transmission node names."""
        return [n.name for n in self.nodes]


@dataclass
class SwapParameters:
    """
    User-configurable parameters for engine swap geometry adjustments.
    
    Loaded from configs/swap_parameters.json
    
    Attributes:
        fix_mesh_offset: Correct visual mesh to align with physics nodes
        shrink_or_expand: How to handle interference (enum value)
        fore_aft_offset: Y-axis adjustment (+rearward, -forward)
        up_down_offset: Z-axis adjustment (+up, -down)
        left_right_offset: X-axis adjustment (+right, -left)
        max_shrink_percent: Maximum allowed engine cube shrink
        max_mount_expansion_m: Maximum mount node movement
        min_mount_clearance_m: Required gap between mounts and engine
        output_format: Where to write nodes (embedded or separate)
        generate_debug_visualization: Add visual debug markers
        target_engine_file: Optional override for target engine selection (filename only)
    """
    fix_mesh_offset: bool = False
    shrink_or_expand: InterferenceResolution = InterferenceResolution.NONE
    fore_aft_offset: float = 0.0
    up_down_offset: float = 0.0
    left_right_offset: float = 0.0
    max_shrink_percent: float = 15.0
    max_mount_expansion_m: float = 0.1
    min_mount_clearance_m: float = 0.02
    output_format: OutputFormat = OutputFormat.EMBEDDED
    generate_debug_visualization: bool = False
    target_engine_file: Optional[str] = None
    
    @classmethod
    def from_file(cls, path: Path) -> SwapParameters:
        """Load parameters from JSON file (with comment support)."""
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Strip JavaScript-style comments (same as JBeamParser)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        data = json.loads(content)
        
        solver_opts = data.get("solver_options", {})
        limits = data.get("limits", {})
        output = data.get("output", {})
        
        # Parse interference resolution enum
        shrink_str = solver_opts.get("swpparam_ShrinkOrExpand", "none")
        try:
            shrink_enum = InterferenceResolution(shrink_str)
        except ValueError:
            logger.warning(f"Unknown shrink option '{shrink_str}', using NONE")
            shrink_enum = InterferenceResolution.NONE
        
        # Parse output format enum
        format_str = output.get("format", "embedded")
        try:
            format_enum = OutputFormat(format_str)
        except ValueError:
            logger.warning(f"Unknown output format '{format_str}', using EMBEDDED")
            format_enum = OutputFormat.EMBEDDED
        
        return cls(
            fix_mesh_offset=solver_opts.get("swpparam_FixMeshOffset", False),
            shrink_or_expand=shrink_enum,
            fore_aft_offset=solver_opts.get("swpparam_ForeAftOffset", 0.0),
            up_down_offset=solver_opts.get("swpparam_UpDownOffset", 0.0),
            left_right_offset=solver_opts.get("swpparam_LeftRightOffset", 0.0),
            max_shrink_percent=limits.get("max_shrink_percent", 15.0),
            max_mount_expansion_m=limits.get("max_mount_expansion_m", 0.1),
            min_mount_clearance_m=limits.get("min_mount_clearance_m", 0.02),
            output_format=format_enum,
            generate_debug_visualization=output.get("generate_debug_visualization", False),
            target_engine_file=data.get("target_engine_file", None)
        )
    
    @classmethod
    def defaults(cls) -> SwapParameters:
        """Return default parameters (no adjustments)."""
        return cls()
    
    def get_user_offset(self) -> Vec3:
        """Get combined user offset as Vec3."""
        return Vec3(
            self.left_right_offset,  # X
            self.fore_aft_offset,    # Y
            self.up_down_offset      # Z
            )


@dataclass
class BeamProperties:
    """
    Beam properties extracted from jbeam files.
    
    Used for both engine cube beams (from source/donor engine) and
    mount beams (from target vehicle).
    
    Attributes:
        beam_spring: Spring stiffness (N/m)
        beam_damp: Damping coefficient
        beam_deform: Deformation threshold
        beam_strength: Breaking strength (or "FLT_MAX" for unbreakable)
    """
    beam_spring: float = 2956300.0
    beam_damp: float = 130.43
    beam_deform: float = 63000.0
    beam_strength: Union[float, str] = "FLT_MAX"
    
    def to_property_dict(self) -> Dict[str, Any]:
        """Convert to jbeam property modifier format."""
        return {
            "beamSpring": self.beam_spring,
            "beamDamp": self.beam_damp,
            "beamDeform": self.beam_deform,
            "beamStrength": self.beam_strength
        }


# Alias for backwards compatibility
MountBeamProperties = BeamProperties


@dataclass
class SolverResult:
    """
    Output from MountSolver.solve() containing translated geometry.
    
    Attributes:
        success: Whether solve completed without critical errors
        engine_cube: Translated (and possibly shrunk) engine cube with BeamNG names
        mount_nodes: Mount nodes (possibly expanded)
        translation: Total translation applied to donor engine
        warnings: Non-fatal issues encountered
        errors: Fatal issues that caused failure
        mesh_offset: Visual mesh correction (if fix_mesh_offset was True)
        scale_applied: Engine cube scale factor applied (1.0 = no change)
        mount_beam_properties: Beam properties for mount connections (from target)
        source_engine_beam_properties: Beam properties for engine cube (from donor)
        transmission_structure: Target vehicle transmission nodes/beams
        camso_gearbox_weight: Total weight of Camso gearbox nodes (for redistribution)
    """
    success: bool
    engine_cube: Optional[EngineCube] = None
    mount_nodes: List[MountNode] = field(default_factory=list)
    translation: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    mesh_offset: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    scale_applied: float = 1.0
    mount_beam_properties: Optional[BeamProperties] = None
    source_engine_beam_properties: Optional[BeamProperties] = None
    transmission_structure: Optional[TransmissionStructure] = None
    camso_gearbox_weight: float = 0.0
    
    def to_jbeam_nodes(self) -> List[List[Any]]:
        """
        Generate jbeam-format node arrays for the translated engine.
        
        Returns:
            List of node arrays ready for insertion into jbeam "nodes" section
        """
        nodes = []
        
        if self.engine_cube:
            for node in self.engine_cube.nodes.values():
                nodes.append(node.to_jbeam())
        
        # Note: Mount nodes come from target vehicle, not generated here
        
        return nodes
    
    def get_summary(self) -> str:
        """Human-readable summary of solve results."""
        lines = []
        lines.append(f"Solve {'SUCCEEDED' if self.success else 'FAILED'}")
        lines.append(f"Translation: {self.translation}")
        lines.append(f"Scale applied: {self.scale_applied:.3f}")
        
        if self.warnings:
            lines.append(f"Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  - {w}")
        
        if self.errors:
            lines.append(f"Errors ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  - {e}")
        
        return "\n".join(lines)


# ============================================================================
# EXTRACTOR CLASSES
# ============================================================================

class DonorEngineExtractor:
    """
    Extracts engine cube geometry from a Camso/Automation engine jbeam file.
    
    Looks for nodes matching Camso pattern: engine0-7, engine_Gearbox8-11
    """
    
    # Expected Camso node names for engine cube
    CAMSO_ENGINE_NODES = [
        "engine0", "engine1", "engine2", "engine3",
        "engine4", "engine5", "engine6", "engine7"
    ]
    
    # Expected Camso node names for gearbox interface
    CAMSO_GEARBOX_NODES = [
        "engine_Gearbox8", "engine_Gearbox9",
        "engine_Gearbox10", "engine_Gearbox11"
    ]
    
    def __init__(self, jbeam_data: Dict[str, Any]):
        """
        Initialize extractor with parsed jbeam data.
        
        Args:
            jbeam_data: Parsed jbeam content (from JBeamParser)
        """
        self.jbeam_data = jbeam_data
        self._engine_cube: Optional[EngineCube] = None
        self._gearbox_nodes: Dict[str, EngineNode] = {}
    
    def extract(self) -> EngineCube:
        """
        Extract engine cube from jbeam data.
        
        Returns:
            EngineCube with Camso-pattern nodes
            
        Raises:
            ValueError: If required engine nodes are not found
        """
        nodes_found: Dict[str, EngineNode] = {}
        
        # Iterate through all parts in jbeam
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            # Look for "nodes" section
            nodes_section = part_data.get("nodes")
            if not nodes_section or not isinstance(nodes_section, list):
                continue
            
            # Parse nodes array
            nodes_found.update(self._parse_nodes_section(nodes_section))
        
        # Validate we found required engine nodes
        missing = []
        for required in self.CAMSO_ENGINE_NODES:
            if required not in nodes_found:
                missing.append(required)
        
        if missing:
            logger.warning(f"Missing Camso engine nodes: {missing}")
            # Try to continue if we have at least 4 nodes
            if len(nodes_found) < 4:
                raise ValueError(
                    f"Insufficient engine nodes found. Need at least 4, found {len(nodes_found)}"
                )
        
        # Promote isExhaust from gearbox nodes to nearest eligible engine cube
        # nodes BEFORE separating them — gearbox nodes carrying isExhaust would
        # otherwise be silently dropped from the adapted output.
        self._promote_gearbox_isExhaust(nodes_found)
        
        # Store gearbox nodes separately
        for name in self.CAMSO_GEARBOX_NODES:
            if name in nodes_found:
                self._gearbox_nodes[name] = nodes_found.pop(name)
        
        self._engine_cube = EngineCube(nodes=nodes_found, source_pattern="camso")
        logger.info(f"Extracted {len(nodes_found)} engine nodes from donor")
        
        return self._engine_cube
    
    def get_gearbox_nodes(self) -> Dict[str, EngineNode]:
        """Return extracted gearbox interface nodes."""
        return self._gearbox_nodes.copy()
    
    def _promote_gearbox_isExhaust(
        self, nodes: Dict[str, EngineNode],
    ) -> None:
        """Transfer isExhaust from gearbox nodes to nearest eligible engine cube nodes.

        Camso engines occasionally place ``{"isExhaust": "mainEngine"}`` on
        gearbox-face nodes (engine_Gearbox8/9) rather than engine-block nodes.
        Because gearbox nodes are dropped from the engine cube during
        adaptation, the isExhaust property would be silently lost.

        This method detects gearbox nodes carrying isExhaust and promotes the
        property to the nearest eligible engine cube node, preserving count and
        approximate spatial relationship.

        Eligibility constraints for the receiving engine cube node:
            1. Must be on the **floor plane** — its Z coordinate matches the
               gearbox node's Z (within tolerance), ensuring the exhaust origin
               stays on the bottom of the engine rather than the top.
            2. Must **not** have ``engine_intake`` in its ``engineGroup`` list,
               avoiding intake-designated nodes.
            3. Must not already carry ``isExhaust`` (prevents double-assignment).

        Args:
            nodes: Mutable dict of all parsed engine* nodes (cube + gearbox).
                   Modified in-place — isExhaust is added to the chosen cube
                   node and removed from the gearbox node.
        """
        Z_TOLERANCE = 0.15  # metres — floor-plane membership tolerance

        gearbox_with_exhaust = [
            (name, node) for name, node in nodes.items()
            if name in self.CAMSO_GEARBOX_NODES
            and node.node_properties.get("isExhaust")
        ]

        if not gearbox_with_exhaust:
            return

        cube_nodes = {
            name: node for name, node in nodes.items()
            if name in self.CAMSO_ENGINE_NODES
        }

        for gb_name, gb_node in gearbox_with_exhaust:
            best_name: Optional[str] = None
            best_dist = float("inf")

            for cube_name, cube_node in cube_nodes.items():
                # --- Constraint 1: floor-plane Z match ---
                if abs(cube_node.position.z - gb_node.position.z) > Z_TOLERANCE:
                    continue

                # --- Constraint 2: not an intake node ---
                engine_group = cube_node.node_properties.get("engineGroup", [])
                if "engine_intake" in engine_group:
                    continue

                # --- Constraint 3: not already carrying isExhaust ---
                if cube_node.node_properties.get("isExhaust"):
                    continue

                dist = (cube_node.position - gb_node.position).magnitude()
                if dist < best_dist:
                    best_dist = dist
                    best_name = cube_name

            if best_name is not None:
                is_exhaust_value = gb_node.node_properties.pop("isExhaust")
                nodes[best_name].node_properties["isExhaust"] = is_exhaust_value
                logger.info(
                    f"Promoted isExhaust from gearbox node {gb_name} → "
                    f"engine cube node {best_name} (dist={best_dist:.4f}m)"
                )
            else:
                logger.warning(
                    f"No eligible engine cube node found for isExhaust "
                    f"promotion from {gb_name} — isExhaust will be lost"
                )
    
    def _parse_nodes_section(self, nodes_section: List[Any]) -> Dict[str, EngineNode]:
        """
        Parse a jbeam "nodes" section into EngineNode objects.
        
        Args:
            nodes_section: List from jbeam "nodes" key
            
        Returns:
            Dict mapping node name to EngineNode
        """
        result = {}
        current_properties = {}
        
        for item in nodes_section:
            if isinstance(item, dict):
                # This is a property modifier for subsequent nodes
                current_properties = item.copy()
                continue
            
            if not isinstance(item, list) or len(item) < 4:
                continue
            
            # Format: ["name", x, y, z] or ["name", x, y, z, {props}]
            name = item[0]
            
            # Skip header row
            if name == "id" or not isinstance(name, str):
                continue
            
            # Clean up node name - strip trailing commas and whitespace
            name = name.strip().rstrip(',').strip()
            
            try:
                x = float(item[1])
                y = float(item[2])
                z = float(item[3])
            except (ValueError, TypeError):
                logger.debug(f"Skipping node with non-numeric coords: {name}")
                continue
            
            # Check for inline properties
            node_props = current_properties.copy()
            if len(item) > 4 and isinstance(item[4], dict):
                node_props.update(item[4])
            
            # Only capture engine-related nodes
            if name.startswith("engine"):
                result[name] = EngineNode(
                    name=name,
                    position=Vec3(x, y, z),
                    node_properties=node_props
                )
        
        return result
    
    def extract_engine_beam_properties(self) -> Optional[BeamProperties]:
        """
        Extract beam properties for engine cube connections from Camso engine structure.
        
        Searches the beams section for properties used on engine-to-engine beams.
        
        Returns:
            BeamProperties with spring/damp/deform/strength values, or None
        """
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            beams_section = part_data.get("beams")
            if not beams_section or not isinstance(beams_section, list):
                continue
            
            # Track current beam properties
            current_props = {}
            
            for item in beams_section:
                if isinstance(item, dict):
                    # Property modifier - update tracked values
                    current_props.update(item)
                elif isinstance(item, list) and len(item) >= 2:
                    # Beam definition - check if it's an engine-to-engine beam
                    id1 = str(item[0]).strip().rstrip(':').rstrip(',')
                    id2 = str(item[1]).strip().rstrip(':').rstrip(',')
                    
                    # Skip header row
                    if id1 == "id1" or id2 == "id2":
                        continue
                    
                    # Check if both nodes are engine cube nodes
                    if id1.startswith("engine") and id2.startswith("engine"):
                        # Extract gearbox nodes (engine_Gearbox*) from engine-to-engine
                        if "Gearbox" in id1 or "Gearbox" in id2:
                            continue
                        
                        # Found an engine-to-engine beam, extract properties
                        beam_spring = current_props.get("beamSpring", 3.30439e+07)
                        beam_damp = current_props.get("beamDamp", 1650.54)
                        beam_deform = current_props.get("beamDeform", 330109)
                        beam_strength = current_props.get("beamStrength", 8.25272e+06)
                        
                        logger.info(f"Extracted source engine beam properties: spring={beam_spring}, damp={beam_damp}")
                        return BeamProperties(
                            beam_spring=beam_spring,
                            beam_damp=beam_damp,
                            beam_deform=beam_deform,
                            beam_strength=beam_strength
                        )
        
        logger.warning("Could not extract engine beam properties from source, using defaults")
        return None
    
    def extract_gearbox_total_weight(self) -> float:
        """
        Extract total weight of Camso gearbox nodes (engine_Gearbox8-11).
        
        This weight will be redistributed across BeamNG transmission nodes.
        
        Returns:
            Total weight in kg of all engine_Gearbox* nodes
        """
        total_weight = 0.0
        gearbox_count = 0
        
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            nodes_section = part_data.get("nodes")
            if not nodes_section or not isinstance(nodes_section, list):
                continue
            
            # Track current nodeWeight
            current_weight = 1.0  # Default
            
            for item in nodes_section:
                if isinstance(item, dict):
                    if "nodeWeight" in item:
                        current_weight = float(item["nodeWeight"])
                elif isinstance(item, list) and len(item) >= 4:
                    name = item[0]
                    if not isinstance(name, str):
                        continue
                    
                    # Check for gearbox nodes
                    if name.startswith("engine_Gearbox") or name.startswith("engine_gearbox"):
                        # Check for inline nodeWeight override
                        if len(item) > 4 and isinstance(item[4], dict):
                            node_weight = item[4].get("nodeWeight", current_weight)
                        else:
                            node_weight = current_weight
                        
                        total_weight += float(node_weight)
                        gearbox_count += 1
        
        if gearbox_count > 0:
            logger.info(f"Extracted Camso gearbox weight: {total_weight:.2f} kg from {gearbox_count} nodes")
        else:
            logger.warning("No Camso gearbox nodes found, using default weight")
            total_weight = 35.0  # Fallback to typical BeamNG weight
        
        return total_weight


class DonorDriveTypeExtractor:
    """
    Determines the drive type of a Camso/Automation donor vehicle.
    
    Analyzes the transfer case jbeam file to identify which driveshaft
    slots are present:
    - Camso_driveshaft_front: Front axle connection
    - Camso_driveshaft_rear: Rear axle connection
    
    Drive type determination:
    - RWD: Only rear driveshaft slot present
    - FWD: Only front driveshaft slot present
    - AWD: Both present with center differential (continuous power split)
    - 4WD: Both present with rangebox/driveModes (selectable modes)
    
    The extractor recursively searches through slot chains since AWD configs
    often define driveshaft slots inside a center differential part.
    """
    
    # Slot type patterns to search for
    FRONT_DRIVESHAFT_PATTERN = re.compile(r'Camso_driveshaft_front', re.IGNORECASE)
    REAR_DRIVESHAFT_PATTERN = re.compile(r'Camso_driveshaft_rear', re.IGNORECASE)
    
    # Patterns indicating 4WD (selectable) vs AWD (continuous)
    FOUR_WD_INDICATORS = ['driveModes', 'transfercaseControl', 'rangeBox', 'rangebox']
    AWD_INDICATORS = ['differential_center', 'center_differential', 'torquesplit', 'diffTorqueSplit']
    
    def __init__(self, jbeam_data: Dict[str, Any]):
        """
        Initialize extractor with parsed transfer case jbeam data.
        
        Args:
            jbeam_data: Parsed jbeam content from transfer case file
        """
        self.jbeam_data = jbeam_data
        self._has_front_driveshaft = False
        self._has_rear_driveshaft = False
        self._has_4wd_indicators = False
        self._has_awd_indicators = False
        self._analyzed = False
    
    def extract_drive_type(self) -> DriveType:
        """
        Analyze transfer case and determine drive type.
        
        Returns:
            DriveType enum value
        """
        if not self._analyzed:
            self._analyze_all_parts()
            self._analyzed = True
        
        # Determine drive type based on findings
        if self._has_front_driveshaft and self._has_rear_driveshaft:
            # Both axles driven - is it AWD or 4WD?
            if self._has_4wd_indicators:
                logger.info("Drive type: 4WD (selectable modes detected)")
                return DriveType.FOUR_WD
            else:
                logger.info("Drive type: AWD (continuous power distribution)")
                return DriveType.AWD
        elif self._has_rear_driveshaft:
            logger.info("Drive type: RWD (rear driveshaft only)")
            return DriveType.RWD
        elif self._has_front_driveshaft:
            logger.info("Drive type: FWD (front driveshaft only)")
            return DriveType.FWD
        else:
            logger.warning("Drive type: UNKNOWN (no driveshaft slots found)")
            return DriveType.UNKNOWN
    
    def get_drive_info(self) -> Dict[str, Any]:
        """
        Get detailed drive configuration info.
        
        Returns:
            Dictionary with drive analysis details
        """
        if not self._analyzed:
            self._analyze_all_parts()
            self._analyzed = True
        
        return {
            "drive_type": self.extract_drive_type().value,
            "has_front_driveshaft": self._has_front_driveshaft,
            "has_rear_driveshaft": self._has_rear_driveshaft,
            "has_4wd_indicators": self._has_4wd_indicators,
            "has_awd_indicators": self._has_awd_indicators,
        }
    
    def _analyze_all_parts(self) -> None:
        """Analyze all parts in the jbeam for driveshaft slots and drive mode indicators."""
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            self._analyze_part(part_name, part_data)
    
    def _analyze_part(self, part_name: str, part_data: Dict[str, Any]) -> None:
        """
        Analyze a single part for driveshaft slots and drive indicators.
        
        Args:
            part_name: Name of the part being analyzed
            part_data: Part definition dictionary
        """
        # Check slots section for driveshaft references
        slots_section = part_data.get("slots")
        if slots_section and isinstance(slots_section, list):
            for item in slots_section:
                if isinstance(item, list) and len(item) >= 2:
                    slot_type = str(item[0])
                    
                    if self.FRONT_DRIVESHAFT_PATTERN.search(slot_type):
                        self._has_front_driveshaft = True
                        logger.debug(f"  Found front driveshaft slot in {part_name}")
                    
                    if self.REAR_DRIVESHAFT_PATTERN.search(slot_type):
                        self._has_rear_driveshaft = True
                        logger.debug(f"  Found rear driveshaft slot in {part_name}")
        
        # Check for 4WD indicators (driveModes, rangeBox, etc.)
        self._check_4wd_indicators(part_name, part_data)
        
        # Check for AWD indicators (center differential, torque split)
        self._check_awd_indicators(part_name, part_data)
    
    def _check_4wd_indicators(self, part_name: str, part_data: Dict[str, Any]) -> None:
        """Check for 4WD-specific indicators in part data."""
        # Check for transfercaseControl or driveModes
        if "transfercaseControl" in part_data:
            self._has_4wd_indicators = True
            logger.debug(f"  Found transfercaseControl in {part_name}")
            return
        
        # Check controller section for driveModes
        controller = part_data.get("controller")
        if controller and isinstance(controller, list):
            for item in controller:
                if isinstance(item, list) and len(item) >= 1:
                    if "driveModes" in str(item):
                        self._has_4wd_indicators = True
                        logger.debug(f"  Found driveModes controller in {part_name}")
                        return
        
        # Check powertrain for rangeBox
        powertrain = part_data.get("powertrain")
        if powertrain and isinstance(powertrain, list):
            for item in powertrain:
                if isinstance(item, list) and len(item) >= 1:
                    if str(item[0]).lower() == "rangebox":
                        self._has_4wd_indicators = True
                        logger.debug(f"  Found rangeBox in powertrain of {part_name}")
                        return
    
    def _check_awd_indicators(self, part_name: str, part_data: Dict[str, Any]) -> None:
        """Check for AWD-specific indicators in part data."""
        # Check slotType for center differential
        slot_type = part_data.get("slotType", "")
        if "differential_center" in slot_type.lower():
            self._has_awd_indicators = True
            logger.debug(f"  Found center differential slotType in {part_name}")
        
        # Check for torque split variables
        if "transferCase" in part_data:
            tc_config = part_data.get("transferCase", {})
            if isinstance(tc_config, dict) and "diffTorqueSplit" in tc_config:
                self._has_awd_indicators = True
                logger.debug(f"  Found diffTorqueSplit in {part_name}")


class TargetVehicleExtractor:
    """
    Extracts mount node structure from a BeamNG target vehicle.
    
    Looks for chassis mount nodes: em1l, em1r, tra1 and optionally
    original engine cube nodes: e1l, e1r, e2l, e2r, e3l, e3r, e4l, e4r
    """
    
    # Expected BeamNG mount nodes
    BEAMNG_MOUNT_NODES = ["em1l", "em1r", "tra1"]
    
    # Expected BeamNG engine cube nodes
    BEAMNG_ENGINE_NODES = [
        "e1l", "e1r", "e2l", "e2r",
        "e3l", "e3r", "e4l", "e4r"
    ]
    
    def __init__(self, jbeam_data: Dict[str, Any]):
        """
        Initialize extractor with parsed jbeam data.
        
        Args:
            jbeam_data: Parsed jbeam content (from JBeamParser)
        """
        self.jbeam_data = jbeam_data
        self._mount_nodes: List[MountNode] = []
        self._engine_cube: Optional[EngineCube] = None
    
    def extract_mounts(self) -> List[MountNode]:
        """
        Extract engine mount nodes from target vehicle.
        
        Returns:
            List of MountNode objects for em1l, em1r, tra1
        """
        all_nodes = self._extract_all_nodes()
        
        self._mount_nodes = []
        for name in self.BEAMNG_MOUNT_NODES:
            if name in all_nodes:
                node = all_nodes[name]
                mount_type = self._classify_mount(name)
                self._mount_nodes.append(MountNode(
                    name=name,
                    position=node.position,
                    mount_type=mount_type
                ))
        
        if not self._mount_nodes:
            logger.warning("No mount nodes (em1l, em1r, tra1) found in target vehicle")
        else:
            logger.info(f"Extracted {len(self._mount_nodes)} mount nodes from target")
        
        return self._mount_nodes
    
    def extract_engine_cube(self) -> Optional[EngineCube]:
        """
        Extract existing engine cube from target vehicle (for reference).
        
        This extracts the target's original engine nodes, useful for
        understanding the expected geometry.
        
        Returns:
            EngineCube with BeamNG-pattern nodes, or None if not found
        """
        all_nodes = self._extract_all_nodes()
        
        engine_nodes = {}
        for name in self.BEAMNG_ENGINE_NODES:
            if name in all_nodes:
                engine_nodes[name] = all_nodes[name]
        
        if len(engine_nodes) < 4:
            logger.debug("Target vehicle has incomplete engine cube")
            return None
        
        self._engine_cube = EngineCube(nodes=engine_nodes, source_pattern="beamng")
        logger.info(f"Extracted {len(engine_nodes)} reference engine nodes from target")
        
        return self._engine_cube
    
    def _extract_all_nodes(self) -> Dict[str, EngineNode]:
        """Extract all nodes from jbeam data."""
        result = {}
        
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            nodes_section = part_data.get("nodes")
            if not nodes_section or not isinstance(nodes_section, list):
                continue
            
            for item in nodes_section:
                if not isinstance(item, list) or len(item) < 4:
                    continue
                
                name = item[0]
                if name == "id" or not isinstance(name, str):
                    continue
                
                # Clean up node name - strip trailing commas and whitespace
                name = name.strip().rstrip(',').strip()
                
                try:
                    x = float(item[1])
                    y = float(item[2])
                    z = float(item[3])
                except (ValueError, TypeError):
                    continue
                
                props = {}
                if len(item) > 4 and isinstance(item[4], dict):
                    props = item[4]
                
                result[name] = EngineNode(
                    name=name,
                    position=Vec3(x, y, z),
                    node_properties=props
                )
        
        return result
    
    def _classify_mount(self, name: str) -> str:
        """Classify mount node type from name."""
        if "em" in name:
            if "l" in name:
                return "engine_left"
            elif "r" in name:
                return "engine_right"
        elif "tra" in name:
            return "transmission"
        return "unknown"
    
    def extract_mount_beam_properties(self) -> MountBeamProperties:
        """
        Extract beam properties for mount connections from target vehicle.
        
        Searches the beams section for connections between em* nodes and e*
        engine cube nodes, extracting the spring/damp/deform/strength values.
        
        Returns:
            MountBeamProperties with extracted or default values
        """
        # Default properties (from pickup reference)
        props = MountBeamProperties()
        
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            beams_section = part_data.get("beams")
            if not beams_section or not isinstance(beams_section, list):
                continue
            
            # Track current beam properties as we iterate
            current_props = {}
            found_mount_beams = False
            
            for item in beams_section:
                # Property modifier row (dict)
                if isinstance(item, dict):
                    # Update tracked properties
                    if "beamSpring" in item:
                        current_props["beamSpring"] = item["beamSpring"]
                    if "beamDamp" in item:
                        current_props["beamDamp"] = item["beamDamp"]
                    if "beamDeform" in item:
                        current_props["beamDeform"] = item["beamDeform"]
                    if "beamStrength" in item:
                        current_props["beamStrength"] = item["beamStrength"]
                    continue
                
                # Beam connection row (list)
                if isinstance(item, list) and len(item) >= 2:
                    id1 = str(item[0]).strip().rstrip(':').rstrip(',')
                    id2 = str(item[1]).strip().rstrip(':').rstrip(',')
                    
                    # Check if this is an em* to e* connection
                    is_mount_beam = False
                    if id1.startswith("em") and id2.startswith("e") and not id2.startswith("em"):
                        is_mount_beam = True
                    elif id2.startswith("em") and id1.startswith("e") and not id1.startswith("em"):
                        is_mount_beam = True
                    
                    if is_mount_beam and not found_mount_beams:
                        # Capture properties at first mount beam encounter
                        found_mount_beams = True
                        if "beamSpring" in current_props:
                            props.beam_spring = current_props["beamSpring"]
                        if "beamDamp" in current_props:
                            props.beam_damp = current_props["beamDamp"]
                        if "beamDeform" in current_props:
                            props.beam_deform = current_props["beamDeform"]
                        if "beamStrength" in current_props:
                            props.beam_strength = current_props["beamStrength"]
                        
                        logger.info(f"Extracted mount beam properties: spring={props.beam_spring}, damp={props.beam_damp}")
                        break  # Found what we need
            
            if found_mount_beams:
                break
        
        return props
    
    def extract_all_mount_nodes(self) -> List[MountNode]:
        """
        Extract ALL engine mount nodes from target vehicle using flexible pattern.
        
        Looks for nodes matching patterns: em1l, em1r, em2l, em2r, etc.
        More flexible than extract_mounts() which uses a fixed list.
        
        Returns:
            List of MountNode objects for all em* nodes found
        """
        import re
        
        all_nodes = self._extract_all_nodes()
        mount_pattern = re.compile(r'^em\d+[lr]$', re.IGNORECASE)
        
        mount_nodes = []
        for name, node in all_nodes.items():
            if mount_pattern.match(name):
                mount_type = self._classify_mount(name)
                mount_nodes.append(MountNode(
                    name=name,
                    position=node.position,
                    mount_type=mount_type
                ))
        
        # Sort by name for consistent ordering (em1l, em1r, em2l, em2r, ...)
        mount_nodes.sort(key=lambda m: m.name)
        
        if mount_nodes:
            logger.info(f"Extracted {len(mount_nodes)} mount nodes: {[m.name for m in mount_nodes]}")
        else:
            logger.warning("No mount nodes (em*l, em*r pattern) found in target vehicle")
        
        return mount_nodes
    
    def extract_transmission_structure(self, slot_type_filter: Optional[str] = None) -> TransmissionStructure:
        """
        Extract transmission node structure from target vehicle.
        
        Looks for transmission nodes (tra1, tra2, tra3, etc.) and their
        beam connections to engine nodes.
        
        Args:
            slot_type_filter: If provided, only process parts whose slotType
                              contains this substring (case-insensitive).
                              Use "transmission" for gearbox parts only.
                              Use "transfer_case" for transfer case parts only.
                              If None, processes all parts (legacy behavior).
        
        Returns:
            TransmissionStructure with nodes, beam properties, and connections
        """
        import re
        
        trans_nodes = []
        beam_props = None
        connected_engine_nodes = []
        
        # Pattern for transmission nodes: tra1, tra2, tra3, etc.
        trans_pattern = re.compile(r'^tra\d+$', re.IGNORECASE)
        
        for part_name, part_data in self.jbeam_data.items():
            if not isinstance(part_data, dict):
                continue
            
            # === SlotType Filter ===
            if slot_type_filter:
                part_slot_type = part_data.get("slotType", "")
                if slot_type_filter.lower() not in part_slot_type.lower():
                    continue  # Skip parts that don't match the filter
            
            # Extract transmission nodes
            nodes_section = part_data.get("nodes")
            if nodes_section and isinstance(nodes_section, list):
                current_weight = 1.0
                current_group = ""
                
                for item in nodes_section:
                    if isinstance(item, dict):
                        if "nodeWeight" in item:
                            current_weight = float(item["nodeWeight"])
                        if "group" in item:
                            current_group = item["group"]
                    elif isinstance(item, list) and len(item) >= 4:
                        name = item[0]
                        if not isinstance(name, str) or name == "id":
                            continue
                        
                        name = name.strip().rstrip(',')
                        
                        if trans_pattern.match(name):
                            try:
                                x = float(item[1])
                                y = float(item[2])
                                z = float(item[3])
                                
                                # Check for inline weight override
                                if len(item) > 4 and isinstance(item[4], dict):
                                    node_weight = item[4].get("nodeWeight", current_weight)
                                else:
                                    node_weight = current_weight
                                
                                trans_nodes.append(TransmissionNode(
                                    name=name,
                                    position=Vec3(x, y, z),
                                    weight=float(node_weight),
                                    group=current_group
                                ))
                            except (ValueError, TypeError):
                                continue
            
            # Extract beam properties for transmission-to-engine connections
            beams_section = part_data.get("beams")
            if beams_section and isinstance(beams_section, list):
                current_props = {}
                
                for item in beams_section:
                    if isinstance(item, dict):
                        current_props.update(item)
                    elif isinstance(item, list) and len(item) >= 2:
                        id1 = str(item[0]).strip().rstrip(':').rstrip(',')
                        id2 = str(item[1]).strip().rstrip(':').rstrip(',')
                        
                        if id1 == "id1" or id2 == "id2":
                            continue
                        
                        # Check if this is a tra* to e* connection
                        is_trans_beam = (
                            (trans_pattern.match(id1) and id2.startswith("e") and not id2.startswith("em")) or
                            (trans_pattern.match(id2) and id1.startswith("e") and not id1.startswith("em"))
                        )
                        
                        if is_trans_beam:
                            # Extract engine node name
                            engine_node = id2 if trans_pattern.match(id1) else id1
                            if engine_node not in connected_engine_nodes:
                                connected_engine_nodes.append(engine_node)
                            
                            # Extract beam properties (first match wins)
                            if beam_props is None:
                                beam_props = BeamProperties(
                                    beam_spring=current_props.get("beamSpring", 18800940),
                                    beam_damp=current_props.get("beamDamp", 470),
                                    beam_deform=current_props.get("beamDeform", 175000),
                                    beam_strength=current_props.get("beamStrength", "FLT_MAX")
                                )
        
        # Sort nodes by name
        trans_nodes.sort(key=lambda n: n.name)
        
        filter_desc = f" (filter: {slot_type_filter})" if slot_type_filter else ""
        if trans_nodes:
            logger.info(f"Extracted {len(trans_nodes)} transmission nodes{filter_desc}: {[n.name for n in trans_nodes]}")
            logger.info(f"Transmission connects to engine nodes: {connected_engine_nodes}")
        else:
            logger.warning(f"No transmission nodes (tra*) found in target vehicle{filter_desc}")
        
        return TransmissionStructure(
            nodes=trans_nodes,
            beam_properties=beam_props,
            connected_engine_nodes=connected_engine_nodes
        )


# ============================================================================
# MAIN SOLVER CLASS
# ============================================================================

class MountSolver:
    """
    Main solver class for transplant mount adaptation.
    
    Takes donor engine geometry and target vehicle mount structure,
    computes the translation needed to align them, and produces
    translated node positions for output.
    
    Usage:
        solver = MountSolver(
            donor_cube=extracted_donor_cube,
            target_mounts=extracted_target_mounts,
            target_reference_cube=extracted_target_engine,  # Optional
            params=swap_parameters
        )
        result = solver.solve()
        
        if result.success:
            jbeam_nodes = result.to_jbeam_nodes()
    """
    
    def __init__(
        self,
        donor_cube: EngineCube,
        target_mounts: List[MountNode],
        target_reference_cube: Optional[EngineCube] = None,
        params: Optional[SwapParameters] = None
    ):
        """
        Initialize solver with geometry and parameters.
        
        Args:
            donor_cube: Engine cube from Camso donor
            target_mounts: Mount nodes from BeamNG target
            target_reference_cube: Target's original engine cube (for reference)
            params: User configuration (defaults if None)
        """
        self.donor_cube = donor_cube
        self.target_mounts = target_mounts
        self.target_reference_cube = target_reference_cube
        self.params = params or SwapParameters.defaults()
        
        # Working copies (modified during solve)
        self._working_cube: Optional[EngineCube] = None
        self._working_mounts: List[MountNode] = []
    
    def solve(self) -> SolverResult:
        """
        Execute the mounting solver algorithm.
        
        Algorithm Phases:
            1. Compute flywheel plane alignment (Y-axis translation)
            2. Compute floor plane alignment (Z-axis translation)
            3. Center laterally (X-axis, typically 0)
            4. Apply user offsets
            5. Check for mount interference
            6. Apply resolution if needed (shrink or expand)
        
        Returns:
            SolverResult with translated geometry and status
        """
        result = SolverResult(success=False)
        
        try:
            # Phase 1: Initialize working copy
            self._working_cube = self.donor_cube
            self._working_mounts = [m for m in self.target_mounts]  # Copy
            
            # Phase 2: Compute flywheel plane alignment (Y-axis)
            y_offset = self._compute_flywheel_alignment()
            logger.debug(f"Flywheel alignment Y offset: {y_offset:.4f}")
            
            # Phase 3: Compute floor plane alignment (Z-axis)
            z_offset = self._compute_floor_alignment()
            logger.debug(f"Floor alignment Z offset: {z_offset:.4f}")
            
            # Phase 4: Lateral centering (X-axis, typically 0)
            x_offset = self._compute_lateral_alignment()
            logger.debug(f"Lateral alignment X offset: {x_offset:.4f}")
            
            # Combine base translation
            base_translation = Vec3(x_offset, y_offset, z_offset)
            
            # Phase 5: Apply user offsets
            user_offset = self.params.get_user_offset()
            total_translation = base_translation + user_offset
            logger.info(f"Total translation (incl. user offset): {total_translation}")
            
            # Apply translation to working cube
            self._working_cube = self._working_cube.translated(total_translation)
            
            # Convert to BeamNG naming convention
            self._working_cube = self._working_cube.with_beamng_names()
            
            # Phase 6: Check interference
            interference = self._check_interference()
            if interference:
                result.warnings.append(f"Detected {len(interference)} mount node interferences")
                
                # Apply resolution based on params
                scale = self._resolve_interference(interference)
                result.scale_applied = scale
            
            # Compute mesh offset if requested
            if self.params.fix_mesh_offset:
                result.mesh_offset = self._compute_mesh_offset()
            
            # Build successful result
            result.success = True
            result.engine_cube = self._working_cube
            result.mount_nodes = self._working_mounts
            result.translation = total_translation
            
            logger.info(f"Solve complete: {result.get_summary()}")
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Solve failed: {e}")
        
        return result
    
    def _compute_flywheel_alignment(self) -> float:
        """
        Compute Y offset to align donor flywheel plane with target.
        
        Returns:
            Y translation value (positive = rearward)
        """
        # Get donor flywheel plane centroid
        donor_flywheel_nodes = self.donor_cube.get_flywheel_plane_nodes()
        if not donor_flywheel_nodes:
            logger.warning("No flywheel plane nodes found in donor")
            return 0.0
        
        donor_flywheel_y = self.donor_cube.get_plane_centroid(donor_flywheel_nodes).y
        
        # If we have target reference cube, align to its flywheel
        if self.target_reference_cube:
            target_flywheel_nodes = self.target_reference_cube.get_flywheel_plane_nodes()
            if target_flywheel_nodes:
                target_flywheel_y = self.target_reference_cube.get_plane_centroid(
                    target_flywheel_nodes
                ).y
                return target_flywheel_y - donor_flywheel_y
        
        # Otherwise, use transmission mount position as reference
        tra_mount = next((m for m in self.target_mounts if m.mount_type == "transmission"), None)
        if tra_mount:
            # Position flywheel just forward of transmission mount
            return tra_mount.position.y - 0.1 - donor_flywheel_y
        
        logger.warning("No flywheel alignment reference available")
        return 0.0
    
    def _compute_floor_alignment(self) -> float:
        """
        Compute Z offset to align donor floor plane with target.
        
        Returns:
            Z translation value (positive = upward)
        """
        # Get donor floor plane centroid
        donor_floor_nodes = self.donor_cube.get_floor_plane_nodes()
        if not donor_floor_nodes:
            logger.warning("No floor plane nodes found in donor")
            return 0.0
        
        donor_floor_z = self.donor_cube.get_plane_centroid(donor_floor_nodes).z
        
        # If we have target reference cube, align to its floor
        if self.target_reference_cube:
            target_floor_nodes = self.target_reference_cube.get_floor_plane_nodes()
            if target_floor_nodes:
                target_floor_z = self.target_reference_cube.get_plane_centroid(
                    target_floor_nodes
                ).z
                return target_floor_z - donor_floor_z
        
        # Otherwise, use engine mount nodes as reference
        engine_mounts = [m for m in self.target_mounts if "engine" in m.mount_type]
        if engine_mounts:
            # Position floor slightly below engine mounts
            mount_avg_z = sum(m.position.z for m in engine_mounts) / len(engine_mounts)
            return (mount_avg_z - 0.05) - donor_floor_z
        
        logger.warning("No floor alignment reference available")
        return 0.0
    
    def _compute_lateral_alignment(self) -> float:
        """
        Compute X offset to center engine laterally.
        
        Returns:
            X translation value (positive = rightward)
        """
        # Get donor center X
        donor_center_x = self.donor_cube.centroid.x
        
        # Target should be centered (X = 0 for most vehicles)
        # Or use target reference cube if available
        if self.target_reference_cube:
            target_center_x = self.target_reference_cube.centroid.x
            return target_center_x - donor_center_x
        
        # Center at X = 0
        return -donor_center_x
    
    def _check_interference(self) -> List[MountNode]:
        """
        Check if any mount nodes are inside the engine cube.
        
        Returns:
            List of mount nodes that have interference
        """
        if not self._working_cube:
            return []
        
        interference = []
        clearance = self.params.min_mount_clearance_m
        
        for mount in self._working_mounts:
            if self._working_cube.contains_point(mount.position, margin=-clearance):
                interference.append(mount)
                logger.debug(f"Interference detected: {mount.name} at {mount.position}")
        
        return interference
    
    def _resolve_interference(self, interference: List[MountNode]) -> float:
        """
        Apply interference resolution based on parameters.
        
        Args:
            interference: List of conflicting mount nodes
            
        Returns:
            Scale factor applied (1.0 if no scaling)
        """
        if self.params.shrink_or_expand == InterferenceResolution.NONE:
            logger.warning("Interference detected but resolution set to NONE")
            return 1.0
        
        if self.params.shrink_or_expand == InterferenceResolution.SHRINK_ENGINE_BLOCK:
            return self._shrink_engine_to_clear(interference)
        
        if self.params.shrink_or_expand == InterferenceResolution.EXPAND_ENGINE_MOUNTS:
            self._expand_mounts_to_clear(interference)
            return 1.0
        
        return 1.0
    
    def _shrink_engine_to_clear(self, interference: List[MountNode]) -> float:
        """
        Shrink engine cube until all mounts are clear.
        
        Returns:
            Final scale factor applied
        """
        max_shrink = self.params.max_shrink_percent / 100.0
        min_scale = 1.0 - max_shrink
        clearance = self.params.min_mount_clearance_m
        
        # Binary search for appropriate scale
        scale = 1.0
        step = 0.05
        
        while scale > min_scale:
            test_cube = self._working_cube.scaled_from_centroid(scale)
            clear = True
            
            for mount in interference:
                if test_cube.contains_point(mount.position, margin=-clearance):
                    clear = False
                    break
            
            if clear:
                self._working_cube = test_cube
                logger.info(f"Shrunk engine cube to {scale:.2%} to clear mounts")
                return scale
            
            scale -= step
        
        # Couldn't resolve within limits
        logger.warning(f"Could not clear interference within {max_shrink:.0%} shrink limit")
        self._working_cube = self._working_cube.scaled_from_centroid(min_scale)
        return min_scale
    
    def _expand_mounts_to_clear(self, interference: List[MountNode]) -> None:
        """
        Move conflicting mounts outward until clear.
        """
        if not self._working_cube:
            return
        
        max_expansion = self.params.max_mount_expansion_m
        clearance = self.params.min_mount_clearance_m
        center = self._working_cube.centroid
        
        for i, mount in enumerate(self._working_mounts):
            if mount not in interference:
                continue
            
            # Direction away from center
            direction = (mount.position - center).normalized()
            
            # Move outward until clear
            distance = 0.01
            while distance <= max_expansion:
                test_pos = mount.position + (direction * distance)
                if not self._working_cube.contains_point(test_pos, margin=-clearance):
                    self._working_mounts[i] = MountNode(
                        name=mount.name,
                        position=test_pos,
                        mount_type=mount.mount_type
                    )
                    logger.info(f"Expanded mount {mount.name} by {distance:.3f}m")
                    break
                distance += 0.01
            else:
                logger.warning(f"Could not clear mount {mount.name} within expansion limit")
    
    def _compute_mesh_offset(self) -> Vec3:
        """
        Compute visual mesh offset correction.
        
        Returns:
            Offset to apply to engine mesh flexbody position
        """
        # This would require analyzing the original Camso mesh position
        # For now, return zero (no correction)
        logger.debug("Mesh offset computation not fully implemented")
        return Vec3(0, 0, 0)


# ============================================================================
# PUBLIC API FUNCTIONS
# ============================================================================

def solve_engine_mount(
    donor_jbeam: Dict[str, Any],
    target_jbeam: Dict[str, Any],
    params_file: Optional[Path] = None
) -> SolverResult:
    """
    High-level function to solve engine mounting.
    
    Args:
        donor_jbeam: Parsed jbeam data for Camso donor engine
        target_jbeam: Parsed jbeam data for BeamNG target vehicle
        params_file: Path to swap_parameters.json (optional)
        
    Returns:
        SolverResult with translated geometry, mount nodes, and beam properties
    """
    # Load parameters
    if params_file and params_file.exists():
        params = SwapParameters.from_file(params_file)
    else:
        params = SwapParameters.defaults()
    
    # Extract donor geometry
    donor_extractor = DonorEngineExtractor(donor_jbeam)
    donor_cube = donor_extractor.extract()
    
    # Extract source engine beam properties (for engine cube beams)
    source_engine_beam_props = donor_extractor.extract_engine_beam_properties()
    
    # Extract target geometry
    target_extractor = TargetVehicleExtractor(target_jbeam)
    target_mounts = target_extractor.extract_mounts()
    target_reference = target_extractor.extract_engine_cube()
    
    # Extract mount nodes (flexible pattern: em1l, em1r, em2l, etc.)
    mount_nodes = target_extractor.extract_all_mount_nodes()
    
    # Extract beam properties for mount connections
    mount_beam_props = target_extractor.extract_mount_beam_properties()
    
    # Extract transmission structure from target vehicle
    transmission_structure = target_extractor.extract_transmission_structure()
    
    # Extract Camso gearbox total weight for redistribution
    camso_gearbox_weight = donor_extractor.extract_gearbox_total_weight()
    
    # Solve
    solver = MountSolver(
        donor_cube=donor_cube,
        target_mounts=target_mounts,
        target_reference_cube=target_reference,
        params=params
    )
    
    result = solver.solve()
    
    # Augment result with mount data from target vehicle
    result.mount_nodes = mount_nodes
    result.mount_beam_properties = mount_beam_props
    result.source_engine_beam_properties = source_engine_beam_props
    result.transmission_structure = transmission_structure
    result.camso_gearbox_weight = camso_gearbox_weight
    
    return result


def generate_engine_beams(cube: EngineCube) -> List[List[str]]:
    """
    Generate beam connections for an engine cube.
    
    Creates the standard beam structure connecting the 8 corners
    of an engine cube for physics simulation.
    
    Args:
        cube: EngineCube with BeamNG-pattern node names
        
    Returns:
        List of beam arrays: [["id1:", "id2:"], ["e1l", "e1r"], ...]
    """
    beams = [["id1:", "id2:"]]  # Header
    
    # Top face (e1l-e1r-e3r-e3l)
    beams.append(["e1l", "e1r"])
    beams.append(["e1r", "e3r"])
    beams.append(["e3r", "e3l"])
    beams.append(["e3l", "e1l"])
    
    # Bottom face (e2l-e2r-e4r-e4l)
    beams.append(["e2l", "e2r"])
    beams.append(["e2r", "e4r"])
    beams.append(["e4r", "e4l"])
    beams.append(["e4l", "e2l"])
    
    # Vertical edges
    beams.append(["e1l", "e2l"])
    beams.append(["e1r", "e2r"])
    beams.append(["e3l", "e4l"])
    beams.append(["e3r", "e4r"])
    
    # Cross braces (for rigidity)
    beams.append(["e1l", "e3r"])
    beams.append(["e1r", "e3l"])
    beams.append(["e2l", "e4r"])
    beams.append(["e2r", "e4l"])
    
    return beams


def generate_mount_beams(mount_nodes: List[MountNode], engine_cube: EngineCube) -> List[List[str]]:
    """
    Generate beam connections between mount nodes and engine cube nodes.
    
    For 2 mount nodes (standard case): each mount connects to all 8 engine nodes.
    For more mount nodes: same pattern, but future enhancement may add
    optimized connection patterns.
    
    Args:
        mount_nodes: List of MountNode objects (em1l, em1r, etc.)
        engine_cube: EngineCube with BeamNG-pattern node names (e1l-e4r)
        
    Returns:
        List of beam arrays: [["em1r", "e1l"], ["em1r", "e1r"], ...]
    """
    beams = []
    
    # Get sorted list of engine node names
    engine_node_names = sorted(engine_cube.nodes.keys())
    
    # For each mount node, create connections to all engine nodes
    for mount in mount_nodes:
        for engine_name in engine_node_names:
            beams.append([mount.name, engine_name])
    
    if beams:
        logger.info(f"Generated {len(beams)} mount-to-engine beams for {len(mount_nodes)} mount nodes")
    
    return beams


def generate_transmission_beams(
    trans_nodes: List[TransmissionNode],
    connected_engine_nodes: List[str]
) -> List[List[str]]:
    """
    Generate beam connections between transmission nodes and engine nodes.
    
    Uses the same connection pattern as the target vehicle:
    each transmission node connects to the same engine nodes.
    
    Args:
        trans_nodes: List of TransmissionNode objects (tra1, tra2, etc.)
        connected_engine_nodes: Engine node names from target vehicle (e1r, e3r, etc.)
        
    Returns:
        List of beam arrays: [["tra1", "e1r"], ["tra1", "e3r"], ...]
    """
    beams = []
    
    for trans in trans_nodes:
        for engine_name in connected_engine_nodes:
            beams.append([trans.name, engine_name])
    
    if beams:
        logger.info(f"Generated {len(beams)} transmission-to-engine beams for {len(trans_nodes)} trans nodes")
    
    return beams


# ============================================================================
# MODULE TESTING
# ============================================================================

if __name__ == "__main__":
    """Run basic module tests when executed directly."""
    import sys
    
    logging.basicConfig(level=logging.DEBUG)
    
    print("=" * 60)
    print("Transplant Mounting Solver - Module Self-Test")
    print("=" * 60)
    
    # Test Vec3
    print("\n[Test: Vec3 operations]")
    v1 = Vec3(1.0, 2.0, 3.0)
    v2 = Vec3(0.5, 0.5, 0.5)
    print(f"  v1 = {v1}")
    print(f"  v2 = {v2}")
    print(f"  v1 + v2 = {v1 + v2}")
    print(f"  v1 - v2 = {v1 - v2}")
    print(f"  v1 * 2 = {v1 * 2}")
    print(f"  v1.magnitude() = {v1.magnitude():.4f}")
    
    # Test EngineCube
    print("\n[Test: EngineCube centroid]")
    test_nodes = {
        "engine0": EngineNode("engine0", Vec3(0.3, -0.5, 0.2)),
        "engine1": EngineNode("engine1", Vec3(-0.3, -0.5, 0.2)),
        "engine2": EngineNode("engine2", Vec3(-0.3, -0.5, 0.6)),
        "engine3": EngineNode("engine3", Vec3(0.3, -0.5, 0.6)),
        "engine4": EngineNode("engine4", Vec3(0.3, 0.3, 0.2)),
        "engine5": EngineNode("engine5", Vec3(-0.3, 0.3, 0.2)),
        "engine6": EngineNode("engine6", Vec3(-0.3, 0.3, 0.6)),
        "engine7": EngineNode("engine7", Vec3(0.3, 0.3, 0.6)),
    }
    cube = EngineCube(nodes=test_nodes, source_pattern="camso")
    print(f"  Centroid: {cube.centroid}")
    print(f"  AABB: {cube.get_aabb()}")
    
    # Test naming conversion
    print("\n[Test: Camso -> BeamNG naming]")
    beamng_cube = cube.with_beamng_names()
    print(f"  Original nodes: {list(cube.nodes.keys())}")
    print(f"  Converted nodes: {list(beamng_cube.nodes.keys())}")
    
    # Test interference check
    print("\n[Test: Interference detection]")
    inside_point = Vec3(0.0, 0.0, 0.4)
    outside_point = Vec3(1.0, 1.0, 1.0)
    print(f"  {inside_point} inside cube: {cube.contains_point(inside_point)}")
    print(f"  {outside_point} inside cube: {cube.contains_point(outside_point)}")
    
    # Test SwapParameters defaults
    print("\n[Test: SwapParameters defaults]")
    params = SwapParameters.defaults()
    print(f"  fore_aft_offset: {params.fore_aft_offset}")
    print(f"  shrink_or_expand: {params.shrink_or_expand}")
    
    print("\n" + "=" * 60)
    print("Self-test complete. Module loaded successfully.")
    print("=" * 60)
