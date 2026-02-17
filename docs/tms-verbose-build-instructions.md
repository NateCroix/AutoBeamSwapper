# Transplant Mounting Solver (TMS) - Reference Documentation

This document provides reference information for AI agents working with the TMS module.
See `docs/lessons_learned.md` for critical conventions.

**Status:** TMS is implemented in `scripts/mount_solver.py`

---

## CRITICAL: Camso Engine File Structure

**Camso/Automation engines ALWAYS separate physics nodes from engine logic:**

| File | Contains | Example |
|------|----------|--------|
| `camso_engine_<variant>.jbeam` | Engine logic (torque curve, thermal, powertrain) | `camso_engine_3813e.jbeam` |
| `camso_engine_structure_<variant>.jbeam` | Physics nodes (engine0-7, beams) | `camso_engine_structure_ec8ba.jbeam` |

The main engine file references the structure via slot:
```jbeam
["Camso_engine_structure", "Camso_engine_structure_ec8ba", "Engine Structure", {"coreSlot": true}]
```

**When extracting donor engine geometry, TMS must:**
1. Parse the main engine file to find the `Camso_engine_structure` slot reference
2. Locate and parse the corresponding `camso_engine_structure_*.jbeam` file
3. Extract nodes (engine0-7) from the structure file, NOT the main engine file

---

## Module Structure

```
scripts/mount_solver.py          # TMS implementation (~1328 lines)
scripts/engineswap.py            # Main utility - imports TMS
docs/swap_parameter_readme.md    # User parameter documentation
configs/swap_parameters.json     # User configuration
```

---

## Key Classes (mount_solver.py)

### Data Structures
- `Vec3` - 3D vector/position in BeamNG coordinate space
- `EngineNode` - Single engine physics node with position and attributes
- `EngineCube` - 8-node bounding box with transformation methods
- `MountResult` - Solver output (translated nodes, beams, warnings)

### Core Functions
```python
# Primary solver entry point
result = solve_engine_mount(
    donor_cube: EngineCube,      # 8 translated donor nodes
    target_cube: EngineCube,     # 8 target vehicle reference nodes  
    user_offset: Vec3 = Vec3(0,0,0),  # User adjustment
    align_flywheel: bool = True
) -> MountResult

# Beam generation for mount connections
beams = generate_engine_beams(
    engine_nodes: List[EngineNode],  # Translated engine nodes
    target_mount_nodes: List[str]    # ["em1l", "em1r"] etc.
) -> List[List]
```

---

## Longitudinal Node Mapping (Single Source of Truth: EngineCube.CAMSO_TO_BEAMNG_MAP)

```
CAMSO → (BEAMNG - Longitudinal) (Validated Feb 2026, BeamNG numeric order)
═══════════════════════════════════════════════════════════
engine2  →  e1l   (Rear-Left-Bottom)
engine3  →  e1r   (Rear-Right-Bottom)
engine1  →  e2l   (Front-Left-Bottom)
engine0  →  e2r   (Front-Right-Bottom)
engine6  →  e3l   (Rear-Left-Top)
engine7  →  e3r   (Rear-Right-Top)
engine5  →  e4l   (Front-Left-Top)
engine4  →  e4r   (Front-Right-Top)
```

---

## JBeam Node Output Format

**Correct property modifier pattern:**
```jbeam
"nodes": [
    ["id", "posX", "posY", "posZ"],
    {"nodeWeight": 33.0109},              // ← Modifier (applies to all below)
    {"frictionCoef": 0.5},
    {"nodeMaterial": "|NM_METAL"},
    {"collision": true},
    {"group": "engine"},
    {"selfCollision": false},
    ["e2r", -0.252, -1.579, 0.486, {"engineGroup": ["engine_block"]}],  // ← Only inline-specific props
    ["e2l",  0.252, -1.579, 0.486, {"engineGroup": ["engine_block"]}]
]
```

