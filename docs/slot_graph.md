# Slot Graph - Unified Slot Dependency Management

## Overview

The `slot_graph.py` module provides a graph-based approach to managing slot dependencies, transformations, and packaging for BeamNG engine swap mods. It serves as the single source of truth for all slot state during the adaptation process, addressing the fragmented slot handling identified in project documentation.

**Key Goals:**
- Unify scattered slot operations into a cohesive graph structure
- Provide full traceability of slot transformations
- Enable safe dependency-aware modifications
- Support both planning and execution phases

**Current Status:** Integration and packaging enhancements complete. Slot graph provides unified slot management with manifest-driven packaging support.

## Architecture

### Core Concepts

**Slot Graph:** A directed graph where nodes represent slots and edges represent parent-child relationships. The graph tracks both original donor state and transformed target state.

**Transformation Pipeline:** Four-phase process:
1. **Build:** Parse donor files and construct slot tree
2. **Plan:** Analyze dispositions and plan transformations
3. **Execute:** Apply transformations to graph state
4. **Output:** Generate adapted files and manifest from graph

**Disposition Rules:** Configurable rules determining how each slot is handled:
- `PRESERVE` - Keep slot as-is (donor ecosystem slots)
- `ADAPT` - Rename slot_type AND update default to target vehicle
- `INJECT` - New slot not present in donor (e.g., enginemounts)
- `PRUNE` - Remove slot entirely (unwanted features)
- `REMAP_DEFAULT` - Keep slot_type unchanged, only update default value

**State Machine:** Slots progress through validated lifecycle states:
```
ORIGINAL → PLANNED → TRANSFORMED → VALIDATED
                  ↘      ↓
                    PRUNED (terminal)
```

**Asset Roles:** Slots are categorized by their role in the export process:
- `SOURCE`: Extraction-only files (NOT exported) - e.g., engine structure files
- `TARGET`: Generated/adapted files (IS exported) - e.g., adapted engine/transmission slots
- `PRESERVE`: Original files (copied to export) - e.g., ecosystem slots (intake, management)
- `INTERNAL`: Processing artifacts (never exported) - e.g., temporary processing files

**Slot Replacement Rules:** Automatic substitution of SOURCE slots with their asset-calling counterparts:
- `Camso_engine_structure` → `Camso_engine_mesh` (provides visual mesh references)
- Suffix-agnostic matching (handles `_ec8ba`, `_3813e` variations)
- Absorption logic: Re-parents existing child slots rather than creating duplicates

### Slot Replacement System

The slot graph implements automatic slot replacement to substitute SOURCE-only slots (extraction targets) with their corresponding asset-calling slots in adapted output files.

**Default Replacements:**
```python
DEFAULT_REPLACEMENTS = {
    "Camso_engine_structure": {
        "replacement_type": "Camso_engine_mesh",
        "description": "Engine Mesh", 
        "options": {"coreSlot": True}
    },
}
```

**Absorption Logic:** When a replacement slot already exists in the graph as a SOURCE child, the system:
1. Re-parents the existing node to the source slot's parent (the engine)
2. Changes disposition from current to `INJECT`
3. Changes asset_role from `SOURCE` to `TARGET`
4. Preserves the suffix from the source slot

**Example:** `Camso_engine_structure_ec8ba` (SOURCE) gets replaced by `Camso_engine_mesh_ec8ba` (TARGET, INJECT)

**SOURCE Filtering:** Slots marked `AssetRole.SOURCE` are excluded from adapted file output, ensuring clean slot arrays without extraction-only slots.

### Module Components

#### Protocol & Exceptions
- `JBeamParserProtocol`: Type-safe interface for parser injection (avoids circular imports)
- `SlotGraphError`: Base exception for all slot graph operations
- `ParserNotAvailableError`: Raised when parser not injected
- `MalformedJBeamError`: Raised on parse failures with context
- `SlotNotFoundError`: Raised when required slot missing
- `InvalidStateTransitionError`: Raised on illegal state changes

