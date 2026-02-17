"""
Slot Graph - Unified Slot Dependency Management for BeamNG Engine Swaps

This module provides a graph-based approach to managing slot dependencies,
transformations, and packaging for engine swap mods. It serves as the single
source of truth for all slot state during the adaptation process.

Architecture:
    - SlotNode: Individual slot in the dependency graph
    - SlotGraph: Complete graph with indices and transformation tracking
    - SlotGraphBuilder: Constructs graph from jbeam files
    - SlotTransformationPlanner: Plans transformations based on rules
    - SlotTransformationExecutor: Applies transformations to graph
    - SlotAwareJBeamWriter: Generates output using graph state
    - SlotAwareManifestGenerator: Creates packaging manifest from graph

Usage:
    # Build graph from donor files
    builder = SlotGraphBuilder("pickup")
    builder.add_donor_file(engine_path)
    builder.add_donor_file(transmission_path)
    graph = builder.build()
    
    # Plan and execute transformations
    rules = SlotDispositionRules(config)
    planner = SlotTransformationPlanner(graph, "pickup", rules)
    planner.plan()
    
    executor = SlotTransformationExecutor(graph)
    executor.execute_all()
    
    # Generate outputs
    writer = SlotAwareJBeamWriter(graph)
    manifest_gen = SlotAwareManifestGenerator(graph)

Author: Engine Transplant Utility
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple, Union, runtime_checkable

logger = logging.getLogger(__name__)


# =============================================================================
# Parser Protocol (avoids circular import with engineswap.py)
# =============================================================================

@runtime_checkable
class JBeamParserProtocol(Protocol):
    """
    Protocol defining the interface required for JBeam parsing.
    
    This allows slot_graph.py to work with any parser implementation
    without creating circular imports with engineswap.py.
    
    Usage:
        # In engineswap.py integration:
        from slot_graph import SlotGraphBuilder
        builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
        
        # Or with a custom parser:
        class MyParser:
            @staticmethod
            def parse_jbeam(path: Path) -> Optional[Dict]: ...
        builder = SlotGraphBuilder("pickup", jbeam_parser=MyParser)
    """
    @staticmethod
    def parse_jbeam(path: Path) -> Optional[Dict[str, Any]]:
        """Parse a .jbeam file and return its content as dict, or None on failure."""
        ...


# =============================================================================
# Custom Exceptions
# =============================================================================

class SlotGraphError(Exception):
    """Base exception for slot graph operations."""
    pass


class ParserNotAvailableError(SlotGraphError):
    """Raised when JBeam parser is not configured."""
    def __init__(self, message: str = "JBeam parser not available - inject via SlotGraphBuilder constructor"):
        super().__init__(message)


class InvalidStateTransitionError(SlotGraphError):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, slot_type: str, from_state: 'SlotState', to_state: 'SlotState'):
        super().__init__(
            f"Invalid state transition for '{slot_type}': {from_state.value} -> {to_state.value}"
        )
        self.slot_type = slot_type
        self.from_state = from_state
        self.to_state = to_state


class SlotNotFoundError(SlotGraphError):
    """Raised when a required slot is not found in the graph."""
    def __init__(self, slot_type: str):
        super().__init__(f"Slot not found in graph: '{slot_type}'")
        self.slot_type = slot_type


class MalformedJBeamError(SlotGraphError):
    """Raised when JBeam data is malformed."""
    def __init__(self, file_path: Path, reason: str):
        super().__init__(f"Malformed JBeam in {file_path.name}: {reason}")
        self.file_path = file_path
        self.reason = reason


# =============================================================================
# Slot Suffix Utilities
# =============================================================================

def extract_slot_suffix(slot_identifier: str) -> Tuple[str, Optional[str]]:
    """
    Extract base slot type and dynamic suffix from a slot identifier.
    
    Camso/Automation slots follow the pattern: Base_Slot_Type_suffix
    where suffix is typically a hash like 'ec8ba', '3813e', etc.
    
    This enables suffix-agnostic matching for slot rules.
    
    Args:
        slot_identifier: Full slot type or part name (e.g., "Camso_engine_structure_ec8ba")
        
    Returns:
        Tuple of (base_type, suffix) where suffix is None if no suffix found.
        Base type has trailing underscore stripped if suffix was extracted.
        
    Examples:
        >>> extract_slot_suffix("Camso_engine_structure_ec8ba")
        ("Camso_engine_structure", "ec8ba")
        >>> extract_slot_suffix("Camso_Engine")
        ("Camso_Engine", None)
        >>> extract_slot_suffix("Camso_Intake_3813e")
        ("Camso_Intake", "3813e")
    """
    # Common suffix patterns: alphanumeric 4-8 chars at end after underscore
    # Match patterns like: _ec8ba, _3813e, _a1b2c3
    match = re.match(r'^(.+?)_([a-zA-Z0-9]{4,8})$', slot_identifier)
    if match:
        return match.group(1), match.group(2)
    return slot_identifier, None


def apply_slot_suffix(base_type: str, suffix: Optional[str]) -> str:
    """
    Apply a suffix to a base slot type/part name.
    
    Args:
        base_type: Base slot type (e.g., "Camso_engine_mesh")
        suffix: Optional suffix to append (e.g., "ec8ba")
        
    Returns:
        Combined identifier (e.g., "Camso_engine_mesh_ec8ba")
        
    Examples:
        >>> apply_slot_suffix("Camso_engine_mesh", "ec8ba")
        "Camso_engine_mesh_ec8ba"
        >>> apply_slot_suffix("Camso_Engine", None)
        "Camso_Engine"
    """
    if suffix:
        return f"{base_type}_{suffix}"
    return base_type


def match_slot_base(slot_type: str, pattern_base: str) -> bool:
    """
    Check if a slot type matches a base pattern (suffix-agnostic).
    
    Args:
        slot_type: Full slot type to check (e.g., "Camso_engine_structure_ec8ba")
        pattern_base: Base pattern to match (e.g., "Camso_engine_structure")
        
    Returns:
        True if slot_type starts with pattern_base (with or without suffix)
    """
    base, _ = extract_slot_suffix(slot_type)
    return base.lower() == pattern_base.lower() or slot_type.lower() == pattern_base.lower()


# =============================================================================
# Enums
# =============================================================================

class SlotState(Enum):
    """Lifecycle state of a slot node in the graph."""
    ORIGINAL = "original"       # As parsed from donor file
    PLANNED = "planned"         # Transformation planned but not yet applied
    TRANSFORMED = "transformed" # Transformation has been applied
    VALIDATED = "validated"     # Slot chain has been validated
    PRUNED = "pruned"          # Marked for removal from output


class AssetRole(Enum):
    """
    Defines whether a slot/file is a source for extraction or a target for export.
    
    This distinguishes between files that are:
    - SOURCE: Loaded for extraction operations only (e.g., engine_structure.jbeam)
             These files are NOT included in the export manifest.
    - TARGET: Generated/adapted files that ARE included in the export.
    - PRESERVE: Original mod files copied as-is to the export.
    - INTERNAL: Intermediate processing artifacts, never exported.
    
    Example:
        - camso_engine_structure_ec8ba.jbeam -> SOURCE (extraction only)
        - pickup_camso_engine_3813e_adapted.jbeam -> TARGET (generated, exported)
        - camso_engine_3813e.jbeam -> PRESERVE (original, copied to export)
    """
    SOURCE = "source"           # Extraction source, NOT exported
    TARGET = "target"           # Generated/adapted, IS exported
    PRESERVE = "preserve"       # Original file, copied as-is to export
    INTERNAL = "internal"       # Processing artifact, never exported


# Valid state transitions (from_state -> [allowed_to_states])
# PRUNED is a terminal state reachable from any non-validated state
VALID_STATE_TRANSITIONS: Dict[SlotState, Set[SlotState]] = {
    SlotState.ORIGINAL: {SlotState.PLANNED, SlotState.PRUNED},
    SlotState.PLANNED: {SlotState.TRANSFORMED, SlotState.PRUNED, SlotState.VALIDATED},
    SlotState.TRANSFORMED: {SlotState.VALIDATED, SlotState.PRUNED},
    SlotState.VALIDATED: set(),  # Terminal (success) state
    SlotState.PRUNED: set(),     # Terminal (removed) state
}


class SlotDisposition(Enum):
    """
    What action should be taken for a slot during adaptation.
    
    Determines how each slot is handled when generating adapted output.
    """
    PRESERVE = "preserve"       # Keep slot as-is (donor ecosystem slots)
    ADAPT = "adapt"            # Rename slot_type AND update default to target vehicle
    INJECT = "inject"          # New slot not present in donor (e.g., enginemounts)
    PRUNE = "prune"            # Remove slot entirely (unwanted features)
    REMAP_DEFAULT = "remap"    # Keep slot_type unchanged, only update default value


class TransformOp(Enum):
    """Types of slot transformation operations."""
    RENAME_SLOT_TYPE = "rename_slot_type"       # Change slot type identifier
    REMAP_DEFAULT = "remap_default"             # Change default part name
    INJECT_SLOT = "inject_slot"                 # Add new slot entry
    REMOVE_SLOT = "remove_slot"                 # Remove single slot
    PRUNE_SUBTREE = "prune_subtree"            # Recursive removal of slot and children
    ADD_OPTIONS = "add_options"                 # Add/modify slot options dict
    UPDATE_DESCRIPTION = "update_description"   # Change slot description


# =============================================================================
# Core Data Structures
# =============================================================================

@dataclass
class SlotTransformation:
    """
    Record of a single transformation operation.
    
    Transformations are planned first, then executed. This provides
    full traceability of what changed and why.
    """
    operation: TransformOp
    target_slot_type: str
    
    # Operation-specific data
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    
    # Traceability
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    applied: bool = False
    
    def __repr__(self) -> str:
        status = "✓" if self.applied else "○"
        return f"{status} {self.operation.value}: {self.target_slot_type} ({self.old_value} -> {self.new_value})"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict (handles datetime)."""
        return {
            "operation": self.operation.value,
            "target_slot_type": self.target_slot_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "options": self.options,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "applied": self.applied,
        }