**Properties that go in modifiers:** nodeWeight, frictionCoef, nodeMaterial, collision, group, selfCollision  
**Properties that stay inline:** engineGroup, isExhaust, tag (node-specific)

---

## Coordinate System

BeamNG uses right-handed coordinates (from driver's perspective):
- **X** = Lateral (positive = passenger side / right)
- **Y** = Longitudinal (positive = rear / backward)
- **Z** = Vertical (positive = up)

---

## Common Integration Issues

1. **Missing structure slot chain** - Structure file provides mesh/exhaust child slots, not just physics nodes
2. **torqueReactionNodes not translated** - Must convert engine0-7 → e1l-e4r in mainEngine section
3. **Duplicate nodes** - If TMS embeds nodes, structure slot must be neutralized or adapted

---

*Last Updated: Based on mount_solver.py implementation*  
*For patterns and conventions, see `docs/lessons_learned.md`*

# ============================================================
# BeamNG uses right-handed coordinate system:
#   X = lateral (positive = passenger side / right)
#   Y = longitudinal (positive = rear / backward)  
#   Z = vertical (positive = up)
#
# All positions from driver's perspective facing forward.
# ============================================================

@dataclass
class Vec3:
    """3D vector/position in BeamNG coordinate space."""
    x: float  # Lateral: + = right (passenger side)
    y: float  # Longitudinal: + = rear (toward trunk)
    z: float  # Vertical: + = up
    
    def __add__(self, other: 'Vec3') -> 'Vec3':
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __sub__(self, other: 'Vec3') -> 'Vec3':
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)
    
    def to_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)
    
    def to_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


@dataclass
class EngineNode:
    """Single engine physics node."""
    id: str                    # Node identifier (e.g., "engine0", "e1l")
    position: Vec3             # 3D position
    node_weight: float = 0.0   # Node mass in kg
    engine_group: List[str] = field(default_factory=list)  # e.g., ["engine_block"]
    attributes: Dict = field(default_factory=dict)  # Additional properties


@dataclass
class EngineCube:
    """
    The 8 nodes defining an engine's bounding box.
    
    Node positions form a rectangular prism:
    
         e4l(FL-Top) ─────── e4r(FR-Top)
          /│              /│
         / │             / │
        e3l(RL-Top)──────e3r(RR-Top)
        │  │            │  │
        │  e2l(FL-Bot)────│──e2r(FR-Bot)
        │ /             │ /
        │/              │/
        e1l(RL-Bot)──────e1r(RR-Bot)
    
    Where: F=Front, R=Rear, L=Left, R=Right
    """
    # Bottom face (lower Z)
    front_right_bottom: EngineNode  # Camso: engine0, BeamNG: e2r
    front_left_bottom: EngineNode   # Camso: engine1, BeamNG: e2l
    rear_left_bottom: EngineNode    # Camso: engine2, BeamNG: e1l
    rear_right_bottom: EngineNode   # Camso: engine3, BeamNG: e1r
    
    # Top face (higher Z)
    front_right_top: EngineNode     # Camso: engine4, BeamNG: e4r
    front_left_top: EngineNode      # Camso: engine5, BeamNG: e4l
    rear_left_top: EngineNode       # Camso: engine6, BeamNG: e3l
    rear_right_top: EngineNode      # Camso: engine7, BeamNG: e3r
    
    def get_all_nodes(self) -> List[EngineNode]:
        """Return all 8 nodes as list."""
        return [
            self.front_right_bottom, self.front_left_bottom,
            self.rear_left_bottom, self.rear_right_bottom,
            self.front_right_top, self.front_left_top,
            self.rear_left_top, self.rear_right_top
        ]
    
    def get_centroid(self) -> Vec3:
        """Calculate geometric center of engine cube."""
        nodes = self.get_all_nodes()
        x = sum(n.position.x for n in nodes) / 8
        y = sum(n.position.y for n in nodes) / 8
        z = sum(n.position.z for n in nodes) / 8
        return Vec3(x, y, z)
    
    def get_flywheel_plane_nodes(self) -> List[EngineNode]:
        """Return the 4 rearmost nodes (flywheel/transmission interface)."""
        return [
            self.rear_left_bottom, self.rear_right_bottom,
            self.rear_left_top, self.rear_right_top
        ]
    
    def get_floor_plane_nodes(self) -> List[EngineNode]:
        """Return the 4 bottom nodes (engine floor)."""
        return [
            self.front_right_bottom, self.front_left_bottom,
            self.rear_left_bottom, self.rear_right_bottom
        ]
    
    def get_bounding_box(self) -> Tuple[Vec3, Vec3]:
        """Return (min_corner, max_corner) of axis-aligned bounding box."""
        nodes = self.get_all_nodes()
        min_x = min(n.position.x for n in nodes)
        min_y = min(n.position.y for n in nodes)
        min_z = min(n.position.z for n in nodes)
        max_x = max(n.position.x for n in nodes)
        max_y = max(n.position.y for n in nodes)
        max_z = max(n.position.z for n in nodes)
        return (Vec3(min_x, min_y, min_z), Vec3(max_x, max_y, max_z))