#### Data Structures
- `SlotNode`: Individual slot with metadata, relationships, cached descendants, and asset role
- `SlotGraph`: Complete graph with indices (`by_slot_type`, `by_part_name`, `by_source_file`)
- `SlotTransformation`: Record of individual transformation operations with timestamps
- `AssetRole`: Enum distinguishing asset types (SOURCE, TARGET, PRESERVE, INTERNAL)

#### Builders and Processors
- `SlotGraphBuilder`: Constructs graph from JBeam files (requires parser injection)
- `SlotDispositionRules`: Determines slot handling based on patterns + explicit overrides + replacement rules
- `SlotTransformationPlanner`: Plans transformations without side effects
- `SlotTransformationExecutor`: Applies planned transformations to graph

#### Output Generators
- `SlotAwareJBeamWriter`: Generates adapted JBeam slot sections
- `SlotAwareManifestGenerator`: Creates v3.0 slot-centric packaging manifest with asset discovery
- `SlotAssets`: Dataclass tracking per-slot asset references (meshes, textures, sounds, materials)
- `SlotManifestEntry`: Dataclass for complete slot manifest data including source file and children

#### Convenience Functions
- `build_slot_graph()`: One-call graph construction from file list
- `plan_and_execute_transformations()`: One-call planning + execution + validation
- `extract_slot_suffix()`: Splits slot names like `Camso_engine_structure_ec8ba` → `("Camso_engine_structure", "ec8ba")`
- `apply_slot_suffix()`: Combines base name with suffix
- `match_slot_base()`: Pattern matching for suffix-agnostic slot comparison

## Usage Patterns

### Basic Workflow

```python
from engineswap import JBeamParser  # Import parser from main module
from slot_graph import (
    SlotGraphBuilder,
    SlotDispositionRules,
    SlotTransformationPlanner,
    SlotTransformationExecutor,
    SlotAwareJBeamWriter,
    SlotAwareManifestGenerator,
)

# Build graph from donor files (parser injection required)
builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
builder.add_donor_file(engine_path)
builder.add_donor_file(transmission_path)
graph = builder.build()

# Plan and execute transformations
config = {"slot_rules": {"prune_slots": ["Camso_Nitrous"]}}
rules = SlotDispositionRules(config)
# For family-architecture vehicles, pass dynamically discovered slot types
planner = SlotTransformationPlanner(
    graph, "pickup", rules,
    slot_type_prefix=None,  # or "etk" for family architectures
    target_mount_slot_type="pickup_enginemounts"  # discovered from engine file slots
)
planner.plan()

executor = SlotTransformationExecutor(graph)
executor.execute_all()

# Validate before output
validation = graph.validate()
if validation["errors"]:
    raise RuntimeError(f"Graph validation failed: {validation['errors']}")

# Generate outputs
writer = SlotAwareJBeamWriter(graph)
slots_array = writer.generate_slots_section("pickup_Camso_Engine_3813e")

manifest_gen = SlotAwareManifestGenerator(graph)
manifest = manifest_gen.generate()
```

### Convenience API

```python
from engineswap import JBeamParser
from slot_graph import build_slot_graph, plan_and_execute_transformations

# One-liner graph construction
graph = build_slot_graph(
    target_vehicle="pickup",
    donor_files=[engine_path, transmission_path],
    jbeam_parser=JBeamParser
)

# One-liner transformation (with optional dynamic slot discovery params)
config = {"slot_rules": {"prune_slots": ["Camso_Nitrous"]}}
graph = plan_and_execute_transformations(
    graph, "pickup", config, validate=True,
    slot_type_prefix=None,                         # e.g. "etk" for family vehicles
    target_mount_slot_type="pickup_enginemounts"    # from find_mount_slot_type()
)
```

### Visualization and Debugging

The slot graph includes comprehensive visualization tools for debugging and analysis:

