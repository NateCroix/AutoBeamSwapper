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

## Node Mapping (Single Source of Truth: EngineCube.CAMSO_TO_BEAMNG_MAP)

```
CAMSO → BEAMNG
═══════════════════════════════════════
engine0  →  e2r   (Front-Right-Bottom)
engine1  →  e2l   (Front-Left-Bottom)
engine2  →  e1l   (Rear-Left-Bottom)
engine3  →  e1r   (Rear-Right-Bottom)
engine4  →  e4r   (Front-Right-Top)
engine5  →  e4l   (Front-Left-Top)
engine6  →  e3l   (Rear-Left-Top)
engine7  →  e3r   (Rear-Right-Top)
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