@dataclass  
class MountNode:
    """Engine mount interface node (emxx type)."""
    id: str           # e.g., "em1l", "em1r", "tra1"
    position: Vec3
    mount_type: str   # "engine_mount" or "transmission_mount"
    node_weight: float = 0.0


class ShrinkExpandOption(Enum):
    """Interference resolution strategies."""
    NONE = "none"
    SHRINK_ENGINE_BLOCK = "shrink_engine_block"
    EXPAND_ENGINE_MOUNTS = "expand_engine_mounts"


@dataclass
class SwapParameters:
    """User-configurable solver parameters."""
    fix_mesh_offset: bool = False
    shrink_or_expand: ShrinkExpandOption = ShrinkExpandOption.NONE
    fore_aft_offset: float = 0.0    # meters, + = rearward
    up_down_offset: float = 0.0     # meters, + = upward
    left_right_offset: float = 0.0  # meters, + = right
    
    # Limits
    max_shrink_percent: float = 15.0
    max_mount_expansion_m: float = 0.1
    min_mount_clearance_m: float = 0.02


@dataclass
class SolverResult:
    """Output from TMS calculation."""
    success: bool
    translation: Vec3                        # Total translation applied
    rotation_pitch: float = 0.0              # Pitch rotation in radians (if needed)
    translated_nodes: List[EngineNode] = field(default_factory=list)
    mount_nodes: List[MountNode] = field(default_factory=list)
    interference_detected: bool = False
    interference_resolution: str = ""
    warnings: List[str] = field(default_factory=list)
    debug_info: Dict = field(default_factory=dict)