```python
# Text-based tree visualization
graph.print_tree(show_files=True, show_transforms=True)

# Filter by asset role
source_slots = graph.get_source_slots()      # Extraction-only slots
exportable_slots = graph.get_exportable_slots()  # TARGET/PRESERVE slots
preserve_slots = graph.get_slots_by_role(AssetRole.PRESERVE)

# Full visualization with filtering
graph.visualize(
    show_files=True,
    show_transforms=True,
    filter_role=AssetRole.TARGET,  # Only show TARGET slots
    markdown_output=True           # Save to markdown file
)
```

**CLI Visualization:**
```bash
# Basic visualization
python engineswap.py visualize engine.jbeam pickup

# Show source files and transformations
python engineswap.py visualize engine.jbeam pickup --show-files --show-transforms

# Filter to specific role and save as markdown
python engineswap.py visualize engine.jbeam pickup --filter-role target --markdown
```

**Asset Role Classification:**
- **SOURCE (S)**: Extraction-only files (NOT exported) - e.g., `camso_engine_structure_ec8ba.jbeam`
- **TARGET (T)**: Generated/adapted files (IS exported) - e.g., `pickup_engine`, `pickup_transmission`
- **PRESERVE (P)**: Original files (copied to export) - e.g., ecosystem slots (intake, management)
- **INTERNAL (I)**: Processing artifacts (never exported)

### Integration Points

**With engineswap.py:**

The slot graph is now integrated into `EngineTransplantUtility` as of Phase 2 completion:

| Method | Integration Details |
|--------|-------------------|
| `__init__()` | Added `swap_config` parameter, `_slot_graph` instance variable, logs "Slot Graph: ENABLED" |
| `generate_adapted_jbeam()` | Calls `_build_slot_graph()` after parsing donor file |
| `_create_adapted_part_name()` | Delegates to `_get_adapted_part_name_from_graph()` |
| `generate_mod_manifest()` | Uses `SlotAwareManifestGenerator` when available, adds slot graph metadata |

**New Helper Methods:**
- `discover_donor_files(donor_engine_path)` - Finds all related Camso-style donor files
- `build_slot_graph(donor_engine_path, target_vehicle)` - Builds and transforms the slot graph
- `get_adapted_slot_type(donor_slot_type, target_vehicle)` - Returns mapped slot type from graph or fallback
- `get_adapted_part_name_from_graph(donor_part_name, target_vehicle)` - Returns mapped part name from graph or fallback

**Key Design Decisions:**
- **Non-breaking:** All changes are additive; existing functionality preserved when slot graph unavailable
- **Fallback behavior:** Each integration point falls back to existing logic if slot graph not built
- **Single source of truth:** Slot graph provides consistent mappings for slot types and part names

### Manifest Format v3.0 (Slot-Centric)

The `SlotAwareManifestGenerator` produces a v3.0 manifest that organizes everything around slots:

```json
{
  "version": "3.0",
  "required_slots": [
    {
      "slot_type": "pickup_engine",
      "original_type": "Camso_Engine",
      "default": "pickup_Camso_Engine_3813e",
      "original_default": "Camso_Engine_3813e",
      "disposition": "adapt",
      "source_file": "camso_engine_3813e.jbeam",
      "requires_generation": true,
      "assets": {
        "meshes": ["ec8ba_mesh.dae"],
        "textures": ["camso_full_alt_baker.dds"]
      },
      "children": ["Camso_engine_structure", "Camso_Intake_3813e"]
    }
  ],
  "copy_plan": {
    "original_jbeam": [{"path": "...", "provides_slots": [...]}],
    "generated_jbeam": [
      {
        "path": "...",
        "output_path": "M:\\BeamNG_Modding_Temp\\temp\\pickup_camso_engine_3813e_adapted.jbeam",
        "output_filename": "pickup_camso_engine_3813e_adapted.jbeam",
        "provides_slots": [...]
      }
    ],
    "excluded_files": [{"path": "...", "reason": "pruned"}]
  },
  "asset_files": {
    "meshes": [{"name": "...", "path": "..."}],
    "textures": [...]
  },
  "mappings": {
    "slot_types": {"Camso_Engine": "pickup_engine"},
    "part_names": {"Camso_Engine_3813e": "pickup_Camso_Engine_3813e"}
  }
}
```