@dataclass
class SlotNode:
    """
    Represents a single slot in the dependency graph.
    
    A SlotNode tracks both the original state (as parsed from donor files)
    and the transformed state (after adaptation). It maintains relationships
    to parent and child slots, forming a tree structure.
    
    Attributes:
        slot_type: Current slot type identifier (may be transformed)
        original_slot_type: Original slot type from donor file
        default_part: Current default part name (may be transformed)
        original_default: Original default from donor file
        source_file: Path to jbeam file that defines this slot
        parent_part: Name of part that contains this slot definition
        description: Human-readable slot description
        options: Slot options dict (e.g., {"coreSlot": true})
        children: Child slots (slot_type -> SlotNode)
        parent: Parent slot node (None for root)
        state: Current lifecycle state
        disposition: What action to take during adaptation
        transformation_history: List of transformations applied to this node
    """
    # Identity
    slot_type: str
    original_slot_type: str
    
    # Default value (what part fills this slot)
    default_part: Optional[str] = None
    original_default: Optional[str] = None
    
    # Source information (always stored as Path, normalized)
    _source_file: Optional[Path] = field(default=None, repr=False)
    parent_part: Optional[str] = None
    
    # Slot metadata from jbeam
    description: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    
    # Graph relationships
    children: Dict[str, 'SlotNode'] = field(default_factory=dict)
    parent: Optional['SlotNode'] = None
    
    # Transformation state
    _state: SlotState = field(default=SlotState.ORIGINAL, repr=False)
    disposition: SlotDisposition = SlotDisposition.PRESERVE
    transformation_history: List[SlotTransformation] = field(default_factory=list)
    
    # Asset role - determines if this slot's source is for extraction or export
    asset_role: AssetRole = AssetRole.PRESERVE
    
    # Cache for descendant traversal (invalidated on structure change)
    _descendants_cache: Optional[List['SlotNode']] = field(default=None, repr=False, compare=False)
    _cache_valid: bool = field(default=False, repr=False, compare=False)
    
    @property
    def source_file(self) -> Optional[Path]:
        """Get normalized source file path."""
        return self._source_file
    
    @source_file.setter
    def source_file(self, value: Optional[Union[Path, str]]) -> None:
        """Set source file, normalizing to Path."""
        if value is None:
            self._source_file = None
        elif isinstance(value, Path):
            self._source_file = value.resolve() if value.is_absolute() else value
        else:
            self._source_file = Path(value)
    
    @property
    def state(self) -> SlotState:
        """Get current state."""
        return self._state
    
    @state.setter
    def state(self, new_state: SlotState) -> None:
        """Set state with transition validation."""
        self._set_state(new_state, validate=True)
    
    def _set_state(self, new_state: SlotState, validate: bool = True) -> None:
        """
        Internal state setter with optional validation.
        
        Args:
            new_state: Target state
            validate: If True, enforce valid transitions; if False, force set
        """
        if validate and self._state != new_state:
            allowed = VALID_STATE_TRANSITIONS.get(self._state, set())
            if new_state not in allowed and self._state != new_state:
                # Log warning but don't raise - allow recovery scenarios
                logger.warning(
                    f"Non-standard state transition for '{self.slot_type}': "
                    f"{self._state.value} -> {new_state.value}"
                )
        self._state = new_state
    
    def force_state(self, new_state: SlotState) -> None:
        """Force state change without validation (for recovery/testing)."""
        self._set_state(new_state, validate=False)
    
    def __repr__(self) -> str:
        child_count = len(self.children)
        return (f"SlotNode({self.slot_type}, default={self.default_part}, "
                f"state={self._state.value}, children={child_count})")
    
    def get_depth(self) -> int:
        """Get depth of this node in the tree (root = 0)."""
        depth = 0
        node = self.parent
        while node:
            depth += 1
            node = node.parent
        return depth
    
    def get_ancestors(self) -> List['SlotNode']:
        """Get list of ancestor nodes from immediate parent to root."""
        ancestors = []
        node = self.parent
        while node:
            ancestors.append(node)
            node = node.parent
        return ancestors
    
    def get_descendants(self, use_cache: bool = True) -> List['SlotNode']:
        """
        Get list of all descendant nodes (breadth-first).
        
        Args:
            use_cache: If True, return cached result if valid
            
        Returns:
            List of descendant SlotNodes
        """
        if use_cache and self._cache_valid and self._descendants_cache is not None:
            return self._descendants_cache
        
        descendants = []
        queue = list(self.children.values())
        while queue:
            node = queue.pop(0)
            descendants.append(node)
            queue.extend(node.children.values())
        
        self._descendants_cache = descendants
        self._cache_valid = True
        return descendants
    
    def invalidate_cache(self) -> None:
        """Invalidate descendant cache (call after structure changes)."""
        self._cache_valid = False
        self._descendants_cache = None
        # Propagate up to ancestors
        if self.parent:
            self.parent.invalidate_cache()
    
    def add_child(self, child: 'SlotNode') -> None:
        """Add child node and invalidate caches."""
        self.children[child.slot_type] = child
        child.parent = self
        self.invalidate_cache()
    
    def remove_child(self, slot_type: str) -> Optional['SlotNode']:
        """Remove child node by slot type and invalidate caches."""
        child = self.children.pop(slot_type, None)
        if child:
            child.parent = None
            self.invalidate_cache()
        return child
    
    def is_pruned(self) -> bool:
        """Check if this node or any ancestor is pruned."""
        if self._state == SlotState.PRUNED:
            return True
        for ancestor in self.get_ancestors():
            if ancestor._state == SlotState.PRUNED:
                return True
        return False