```

---

## TMS Output Conventions

### Node Property Modifier Convention

**Problem Statement**

BeamNG .jbeam files support two ways to apply node properties:

1. **Property Modifier Rows** (preferred): A dictionary row applies to ALL subsequent nodes
2. **Inline Properties**: A dictionary on each node row applies only to that node

**Camso/Automation Source Pattern (Correct):**
```json
"nodes": [
    ["id", "posX", "posY", "posZ"],
    {"frictionCoef": 0.5},
    {"nodeMaterial": "|NM_METAL"},
    {"collision": true},
    {"group": "engine"},
    {"selfCollision": false},
    {"nodeWeight": 33.0109},
    ["engine0", -0.238129, -1.20428, 0.824838, {"engineGroup": ["engine_block"]}],
    ["engine1",  0.265992, -1.20428, 0.824838, {"engineGroup": ["engine_block"]}]
]
```

**Wrong Pattern (pre-fix):**
```json
"nodes": [
    ["id", "posX", "posY", "posZ"],
    {"group": "engine"},
    {"nodeWeight": 33.0109},
    ["e2r", -0.252061, -1.578731, 0.486494, {"nodeWeight": 33.0109, "engineGroup": ["engine_block"]}],
    ["e2l",  0.252061, -1.578731, 0.486494, {"nodeWeight": 33.0109, "engineGroup": ["engine_block"]}]
]
```

**Issues with Wrong Pattern:**

1. **Redundancy**: `nodeWeight` appears on every node instead of once
2. **File Size**: Larger files with repeated data
3. **Maintainability**: Changing weight requires editing every node
4. **Convention Violation**: Doesn't match BeamNG source files or Camso exports

### TMS Output Format (Required Convention)

**Property Categories**

**Modifier Row Properties** (emitted once, apply to all subsequent nodes):
- `frictionCoef` - Surface friction coefficient
- `nodeMaterial` - Physics material type
- `collision` - Whether node participates in collision
- `group` - Node group assignment (e.g., "engine")
- `selfCollision` - Whether group members can collide with each other
- `nodeWeight` - Mass of each node in kg

**Inline Properties** (vary per node, stay on node row):
- `engineGroup` - Engine component classification (e.g., `["engine_block"]`, `["engine_intake"]`)
- `isExhaust` - Exhaust attachment point marker (e.g., `"mainEngine"`)
- `tag` - Special node tags

**Output Structure Example:**

```json
"nodes": [
    ["id", "posX", "posY", "posZ"],
    {"frictionCoef": 0.5},
    {"nodeMaterial": "|NM_METAL"},
    {"collision": true},
    {"group": "engine"},
    {"selfCollision": false},
    {"nodeWeight": 33.0109},
    ["e2r", -0.252061, -1.578731, 0.486494, {"engineGroup": ["engine_block"]}],
    ["e2l",  0.252061, -1.578731, 0.486494, {"engineGroup": ["engine_block"]}],
    ["e1l",  0.252061, -1.211269, 0.486494, {"engineGroup": ["engine_block"], "isExhaust": "mainEngine"}],
    ["e1r", -0.252061, -1.211269, 0.486494, {"engineGroup": ["engine_block"]}],
    ["e4r", -0.252061, -1.578731, 0.823506, {"engineGroup": ["engine_block", "engine_intake"]}],
    ["e4l",  0.252061, -1.578731, 0.823506, {"engineGroup": ["engine_block"]}],
    ["e3l",  0.252061, -1.211269, 0.823506, {"engineGroup": ["engine_block"]}],
    ["e3r", -0.252061, -1.211269, 0.823506, {"engineGroup": ["engine_block", "engine_intake"]}]
]
```

### Implementation Requirements

**`_extract_common_node_properties()` Method**

Extracts common properties from engine cube nodes and returns them as an ordered list of property modifier dictionaries:

1. `{"frictionCoef": 0.5}` - Default for metal engine parts
2. `{"nodeMaterial": "|NM_METAL"}` - Engine block material
3. `{"collision": true}` - Engine participates in collision
4. `{"group": "engine"}` - Assigns to engine physics group
5. `{"selfCollision": false}` - Engine nodes don't self-collide
6. `{"nodeWeight": <extracted>}` - From donor or default 33.0109

**`_generate_clean_node_arrays()` Method**

Generates node arrays with only inline properties (engineGroup, isExhaust):

```python
INLINE_PROPERTIES = {'engineGroup', 'isExhaust', 'tag'}
MODIFIER_PROPERTIES = {'nodeWeight', 'frictionCoef', 'nodeMaterial', 
                       'collision', 'selfCollision', 'group'}