**Note (engineswap integration):** `scripts/engineswap.py` may append additional top-level sections to the manifest when generating a complete swap (beyond what `SlotAwareManifestGenerator` emits). Most notably, transfer case adaptation can add a `drivetrain` block containing the selected strategy and traceability for powertrain device name remaps.

Example (abridged):
```json
{
  "drivetrain": {
    "swap_strategy": "DIRECT_AWD",
    "selected_beamng_tc": "pickup_transfer_case_AWD",
    "slots_pruned": ["Camso_driveshaft_front", "Camso_driveshaft_rear"],
    "device_name_mapping": {"transferCase": "transfercase"},
    "device_name_provenance": [
      {
        "donor_name": "transferCase",
        "target_name": "transfercase",
        "reason": "structural: differential(inputName='gearbox')"
      }
    ]
  }
}
```

**Benefits:**
- **Packaging-Ready:** Includes actual output paths for direct file operations
- **Minimum Necessary Files:** Only files providing required slots are included, INJECT slots don't require source file copying
- **Complete Coverage:** Includes all generated files, even those created outside the slot tree
- **Pruning Support:** Excluded files are explicitly listed with reason
- **Asset Traceability:** Each slot lists its mesh/texture dependencies
- **Dependency Visibility:** Slot tree structure exposed via children field
- **Generation Tracking:** Clear distinction between original and generated files

**Copy Plan Logic:**
- **PRESERVE slots:** Source files copied to `original_jbeam` (e.g., ecosystem slots like intakes)
- **ADAPT slots:** Source files generate adapted versions in `generated_jbeam` with output paths
- **INJECT slots:** Content injected into adapted files, no source file copying needed
- **Additional generated files:** Files created outside slot tree (e.g., sequential transmissions) included in `generated_jbeam`

**Actual Integration Flow:**
```python
# In EngineTransplantUtility.generate_complete_swap()
def generate_complete_swap(self, donor_path, target_vehicle, config):
    # Discover all donor files (engine, transmission, etc.)
    donor_files = self.discover_donor_files(donor_path)
    
    # Build slot graph if available
    # mount_slot_type is dynamically discovered from target engine file slots
    if SLOT_GRAPH_AVAILABLE:
        self._slot_graph = self.build_slot_graph(
            donor_path, target_vehicle,
            engine_slot_type=target_vehicle.engine_slot_type,
            mount_slot_type=target_vehicle.mount_slot_type  # e.g. "etk_enginemounts"
        )
        # Graph used throughout pipeline for consistent mappings
    
    # ... rest of workflow uses graph as source of truth
    # Slot type adaptation, part naming, manifest generation all delegate to graph
```

### Dynamic Mount Slot Discovery

The `INJECT_SLOT` operation for enginemounts uses a **dynamically discovered** slot type read from the target vehicle's engine files, rather than synthesizing it from the vehicle name. This is critical for family-architecture vehicles (e.g., etk800 → `etk_enginemounts`, not `etk800_enginemounts`).

**Discovery flow:**
1. `VehicleAnalyzer.find_mount_slot_type()` reads target engine `.jbeam` files
2. Searches for slot entries containing `enginemounts` in the slot type field
3. Result stored in `VehicleInfo.mount_slot_type`
4. Threaded through `_build_slot_graph()` → `plan_and_execute_transformations()` → `SlotTransformationPlanner`
5. `_plan_required_injections()` uses it to create the correct `INJECT_SLOT` transformation
6. `_inject_engine_mount_slot()` in engineswap.py applies it to the adapted engine part data

**Fallback:** If no mount slot is discovered in target engine files, derives name from `slot_type_prefix` (family prefix) or `target_vehicle` name.

**With mount_solver.py:**

Mount solver operates on node positions, which are orthogonal to slot management. However:
- Slot graph identifies which engine/transmission parts need mount adaptation
- Mount solver uses the identified parts to locate node definitions
- Results feed back as metadata on relevant `SlotNode` objects (future enhancement)

**With JBeamParser:**