@dataclass
class SlotGraph:
    """
    Complete graph of slot dependencies for an engine swap.
    
    This is the single source of truth for all slot state during transformation.
    It maintains multiple indices for fast lookup and tracks all transformations.
    
    The graph is built in phases:
    1. Construction: Parse files and build node relationships
    2. Planning: Determine dispositions and plan transformations
    3. Execution: Apply transformations to graph state
    4. Output: Generate adapted files and manifest from graph
    
    Attributes:
        root: Root node of the slot tree (target vehicle's engine slot)
        by_slot_type: Index of nodes by slot type
        by_part_name: Index of nodes by default part name
        by_source_file: Index of nodes by source file path
        transformations: List of all planned/applied transformations
        slot_type_map: Mapping of old -> new slot types
        part_name_map: Mapping of old -> new part names
        donor_files: Set of all donor files added to graph
        generated_files: Set of output files generated from graph
        target_vehicle: Name of target vehicle
        donor_engine: Path to primary donor engine file
    """
    # The root of the graph (target vehicle's engine slot)
    root: Optional[SlotNode] = None
    
    # Fast lookup indices
    # NOTE: PRUNED nodes remain in indices intentionally for traceability.
    # Use get_active_slots() to get non-pruned nodes.
    by_slot_type: Dict[str, SlotNode] = field(default_factory=dict)
    by_part_name: Dict[str, SlotNode] = field(default_factory=dict)
    by_source_file: Dict[Path, List[SlotNode]] = field(default_factory=dict)
    
    # Transformation tracking
    transformations: List[SlotTransformation] = field(default_factory=list)
    
    # Mapping tables (built during planning phase)
    slot_type_map: Dict[str, str] = field(default_factory=dict)    # old -> new slot types
    part_name_map: Dict[str, str] = field(default_factory=dict)    # old -> new part names
    
    # Files involved (normalized to Path)
    donor_files: Set[Path] = field(default_factory=set)
    generated_files: Set[Path] = field(default_factory=set)
    
    # Context
    target_vehicle: str = ""
    donor_engine: str = ""
    
    def add_donor_file(self, path: Union[Path, str]) -> None:
        """Add a donor file path, normalizing to Path."""
        self.donor_files.add(Path(path) if isinstance(path, str) else path)
    
    def add_generated_file(self, path: Union[Path, str]) -> None:
        """Add a generated file path, normalizing to Path."""
        self.generated_files.add(Path(path) if isinstance(path, str) else path)
    
    def __repr__(self) -> str:
        return (f"SlotGraph(target={self.target_vehicle}, "
                f"slots={len(self.by_slot_type)}, "
                f"files={len(self.donor_files)}, "
                f"transforms={len(self.transformations)})")
    
    def get_node(self, slot_type: str) -> Optional[SlotNode]:
        """Get node by slot type, checking both original and transformed types."""
        # Direct lookup
        if slot_type in self.by_slot_type:
            return self.by_slot_type[slot_type]
        
        # Check if it's an original type that was renamed
        for node in self.by_slot_type.values():
            if node.original_slot_type == slot_type:
                return node
        
        return None
    
    def get_active_slots(self) -> List[SlotNode]:
        """Get all non-pruned slots."""
        return [n for n in self.by_slot_type.values() if not n.is_pruned()]
    
    def get_slots_by_disposition(self, disposition: SlotDisposition) -> List[SlotNode]:
        """Get all slots with a specific disposition."""
        return [n for n in self.by_slot_type.values() if n.disposition == disposition]
    
    def get_transformation_summary(self) -> Dict[str, int]:
        """Get count of transformations by operation type."""
        summary = {}
        for t in self.transformations:
            key = t.operation.value
            summary[key] = summary.get(key, 0) + 1
        return summary
    
    def validate(self, raise_on_error: bool = False) -> Dict[str, Any]:
        """
        Validate graph integrity at any point (not just at manifest generation).
        
        Checks:
        - All non-pruned slots have resolvable defaults
        - No orphan adapted parts
        - No circular references
        - All transformations have valid targets
        
        Args:
            raise_on_error: If True, raise SlotGraphError on first error
            
        Returns:
            Validation result dict with errors and warnings
        """
        errors = []
        warnings = []
        
        # Check all non-pruned slots have resolvable defaults
        for slot_type, node in self.by_slot_type.items():
            if node.is_pruned():
                continue
            
            if node.default_part:
                # Check if default part exists in graph or is a known mapping
                if (node.default_part not in self.by_part_name and
                    node.default_part not in self.part_name_map.values()):
                    # Not an error if it's an external reference (like stock parts)
                    if not node.default_part.startswith(self.target_vehicle):
                        warnings.append(
                            f"Slot '{slot_type}' default '{node.default_part}' not found in graph "
                            f"(may be external reference)"
                        )
        
        # Check for orphan adapted parts
        adapted_parts = set()
        for node in self.by_slot_type.values():
            if node.disposition == SlotDisposition.ADAPT and node.default_part:
                adapted_parts.add(node.default_part)
        
        for part_name in adapted_parts:
            referenced = False
            for node in self.by_slot_type.values():
                if node.default_part == part_name and not node.is_pruned():
                    referenced = True
                    break
            if not referenced:
                warnings.append(f"Adapted part '{part_name}' not referenced by any active slot")
        
        # Check for circular references (shouldn't happen with tree structure)
        for node in self.by_slot_type.values():
            ancestors = node.get_ancestors()
            if node in ancestors:
                msg = f"Circular reference detected involving '{node.slot_type}'"
                errors.append(msg)
                if raise_on_error:
                    raise SlotGraphError(msg)
        
        # Check transformation targets exist
        for t in self.transformations:
            if t.operation != TransformOp.INJECT_SLOT:
                if t.target_slot_type not in self.by_slot_type:
                    # Check original types too
                    found = any(
                        n.original_slot_type == t.target_slot_type 
                        for n in self.by_slot_type.values()
                    )
                    if not found:
                        warnings.append(
                            f"Transformation target '{t.target_slot_type}' not found in graph"
                        )
        
        return {
            "valid": len(errors) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings
        }
    
    def print_tree(self, node: Optional[SlotNode] = None, indent: int = 0) -> None:
        """Print the slot tree for debugging."""
        if node is None:
            node = self.root
        if node is None:
            print("(empty graph)")
            return
        
        prefix = "  " * indent
        state_icon = {
            SlotState.ORIGINAL: "○",
            SlotState.PLANNED: "◐",
            SlotState.TRANSFORMED: "●",
            SlotState.VALIDATED: "✓",
            SlotState.PRUNED: "✗",
        }.get(node.state, "?")
        
        disp_icon = {
            SlotDisposition.PRESERVE: "P",
            SlotDisposition.ADAPT: "A",
            SlotDisposition.INJECT: "I",
            SlotDisposition.PRUNE: "X",
            SlotDisposition.REMAP_DEFAULT: "R",
        }.get(node.disposition, "?")
        
        role_icon = {
            AssetRole.SOURCE: "S",    # Source for extraction
            AssetRole.TARGET: "T",    # Target for export
            AssetRole.PRESERVE: "P",  # Preserve original
            AssetRole.INTERNAL: "i",  # Internal only
        }.get(node.asset_role, "?")
        
        print(f"{prefix}{state_icon}[{disp_icon}/{role_icon}] {node.slot_type} -> {node.default_part or '(empty)'}")
        
        for child in node.children.values():
            self.print_tree(child, indent + 1)
    
    def visualize(self, 
                  show_source_files: bool = False,
                  show_transformations: bool = False,
                  filter_role: Optional[AssetRole] = None,
                  filter_disposition: Optional[SlotDisposition] = None,
                  output_format: str = "text") -> str:
        """
        Generate a detailed visualization of the slot graph.
        
        This provides insight into the graph state at any point during processing,
        showing which slots are sources (extraction only) vs targets (exported).
        
        Args:
            show_source_files: Include source file paths in output
            show_transformations: Include transformation history
            filter_role: Only show slots with this asset role
            filter_disposition: Only show slots with this disposition
            output_format: "text" for console, "markdown" for docs
            
        Returns:
            Formatted string visualization
        """
        lines = []
        
        # Header
        if output_format == "markdown":
            lines.append(f"# Slot Graph: {self.target_vehicle}")
            lines.append("")
            lines.append(f"**Slots:** {len(self.by_slot_type)} | "
                        f"**Active:** {len(self.get_active_slots())} | "
                        f"**Donor Files:** {len(self.donor_files)} | "
                        f"**Transforms:** {len(self.transformations)}")
            lines.append("")
        else:
            lines.append(f"═══════════════════════════════════════════════════════")
            lines.append(f" SLOT GRAPH: {self.target_vehicle}")
            lines.append(f" Slots: {len(self.by_slot_type)} | Active: {len(self.get_active_slots())} | "
                        f"Donor Files: {len(self.donor_files)} | Transforms: {len(self.transformations)}")
            lines.append(f"═══════════════════════════════════════════════════════")
        
        # Legend
        lines.append("")
        if output_format == "markdown":
            lines.append("## Legend")
            lines.append("- **State:** ○=original ◐=planned ●=transformed ✓=validated ✗=pruned")
            lines.append("- **Disposition:** P=preserve A=adapt I=inject X=prune R=remap")
            lines.append("- **Role:** S=source(extraction) T=target(export) P=preserve i=internal")
        else:
            lines.append(" Legend:")
            lines.append("   State:       ○=original  ◐=planned  ●=transformed  ✓=validated  ✗=pruned")
            lines.append("   Disposition: P=preserve  A=adapt    I=inject       X=prune      R=remap")
            lines.append("   Role:        S=source(extraction)  T=target(export)  P=preserve  i=internal")
        
        # Tree visualization
        lines.append("")
        if output_format == "markdown":
            lines.append("## Slot Tree")
            lines.append("```")
        else:
            lines.append(" ─── Slot Tree ───")
        
        def _visualize_node(node: SlotNode, depth: int = 0) -> None:
            # Apply filters
            if filter_role and node.asset_role != filter_role:
                return
            if filter_disposition and node.disposition != filter_disposition:
                return
            
            prefix = "│   " * depth
            connector = "├── " if depth > 0 else ""
            
            state_icon = "○◐●✓✗"["ORIGINAL PLANNED TRANSFORMED VALIDATED PRUNED".split().index(node.state.name)]
            disp_char = node.disposition.value[0].upper()
            role_char = node.asset_role.value[0].upper()
            
            # Format the node line
            slot_display = node.slot_type
            if node.slot_type != node.original_slot_type:
                slot_display = f"{node.original_slot_type} → {node.slot_type}"
            
            default_display = node.default_part or "(none)"
            if node.original_default and node.default_part != node.original_default:
                default_display = f"{node.original_default} → {node.default_part}"
            
            line = f"{prefix}{connector}{state_icon}[{disp_char}/{role_char}] {slot_display}"
            if node.default_part:
                line += f" = {default_display}"
            
            lines.append(line)
            
            # Source file info
            if show_source_files and node.source_file:
                lines.append(f"{prefix}│       └─ file: {node.source_file.name}")
            
            # Recurse to children
            for child in node.children.values():
                _visualize_node(child, depth + 1)
        
        if self.root:
            _visualize_node(self.root)
        else:
            lines.append("  (empty graph)")
        
        if output_format == "markdown":
            lines.append("```")
        
        # Statistics by role
        lines.append("")
        if output_format == "markdown":
            lines.append("## Statistics by Asset Role")
        else:
            lines.append(" ─── Statistics by Asset Role ───")
        
        role_counts = {}
        for node in self.by_slot_type.values():
            role = node.asset_role.value
            role_counts[role] = role_counts.get(role, 0) + 1
        
        for role, count in sorted(role_counts.items()):
            desc = {
                "source": "Extraction only (NOT exported)",
                "target": "Generated/adapted (IS exported)",
                "preserve": "Original files (copied to export)",
                "internal": "Processing artifacts (never exported)",
            }.get(role, "")
            if output_format == "markdown":
                lines.append(f"- **{role}**: {count} slots - {desc}")
            else:
                lines.append(f"   {role:10} : {count:3} slots - {desc}")
        
        # Transformation history (optional)
        if show_transformations and self.transformations:
            lines.append("")
            if output_format == "markdown":
                lines.append("## Transformation History")
                for i, t in enumerate(self.transformations, 1):
                    status = "✓" if t.applied else "○"
                    lines.append(f"{i}. {status} **{t.operation.value}** on `{t.target_slot_type}`: "
                                f"`{t.old_value}` → `{t.new_value}` - {t.reason}")
            else:
                lines.append(" ─── Transformation History ───")
                for i, t in enumerate(self.transformations, 1):
                    status = "✓" if t.applied else "○"
                    lines.append(f"   {i:2}. {status} {t.operation.value:20} {t.target_slot_type:30} "
                                f"{t.old_value or ''} -> {t.new_value or ''}")
        
        return "\n".join(lines)
    
    def inject_replacement_slot(
        self,
        source_slot_type: str,
        replacement_type: str,
        replacement_default: Optional[str] = None,
        description: str = "",
        options: Optional[Dict[str, Any]] = None
    ) -> Optional[SlotNode]:
        """
        Inject a replacement slot for a SOURCE slot being removed from output.
        
        When assets are extracted from a SOURCE slot (e.g., engine_structure),
        this method injects a replacement slot that calls the extracted asset
        from the new location where it was injected.
        
        The replacement inherits the suffix from the source slot for consistency.
        
        Args:
            source_slot_type: The SOURCE slot being replaced (e.g., "Camso_engine_structure_ec8ba")
            replacement_type: Base type for replacement (e.g., "Camso_engine_mesh")
            replacement_default: Default part name (auto-generated from type if None)
            description: Slot description (e.g., "Engine Mesh")
            options: Slot options dict (e.g., {"coreSlot": True})
            
        Returns:
            The injected SlotNode, or None if source slot not found
            
        Example:
            # Source: Camso_engine_structure_ec8ba (marked SOURCE, not exported)
            # Inject: Camso_engine_mesh_ec8ba (INJECT disposition, replaces source in output)
            graph.inject_replacement_slot(
                source_slot_type="Camso_engine_structure_ec8ba",
                replacement_type="Camso_engine_mesh",
                description="Engine Mesh",
                options={"coreSlot": True}
            )
        """
        # Find source slot
        source_node = self.get_node(source_slot_type)
        if not source_node:
            logger.warning(f"[SlotGraph] Cannot inject replacement: source slot '{source_slot_type}' not found")
            return None
        
        # Extract suffix from source slot for consistency
        _, suffix = extract_slot_suffix(source_slot_type)
        
        # Build replacement slot type and default with suffix
        full_replacement_type = apply_slot_suffix(replacement_type, suffix)
        if replacement_default is None:
            replacement_default = full_replacement_type  # Default to slot type name
        else:
            # Apply suffix to provided default as well
            default_base, _ = extract_slot_suffix(replacement_default)
            replacement_default = apply_slot_suffix(default_base, suffix)
        
        # Check if replacement slot already exists (e.g., from structure file)
        if full_replacement_type in self.by_slot_type:
            existing_node = self.by_slot_type[full_replacement_type]
            
            # If the existing node is currently a SOURCE child (from structure file),
            # we need to "absorb" it: re-parent to engine, change to INJECT/TARGET
            if existing_node.asset_role == AssetRole.SOURCE:
                logger.info(f"[SlotGraph] Absorbing existing SOURCE slot '{full_replacement_type}' as replacement")
                
                # Remove from old parent's children
                if existing_node.parent and full_replacement_type in existing_node.parent.children:
                    del existing_node.parent.children[full_replacement_type]
                
                # Re-parent to source's parent (the engine slot)
                existing_node.parent = source_node.parent
                if source_node.parent:
                    source_node.parent.children[full_replacement_type] = existing_node
                
                # Update disposition and role
                existing_node.disposition = SlotDisposition.INJECT
                existing_node.asset_role = AssetRole.TARGET
                existing_node.state = SlotState.TRANSFORMED
                
                # Update description and options if provided
                if description:
                    existing_node.description = description
                if options:
                    existing_node.options.update(options)
                
                # Record transformation
                self.transformations.append(SlotTransformation(
                    operation=TransformOp.INJECT_SLOT,
                    target_slot_type=full_replacement_type,
                    old_value=source_slot_type,
                    new_value=full_replacement_type,
                    options=options,
                    reason=f"Absorbed from SOURCE slot structure as replacement for '{source_slot_type}'",
                    applied=True
                ))
                
                logger.info(f"[SlotGraph] Absorbed replacement: {source_slot_type} -> {full_replacement_type}")
                return existing_node
            else:
                # Non-SOURCE existing slot - just return it as-is
                logger.debug(f"[SlotGraph] Replacement slot '{full_replacement_type}' already exists (non-SOURCE)")
                return existing_node
        
        # Create replacement node (no existing slot found)
        replacement_node = SlotNode(
            slot_type=full_replacement_type,
            original_slot_type=full_replacement_type,
            default_part=replacement_default,
            original_default=replacement_default,
            description=description or f"Replacement for {source_slot_type}",
            options=options or {},
            parent=source_node.parent,  # Same parent as source
            _state=SlotState.PLANNED,
        )
        replacement_node.disposition = SlotDisposition.INJECT
        replacement_node.asset_role = AssetRole.TARGET  # Injected slots are exported
        
        # Add to indices
        self.by_slot_type[full_replacement_type] = replacement_node
        if replacement_default:
            self.by_part_name[replacement_default] = replacement_node
        
        # Add to parent's children
        if source_node.parent:
            source_node.parent.children[full_replacement_type] = replacement_node
        
        # Record transformation
        self.transformations.append(SlotTransformation(
            operation=TransformOp.INJECT_SLOT,
            target_slot_type=full_replacement_type,
            old_value=source_slot_type,
            new_value=full_replacement_type,
            options=options,
            reason=f"Replacement for SOURCE slot '{source_slot_type}'",
            applied=True
        ))
        
        logger.info(f"[SlotGraph] Injected replacement: {source_slot_type} -> {full_replacement_type}")
        return replacement_node
    
    def get_slots_by_role(self, role: AssetRole) -> List[SlotNode]:
        """Get all slots with a specific asset role."""
        return [n for n in self.by_slot_type.values() if n.asset_role == role]
    
    def get_exportable_slots(self) -> List[SlotNode]:
        """Get slots that should be included in export manifest (TARGET or PRESERVE, not PRUNED)."""
        return [
            n for n in self.by_slot_type.values()
            if n.asset_role in (AssetRole.TARGET, AssetRole.PRESERVE)
            and not n.is_pruned()
        ]
    
    def get_source_slots(self) -> List[SlotNode]:
        """Get slots that are sources for extraction only (not exported)."""
        return [n for n in self.by_slot_type.values() if n.asset_role == AssetRole.SOURCE]