```

### Default Values

When properties are not found in the donor engine, TMS uses these defaults:

| Property | Default | Source |
|----------|---------|--------|
| frictionCoef | 0.5 | BeamNG engine convention |
| nodeMaterial | "\|NM_METAL" | BeamNG engine convention |
| collision | true | Standard for solid parts |
| group | "engine" | Required for engine physics |
| selfCollision | false | Prevents internal jitter |
| nodeWeight | 33.0109 | Camso reference average |

### Output Verification Checklist

To verify correct TMS output, check the generated file:

1. ✅ **Property modifier rows should appear ONCE** before node data rows
2. ✅ **Node rows should NOT have** `nodeWeight`, `frictionCoef`, etc.
3. ✅ **Node rows MAY have** `engineGroup`, `isExhaust` as inline properties
4. ✅ **All 8 engine nodes** (e1l, e1r, e2l, e2r, e3l, e3r, e4l, e4r) should be present

---

## Implementation Checklist

### Phase 1: Module Foundation
```
□ Create scripts/mount_solver.py with:
  □ Module docstring explaining purpose
  □ Import statements (dataclasses, typing, pathlib, numpy, logging)
  □ All dataclass definitions from above
  □ MountSolver class stub with __init__
  □ Logging setup matching engineswap.py pattern

□ Create configs/swap_parameters.json:
  □ Default parameter values
  □ JSON schema reference
  
□ Create docs/swap_parameter_readme.md:
  □ Parameter descriptions
  □ Usage examples
  □ Behavior explanations
```

### Phase 2: Node Extraction
```
□ Implement TargetVehicleExtractor class:
  □ Method: extract_engine_cube(jbeam_data) -> EngineCube
  □ Method: extract_mount_nodes(jbeam_data) -> List[MountNode]
  □ Method: extract_torque_reaction_nodes(jbeam_data) -> List[str]
  □ Handle missing nodes gracefully (log warning, use defaults)

□ Implement DonorEngineExtractor class:
  □ Method: extract_camso_engine_cube(jbeam_data) -> EngineCube
  □ Method: extract_gearbox_nodes(jbeam_data) -> List[EngineNode]
  □ Map Camso node naming to internal representation
```

### Phase 3: Geometry Utilities
```
□ Implement geometry helper functions:
  □ calculate_plane_centroid(nodes: List[EngineNode]) -> Vec3
  □ calculate_plane_normal(nodes: List[EngineNode]) -> Vec3
  □ point_in_aabb(point: Vec3, min: Vec3, max: Vec3) -> bool
  □ scale_nodes_about_centroid(nodes, scale_factor, centroid) -> List[EngineNode]
```

### Phase 4: Solver Core
```
□ Implement MountSolver.solve() method:
  □ Step 1: Calculate flywheel plane alignment translation
  □ Step 2: Calculate floor plane vertical adjustment
  □ Step 3: Apply user offsets from SwapParameters
  □ Step 4: Check for mount node interference
  □ Step 5: Apply shrink/expand if configured
  □ Step 6: Return SolverResult with all transformed nodes
```

### Phase 5: Output Generation
```
□ Implement output methods (MUST follow TMS Output Conventions):
  □ _extract_common_node_properties() -> List[Dict]
  □ _generate_clean_node_arrays() -> List[List]
  □ generate_nodes_section(result: SolverResult) -> List[List]
  □ generate_beams_section(result: SolverResult) -> List[List]
  □ Integrate with engineswap.py generate_adapted_jbeam()

□ Add to engineswap.py:
  □ Import mount_solver module
  □ Call MountSolver during generation
  □ Inject generated nodes/beams into adapted part
  □ Emit property modifier rows BEFORE node data
  □ Strip common properties from individual nodes
  
□ Verify output follows conventions:
  □ Use verify_node_output() function
  □ No inline nodeWeight on nodes
  □ 6 property modifier rows present
  □ All 8 engine nodes present