Parser injection via Protocol pattern:
```python
# JBeamParser must implement this interface (it already does)
class JBeamParserProtocol(Protocol):
    @staticmethod
    def parse_jbeam(path: Path) -> Optional[Dict[str, Any]]: ...

# Usage - pass the class, not an instance
builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
```

This avoids circular imports since slot_graph.py never imports from engineswap.py.

## Key Features

### Dependency Tracking
- Models slot hierarchies as tree structure (parent → children)
- Multiple indices for fast lookup (`by_slot_type`, `by_part_name`, `by_source_file`)
- Prevents broken dependencies during transformations
- Validates graph integrity via `graph.validate()`
- Asset role classification for export control

### Visualization and Debugging
- `visualize()`: Comprehensive tree visualization with filtering options
- `print_tree()`: Text-based tree display with role indicators
- `get_slots_by_role()`: Filter slots by asset role
- `get_exportable_slots()`: Get TARGET/PRESERVE slots (not PRUNED)
- `get_source_slots()`: Get SOURCE slots (extraction only)

### Transformation Traceability
- Complete audit trail via `SlotTransformation` records
- Timestamps on all transformations
- State tracking per node (`ORIGINAL` → `PLANNED` → `TRANSFORMED`)
- Transformation history stored on each `SlotNode`

### Flexible Configuration
- Pattern-based disposition rules (regex matching)
- Explicit overrides via `prune_slots`, `preserve_slots`, `force_adapt_slots`
- Extensible transformation types via `TransformOp` enum
- Default patterns follow proven "Cummins mod" approach

### Performance Optimizations
- Descendant traversal caching with automatic invalidation
- Indices updated incrementally during transformations
- Lazy validation (call when needed, not on every operation)

## Configuration

### Disposition Rules

```python
config = {
    "slot_rules": {
        # Slots to completely remove (with all descendants)
        "prune_slots": ["Camso_Supercharger_3813e", "Camso_Nitrous"],
        
        # Slots to keep unchanged (override ADAPT pattern match)
        "preserve_slots": ["Camso_Intake_3813e"],
        
        # Slots to force adapt (override PRESERVE pattern match)
        "force_adapt_slots": ["Camso_CustomSlot"],
    }
}
```

### Built-in Pattern Rules

**ADAPT Patterns** (renamed to target vehicle namespace):
- `^Camso_Engine$` → `{target}_engine`
- `^Camso_Transmission$` → `{target}_transmission`
- `^Camso_TransferCase$` → `{target}_transfer_case`

**PRESERVE Patterns** (kept in donor namespace):
- `Camso_Intake.*`, `Camso_EngineManagement.*`, `Camso_EngineInternals.*`
- `Camso_Turbo.*`, `Camso_Supercharger.*`, `Camso_BalancingMass.*`
- `Camso_RevLimiter.*`, `Camso_Nitrous.*`
- `Camso_differential.*`, `Camso_driveshaft.*`
- `Camso_engine_mesh.*`, `Camso_engine_structure.*`, `Camso_exhaust.*`
- `camso_tuning.*`

### Transformation Operations

| Operation | Description | Example |
|-----------|-------------|---------|
| `RENAME_SLOT_TYPE` | Change slot type identifier | `Camso_Engine` → `pickup_engine` |
| `REMAP_DEFAULT` | Change default part name | `Camso_Engine_3813e` → `pickup_Camso_Engine_3813e` |
| `INJECT_SLOT` | Add new slot entry | Dynamically discovered mount slot (e.g., `pickup_enginemounts`, `etk_enginemounts`) |
| `PRUNE_SUBTREE` | Recursive removal | Remove `Camso_Nitrous` and all children |
| `ADD_OPTIONS` | Add/modify slot options | Add `{"coreSlot": true}` |
| `REMOVE_SLOT` | Remove single slot | Non-recursive removal |
| `UPDATE_DESCRIPTION` | Change slot description | Update UI text |

## Validation and Testing

### Graph Validation

Call `graph.validate()` at any point to check integrity:

