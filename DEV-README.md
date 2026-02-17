# AutoBeamSwapper BeamNG Engine Transplant Utility - Development Workspace

A comprehensive development environment for analyzing BeamNG engine swap mods and building an automated Automation > BeamNG engine transplant utility.

## Project Overview

This project aims to create a Python utility that can automatically transplant engines from Automation into BeamNG original content vehicles. The utility will analyze engine .jbeam files and adapt them to work with different vehicle frameworks used across BeamNG's base game vehicles.


## VScode Extensions used in this workspace:
JBeam Editor > beamng.jbeam-editor
Jbeam Syntax > useful-artifacts.jbeam-syntax


## Project Structure

```
├── mods/
│   ├── unpacked/
│   │   ├── engineswaps/vehicles/   # Target for new engine swap development
│   └── ...
├── SteamLibrary_content_vehicles/   # BeamNG base game vehicle files
├── vehicles/                        # Custom vehicle definitions
├── scripts/                         # Python scripts for automation
├── configs/                         # Configuration templates
├── docs/                            # Extended documentation
└── .github/                         # Workspace settings
```

---

## Current Implementation

### Python Modules

The utility consists of several Python modules working together:

#### `engineswap.py` - Main Orchestrator
- **Purpose:** Command-line interface and workflow orchestration
- **Key Features:**
  - Parses donor engine files (Camso/Automation format)
  - Adapts slot types and part names for target vehicles
  - Integrates Transplant Mounting Solver (TMS) for physical positioning
  - Generates complete mod packages with manifests
- **Integration:** Uses slot graph for unified slot dependency management

#### `mount_solver.py` - Transplant Mounting Solver (TMS)
- **Purpose:** Geometric solver for engine physical positioning
- **Key Features:**
  - Extracts engine nodes from donor structure files
  - Calculates transformations to fit target vehicle engine bay
  - Translates Camso node names to BeamNG conventions
  - Generates mount beams and torque reaction nodes
- **Status:** Implemented and validated

#### `slot_graph.py` - Unified Slot Management
- **Purpose:** Graph-based slot dependency tracking and transformation
- **Key Features:**
  - Models slot hierarchies as directed graphs
  - Provides single source of truth for slot state
  - Handles disposition rules (preserve/adapt/prune/inject)
  - Generates adapted JBeam slot sections and manifests
- **Status:** Phase 2 complete - integrated into main workflow

#### `jbeam_parser.py` - JBeam File Parser (Planned)
- **Purpose:** Comment-preserving JBeam parsing
- **Status:** Planned extraction from engineswap.py

### Configuration System

#### `swap_parameters.json` - User Configuration
- **Location:** `configs/swap_parameters.json`
- **Purpose:** User-tunable parameters for TMS positioning
- **Features:**
  - Path configuration (base directories, output locations)
  - Solver parameters (offsets, interference resolution)
  - Slot rules (pruning, preservation, adaptation)

#### Schema Validation
- **File:** `configs/schemas/swap_parameters.schema.json`
- **Purpose:** JSON Schema validation for configuration files

---

## JBEAM Indentation Best Practices
It is best to indent your Jbeam in a way that the node names and coordinates are aligned in columns. 

This way, whenever you need to change a value in many rows at once, you can use vertical selection (LEFT ALT + LMB in notepad++, SHIFT + ALT + LMB or use middle mouse button instead of left one in VS Code and related programs).

We have not yet implemented these indentation practices in all modules, some generated slots are still a mess.

---

## Critical: Engine Physical Mounting

### The Engine Mount Challenge

**Mounting arbitrary engine swaps is difficult** because Camso engines are willy-nilly connected to the rest of the Camso car, while BeamNG engines must be attached to the chassis through specific node/beam structures in order to maintain modular and cross-compatible powertrain components (engine,transmission,transfercase). Unlike slotType adaptation (which is logical), mounting requires precise physical alignment.

#### How Mounting Works in BeamNG

1. **Engine Nodes**: Engines define physics nodes (e.g., `em1l`, `em1r` for left/right mounts, `tra1` for transmission mount)
2. **Chassis Nodes**: Vehicles have frame nodes (e.g., `f2l`, `f2r`, `f3l`, `f3r`) where engines attach
3. **Mount Beams**: Special beams connect engine nodes to chassis nodes with spring/damping properties
4. **Engine Mount Slot**: Vehicles provide `{vehicle}_enginemounts` slot containing mount beams as the engine/chassis interface

#### The Cummins Mod Solution