# =============================================================================
# Graph Builder
# =============================================================================

class SlotGraphBuilder:
    """
    Builds a complete SlotGraph from donor mod files.
    
    Two-phase construction:
    1. Parse all relevant files, extract slot definitions and parts
    2. Link parent-child relationships to form tree structure
    
    Usage:
        builder = SlotGraphBuilder("pickup")
        builder.add_donor_file(engine_path)
        builder.add_donor_file(transmission_path)
        graph = builder.build()
    """
    
    def __init__(self, target_vehicle: str, jbeam_parser: Optional[JBeamParserProtocol] = None):
        """
        Initialize builder.
        
        Args:
            target_vehicle: Name of target vehicle (e.g., "pickup")
            jbeam_parser: JBeam parser class/instance implementing JBeamParserProtocol.
                          Must have a parse_jbeam(Path) -> Optional[Dict] method.
                          Required for file parsing - pass in from engineswap.py.
        """
        self.target_vehicle = target_vehicle
        self.parser = jbeam_parser
        self.graph = SlotGraph(target_vehicle=target_vehicle)
        
        # Pending links to resolve after all files parsed
        # (parent_slot_type, child_slot_type, child_node, parent_part_name)
        self._pending_links: List[Tuple[str, str, SlotNode, str]] = []
        
        # Track which parts define which slots
        self._part_slots: Dict[str, List[str]] = {}  # part_name -> [slot_types]
    
    def add_donor_file(self, file_path: Union[Path, str]) -> int:
        """
        Parse a donor jbeam file and add its slots to the graph.
        
        Args:
            file_path: Path to .jbeam file (Path or string)
            
        Returns:
            Number of slots extracted from file
            
        Raises:
            ParserNotAvailableError: If no parser was provided to constructor
            MalformedJBeamError: If file cannot be parsed
        """
        if self.parser is None:
            raise ParserNotAvailableError(
                "JBeam parser not provided - pass jbeam_parser to SlotGraphBuilder constructor"
            )
        
        # Normalize path
        file_path = Path(file_path) if isinstance(file_path, str) else file_path
        
        try:
            data = self.parser.parse_jbeam(file_path)
        except Exception as e:
            logger.error(f"  [SlotGraph] Parse error in {file_path.name}: {e}")
            raise MalformedJBeamError(file_path, str(e)) from e
        
        if not data:
            logger.warning(f"  [SlotGraph] Empty or failed parse: {file_path.name}")
            return 0
        
        if not isinstance(data, dict):
            raise MalformedJBeamError(file_path, "Expected dict at root level")
        
        self.graph.add_donor_file(file_path)
        slots_added = 0
        
        for part_name, part_data in data.items():
            if not isinstance(part_data, dict):
                continue
            
            # Extract this part's slotType (what slot it fills)
            part_slot_type = part_data.get('slotType', '')
            
            # Create/update node for this part's slotType
            if part_slot_type:
                node = self._get_or_create_node(part_slot_type)
                node.default_part = part_name
                node.original_default = part_name
                node.source_file = file_path
                self.graph.by_part_name[part_name] = node
                
                # Index by source file
                if file_path not in self.graph.by_source_file:
                    self.graph.by_source_file[file_path] = []
                self.graph.by_source_file[file_path].append(node)
                
                slots_added += 1
            
            # Extract child slots this part defines
            slots = part_data.get('slots', [])
            self._part_slots[part_name] = []
            
            for slot in slots:
                if not isinstance(slot, list) or len(slot) < 2:
                    continue
                if slot[0] == "type":  # Header row
                    continue
                
                child_type = str(slot[0])
                child_default = str(slot[1]) if len(slot) > 1 and slot[1] else ""
                child_desc = str(slot[2]) if len(slot) > 2 else ""
                child_opts = slot[3] if len(slot) > 3 and isinstance(slot[3], dict) else {}
                
                child_node = self._get_or_create_node(child_type)
                
                # Only update if we have more info than existing node
                if child_default and not child_node.default_part:
                    child_node.default_part = child_default
                    child_node.original_default = child_default
                if child_desc and not child_node.description:
                    child_node.description = child_desc
                if child_opts:
                    child_node.options.update(child_opts)
                
                child_node.parent_part = part_name
                self._part_slots[part_name].append(child_type)
                
                # Queue parent-child link
                if part_slot_type:
                    self._pending_links.append((part_slot_type, child_type, child_node, part_name))
                
                slots_added += 1
        
        logger.debug(f"  [SlotGraph] Added {slots_added} slots from {file_path.name}")
        return slots_added
    
    def build(self) -> SlotGraph:
        """
        Finalize graph construction by linking all relationships.
        
        Returns:
            Completed SlotGraph
        """
        # Resolve parent-child links
        for parent_type, child_type, child_node, parent_part in self._pending_links:
            parent_node = self.graph.by_slot_type.get(parent_type)
            if parent_node:
                parent_node.children[child_type] = child_node
                child_node.parent = parent_node
        
        # Find root node (typically the primary engine slot)
        self._identify_root()
        
        logger.info(f"  [SlotGraph] Built graph: {len(self.graph.by_slot_type)} slots, "
                   f"{len(self.graph.donor_files)} files")
        
        return self.graph
    
    def _get_or_create_node(self, slot_type: str) -> SlotNode:
        """Get existing node or create new one."""
        if slot_type not in self.graph.by_slot_type:
            node = SlotNode(
                slot_type=slot_type,
                original_slot_type=slot_type
            )
            self.graph.by_slot_type[slot_type] = node
        return self.graph.by_slot_type[slot_type]
    
    def _identify_root(self) -> None:
        """Identify the root node of the slot tree."""
        # Look for primary engine slot (Camso_Engine, etc.)
        for slot_type, node in self.graph.by_slot_type.items():
            slot_lower = slot_type.lower()
            # Primary engine slot has no parent and contains "engine" 
            # but not "management", "internals", etc.
            if ('engine' in slot_lower and 
                'management' not in slot_lower and 
                'internals' not in slot_lower and
                'structure' not in slot_lower and
                'mesh' not in slot_lower and
                'mount' not in slot_lower and
                node.parent is None):
                self.graph.root = node
                logger.debug(f"  [SlotGraph] Identified root: {slot_type}")
                return
        
        # Fallback: first node with no parent
        for node in self.graph.by_slot_type.values():
            if node.parent is None and node.children:
                self.graph.root = node
                logger.debug(f"  [SlotGraph] Fallback root: {node.slot_type}")
                return


# =============================================================================
# Disposition Rules Engine
# =============================================================================