```

---

## Key Implementation Notes

### Node Extraction Pattern

When parsing nodes from JBeam:
```python
def extract_nodes_from_jbeam(jbeam_data: Dict, node_ids: List[str]) -> Dict[str, EngineNode]:
    """
    Extract specific nodes from JBeam data structure.
    
    JBeam nodes format:
    "nodes": [
        ["id", "posX", "posY", "posZ"],  # Header row
        {"group": "engine"},              # Property row
        ["e1l", 0.15, -0.8, 0.35, {...}], # Node definition
        ...
    ]
    """
    result = {}
    nodes_section = jbeam_data.get('nodes', [])
    
    current_properties = {}
    for row in nodes_section:
        if isinstance(row, dict):
            # Property row - update current state
            current_properties.update(row)
        elif isinstance(row, list) and len(row) >= 4:
            node_id = row[0]
            if node_id in node_ids:
                # Extract position
                pos = Vec3(float(row[1]), float(row[2]), float(row[3]))
                
                # Extract additional attributes if present
                attrs = row[4] if len(row) > 4 and isinstance(row[4], dict) else {}
                
                # Build node
                result[node_id] = EngineNode(
                    id=node_id,
                    position=pos,
                    node_weight=current_properties.get('nodeWeight', 0.0),
                    engine_group=attrs.get('engineGroup', []),
                    attributes=attrs
                )
    
    return result
```

### Plane Alignment Calculation

```python
def calculate_flywheel_alignment(
    donor_cube: EngineCube, 
    target_cube: EngineCube
) -> Vec3:
    """
    Calculate translation to align donor flywheel plane to target flywheel plane.
    
    For longitudinal engines, the flywheel plane is the rear face of the engine cube.
    We align the centroids of these planes.
    """
    # Get flywheel plane centroids
    donor_flywheel = donor_cube.get_flywheel_plane_nodes()
    target_flywheel = target_cube.get_flywheel_plane_nodes()
    
    donor_centroid = Vec3(
        sum(n.position.x for n in donor_flywheel) / 4,
        sum(n.position.y for n in donor_flywheel) / 4,
        sum(n.position.z for n in donor_flywheel) / 4
    )
    
    target_centroid = Vec3(
        sum(n.position.x for n in target_flywheel) / 4,
        sum(n.position.y for n in target_flywheel) / 4,
        sum(n.position.z for n in target_flywheel) / 4
    )
    
    # Translation needed to move donor to target
    return target_centroid - donor_centroid
```

### Interference Detection

```python
def check_mount_interference(
    mount_nodes: List[MountNode],
    engine_bbox: Tuple[Vec3, Vec3],
    clearance: float = 0.02
) -> List[MountNode]:
    """
    Check if any mount nodes are inside the engine bounding box.
    
    Returns list of mount nodes that have interference.
    """
    min_corner, max_corner = engine_bbox
    
    # Expand bbox by clearance for safety margin
    min_corner = Vec3(
        min_corner.x - clearance,
        min_corner.y - clearance, 
        min_corner.z - clearance
    )
    max_corner = Vec3(
        max_corner.x + clearance,
        max_corner.y + clearance,
        max_corner.z + clearance
    )
    
    conflicts = []
    for mount in mount_nodes:
        p = mount.position
        if (min_corner.x <= p.x <= max_corner.x and
            min_corner.y <= p.y <= max_corner.y and
            min_corner.z <= p.z <= max_corner.z):
            conflicts.append(mount)
    
    return conflicts