```python
result = graph.validate(raise_on_error=False)
# Returns:
# {
#     "valid": True/False,
#     "error_count": 0,
#     "warning_count": 5,
#     "errors": [...],
#     "warnings": [...]
# }
```

**Checks performed:**
- All non-pruned slots have resolvable defaults
- No orphan adapted parts (parts not referenced by any slot)
- No circular references in tree
- All transformation targets exist in graph

### Test Coverage

Test file: `scripts/test_slot_graph.py`

| Test | Description |
|------|-------------|
| Protocol Compliance | Verifies JBeamParser conforms to `JBeamParserProtocol` |
| Graph Building | Builds graph from 5 donor files, verifies 20 slots |
| Disposition Rules | Confirms ADAPT for Engine/Transmission/TransferCase, PRESERVE for ecosystem |
| Transformation Planning | Plans 10 transformations (3 renames, 3 remaps, 3 options, 1 inject) |
| Transformation Execution | Executes 10/10 transformations successfully |
| JBeam Writer | Generates 11-slot array with correct mappings |
| Manifest Generation | Valid manifest with 5 warnings (external references) |
| Pruning | Correctly prunes 2 slots (`Camso_Nitrous`, `Camso_Supercharger_3813e`) |

Run tests with Python 3.12:
```bash
& "C:\Users\owner\AppData\Local\Programs\Python\Python312\python.exe" scripts/test_slot_graph.py
```

## Error Handling

### Exception Hierarchy

```
SlotGraphError (base)
├── ParserNotAvailableError    # No parser injected
├── MalformedJBeamError        # Parse failure with file context
├── SlotNotFoundError          # Required slot missing
└── InvalidStateTransitionError # Illegal state change attempted
```

### Handling Examples

```python
from slot_graph import (
    SlotGraphBuilder, 
    ParserNotAvailableError,
    MalformedJBeamError
)

try:
    builder = SlotGraphBuilder("pickup", jbeam_parser=None)
    builder.add_donor_file(some_path)
except ParserNotAvailableError as e:
    print(f"Parser required: {e}")

try:
    builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
    builder.add_donor_file(Path("malformed.jbeam"))
except MalformedJBeamError as e:
    print(f"Parse failed for {e.file_path.name}: {e.reason}")
```

## Future Expansion Areas

### Planned Enhancements
- **Exhaust/Driveshaft Solvers:** Slot graph will identify which parts need solver attention
- **Multi-Engine Support:** Graph per engine variant, merged at output
- **Cross-Mod Compatibility:** Graph comparison for conflict detection

### Performance Optimizations
- **Parallel File Parsing:** Parse multiple donor files concurrently
- **Incremental Updates:** Modify graph without full rebuild
- **Serialization:** Save/load graph state for caching

### Integration Enhancements
- **Graph Visualization:** Tree diagram output for debugging
- **Real-time Validation:** Validate incrementally during building
- **Undo/Redo:** Leverage transformation history for reversal

## Implementation Notes

### Dependencies
- **Python 3.12+** required for `Protocol` and `runtime_checkable`
- **JBeamParser** from engineswap.py (injected, not imported)
- **pathlib.Path** for all file operations
- Compatible with existing `swap_parameters.json` structure

### Design Decisions

**Why Protocol-based Parser Injection?**
- Avoids circular import between slot_graph.py and engineswap.py
- Enables testing with mock parsers
- Allows future parser implementations without code changes

**Why Keep PRUNED Nodes in Indices?**
- Traceability: Can query what was pruned and why
- Validation: Can detect if pruned slots are referenced
- Manifest: Can report pruned files for exclusion

**Why State Transition Validation?**
- Prevents illegal operations (e.g., transforming already-validated node)
- Debugging: Warnings logged for non-standard transitions
- Recovery: `force_state()` available for edge cases

### Performance Considerations
- Graph operations O(n) where n = slot count (typically <100)
- Descendant cache reduces repeated traversals
- Memory ~500 bytes per slot (negligible for typical swaps)

---

*Documentation current as of Phase 2 completion. Slot graph is now active in the main engineswap.py workflow.*