class SlotDispositionRules:
    """
    Determines what should happen to each slot based on configurable rules.
    
    Default rules follow the "Cummins Pattern":
    - Primary integration slots (engine, transmission, transfer_case) → ADAPT
    - Ecosystem slots (intake, management, internals) → PRESERVE  
    - Optional features user doesn't want → PRUNE
    - Vehicle-specific requirements → INJECT
    
    Configuration can override defaults via:
    - prune_slots: List of slot types to remove
    - preserve_slots: List of slot types to force preserve
    - force_adapt_slots: List of slot types to force adapt
    """
    
    # Patterns that trigger ADAPT disposition (target vehicle integration points)
    ADAPT_PATTERNS = [
        r"^Camso_Engine$",           # Primary engine slot
        r"^Camso_Transmission$",     # Primary transmission slot
        r"^Camso_TransferCase$",     # Primary transfer case slot
    ]
    
    # Patterns that stay PRESERVE (donor ecosystem - kept as-is)
    PRESERVE_PATTERNS = [
        r"^Camso_Intake.*",
        r"^Camso_EngineManagement.*",
        r"^Camso_EngineInternals.*",
        r"^Camso_Turbo.*",
        r"^Camso_Supercharger.*",
        r"^Camso_BalancingMass.*",
        r"^Camso_RevLimiter.*",
        r"^Camso_Nitrous.*",
        r"^Camso_differential.*",
        r"^Camso_driveshaft.*",
        r"^Camso_engine_mesh.*",
        r"^Camso_engine_structure.*",
        r"^Camso_exhaust.*",
        r"^camso_tuning.*",
    ]
    
    # Default slot replacements (extraction sources → injected replacements)
    # Keys are base slot types (suffix-agnostic), values specify replacement
    DEFAULT_REPLACEMENTS: Dict[str, Dict[str, str]] = {
        "Camso_engine_structure": {
            "replacement_type": "Camso_engine_mesh",
            "description": "Engine Mesh",
            "options": {"coreSlot": True}
        },
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize rules engine.
        
        Args:
            config: Optional configuration dict with slot_rules section
        """
        self.config = config or {}
        slot_rules = self.config.get('slot_rules', {})
        
        self.explicit_prune: Set[str] = set(slot_rules.get('prune_slots', []))
        self.explicit_preserve: Set[str] = set(slot_rules.get('preserve_slots', []))
        self.explicit_adapt: Set[str] = set(slot_rules.get('force_adapt_slots', []))
        
        # Slot replacements: when a slot is marked SOURCE, inject its replacement
        # Merge user config with defaults (user config wins)
        self.replace_slots: Dict[str, Dict[str, str]] = dict(self.DEFAULT_REPLACEMENTS)
        user_replacements = slot_rules.get('replace_slots', {})
        self.replace_slots.update(user_replacements)
        
        logger.debug(f"[SlotDispositionRules] Initialized with {len(self.replace_slots)} replacement rules")
    
    def determine_disposition(self, node: SlotNode, target_vehicle: str) -> SlotDisposition:
        """
        Determine what should happen to this slot during adaptation.
        
        Args:
            node: SlotNode to evaluate
            target_vehicle: Name of target vehicle
            
        Returns:
            SlotDisposition indicating how to handle this slot
        """
        slot_type = node.original_slot_type
        
        # 1. Explicit user overrides first
        if slot_type in self.explicit_prune:
            return SlotDisposition.PRUNE
        if slot_type in self.explicit_preserve:
            return SlotDisposition.PRESERVE
        if slot_type in self.explicit_adapt:
            return SlotDisposition.ADAPT
        
        # 2. Check ADAPT patterns (primary integration points)
        for pattern in self.ADAPT_PATTERNS:
            if re.match(pattern, slot_type, re.IGNORECASE):
                return SlotDisposition.ADAPT
        
        # 3. Check PRESERVE patterns (donor ecosystem)
        for pattern in self.PRESERVE_PATTERNS:
            if re.match(pattern, slot_type, re.IGNORECASE):
                return SlotDisposition.PRESERVE
        
        # 4. Default: preserve (safer - don't break unknown slots)
        return SlotDisposition.PRESERVE
    
    def get_target_slot_type(self, donor_slot_type: str, target_vehicle: str,
                             slot_type_prefix: Optional[str] = None) -> str:
        """
        Derive target vehicle slot type from donor slot type.
        
        Args:
            donor_slot_type: Original donor slot type
            target_vehicle: Name of target vehicle
            slot_type_prefix: Optional family prefix for slot types (e.g. "etk" 
                for etk800). When provided, slot types use this prefix instead of 
                the vehicle name. Derived from engine_slot_type discovery.
            
        Returns:
            Corresponding target vehicle slot type
        """
        prefix = slot_type_prefix or target_vehicle
        donor_lower = donor_slot_type.lower()
        
        if 'engine' in donor_lower and 'management' not in donor_lower and 'internal' not in donor_lower:
            return f"{prefix}_engine"
        if 'transmission' in donor_lower:
            return f"{prefix}_transmission"
        if 'transfer' in donor_lower:
            return f"{prefix}_transfer_case"
        
        return donor_slot_type  # Preserve as-is
    
    def get_replacement_for_slot(self, slot_type: str) -> Optional[Dict[str, Any]]:
        """
        Get replacement configuration for a slot if one exists (suffix-agnostic).
        
        This enables the convention: when assets are extracted from a SOURCE slot,
        inject a replacement slot that calls those assets from their new location.
        
        Args:
            slot_type: Full slot type to check (e.g., "Camso_engine_structure_ec8ba")
            
        Returns:
            Dict with replacement config if match found, None otherwise.
            Config includes: replacement_type, description, options
        """
        # Extract base slot type for suffix-agnostic matching
        base_type, suffix = extract_slot_suffix(slot_type)
        
        # Check if base type has a replacement rule
        if base_type in self.replace_slots:
            return self.replace_slots[base_type]
        
        # Also check exact match (for slots without suffix)
        if slot_type in self.replace_slots:
            return self.replace_slots[slot_type]
        
        return None
    
    def has_replacement(self, slot_type: str) -> bool:
        """Check if a slot has a replacement rule (suffix-agnostic)."""
        return self.get_replacement_for_slot(slot_type) is not None


# =============================================================================
# Transformation Planner
# =============================================================================

class SlotTransformationPlanner:
    """
    Plans all transformations based on disposition rules.
    
    Creates a complete transformation plan before any changes are made.
    This allows for validation and preview before execution.
    """
    
    def __init__(self, graph: SlotGraph, target_vehicle: str, rules: SlotDispositionRules,
                 slot_type_prefix: Optional[str] = None,
                 target_mount_slot_type: Optional[str] = None):
        """
        Initialize planner.
        
        Args:
            graph: SlotGraph to plan transformations for
            target_vehicle: Name of target vehicle
            rules: SlotDispositionRules for determining dispositions
            slot_type_prefix: Optional family prefix for slot types (e.g. "etk"
                for etk800). When provided, drivetrain slot types use this prefix.
            target_mount_slot_type: Dynamically discovered enginemounts slot type
                from target engine files (e.g. "etk_enginemounts"). When provided,
                used for mount slot injection instead of synthesized name.
        """
        self.graph = graph
        self.target_vehicle = target_vehicle
        self.rules = rules
        self.slot_type_prefix = slot_type_prefix
        self.target_mount_slot_type = target_mount_slot_type
    
    def plan(self) -> List[SlotTransformation]:
        """
        Generate complete transformation plan.
        
        Returns:
            List of planned SlotTransformation objects
        """
        transformations = []
        
        # Walk the graph and determine dispositions
        for slot_type, node in self.graph.by_slot_type.items():
            disposition = self.rules.determine_disposition(node, self.target_vehicle)
            node.disposition = disposition
            node.state = SlotState.PLANNED
            
            if disposition == SlotDisposition.ADAPT:
                transformations.extend(self._plan_adaptation(node))
            elif disposition == SlotDisposition.PRUNE:
                transformations.extend(self._plan_prune(node))
        
        # Plan injections for required vehicle slots not in donor
        transformations.extend(self._plan_required_injections())
        
        # Build mapping tables for later use
        for t in transformations:
            if t.operation == TransformOp.RENAME_SLOT_TYPE:
                self.graph.slot_type_map[t.old_value] = t.new_value
            elif t.operation == TransformOp.REMAP_DEFAULT:
                self.graph.part_name_map[t.old_value] = t.new_value
        
        self.graph.transformations = transformations
        
        logger.info(f"  [SlotGraph] Planned {len(transformations)} transformations")
        return transformations
    
    def _plan_adaptation(self, node: SlotNode) -> List[SlotTransformation]:
        """Plan transformations for an ADAPT disposition slot."""
        transforms = []
        
        # Determine target slot type
        target_slot_type = self.rules.get_target_slot_type(
            node.original_slot_type, 
            self.target_vehicle,
            slot_type_prefix=self.slot_type_prefix
        )
        
        # Plan slot type rename if different
        if target_slot_type != node.original_slot_type:
            transforms.append(SlotTransformation(
                operation=TransformOp.RENAME_SLOT_TYPE,
                target_slot_type=node.original_slot_type,
                old_value=node.original_slot_type,
                new_value=target_slot_type,
                reason=f"Adapt to {self.target_vehicle} slot system"
            ))
        
        # Plan default remapping if part exists
        if node.original_default:
            new_part_name = f"{self.target_vehicle}_{node.original_default}"
            transforms.append(SlotTransformation(
                operation=TransformOp.REMAP_DEFAULT,
                target_slot_type=node.original_slot_type,
                old_value=node.original_default,
                new_value=new_part_name,
                reason=f"Remap to adapted part name"
            ))
        
        # Add coreSlot option for primary slots
        if not node.options.get('coreSlot'):
            transforms.append(SlotTransformation(
                operation=TransformOp.ADD_OPTIONS,
                target_slot_type=node.original_slot_type,
                options={"coreSlot": True},
                reason="Mark as core slot for adapted part"
            ))
        
        return transforms
    
    def _plan_prune(self, node: SlotNode) -> List[SlotTransformation]:
        """Plan recursive removal of a slot subtree."""
        transforms = []
        
        # Mark this node for pruning (executor will handle recursion)
        transforms.append(SlotTransformation(
            operation=TransformOp.PRUNE_SUBTREE,
            target_slot_type=node.original_slot_type,
            reason=f"Pruning {node.original_slot_type} and {len(node.get_descendants())} descendants"
        ))
        
        return transforms
    
    def _plan_required_injections(self) -> List[SlotTransformation]:
        """Plan injection of slots required by target vehicle but missing from donor."""
        transforms = []
        
        # Engine mounts are always required for physical attachment.
        # Use dynamically discovered mount slot type from target engine files,
        # falling back to prefix-based derivation for robustness.
        if self.target_mount_slot_type:
            mount_slot = self.target_mount_slot_type
        else:
            prefix = self.slot_type_prefix or self.target_vehicle
            mount_slot = f"{prefix}_enginemounts"
        if mount_slot not in self.graph.by_slot_type:
            transforms.append(SlotTransformation(
                operation=TransformOp.INJECT_SLOT,
                target_slot_type=mount_slot,
                new_value=mount_slot,  # default to stock mounts
                options={"coreSlot": True},
                reason="Required for physical engine attachment"
            ))
        
        return transforms
    
    def get_plan_summary(self) -> Dict[str, Any]:
        """Get human-readable summary of the transformation plan."""
        summary = {
            "total_transformations": len(self.graph.transformations),
            "by_operation": self.graph.get_transformation_summary(),
            "by_disposition": {
                d.value: len(self.graph.get_slots_by_disposition(d))
                for d in SlotDisposition
            },
            "slot_type_mappings": dict(self.graph.slot_type_map),
            "part_name_mappings": dict(self.graph.part_name_map),
        }
        return summary


# =============================================================================
# Transformation Executor
# =============================================================================

class SlotTransformationExecutor:
    """
    Executes planned transformations on the slot graph.
    
    All transformations are applied to the graph state.
    The graph is then used as source of truth for output generation.
    """
    
    def __init__(self, graph: SlotGraph):
        """
        Initialize executor.
        
        Args:
            graph: SlotGraph with planned transformations
        """
        self.graph = graph
    
    def execute_all(self) -> int:
        """
        Execute all planned transformations.
        
        Returns:
            Number of transformations successfully executed
        """
        executed = 0
        for transform in self.graph.transformations:
            if self._execute_one(transform):
                executed += 1
        
        logger.info(f"  [SlotGraph] Executed {executed}/{len(self.graph.transformations)} transformations")
        return executed
    
    def _execute_one(self, t: SlotTransformation) -> bool:
        """
        Execute a single transformation.
        
        Returns:
            True if transformation was successfully applied
        """
        # For inject operations, node doesn't exist yet
        if t.operation == TransformOp.INJECT_SLOT:
            return self._execute_inject(t)
        
        # Find target node
        node = self.graph.get_node(t.target_slot_type)
        if not node:
            logger.warning(f"  [SlotGraph] Slot not found: {t.target_slot_type}")
            return False
        
        success = False
        
        if t.operation == TransformOp.RENAME_SLOT_TYPE:
            success = self._execute_rename(node, t)
        elif t.operation == TransformOp.REMAP_DEFAULT:
            success = self._execute_remap_default(node, t)
        elif t.operation == TransformOp.PRUNE_SUBTREE:
            success = self._execute_prune(node, t)
        elif t.operation == TransformOp.ADD_OPTIONS:
            success = self._execute_add_options(node, t)
        elif t.operation == TransformOp.REMOVE_SLOT:
            success = self._execute_remove(node, t)
        
        if success:
            t.applied = True
            # Don't override PRUNED state with TRANSFORMED
            if node.state != SlotState.PRUNED:
                node.state = SlotState.TRANSFORMED
            node.transformation_history.append(t)
        
        return success
    
    def _execute_rename(self, node: SlotNode, t: SlotTransformation) -> bool:
        """Rename a slot type."""
        old_type = node.slot_type
        new_type = t.new_value
        
        node.slot_type = new_type
        
        # Update index
        if old_type in self.graph.by_slot_type:
            del self.graph.by_slot_type[old_type]
        self.graph.by_slot_type[new_type] = node
        
        # Update parent's children dict if needed
        if node.parent and old_type in node.parent.children:
            del node.parent.children[old_type]
            node.parent.children[new_type] = node
        
        logger.debug(f"  [SlotGraph] Renamed: {old_type} -> {new_type}")
        return True
    
    def _execute_remap_default(self, node: SlotNode, t: SlotTransformation) -> bool:
        """Change the default part for a slot."""
        old_default = node.default_part
        node.default_part = t.new_value
        
        # Update part name index - always add new mapping
        # This is critical for generate_slots_section lookup
        self.graph.by_part_name[t.new_value] = node
        
        logger.debug(f"  [SlotGraph] Remapped default: {t.old_value} -> {t.new_value}")
        return True
    
    def _execute_inject(self, t: SlotTransformation) -> bool:
        """Inject a new slot into the graph."""
        new_node = SlotNode(
            slot_type=t.target_slot_type,
            original_slot_type=t.target_slot_type,
            default_part=t.new_value,
            options=t.options or {},
            disposition=SlotDisposition.INJECT,
        )
        # Use force_state to bypass transition validation for injected nodes
        new_node.force_state(SlotState.TRANSFORMED)
        new_node.transformation_history.append(t)
        
        self.graph.by_slot_type[t.target_slot_type] = new_node
        
        # Link to root as child if we have a root
        if self.graph.root:
            self.graph.root.add_child(new_node)  # Use add_child for proper cache invalidation
        
        t.applied = True
        logger.debug(f"  [SlotGraph] Injected: {t.target_slot_type}")
        return True
    
    def _execute_prune(self, node: SlotNode, t: SlotTransformation) -> bool:
        """Recursively prune a slot subtree."""
        pruned_count = self._prune_recursive(node)
        logger.debug(f"  [SlotGraph] Pruned: {node.slot_type} (+ {pruned_count - 1} descendants)")
        return True
    
    def _prune_recursive(self, node: SlotNode) -> int:
        """Mark node and all descendants as pruned. Returns count of pruned nodes."""
        count = 1
        node.state = SlotState.PRUNED
        node.disposition = SlotDisposition.PRUNE
        
        for child in node.children.values():
            count += self._prune_recursive(child)
        
        return count
    
    def _execute_add_options(self, node: SlotNode, t: SlotTransformation) -> bool:
        """Add or update options for a slot."""
        if t.options:
            node.options.update(t.options)
        logger.debug(f"  [SlotGraph] Updated options: {node.slot_type}")
        return True
    
    def _execute_remove(self, node: SlotNode, t: SlotTransformation) -> bool:
        """Remove a single slot (not recursive)."""
        node.state = SlotState.PRUNED
        logger.debug(f"  [SlotGraph] Removed: {node.slot_type}")
        return True


# =============================================================================
# JBeam Output Writer
# =============================================================================

class SlotAwareJBeamWriter:
    """
    Generates adapted jbeam content using the slot graph as source of truth.
    
    Replaces scattered slot manipulation with graph-driven output generation.
    """
    
    def __init__(self, graph: SlotGraph):
        """
        Initialize writer.
        
        Args:
            graph: SlotGraph with executed transformations
        """
        self.graph = graph
    
    def generate_slots_section(self, parent_part_name: str) -> List:
        """
        Generate the slots array for a part, applying all graph transformations.
        
        Args:
            parent_part_name: The part whose slots we're generating
            
        Returns:
            List of slot entries ready for jbeam output
        """
        parent_node = self.graph.by_part_name.get(parent_part_name)
        if not parent_node:
            logger.debug(f"  [SlotAwareWriter] No parent node for '{parent_part_name}' in by_part_name")
            return []
        
        slots = [["type", "default", "description"]]
        
        # Collect slots from graph (injected first, then children)
        slot_entries = []
        
        # Add injected slots that belong to this parent
        for slot_type, node in self.graph.by_slot_type.items():
            if (node.disposition == SlotDisposition.INJECT and 
                node.parent == parent_node):
                slot_entries.append(node)
        
        # Add existing children (non-pruned, non-SOURCE)
        for child_type, child_node in parent_node.children.items():
            if child_node.state == SlotState.PRUNED:
                continue  # Skip pruned slots
            if child_node.asset_role == AssetRole.SOURCE:
                continue  # Skip extraction-only slots (e.g., engine_structure)
            if child_node.disposition == SlotDisposition.INJECT:
                continue  # Already added above
            slot_entries.append(child_node)
        
        # Format slot entries
        for node in slot_entries:
            slots.append(self._format_slot_entry(node))
        
        return slots
    
    def _format_slot_entry(self, node: SlotNode) -> List:
        """Format a slot node as a jbeam slot entry."""
        entry = [
            node.slot_type,           # Transformed slot type
            node.default_part or "",  # Transformed default
            node.description
        ]
        
        if node.options:
            entry.append(node.options)
        
        return entry
    
    def get_adapted_slot_type(self, original_type: str) -> str:
        """Get the transformed slot type for an original type."""
        return self.graph.slot_type_map.get(original_type, original_type)
    
    def get_adapted_part_name(self, original_name: str) -> str:
        """Get the transformed part name for an original name."""
        return self.graph.part_name_map.get(original_name, original_name)
    
    def should_include_slot(self, slot_type: str) -> bool:
        """Check if a slot should be included in output."""
        node = self.graph.get_node(slot_type)
        if not node:
            return True  # Unknown slots pass through
        return not node.is_pruned()


# =============================================================================
# Manifest Generator
# =============================================================================

@dataclass
class SlotAssets:
    """Assets (meshes, textures, sounds) associated with a slot."""
    meshes: List[str] = field(default_factory=list)
    textures: List[str] = field(default_factory=list)
    sounds: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    
    def is_empty(self) -> bool:
        return not (self.meshes or self.textures or self.sounds or self.materials)
    
    def to_dict(self) -> Dict[str, List[str]]:
        result = {}
        if self.meshes:
            result["meshes"] = self.meshes
        if self.textures:
            result["textures"] = self.textures
        if self.sounds:
            result["sounds"] = self.sounds
        if self.materials:
            result["materials"] = self.materials
        return result


@dataclass  
class SlotManifestEntry:
    """Complete manifest entry for a single slot."""
    slot_type: str
    original_slot_type: str
    default_part: str
    original_default: str
    disposition: SlotDisposition
    state: SlotState
    description: str
    source_file: Optional[Path]
    requires_generation: bool  # True if this slot's jbeam needs adaptation
    assets: SlotAssets
    children: List[str]
    options: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "original_slot_type": self.original_slot_type,
            "default_part": self.default_part,
            "original_default": self.original_default,
            "disposition": self.disposition.value,
            "state": self.state.value,
            "description": self.description,
            "source_file": str(self.source_file) if self.source_file else None,
            "requires_generation": self.requires_generation,
            "assets": self.assets.to_dict(),
            "children": self.children,
            "options": self.options,
        }


class SlotAwareManifestGenerator:
    """
    Generate slot-centric packaging manifest from slot graph.
    
    This generator walks the slot dependency tree to build a comprehensive
    manifest that includes:
    - All required slots with their transformation states
    - Asset dependencies (meshes, textures, sounds) per slot
    - Clear copy plan separating original vs generated files
    - Minimum necessary files (excludes pruned subtrees)
    
    The manifest is designed to support automated mod packaging by providing
    complete traceability from slots to files.
    """
    
    def __init__(self, 
                 graph: SlotGraph, 
                 jbeam_parser: Optional[JBeamParserProtocol] = None,
                 output_base_path: Optional[Path] = None):
        """
        Initialize manifest generator.
        
        Args:
            graph: SlotGraph with executed transformations
            jbeam_parser: Optional parser for extracting assets from jbeam files
            output_base_path: Base path where generated files are written.
                              Used to compute output_path for generated_jbeam entries.
                              Format: {output_base_path}/{target_vehicle}_{source_stem}_adapted.jbeam
        """
        self.graph = graph
        self.jbeam_parser = jbeam_parser
        self.output_base_path = output_base_path
        self._asset_cache: Dict[Path, SlotAssets] = {}
    
    def generate(self) -> Dict[str, Any]:
        """
        Generate complete slot-centric packaging manifest.
        
        Returns:
            Manifest dict with:
            - required_slots: List of all non-pruned slots with assets
            - copy_plan: Categorized file lists for packaging
            - mappings: Slot type and part name transformations
            - statistics: Summary counts
            - validation: Graph validation results
        """
        logger.info("  [Manifest] Generating slot-aware manifest...")
        
        # Walk slot tree and build entries
        slot_entries = self._walk_slot_tree()
        
        # Build copy plan from entries
        copy_plan = self._build_copy_plan(slot_entries)
        
        # Build manifest
        manifest = {
            "version": "3.0",
            "target_vehicle": self.graph.target_vehicle,
            "donor_engine": self.graph.donor_engine,
            
            # Slot-centric dependency list
            "required_slots": [e.to_dict() for e in slot_entries],
            
            # Copy plan for packaging
            "copy_plan": copy_plan,
            
            # Transformation mappings
            "mappings": {
                "slot_types": dict(self.graph.slot_type_map),
                "part_names": dict(self.graph.part_name_map),
            },
            
            # Validation results
            "validation": self.graph.validate(),
            
            # Statistics
            "statistics": self._get_statistics(slot_entries, copy_plan),
        }
        
        logger.info(f"  [Manifest] Generated: {len(slot_entries)} slots, "
                   f"{len(copy_plan['original_jbeam'])} original files, "
                   f"{len(copy_plan['generated_jbeam'])} generated files")
        
        return manifest
    
    def _walk_slot_tree(self) -> List[SlotManifestEntry]:
        """
        Walk the slot tree and build manifest entries for exportable slots.
        
        Filters out:
        - Pruned slots
        - SOURCE-role slots (extraction-only, not exported)
        - INTERNAL-role slots (processing artifacts)
        
        Returns:
            List of SlotManifestEntry for each exportable slot
        """
        entries = []
        
        # Find root slot (the engine slot)
        root = self._find_root_slot()
        if not root:
            logger.warning("  [Manifest] No root slot found")
            return entries
        
        # BFS walk from root
        visited: Set[str] = set()
        queue = [root]
        
        while queue:
            node = queue.pop(0)
            
            if node.slot_type in visited:
                continue
            visited.add(node.slot_type)
            
            # Skip pruned slots
            if node.is_pruned():
                continue
            
            # Skip SOURCE and INTERNAL role slots - they are for extraction only
            if node.asset_role in (AssetRole.SOURCE, AssetRole.INTERNAL):
                logger.debug(f"  [Manifest] Skipping {node.asset_role.value} slot: {node.slot_type}")
                # Still process children - they may be exportable
                for child in node.children.values():
                    if child.slot_type not in visited:
                        queue.append(child)
                continue
            
            # Extract assets for this slot
            assets = self._extract_assets(node)
            
            # Determine if this slot requires generation (adapted jbeam)
            requires_generation = node.disposition == SlotDisposition.ADAPT
            
            entry = SlotManifestEntry(
                slot_type=node.slot_type,
                original_slot_type=node.original_slot_type,
                default_part=node.default_part,
                original_default=node.original_default,
                disposition=node.disposition,
                state=node.state,
                description=node.description,
                source_file=node.source_file,
                requires_generation=requires_generation,
                assets=assets,
                children=[c.slot_type for c in node.children.values() if not c.is_pruned()],
                options=node.options,
            )
            entries.append(entry)
            
            # Queue children
            for child in node.children.values():
                if child.slot_type not in visited:
                    queue.append(child)
        
        return entries
    
    def _find_root_slot(self) -> Optional[SlotNode]:
        """Find the root slot (engine slot with no parent)."""
        for node in self.graph.by_slot_type.values():
            if node.parent is None and not node.is_pruned():
                return node
        return None
    
    def _extract_assets(self, node: SlotNode) -> SlotAssets:
        """
        Extract asset references (meshes, textures, sounds) from a slot's jbeam.
        
        Args:
            node: SlotNode to extract assets from
            
        Returns:
            SlotAssets with discovered asset references
        """
        assets = SlotAssets()
        
        if not node.source_file or not node.source_file.exists():
            return assets
        
        # Check cache
        if node.source_file in self._asset_cache:
            return self._asset_cache[node.source_file]
        
        # Parse the jbeam file if parser available
        if not self.jbeam_parser:
            return assets
        
        try:
            jbeam_data = self.jbeam_parser.parse_jbeam(node.source_file)
            if not jbeam_data:
                return assets
            
            # Look for parts that match this slot's default
            for part_name, part_data in jbeam_data.items():
                if not isinstance(part_data, dict):
                    continue
                
                # Extract flexbodies
                flexbodies = part_data.get('flexbodies', [])
                for fb in flexbodies:
                    if isinstance(fb, list) and len(fb) > 0:
                        # Skip header row
                        if fb[0] == 'mesh' or fb[0] == 'type':
                            continue
                        mesh_name = fb[0]
                        if isinstance(mesh_name, str) and mesh_name:
                            assets.meshes.append(mesh_name)
                
                # Extract props (similar structure)
                props = part_data.get('props', [])
                for prop in props:
                    if isinstance(prop, list) and len(prop) > 1:
                        # Skip header row
                        if prop[0] == 'func' or prop[0] == 'type':
                            continue
                        # Props have mesh in position 1 typically
                        if len(prop) > 1 and isinstance(prop[1], str):
                            mesh_ref = prop[1]
                            if mesh_ref and not mesh_ref.startswith('$'):
                                assets.meshes.append(mesh_ref)
                
                # Extract sounds (from mainEngine, etc.)
                main_engine = part_data.get('mainEngine', {})
                if isinstance(main_engine, dict):
                    for key, value in main_engine.items():
                        if 'sound' in key.lower() and isinstance(value, str):
                            assets.sounds.append(value)
                
                # Extract soundscape references
                soundscape = part_data.get('soundscape', [])
                for entry in soundscape:
                    if isinstance(entry, dict):
                        for key, value in entry.items():
                            if isinstance(value, str) and ('/' in value or value.endswith('.ogg')):
                                assets.sounds.append(value)
            
            # Deduplicate
            assets.meshes = list(dict.fromkeys(assets.meshes))
            assets.textures = list(dict.fromkeys(assets.textures))
            assets.sounds = list(dict.fromkeys(assets.sounds))
            
            # Cache result
            self._asset_cache[node.source_file] = assets
            
        except Exception as e:
            logger.debug(f"  [Manifest] Failed to extract assets from {node.source_file}: {e}")
        
        return assets
    
    def _build_copy_plan(self, entries: List[SlotManifestEntry]) -> Dict[str, Any]:
        """
        Build the copy plan categorizing files by type and handling.
        
        Args:
            entries: List of slot manifest entries
            
        Returns:
            Copy plan dict with categorized file lists including:
            - original_jbeam: Files to copy as-is (PRESERVE/INJECT disposition)
            - generated_jbeam: Adapted files with computed output_path
            - asset_files: Referenced meshes, textures, sounds
            - excluded_files: Pruned files with reasons
        """
        plan = {
            "original_jbeam": [],      # Camso jbeam files to copy as-is (PRESERVE slots)
            "generated_jbeam": [],     # Adapted jbeam files we created (ADAPT slots)
            "asset_files": {
                "meshes": [],
                "textures": [],
                "sounds": [],
            },
            "excluded_files": [],      # Files excluded due to pruning
        }
        
        seen_files: Set[str] = set()
        seen_meshes: Set[str] = set()
        seen_sounds: Set[str] = set()
        
        for entry in entries:
            # Handle jbeam files
            if entry.source_file:
                file_str = str(entry.source_file)
                if file_str not in seen_files:
                    seen_files.add(file_str)
                    
                    file_info = {
                        "path": file_str,
                        "provides_slots": [entry.slot_type],
                        "disposition": entry.disposition.value,
                    }
                    
                    if entry.requires_generation:
                        # ADAPT disposition: we create an adapted version
                        output_path = self._compute_output_path(entry.source_file)
                        if output_path:
                            file_info["output_path"] = str(output_path)
                            file_info["output_filename"] = output_path.name
                        plan["generated_jbeam"].append(file_info)
                    elif entry.disposition == SlotDisposition.PRESERVE:
                        # PRESERVE disposition: copy original file as-is
                        plan["original_jbeam"].append(file_info)
                    # INJECT disposition: content is injected into adapted files,
                    # so source file is NOT added to either list (no copy needed)
                else:
                    # File already added, append this slot to provides_slots
                    for f in plan["original_jbeam"] + plan["generated_jbeam"]:
                        if f["path"] == file_str:
                            f["provides_slots"].append(entry.slot_type)
                            break
            
            # Collect asset files
            for mesh in entry.assets.meshes:
                if mesh not in seen_meshes:
                    seen_meshes.add(mesh)
                    plan["asset_files"]["meshes"].append({
                        "name": mesh,
                        "from_slot": entry.slot_type,
                    })
            
            for sound in entry.assets.sounds:
                if sound not in seen_sounds:
                    seen_sounds.add(sound)
                    plan["asset_files"]["sounds"].append({
                        "name": sound,
                        "from_slot": entry.slot_type,
                    })
        
        # Add pruned files
        for file_path, nodes in self.graph.by_source_file.items():
            if all(n.state == SlotState.PRUNED for n in nodes):
                plan["excluded_files"].append({
                    "path": str(file_path),
                    "reason": "all_slots_pruned",
                    "pruned_slots": [n.slot_type for n in nodes],
                })
        
        # Add additional generated files not tracked in slot tree
        # (e.g., alternate transmission variants like sequential)
        generated_paths = {Path(f.get("output_path", "")) for f in plan["generated_jbeam"] if f.get("output_path")}
        for gen_file in self.graph.generated_files:
            if gen_file not in generated_paths:
                plan["generated_jbeam"].append({
                    "path": "",  # No source file - generated separately
                    "provides_slots": [],  # Alternate variant for existing slot
                    "disposition": "adapt",
                    "output_path": str(gen_file),
                    "output_filename": gen_file.name,
                    "note": "additional_variant",
                })
        
        return plan
    
    def _compute_output_path(self, source_file: Path) -> Optional[Path]:
        """
        Compute the output path for a generated file.
        
        Uses the same naming convention as engineswap.py:
        {output_base_path}/{target_vehicle}_{source_stem}_adapted.jbeam
        
        Args:
            source_file: Original source file path
            
        Returns:
            Computed output path, or None if output_base_path not set
        """
        if not self.output_base_path:
            return None
        
        target_vehicle = self.graph.target_vehicle
        if not target_vehicle:
            return None
        
        source_stem = Path(source_file).stem
        output_filename = f"{target_vehicle}_{source_stem}_adapted.jbeam"
        return self.output_base_path / output_filename
    
    def validate_generated_files(self) -> Dict[str, Any]:
        """
        Validate that computed output paths match actual generated files.
        
        Returns:
            Dict with validation results:
            - valid: bool indicating all files match
            - matched: list of files that exist at computed paths
            - missing: list of files computed but not found
            - extra: list of files found but not in manifest
        """
        results = {
            "valid": True,
            "matched": [],
            "missing": [],
            "extra": [],
        }
        
        if not self.output_base_path or not self.output_base_path.exists():
            results["valid"] = False
            results["error"] = "output_base_path not set or doesn't exist"
            return results
        
        # Get computed output paths from generated entries
        entries = self._walk_slot_tree()
        expected_files = set()
        
        for entry in entries:
            if entry.requires_generation and entry.source_file:
                output_path = self._compute_output_path(entry.source_file)
                if output_path:
                    expected_files.add(output_path)
        
        # Check which files actually exist
        actual_files = set(self.output_base_path.glob("*_adapted.jbeam"))
        
        for expected in expected_files:
            if expected.exists():
                results["matched"].append(str(expected))
            else:
                results["missing"].append(str(expected))
                results["valid"] = False
        
        # Find extra files not in manifest
        for actual in actual_files:
            if actual not in expected_files:
                results["extra"].append(str(actual))
        
        return results
    
    def resolve_physical_assets(self, mod_root: Path, copy_plan: Dict) -> Dict[str, List[Dict]]:
        """
        Resolve mesh/texture/sound names from copy_plan to actual physical files.
        
        This method provides post-transform asset enumeration by:
        1. Using mesh names already captured in copy_plan.asset_files
        2. Scanning DAE files in mod_root for mesh name references
        3. Returning only DAE files that contain referenced meshes
        
        This ensures only assets needed for the transformed output are included,
        filtering out unrelated files like bodymesh.dae, suspension files, etc.
        
        Args:
            mod_root: Root path of the donor mod folder
            copy_plan: Copy plan dict containing asset_files.meshes with names
            
        Returns:
            Dict with resolved physical asset files:
            - meshes: List of {name, path, full_path, provides_meshes}
            - textures: List of {path, full_path}  
            - sounds: List of {path, full_path}
        """
        resolved = {
            "meshes": [],
            "textures": [],
            "sounds": [],
        }
        
        # Get mesh names from copy_plan (these came from slot graph assets)
        mesh_names = {m.get("name") for m in copy_plan.get("asset_files", {}).get("meshes", [])}
        sound_names = {s.get("name") for s in copy_plan.get("asset_files", {}).get("sounds", [])}
        
        if not mesh_names and not sound_names:
            logger.debug("  [AssetResolver] No mesh/sound references to resolve")
            return resolved
        
        logger.debug(f"  [AssetResolver] Resolving {len(mesh_names)} mesh references, {len(sound_names)} sound references")
        
        # === RESOLVE MESHES ===
        # Build DAE file index: scan content for referenced mesh names
        dae_files = list(mod_root.glob("**/*.dae")) + list(mod_root.glob("**/*.cdae"))
        matched_dae_files: Dict[Path, List[str]] = {}  # dae_path -> list of meshes it provides
        
        for dae_file in dae_files:
            try:
                # Read DAE content and search for mesh name references
                content = dae_file.read_text(encoding='utf-8', errors='replace')
                provides_meshes = []
                
                for mesh_name in mesh_names:
                    if mesh_name and mesh_name in content:
                        provides_meshes.append(mesh_name)
                
                if provides_meshes:
                    matched_dae_files[dae_file] = provides_meshes
                    logger.debug(f"  [AssetResolver] {dae_file.name} provides: {provides_meshes}")
                    
            except Exception as e:
                logger.debug(f"  [AssetResolver] Failed to read {dae_file}: {e}")
        
        # Build resolved mesh list
        for dae_path, meshes_provided in matched_dae_files.items():
            try:
                rel_path = dae_path.relative_to(mod_root)
            except ValueError:
                rel_path = dae_path
            
            resolved["meshes"].append({
                "name": dae_path.stem,
                "path": str(rel_path),
                "full_path": str(dae_path),
                "provides_meshes": meshes_provided,
            })
        
        # === RESOLVE TEXTURES ===
        # For textures, include those that share prefix with resolved meshes
        # This is a heuristic: ec8ba_mesh.dae likely uses ec8ba_*.dds textures
        mesh_prefixes = set()
        for dae_path in matched_dae_files.keys():
            # Extract prefix from DAE filename (e.g., "ec8ba" from "ec8ba_mesh.dae")
            stem = dae_path.stem
            if '_' in stem:
                prefix = stem.split('_')[0]
                mesh_prefixes.add(prefix)
        
        texture_files = list(mod_root.glob("**/*.dds")) + list(mod_root.glob("**/*.png"))
        resolved_texture_paths = set()  # Track full_paths to avoid duplicates
        
        for tex_file in texture_files:
            tex_stem = tex_file.stem.lower()
            # Include texture if it matches any mesh prefix
            for prefix in mesh_prefixes:
                if tex_stem.startswith(prefix.lower()):
                    try:
                        rel_path = tex_file.relative_to(mod_root)
                    except ValueError:
                        rel_path = tex_file
                    resolved["textures"].append({
                        "path": str(rel_path),
                        "full_path": str(tex_file),
                    })
                    resolved_texture_paths.add(str(tex_file))
                    break  # Only add once
        
        # === MATERIALS.JSON TEXTURE DISCOVERY ===
        # Parse {prefix}.materials.json files to discover additional textures
        # that don't share the mesh prefix (e.g., camso_*.dds referenced by 036a5.materials.json)
        for prefix in mesh_prefixes:
            # Search for materials.json in same folder as DAE files and parent folders
            mat_candidates = list(mod_root.glob(f"**/{prefix}.materials.json"))
            for mat_file in mat_candidates:
                try:
                    mat_text = mat_file.read_text(encoding='utf-8', errors='replace')
                    # Extract all .dds/.png filenames referenced in the materials file
                    referenced_textures = set(re.findall(r'[\w.]+\.(?:dds|png)', mat_text))
                    mat_dir = mat_file.parent
                    
                    for tex_name in referenced_textures:
                        tex_path = mat_dir / tex_name
                        if tex_path.exists() and str(tex_path) not in resolved_texture_paths:
                            try:
                                rel_path = tex_path.relative_to(mod_root)
                            except ValueError:
                                rel_path = tex_path
                            resolved["textures"].append({
                                "path": str(rel_path),
                                "full_path": str(tex_path),
                            })
                            resolved_texture_paths.add(str(tex_path))
                            
                    if referenced_textures:
                        newly_added = len(referenced_textures)
                        logger.debug(f"  [AssetResolver] {mat_file.name}: {newly_added} texture references parsed")
                        
                except Exception as e:
                    logger.debug(f"  [AssetResolver] Failed to parse {mat_file}: {e}")
        
        # === RESOLVE SOUNDS ===
        # For sounds, scan audio folders for referenced sound configs
        # Include .ogg/.wav audio samples and .sfxBlend2D.json blend definition files
        sound_files = (
            list(mod_root.glob("**/*.ogg"))
            + list(mod_root.glob("**/*.wav"))
            + list(mod_root.glob("**/*.sfxBlend2D.json"))
        )
        for sound_file in sound_files:
            try:
                rel_path = sound_file.relative_to(mod_root)
            except ValueError:
                rel_path = sound_file
            resolved["sounds"].append({
                "path": str(rel_path),
                "full_path": str(sound_file),
            })
        
        logger.info(f"  [AssetResolver] Resolved: {len(resolved['meshes'])} meshes, "
                   f"{len(resolved['textures'])} textures, {len(resolved['sounds'])} sounds")
        
        return resolved
    
    def _get_statistics(self, entries: List[SlotManifestEntry], copy_plan: Dict) -> Dict[str, Any]:
        """Generate manifest statistics."""
        dispositions = {}
        states = {}
        
        for entry in entries:
            d = entry.disposition.value
            s = entry.state.value
            dispositions[d] = dispositions.get(d, 0) + 1
            states[s] = states.get(s, 0) + 1
        
        return {
            "total_slots": len(entries),
            "by_disposition": dispositions,
            "by_state": states,
            "original_jbeam_files": len(copy_plan["original_jbeam"]),
            "generated_jbeam_files": len(copy_plan["generated_jbeam"]),
            "excluded_files": len(copy_plan["excluded_files"]),
            "mesh_count": len(copy_plan["asset_files"]["meshes"]),
            "sound_count": len(copy_plan["asset_files"]["sounds"]),
            "transformations_applied": len(self.graph.transformations),
        }
    
    # Legacy method for backwards compatibility
    def generate_legacy(self) -> Dict[str, Any]:
        """Generate manifest in legacy v2.0 format for backwards compatibility."""
        manifest = {
            "version": "2.0",
            "target_vehicle": self.graph.target_vehicle,
            "donor_engine": self.graph.donor_engine,
            "slot_graph": self._serialize_slot_graph_legacy(),
            "transformations": self._serialize_transformations(),
            "mappings": {
                "slot_types": dict(self.graph.slot_type_map),
                "part_names": dict(self.graph.part_name_map),
            },
            "files": {
                "donor_files": [str(f) for f in self.graph.donor_files],
                "generated_files": [str(f) for f in self.graph.generated_files],
                "required_files": self._get_required_files_legacy(),
                "pruned_files": self._get_pruned_files_legacy(),
            },
            "validation": self.graph.validate(),
            "statistics": self._get_statistics_legacy(),
        }
        return manifest
    
    def _serialize_slot_graph_legacy(self) -> Dict:
        """Serialize slot graph for legacy manifest output."""
        nodes = {}
        for slot_type, node in self.graph.by_slot_type.items():
            nodes[slot_type] = {
                "original_type": node.original_slot_type,
                "default": node.default_part,
                "original_default": node.original_default,
                "description": node.description,
                "disposition": node.disposition.value,
                "state": node.state.value,
                "children": list(node.children.keys()),
                "parent": node.parent.slot_type if node.parent else None,
                "source_file": str(node.source_file) if node.source_file else None,
                "options": node.options,
            }
        return nodes
    
    def _serialize_transformations(self) -> List[Dict]:
        """Serialize transformations for manifest output."""
        return [t.to_dict() for t in self.graph.transformations]
    
    def _get_required_files_legacy(self) -> List[Dict]:
        """Get list of files required (legacy format)."""
        required = []
        seen_files: Set[Path] = set()
        
        for node in self.graph.by_slot_type.values():
            if node.state == SlotState.PRUNED:
                continue
            if node.source_file and node.source_file not in seen_files:
                seen_files.add(node.source_file)
                file_slots = self.graph.by_source_file.get(node.source_file, [])
                active_slots = [s.slot_type for s in file_slots if not s.is_pruned()]
                required.append({
                    "path": str(node.source_file),
                    "provides_slots": active_slots,
                    "disposition": node.disposition.value
                })
        return required
    
    def _get_pruned_files_legacy(self) -> List[str]:
        """Get files that can be excluded (legacy format)."""
        pruned_files = []
        for file_path, nodes in self.graph.by_source_file.items():
            if all(n.state == SlotState.PRUNED for n in nodes):
                pruned_files.append(str(file_path))
        return pruned_files
    
    def _get_statistics_legacy(self) -> Dict:
        """Get graph statistics (legacy format)."""
        dispositions = {}
        states = {}
        for node in self.graph.by_slot_type.values():
            d = node.disposition.value
            s = node.state.value
            dispositions[d] = dispositions.get(d, 0) + 1
            states[s] = states.get(s, 0) + 1
        return {
            "total_slots": len(self.graph.by_slot_type),
            "active_slots": len(self.graph.get_active_slots()),
            "donor_files": len(self.graph.donor_files),
            "transformations": len(self.graph.transformations),
            "by_disposition": dispositions,
            "by_state": states,
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def build_slot_graph(
    target_vehicle: str,
    donor_files: List[Union[Path, str]],
    jbeam_parser: Optional[JBeamParserProtocol] = None
) -> SlotGraph:
    """
    Convenience function to build a slot graph from donor files.
    
    Args:
        target_vehicle: Name of target vehicle
        donor_files: List of paths to donor jbeam files (Path or string)
        jbeam_parser: JBeam parser implementing JBeamParserProtocol (required)
        
    Returns:
        Constructed SlotGraph
        
    Raises:
        ParserNotAvailableError: If jbeam_parser is not provided
    """
    if jbeam_parser is None:
        raise ParserNotAvailableError(
            "jbeam_parser is required - pass JBeamParser from engineswap.py"
        )
    builder = SlotGraphBuilder(target_vehicle, jbeam_parser)
    for f in donor_files:
        builder.add_donor_file(f)
    return builder.build()


def plan_and_execute_transformations(
    graph: SlotGraph,
    target_vehicle: str,
    config: Optional[Dict] = None,
    validate: bool = True,
    slot_type_prefix: Optional[str] = None,
    target_mount_slot_type: Optional[str] = None
) -> SlotGraph:
    """
    Convenience function to plan and execute all transformations.
    
    Args:
        graph: SlotGraph to transform
        target_vehicle: Name of target vehicle
        config: Optional configuration dict with slot_rules section
        validate: If True, validate graph after execution
        slot_type_prefix: Optional family prefix for slot types (e.g. "etk"
            for etk800). Derived from engine_slot_type to support vehicles
            with shared/family drivetrain slot types.
        target_mount_slot_type: Dynamically discovered enginemounts slot type
            from target engine files (e.g. "etk_enginemounts").
        
    Returns:
        Transformed SlotGraph
    """
    rules = SlotDispositionRules(config)
    
    planner = SlotTransformationPlanner(graph, target_vehicle, rules,
                                         slot_type_prefix=slot_type_prefix,
                                         target_mount_slot_type=target_mount_slot_type)
    planner.plan()
    
    executor = SlotTransformationExecutor(graph)
    executor.execute_all()
    
    if validate:
        result = graph.validate()
        if result['errors']:
            logger.warning(f"  [SlotGraph] Validation errors: {result['errors']}")
    
    return graph


# =============================================================================
# Module Info
# =============================================================================

__all__ = [
    # Protocol
    'JBeamParserProtocol',
    
    # Exceptions
    'SlotGraphError',
    'ParserNotAvailableError',
    'InvalidStateTransitionError',
    'SlotNotFoundError',
    'MalformedJBeamError',
    
    # Constants
    'VALID_STATE_TRANSITIONS',
    
    # Enums
    'SlotState',
    'SlotDisposition', 
    'TransformOp',
    'AssetRole',
    
    # Utility functions (suffix-agnostic slot handling)
    'extract_slot_suffix',
    'apply_slot_suffix',
    'match_slot_base',
    
    # Core classes
    'SlotNode',
    'SlotGraph',
    'SlotTransformation',
    
    # Manifest data classes
    'SlotAssets',
    'SlotManifestEntry',
    
    # Builder and processors
    'SlotGraphBuilder',
    'SlotDispositionRules',
    'SlotTransformationPlanner',
    'SlotTransformationExecutor',
    
    # Output generators
    'SlotAwareJBeamWriter',
    'SlotAwareManifestGenerator',
    
    # Convenience functions
    'build_slot_graph',
    'plan_and_execute_transformations',
]