```

---

## Testing Strategy

### Unit Tests (Priority Order)

1. **Vec3 Operations**
   - Addition, subtraction
   - Conversion to/from tuple and array

2. **EngineCube Methods**
   - Centroid calculation with known positions
   - Bounding box calculation
   - Plane node extraction

3. **Node Extraction**
   - Parse pickup_engine_i6_4.1.jbeam → verify node positions
   - Parse camso_engine_structure_ec8ba.jbeam → verify node positions
   - Handle missing nodes

4. **Alignment Calculation**
   - Known donor/target → verify translation vector
   - Verify flywheel planes align after translation

5. **Interference Detection**
   - Mount inside bbox → detected
   - Mount outside bbox → not detected
   - Edge cases (on boundary)

### Integration Test

```python
def test_pickup_camso_swap():
    """
    End-to-end test: Camso engine → Pickup vehicle.
    Verify the engine would be physically mountable.
    """
    solver = MountSolver()
    
    # Load real files
    target = solver.load_target_vehicle("pickup")
    donor = solver.load_donor_engine("camso_engine_3813e")
    
    # Solve with default parameters
    result = solver.solve(donor, target, SwapParameters())
    
    # Assertions
    assert result.success
    assert len(result.translated_nodes) == 8  # Engine cube
    assert len(result.mount_nodes) >= 2        # At least em1l, em1r
    assert not result.interference_detected or result.interference_resolution != ""
```

---

## Common Pitfalls to Avoid

1. **Coordinate System Confusion**
   - Always use BeamNG conventions: X=lateral, Y=longitudinal, Z=vertical
   - Positive Y is REARWARD (toward trunk)
   - Document any coordinate transformations explicitly

2. **Node Naming Inconsistency**
   - Camso uses `engine0-7`, BeamNG uses `e1l, e2r`, etc.
   - Always work in internal representation, convert at I/O boundaries
   - Use the mapping table from README.md

3. **Missing Nodes**
   - Not all vehicles have all expected nodes
   - Always check for None/missing and provide fallbacks
   - Log warnings but don't crash

4. **JBeam Parsing**
   - JBeam allows comments (strip them)
   - JBeam allows trailing commas (handle them)
   - Use the existing JBeamParser class

5. **Floating Point Precision**
   - Node positions are in meters with high precision
   - Use appropriate epsilon (1e-6) for comparisons
   - Don't accumulate rounding errors across transformations

---

## Debugging Tips

1. **Enable Debug Output**
   ```python
   solver = MountSolver(debug=True)
   result = solver.solve(...)
   print(result.debug_info)  # Contains intermediate calculations
   ```

2. **Visualize in BeamNG**
   - Generate with `generate_debug_visualization: true`
   - Creates highlighted node markers for testing
   - Check node positions in debug mode (F11)

3. **Log Translation Steps**
   ```python
   logger.debug(f"Flywheel alignment translation: {translation_1}")
   logger.debug(f"Floor adjustment: {vertical_adj}")
   logger.debug(f"User offset: {user_offset}")
   logger.debug(f"Total translation: {total}")
   ```

---

## Success Criteria

The TMS implementation is complete when:

1. ✅ Camso engine can be mounted in Pickup vehicle
2. ✅ Engine stays attached to chassis (doesn't fall)
3. ✅ Flywheel aligns with transmission
4. ✅ No node interference warnings
5. ✅ User can adjust position via swap_parameters.json
6. ✅ Works with at least 2 different target vehicles
7. ✅ Comprehensive logging of solver decisions
8. ✅ All unit tests pass
9. ✅ **Output follows property modifier conventions** (no inline nodeWeight)
10. ✅ **verify_node_output()** passes for generated files

---

## Quick Reference: Node Mapping

```
CAMSO → BEAMNG (Validated Feb 2026, BeamNG numeric order)
════════════════════════════════════════════════════════════
engine2  →  e1l   (Rear-Left-Bottom)
engine3  →  e1r   (Rear-Right-Bottom)
engine1  →  e2l   (Front-Left-Bottom)
engine0  →  e2r   (Front-Right-Bottom)
engine6  →  e3l   (Rear-Left-Top)
engine7  →  e3r   (Rear-Right-Top)
engine5  →  e4l   (Front-Left-Top)
engine4  →  e4r   (Front-Right-Top)
────────────────────────────────────────────────────────────
(new)    →  em1l  (Mount-Left)
(new)    →  em1r  (Mount-Right)
(new)    →  tra1  (Transmission-Mount)
```

---

*Last Updated: February 4, 2026*  
*For main project documentation, see README.md*