The Cummins reference mod solves mounting by **using the target vehicle's mounting infrastructure**:

1. **Adds vehicle-specific enginemount slot**:
   ```jbeam
   ["pickup_enginemounts", "pickup_enginemounts_heavy", "Engine Mounts", {"coreSlot":true}]
   ```

2. **Defines engine nodes matching target vehicle's expectations**:
   - `em1l`, `em1r`: Engine mount points (left/right)
   - `tra1`: Transmission mount point
   - `e1l`, `e2l`, `e4r`: Torque reaction nodes (referenced in `torqueReactionNodes`)

3. **Positions nodes to align with chassis mount locations** (from donor vehicle's stock engine)

4. **Vehicle provides mount beams** via enginemounts slot that connects:
   ```jbeam
   ["em1r", "f3r"]  // Right engine mount to front-right chassis
   ["em1l", "f3l"]  // Left engine mount to front-left chassis
   ["tra1", "f14"]  // Transmission mount to frame
   ```

---

## Transplant Mounting Solver (TMS) - Technical Specification

### Overview

The **Transplant Mounting Solver (TMS)** is a heuristic geometry solver that calculates the necessary transformations to physically adapt a donor engine (Camso/Automation) to fit within a target vehicle's (BeamNG original) engine bay while maintaining realistic positioning and proper attachment to the chassis.

**Design Philosophy:** Rather than attempting pixel-perfect positioning, TMS aims for "pseudorealistic" engine placement that:
- Aligns transmission interfaces (flywheel planes)
- Respects engine bay floor constraints
- Maintains engine mount clearance
- Allows user fine-tuning via parameter file

### Node Naming Conventions

#### Camso/Automation Engine Structure Nodes
**Source File:** `Camso_engine_structure_<variant>.jbeam`  
**Engine Group:** `"engineGroup":"engine_block"`  
**Layout Reference:** Front-engine, longitudinal (RWD/AWD)

All positions described from driver's perspective, facing forward:

| Node ID | Position Description | Coordinate Role |
|---------|---------------------|-----------------|
| `engine0` | RH-side, Frontmost, Lower | Front-Right-Bottom |
| `engine1` | LH-side, Frontmost, Lower | Front-Left-Bottom |
| `engine2` | LH-side, Rearmost, Lower | Rear-Left-Bottom |
| `engine3` | RH-side, Rearmost, Lower | Rear-Right-Bottom |
| `engine4` | RH-side, Frontmost, Upper | Front-Right-Top |
| `engine5` | LH-side, Frontmost, Upper | Front-Left-Top |
| `engine6` | LH-side, Rearmost, Upper | Rear-Left-Top |
| `engine7` | RH-side, Rearmost, Upper | Rear-Right-Top |
| `engine_Gearbox8-11` | Transmission housing nodes | Gearbox attachment |

**Camso Convention Notes:**
- Engine cube nodes form bounding box around visual mesh
- Nodes may be offset from visual mesh centroid (for CoG tuning)
- Mesh position controlled via `$EngineOffsetXVis`, `$EngineOffsetYVis`, `$EngineOffsetZVis`
- Nodes connect to chassis via distributed beams to `Camso_Trim` / `a<>` body nodes

#### BeamNG Original Engine Structure Nodes
**Source File:** `{vehicle}_engine_*.jbeam` (embedded in engine part)  
**Engine Group:** `"engineGroup":"engine_block"`

| Node ID | Position Description | Coordinate Role |
|---------|---------------------|-----------------|
| `e1l` | LH-side, Rearmost, Lower | Rear-Left-Bottom |
| `e1r` | RH-side, Rearmost, Lower | Rear-Right-Bottom |
| `e2l` | LH-side, Frontmost, Lower | Front-Left-Bottom |
| `e2r` | RH-side, Frontmost, Lower | Front-Right-Bottom |
| `e3l` | LH-side, Rearmost, Upper | Rear-Left-Top |
| `e3r` | RH-side, Rearmost, Upper | Rear-Right-Top |
| `e4l` | LH-side, Frontmost, Upper | Front-Left-Top (special: yellow debug) |
| `e4r` | RH-side, Frontmost, Upper | Front-Right-Top (special: yellow debug) |

**Engine Mount Interface Nodes (`emxx` type):**

| Node ID | Position Description | Role |
|---------|---------------------|------|
| `em1l` | LH-side, Mid-height, Mid-length | Primary engine mount (driver side) |
| `em1r` | RH-side, Mid-height, Mid-length | Primary engine mount (passenger side) |
| `tra1` | Center, Transmission area | Transmission mount point |

**BeamNG Convention Notes:**
- Engine cube centroid = theoretical center of mass
- `emxx` nodes connect to engine cube via soft/flexible beams
- `emxx` nodes connect to chassis `f<>` nodes via `{vehicle}_enginemounts` slot
- Some vehicles use transmission mount (`tra1`) for triangulation
- Modern vehicles may have additional mount points

### Node Mapping: Camso → BeamNG (Validated Feb 2026, BeamNG Numeric Order)

```
CAMSO NODE    →    BEAMNG NODE    POSITION
──────────────────────────────────────────────────
engine2       →    e1l            Rear-Left-Bottom
engine3       →    e1r            Rear-Right-Bottom
engine1       →    e2l            Front-Left-Bottom
engine0       →    e2r            Front-Right-Bottom
engine6       →    e3l            Rear-Left-Top
engine7       →    e3r            Rear-Right-Top
engine5       →    e4l            Front-Left-Top
engine4       →    e4r            Front-Right-Top
(generated)   →    em1l           Mount-Left
(generated)   →    em1r           Mount-Right
(generated)   →    tra1           Transmission-Mount
```

### Geometric Concepts

#### Engine Cube Bounding Box
The 8 engine block nodes define a rectangular prism ("engine cube") that:
- Contains the engine's physical mass distribution
- Defines collision/interference boundaries
- Establishes center of gravity reference point

#### Flywheel Plane
**Definition:** The vertical plane formed by the 4 rearmost engine block nodes.

```
Flywheel Plane (rear face of engine cube):
          
     e3l ─────── e3r
      │           │
      │  FLYWHEEL │
      │   PLANE   │
      │           │
     e1l ─────── e1r
       ---floor---
```

**Purpose:** 
- Primary alignment reference for transmission interface
- Ensures donor transmission connects properly
- Critical for powertrain chain alignment

#### Engine Floor Plane
**Definition:** The horizontal plane established by the 2 lowest nodes on the bottom face.

```
Engine Floor Plane (bottom face):
          _____
         |     |
     e2l ─────── e2r
      │           │
      │   FLOOR   │
      │   PLANE   │
      │           │
     e1l ─────── e1r
      ---flywheel---
```

**Purpose:**
- Prevents engine from clipping through oil pan area
- Establishes vertical clearance baseline
- Accommodates engines with non-flat bottoms

### TMS Algorithm Specification

#### Phase 1: Target Vehicle Analysis

```
STEP 1.1: Extract Engine Mount Nodes
├── Parse target vehicle's stock engine .jbeam
├── Locate all 'emxx' type nodes (em1l, em1r, tra1, etc.)
├── Store positions: target_mount_nodes = {node_id: (x, y, z)}
└── Note: These positions are FIXED (defined by chassis)

STEP 1.2: Extract Engine Cube Nodes  
├── Parse target vehicle's stock engine .jbeam
├── Locate engine block nodes (e1l, e1r, e2l, e2r, e3l, e3r, e4l, e4r)
├── Store positions: target_engine_cube = {node_id: (x, y, z)}
└── Calculate target_centroid = average of all 8 positions

STEP 1.3: Define Reference Planes
├── flywheel_plane_target = plane(e1l, e1r, e3l, e3r)
├── floor_plane_target = plane(e1l, e1r, e2l, e2r)
└── Store plane equations for later alignment
```

#### Phase 2: Donor Engine Analysis

```
STEP 2.1: Extract Donor Engine Cube Nodes
├── Parse Camso engine_structure .jbeam
├── Locate nodes: engine0-engine7
├── Store positions: donor_engine_cube = {node_id: (x, y, z)}
└── Calculate donor_centroid = average of all 8 positions

STEP 2.2: Define Donor Reference Planes
├── flywheel_plane_donor = plane(engine2, engine3, engine6, engine7)
├── floor_plane_donor = plane(engine0, engine1, engine2, engine3)
└── Store plane equations

STEP 2.3: Calculate Donor Dimensions
├── donor_length = |front_nodes - rear_nodes|
├── donor_width = |left_nodes - right_nodes|
├── donor_height = |bottom_nodes - top_nodes|
└── Store for interference checking
```

#### Phase 3: Alignment Calculation

```
STEP 3.1: Flywheel Plane Alignment (PRIMARY)
├── Calculate translation to align flywheel plane centroids
├── translation_flywheel = target_flywheel_centroid - donor_flywheel_centroid
├── Check if plane normals are parallel (should be for longitudinal engines)
├── If non-parallel: calculate pitch rotation (rare, log warning)
└── Result: translation_vector_1

STEP 3.2: Floor Plane Alignment (SECONDARY)
├── Find lowest donor node after flywheel alignment
├── Project onto target floor plane
├── Calculate vertical offset to place lowest node ON floor plane
├── vertical_adjustment = target_floor_z - (donor_lowest_z + translation_vector_1.z)
└── Result: translation_vector_2

STEP 3.3: Combine Translations
├── solver_base_translation = translation_vector_1 + (0, 0, vertical_adjustment)
└── This positions donor engine with flywheel aligned and floor respected
```

#### Phase 4: User Adjustments

```
STEP 4.1: Apply User Offsets
├── Read swpparam_ForeAftOffset (meters, + = rearward)
├── Read swpparam_UpDownOffset (meters, + = upward)
├── solver_useroffset_translation = (0, swpparam_ForeAftOffset, swpparam_UpDownOffset)
└── combined_translation = solver_base_translation + solver_useroffset_translation

STEP 4.2: Apply Mesh Offset Correction (Optional)
├── If swpparam_FixMeshOffset == True:
│   ├── Calculate visual mesh centroid offset from node centroid
│   ├── Generate $EngineOffsetXVis, $EngineOffsetYVis, $EngineOffsetZVis corrections
│   └── Store in output variables section
└── Else: preserve original Camso mesh offsets
```

#### Phase 5: Interference Check

```
STEP 5.1: Mount Node Clearance Check
├── For each target mount node (em1l, em1r, tra1):
│   ├── Check if node position is INSIDE translated donor engine cube
│   ├── Use axis-aligned bounding box (AABB) check
│   └── If inside: flag interference
└── Result: interference_flags[]

STEP 5.2: Resolve Interference (if any)
├── Read swpparam_ShrinkOrExpand option
├── If "shrink_engine_block":
│   ├── Calculate minimum scale factor to clear all mount nodes
│   ├── Scale engine cube inward about centroid
│   └── LIMIT: max shrink = 15% (preserve mass distribution)
├── If "expand_engine_mounts":
│   ├── Calculate outward translation for each conflicting emxx node
│   ├── Move mount nodes to just outside engine cube
│   └── LIMIT: max expansion = 0.1m per node
├── If "none":
│   └── Log warning, proceed without modification
└── Result: adjusted_nodes{}
```

#### Phase 6: Output Generation

```
STEP 6.1: Generate Translated Node Definitions
├── For each donor node:
│   ├── new_position = original_position + combined_translation
│   ├── Apply interference adjustments if applicable
│   └── Map to BeamNG naming convention
└── Result: translated_nodes[]

STEP 6.2: Generate Mount Nodes
├── Copy target vehicle's emxx positions exactly
├── These become the engine's mount interface
└── Result: mount_nodes[]

STEP 6.3: Generate Beam Definitions  
├── Copy BeamNG-style engine cube beam structure
├── Generate emxx-to-engine-cube connection beams
├── Apply appropriate spring/damp values
└── Result: beam_definitions[]

STEP 6.4: Write Output
├── Option A: Embed in adapted engine.jbeam (Cummins pattern)
├── Option B: Generate separate engine_structure.jbeam (Camso pattern)
└── Decision: See "Output Format Decision" section
```

### Swap Parameter File Specification

**Filename:** `swap_parameters.json`  
**Documentation:** See `docs/swap_parameter_readme.md`

```json
{
  "$schema": "./schemas/swap_parameters.schema.json",
  "version": "1.0",
  "description": "TMS configuration for [donor] → [target] swap",
  
  "solver_options": {
    "swpparam_FixMeshOffset": false,
    "swpparam_ShrinkOrExpand": "none",
    "swpparam_ForeAftOffset": 0.0,
    "swpparam_UpDownOffset": 0.0,
    "swpparam_LeftRightOffset": 0.0
  },
  
  "limits": {
    "max_shrink_percent": 15,
    "max_mount_expansion_m": 0.1,
    "min_mount_clearance_m": 0.02
  },
  
  "output": {
    "format": "embedded",
    "generate_debug_visualization": false
  }
}
```

**Parameter Reference:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `swpparam_FixMeshOffset` | bool | false | Align visual mesh centroid to physics node centroid |
| `swpparam_ShrinkOrExpand` | enum | "none" | Interference resolution: "shrink_engine_block", "expand_engine_mounts", "none" |
| `swpparam_ForeAftOffset` | float | 0.0 | Additional Y offset in meters (+ = rearward) |
| `swpparam_UpDownOffset` | float | 0.0 | Additional Z offset in meters (+ = upward) |
| `swpparam_LeftRightOffset` | float | 0.0 | Additional X offset in meters (+ = right) |

### Critical: Camso Engine File Structure

**Camso/Automation engines ALWAYS store physics nodes in a SEPARATE file:**

| File Type | Contains | Example |
|-----------|----------|---------|
| Main Engine | Torque curves, thermal, powertrain, slots | `camso_engine_3813e.jbeam` |
| Structure File | Physics nodes (engine0-7), beams | `camso_engine_structure_ec8ba.jbeam` |

The main engine references the structure via a slot:
```jbeam
["Camso_engine_structure", "Camso_engine_structure_ec8ba", "Engine Structure", {"coreSlot": true}]
```

**TMS must parse BOTH files:**
1. Main engine file → to get the structure slot reference
2. Structure file → to extract engine0-7 node positions

This differs from BeamNG original engines (and Cummins mod) which embed nodes directly.

### Output Format Decision

**Question:** Embed translated nodes in adapted engine.jbeam or preserve Camso's separate structure file convention?

#### Option A: Embedded (Cummins Pattern) ✓ CURRENT IMPLEMENTATION

**Pros:**
- Single adapted file per engine variant
- Matches BeamNG native engine convention
- TMS-translated nodes go directly into adapted engine
- Simpler deployment (fewer files to manage)
- Works seamlessly with `{vehicle}_enginemounts` slot system
- `torqueReactionNodes` can reference translated node names directly

**Cons:**
- Larger individual files
- Loses Camso's separation of concerns
- Original Camso structure file becomes orphaned (not referenced)
- If structure is shared across engines, must translate each time

#### Option B: Separate engine_structure.jbeam (Preserve Camso Pattern)

**Pros:**
- Clean separation of engine logic vs. physics structure
- Could potentially translate structure ONCE and share across adapted engines
- Preserves original Camso file organization
- Smaller adapted engine files

**Cons:**
- Requires creating adapted structure file(s)
- Must update slot references in adapted engine to point to adapted structure
- Additional file management complexity
- Must track structure→engine relationships
- Complicates `{vehicle}_enginemounts` integration (structure must also include mount slot)

**Current Decision:** Use **Option A (Embedded)** for output. This aligns with proven Cummins mod patterns. However, the implementation must:
1. Parse the donor's separate structure file to get node positions
2. Translate nodes and embed them in the adapted engine file
3. Remove or neutralize the `Camso_engine_structure` slot reference (since nodes are now embedded)

**Future Consideration:** If multiple engines share the same structure (e.g., engine variants), Option B might reduce duplication. This could be revisited if significant redundancy is observed.

### Module Architecture Decision

**Question:** Separate module or integrate into engineswap.py?

**Decision:** Implement as **separate module** (`mount_solver.py`) that is imported by `engineswap.py`.

**Rationale:**
- Clear separation of concerns
- Easier testing and validation
- Can be developed/debugged independently
- Cleaner codebase organization
- Allows future reuse in other tools

**File Structure:**
```
scripts/
├── engineswap.py           # Main orchestrator (imports mount_solver)
├── mount_solver.py         # TMS implementation
├── jbeam_parser.py         # JBeam parsing utilities (future extraction)
└── swap_parameters.json    # Default/example parameter file
```

### Implementation Phases

**Phase 1: Foundation** (Current Target)
- [x] Document node conventions
- [x] Define TMS algorithm
- [x] Specify parameter file format
- [ ] Create `mount_solver.py` stub with classes

**Phase 2: Extraction**
- [ ] Implement target vehicle node extraction
- [ ] Implement donor engine node extraction
- [ ] Add plane calculation utilities

**Phase 3: Solver Core**
- [ ] Implement flywheel plane alignment
- [ ] Implement floor plane adjustment
- [ ] Add user offset application

**Phase 4: Output Generation**
- [ ] Implement node translation and renaming
- [ ] Generate beam definitions
- [ ] Integrate with engineswap.py

**Phase 5: Refinement**
- [ ] Add interference detection
- [ ] Implement shrink/expand resolution
- [ ] Add mesh offset correction

---

## Engine Architecture Patterns (Detailed)

### Understanding Vehicle Engine Frameworks

BeamNG's base game vehicles use **three primary powertrain integration patterns**:

#### 1. **Direct Vehicle-Specific Engines** (Simplest)
- Engine files live directly in the vehicle folder
- Example: `vehicles/moonhawk/moonhawk_engine.jbeam`
- SlotType: `{vehicle}_engine` (e.g., `moonhawk_engine`)
- All components are vehicle-specific and self-contained

#### 2. **Common Folder Architecture** (Most Common)
- Engine files in `vehicles/common/{vehicle_family}/engines/`
- Shared across multiple vehicle variants
- Example: `vehicles/common/pickup/engines/pickup_engine_*.jbeam`
- SlotType: `{family}_engine` (e.g., `pickup_engine`)
- Components reused across vehicle family

#### 3. **Submodel .pc Architecture** (Most Complex)
- Engine components defined in separate model folders
- Example: ETK800 uses engines from `etk` subfolder
- Referenced via `.pc` configuration files
- SlotType references components from different model namespaces
- Requires understanding of cross-model dependencies

---

## Cummins Mod Analysis - Key Findings

### Directory Structure Pattern

The Cummins mod demonstrates **best practices** for multi-vehicle engine swaps:

```
Cummins/
├── vehicles/
│   ├── common/pickup/               # Shared components
│   │   ├── engines/                 # Engine variants organized by model
│   │   │   ├── 5.9L 12V Cummins 6BT/
│   │   │   ├── 5.9L 24V Cummins ISB (VP44)/
│   │   │   ├── 5.9L 24V Cummins ISB (CommonRail)/
│   │   │   └── 6.7L 24V Cummins ISB/
│   │   ├── transmissions/           # Compatible transmissions
│   │   ├── cummins_i6_pistons.jbeam
│   │   ├── cummins_i6_injectors.jbeam
│   │   └── ...                      # Other shared components
│   ├── pickup/                      # Pickup-specific adaptations
│   │   ├── cummins_radsupport.jbeam
│   │   ├── pickup_radiator_Cummins_Drag.jbeam
│   │   ├── Cummins Street.pc        # Pre-configured vehicles
│   │   ├── Cummins Drag.pc
│   │   └── ...
│   ├── semi/                        # Semi truck adaptations
│   │   ├── engines/
│   │   │   └── semi_engine_i6_Cummins12V_6BT.jbeam
│   │   └── semi_Manifolds.jbeam
│   ├── roamer/                      # SUV adaptations
│   ├── moonhawk/                    # Car adaptations
│   └── ...                          # Other vehicles
└── art/                             # 3D models and textures
```

### Critical Implementation Patterns

#### 1. **SlotType Adaptation**
The mod creates **vehicle-specific engine variants** by changing slotType:

**Original Common Engine:**
```json
"pickup_engine_i6_Cummins12V": {
    "slotType": "pickup_engine",
    ...
}
```

**Semi Truck Variant:**
```json
"semi_engine_i6_Cummins12V": {
    "slotType": "semi_engine",  // Changed for semi compatibility
    ...
}
```

**Key Insight:** The SAME engine characteristics can be used across vehicles by **cloning the part and changing only the slotType** and vehicle-specific slot references.

#### 2. **Slot Hierarchy System**

Engine swaps use a **nested slot system**:

```
pickup_engine (main engine slot)
├── pickup_enginemounts (structural)
├── pickup_oilpan_i6 (structural)
├── 6BT_intake (forced induction)
│   ├── pickup_supercharger_6BT_stage1
│   └── pickup_intake_6BT_S
├── cummins_i6_pistons (internal upgrade)
├── cummins_i6_injectors (fuel system)
├── pickup_engine_i6_ecu_12V (control)
│   ├── pickup_engine_i6_governor_12V
│   └── pickup_engine_i6_governor3000_12V
├── pickup_cummins_internals_12V (engine block variant)
│   ├── pickup_cummins_internals_Stock_12V
│   ├── pickup_cummins_internals_heavy_12V
│   └── pickup_cummins_internals_drag_12V
└── pickup_transmission (drivetrain)
```

#### 3. **Component Dependency Management**

**Support Components Required:**
- **Radiator Support:** Custom `cummins_radsupport.jbeam` with flexbody mesh
- **Engine Mounts:** Heavy duty variants (`pickup_enginemounts_heavy`)
- **Cooling System:** Upgraded radiators for different power levels
- **Exhaust System:** Custom manifolds and exhaust routing
- **Fuel System:** Diesel-specific components

#### 4. **Cross-Vehicle Component Reuse**

The Cummins mod demonstrates **maximum code reuse**:

**Shared Components** (in `/common/pickup/`):
- Pistons, connecting rods, valve springs
- Injectors, lift pumps
- Transmissions
- Base engine definitions

**Vehicle-Specific Components:**
- SlotType wrappers (e.g., `semi_engine_i6_Cummins12V`)
- Exhaust manifolds adapted to vehicle chassis
- Radiator support structures
- Engine mount geometries

## Engine Transplant Workflow

### Phase 1: Analysis
1. **Identify source engine .jbeam file** (from Automation or donor vehicle)
2. **Extract core engine characteristics:**
   - Torque curve
   - RPM limits (idle, max, redline)
   - Inertia, friction, thermal properties
   - Sound configuration
   - Physical dimensions (node positions)
3. **Identify target vehicle architecture** (direct, common, or submodel)

### Phase 1.5: Asset Extraction (Slot Graph Processing)
1. **Parse donor engine files** using JBeam parser
2. **Build slot dependency graph** with directed relationships
3. **Classify asset roles:**
   - **SOURCE:** Extraction-only slots (marked for replacement)
   - **TARGET:** Generated slots for adapted output
   - **PRESERVE:** Original slots kept unchanged
   - **INTERNAL:** Processing slots (filtered from output)
4. **Apply slot replacement rules:**
   - Substitute SOURCE slots with asset-calling counterparts
   - Use suffix-agnostic matching for flexible patterns
   - Implement absorption logic to prevent duplicates
5. **Generate clean adapted output** with SOURCE filtering

### Phase 2: Adaptation
1. **Create vehicle-specific slotType variant**
2. **Map component dependencies:**
   - Identify required support slots
   - Match or create compatible components
3. **Adapt physical integration:**
   - Engine mount node positions
   - Radiator connections
   - Exhaust routing
   - Torque reaction nodes
4. **Configure powertrain compatibility:**
   - Transmission bolt patterns
   - Flywheel specifications
   - Differential/transfer case compatibility

### Phase 3: Validation
1. **Check for conflicting part names**
2. **Validate slot hierarchy completeness**
3. **Test thermal/cooling balance**
4. **Verify physics node integrity**

### Phase 4: Packaging
1. **Resolve physical assets** from transformed slot references
2. **Copy required files** maintaining proper directory structure
3. **Include extra assets** (powertrain Lua, materials JSON)
4. **Generate complete mod package** ready for distribution

---

## Best Practices

### 1. **Naming Conventions**
- **Engine Parts:** `{vehicle_family}_engine_{config}_{variant}`
  - Example: `pickup_engine_i6_Cummins12V`
- **Support Components:** `{vehicle_family}_{component}_{variant}`
  - Example: `pickup_radiator_Cummins_Drag`
- **Slots:** Use clear hierarchical names
  - Example: `cummins_i6_injectors`, `6BT_intake`

### 2. **SlotType Strategy**
- **Always match target vehicle's expected slotType**
- Create vehicle-specific wrappers that **inherit** from common base
- Use `"slotType": "{target_vehicle}_engine"` for compatibility

### 3. **Node Position Management**
- Engine node positions MUST align with vehicle chassis
- Copy node layout from donor vehicle's original engine
- Adjust Z-height for different engine sizes
- Maintain torque reaction node relationships

### 4. **Thermal Balance**
- Scale radiator capacity to engine power output
- Larger/more powerful engines need:
  - Increased `radiatorArea`
  - Higher `radiatorEffectiveness`
  - More `coolantVolume`
  - Potentially electric fans (`radiatorFanType:"electric"`)

### 5. **Slot Defaults**
- Always provide sensible `default` slot values
- Mark structural slots as `"coreSlot":true`
- Chain slot dependencies logically (e.g., turbo → exhaust outlet)

### 6. **Component Modularization**
- Separate upgrade paths into independent slots:
  - Engine block variants (stock, heavy duty, racing)
  - Forced induction options (turbo, supercharger stages)
  - Internal components (pistons, rods, springs)
  - ECU/tuning (governor springs, fuel maps)

---

## Mod Packaging System

The utility includes an automated packaging system that creates complete, distributable mod packages from generated manifests.

### `mod_packager.py` - Packaging Utility
- **Purpose:** Copy all required files from donor mods to target locations
- **Integration:** Available as standalone script or integrated via `--package` flag
- **Features:**
  - Post-transform asset resolution (uses transformed slot references)
  - Proper directory structure maintenance
  - Extra asset inclusion (powertrain Lua, materials JSON)
  - Dry-run validation and force overwrite options

### Packaging Process
1. **Asset Resolution:** Parse generated files to identify required meshes/textures/sounds
2. **Path Management:** Strip donor vehicle folders, route `art/` to mod root
3. **File Copying:** Maintain subdirectory structure for proper BeamNG loading
4. **Validation:** Verify all source files exist before copying

### Final Mod Structure
```
engineswaps/                    ← Mod package root (configurable)
├── art/sound/engine/...        ← Shared sounds at correct level
├── vehicles/
│   └── pickup/                 ← Target vehicle folder
│       ├── ec8ba/              ← Mesh subfolder (stripped donor path)
│       │   └── ec8ba_mesh.dae
│       ├── lua/powertrain/     ← Powertrain scripts
│       │   ├── camsoEngine.lua
│       │   └── camsoTurbocharger.lua
│       ├── ec8ba.materials.json ← Materials definitions
│       ├── ec8ba.png           ← Textures
│       └── *.jbeam             ← Generated engine files
```

### Usage Examples
```bash
# Standalone packaging
python scripts/mod_packager.py package manifest.json

# Integrated with generation
python scripts/engineswap.py generate engine.jbeam pickup --package

# Dry run to preview
python scripts/engineswap.py generate engine.jbeam pickup --package-dry-run
```

---

## Common Gotchas and Mitigations

### ❌ **SlotType Mismatch**
**Problem:** Engine part has `slotType: "pickup_engine"` but target vehicle expects `"semi_engine"`

**Solution:** Create vehicle-specific wrapper:
```json
"semi_engine_i6_Cummins12V": {
    "slotType": "semi_engine",
    // Copy all other properties from pickup version
}
```

### ❌ **Missing Support Structures**
**Problem:** Engine loads but causes physics errors or visual glitches

**Solution:** 
- Always include radiator support structure
- Create vehicle-specific engine bay flexbodies
- Verify all node groups are properly defined

### ❌ **Incompatible Transmission Slot**
**Problem:** Engine references transmission slot that doesn't exist on target vehicle

**Solution:**
- Check target vehicle's transmission slotType
- Create adapter transmission parts if needed
- Or modify engine slots to match target vehicle's naming

### ❌ **Overheating Issues**
**Problem:** Swapped engine overheats instantly

**Solution:**
- Check `radiatorArea` and `radiatorEffectiveness`
- Verify `coolantVolume` is appropriate for engine size
- Ensure radiator nodes are properly connected
- May need custom high-performance radiator part

### ❌ **Sound Configuration Errors**
**Problem:** Engine has no sound or wrong sound profile

**Solution:**
- Verify sound event paths exist in game files
- Use similar engine's sound config as template
- Match `fundamentalFrequencyCylinderCount` to actual cylinder count

### ❌ **Node Collision/Physics Instability**
**Problem:** Engine vibrates wildly or falls through chassis

**Solution:**
- Copy node positions from donor vehicle's engine
- Verify engine mount node connections to chassis
- Check beam spring/damp values are reasonable
- Ensure `torqueReactionNodes` are properly referenced

### ❌ **Part Namespace Conflicts**
**Problem:** Mod parts conflict with other mods or base game

**Solution:**
- Use unique part name prefixes (e.g., `cummins_`, `custom_`)
- Never override base game parts directly
- Check for name collisions before distribution

---

## Resources

### Official Documentation
- [BeamNG Official Modding Documentation](https://documentation.beamng.com/)
- [JBeam Physics Documentation](https://documentation.beamng.com/modding/vehicle/jbeam/)
- [BeamNG Mod Resources](https://www.beamng.com/resources/)
- [Vehicle Slots and Parts](https://documentation.beamng.com/modding/vehicle/vehicle_creation/)

### Community Resources
- BeamNG Modding Forums
- BeamNG Discord - Modding Channels
- Repository Modding Wiki

### Reference Mods
- **FakeCarGuy Cummins mod** - Multi-vehicle integration example

### Tools
- **JBeam Editor** - Syntax validation
- **BeamNG Vehicle Config Editor** - .pc file editing
- **Python 3.11+** - For automation scripts

---

## Contributing

If you undertake independent development and want your changes merged back into this project, your code should be documented. At minimum, include function/module docstrings, explain non-obvious logic and assumptions, and update related docs. 

---

**Project Status:** Analysis Phase  
**Last Updated:** February 1, 2026
