# Configuration System Updates - February 3, 2026

## Overview

The engine swap utility now uses a centralized configuration file (`swap_parameters.json`) to control output paths and workspace organization.

## Changes Made

### 1. Configuration File Structure

**File**: `configs/swap_parameters.json`

```json
{
  "$schema": "./schemas/swap_parameters.schema.json",
  "version": "1.0",
  "description": "Test configuration - expand engine mounts to clear interference",
  
  "base_output_path": "M:\\BeamNG_Modding_Temp",  // NEW: Base path for all outputs
  
  "solver_options": { ... },
  "limits": { ... },
  "output": { ... }
}
```

### 2. Output Path Resolution

The full output path is constructed as:

```
{base_output_path}/mods/unpacked/engineswaps/vehicles/{target_vehicle}
```

**Example**:
- `base_output_path`: `M:\BeamNG_Modding_Temp`
- `target_vehicle`: `pickup`
- **Result**: `M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles\pickup`

### 3. Modular Workspace Subfolders

The workspace subfolder is now determined dynamically:

| Command | Subfolder Used |
|---------|---------------|
| `analyze-engine` | `temp` |
| `analyze-vehicle` | `temp` |
| `plan {engine} {vehicle}` | `{vehicle}` |
| `generate {engine} {vehicle}` | `{vehicle}` |

**Benefits**:
- Each vehicle gets its own organized folder
- No need to manually manage temporary files
- Easy to compare outputs for different vehicles

### 4. CLI Overrides

The CLI still supports path overrides:

```powershell
# Use config file path
python engineswap.py generate engine.jbeam pickup

# Override config with custom path
python engineswap.py generate engine.jbeam pickup --output "D:\CustomFolder"

# Use different config file
python engineswap.py generate engine.jbeam pickup --config "path/to/custom_config.json"
```

### 5. Schema Validation

**File**: `configs/schemas/swap_parameters.schema.json`

Updated to validate the new `base_output_path` field:

```json
{
  "base_output_path": {
    "type": "string",
    "description": "Base directory path for mod output"
  }
}
```

## Code Changes

### New Function: `load_swap_parameters()`

Location: `scripts/engineswap.py`

```python
def load_swap_parameters(config_path: Path = None) -> Dict[str, Any]:
    """
    Load swap parameters from JSON config file.
    
    Default location: ../configs/swap_parameters.json
    """
```

### Modified: `EngineTransplantUtility.__init__()`

Added `workspace_subfolder` parameter:

```python
def __init__(self, 
             base_vehicles_path: Path,
             output_path: Path,
             workspace_subfolder: str = "temp"):
    """
    Args:
        workspace_subfolder: Subfolder name (default: "temp", or vehicle name)
    """
    self.temp_path = self.output_path / workspace_subfolder
```

### Modified: `main()`

Now loads config and determines paths dynamically:

```python
# Load configuration
swap_config = load_swap_parameters(config_path)

# Determine output path (CLI overrides config)
if args.output:
    output_base = Path(args.output)
elif 'base_output_path' in swap_config:
    base = Path(swap_config['base_output_path'])
    output_base = base / "mods" / "unpacked" / "engineswaps" / "vehicles"
else:
    output_base = Path('../mods/unpacked/engineswaps/vehicles')

# Determine workspace subfolder based on target vehicle
workspace_subfolder = "temp"
if args.command in ['generate', 'plan'] and args.target:
    workspace_subfolder = args.target
```

## Migration Notes

### For Existing Projects

1. **Update `swap_parameters.json`**:
   ```json
   {
     "base_output_path": "M:\\Your\\Project\\Path",
     ...
   }
   ```

2. **No command-line changes needed** - existing commands work the same

3. **Output location changes**:
   - OLD: `../mods/unpacked/engineswaps/vehicles/temp/`
   - NEW: `{base_output_path}/mods/unpacked/engineswaps/vehicles/{vehicle}/`

### For New Projects

1. Copy `configs/swap_parameters.json` template
2. Set `base_output_path` to your project root
3. Run commands normally - paths are automatic

## Examples

### Standard Usage (Config-Based)

```powershell
cd M:\BeamNG_Modding_Temp\scripts

# Generate for pickup (outputs to: M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles\pickup)
python engineswap.py generate "../mods/unpacked/persh_crayenne_moracc/.../engine.jbeam" pickup

# Generate for moonhawk (outputs to: M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles\moonhawk)
python engineswap.py generate "../mods/unpacked/persh_crayenne_moracc/.../engine.jbeam" moonhawk
```

### Custom Path Override

```powershell
# Force output to specific directory
python engineswap.py generate engine.jbeam pickup --output "D:\BeamNG_Testing\output"
```

### Custom Config

```powershell
# Use different configuration file
python engineswap.py generate engine.jbeam pickup --config "configs/production_config.json"
```

## Benefits

1. **Centralized Configuration**: All paths in one place
2. **Per-Vehicle Organization**: Each vehicle gets its own folder
3. **Easier Testing**: Compare outputs side-by-side
4. **Flexible**: CLI overrides still work for edge cases
5. **Version Controlled**: Config file tracks project settings
6. **Schema Validated**: Catches configuration errors early

## Related Files

- `configs/swap_parameters.json` - Main configuration
- `configs/schemas/swap_parameters.schema.json` - Validation schema
- `scripts/engineswap.py` - Implementation
- `.github/tms-build-instructions.md` - Build documentation

---

## Additional Configuration Updates - February 4, 2026

### Target Engine File Override

**New Parameter**: `target_engine_file` in `swap_parameters.json`

Allows manual specification of which BeamNG target vehicle engine file to use for TMS node extraction:

```json
{
  "target_engine_file": "pickup_engine_v8_5.5.jbeam"  // Filename only, or null for auto-selection
}
```

**Behavior**:
- If set: Searches standard paths for exact filename match
- If not found: Falls back to automatic selection with warning
- If null: Uses existing auto-selection logic

**Use Case**: Override automatic engine selection for vehicles with multiple engine variants.

---

*Document Version: 1.2*
*Last Updated: February 4, 2026*



### Slot-Aware Manifest Generation v3.0

**New Feature**: Completely rewritten manifest generation system with slot-centric organization and asset discovery.

**Changes Made:**

#### slot_graph.py - New Manifest Infrastructure
- Added `SlotAssets` dataclass: Tracks per-slot asset references (meshes, textures, sounds, materials) extracted from jbeam flexbodies/props
- Added `SlotManifestEntry` dataclass: Complete slot manifest data including source_file, requires_generation flag, and children
- Completely rewrote `SlotAwareManifestGenerator`:
  - New constructor accepts optional jbeam_parser protocol for asset extraction
  - `generate()`: Produces v3.0 slot-centric manifest with required_slots, copy_plan, mappings, statistics, validation
  - `_walk_slot_tree()`: BFS traversal from root slot discovering all dependent slots
  - `_extract_assets()`: Parses jbeam flexbodies/props/sounds for asset references
  - `_build_copy_plan()`: Categorizes files by disposition (preserve/inject/prune)
  - `generate_legacy()`: Retained for backwards compatibility with v2.0 format

#### engineswap.py - Manifest Integration
- Rewrote `generate_mod_manifest()`:
  - Primary path: When slot graph available, generates v3.0 slot-centric manifest
  - Fallback path: `_generate_legacy_manifest()` for v1.0 pattern-based scanning
- New helper methods:
  - `_discover_asset_files()`: Scans for physical mesh/texture/sound files
  - `_generate_copy_instructions()`: Human-readable packaging instructions based on copy plan
- Updated main CLI output handling for v3.0 manifest format statistics

**Manifest Format v3.0:**
```json
{
  "version": "3.0",
  "required_slots": [
    {
      "slot_type": "pickup_engine",
      "disposition": "adapt",
      "source_file": "camso_engine_3813e.jbeam",
      "requires_generation": true,
      "assets": {"meshes": ["ec8ba_mesh.dae"]},
      "children": ["Camso_engine_structure", "Camso_Intake_3813e"]
    }
  ],
  "copy_plan": {
    "original_jbeam": [{"path": "...", "provides_slots": [...]}],
    "generated_jbeam": [{"path": "...", "provides_slots": [...]}],
    "excluded_files": [{"path": "...", "reason": "pruned"}]
  },
  "asset_files": {
    "meshes": [{"name": "...", "path": "..."}],
    "textures": [...]
  }
}
```

**Benefits:**
- **Minimum Necessary Files**: Only files providing required slots are included
- **Pruning Support**: Excluded files are explicitly listed with reason
- **Asset Traceability**: Each slot lists its mesh/texture dependencies
- **Dependency Visibility**: Slot tree structure exposed via children field
- **Generation Tracking**: Clear distinction between original and generated files

**Verification:**
- Engine slotType adaptation: `Camso_Engine` → `pickup_engine`
- Engine mounts slot injection: `["pickup_enginemounts",...,{"coreSlot":true}]`
- Transmission slotType adaptation: `Camso_Transmission` → `pickup_transmission`
- Manifest v3.0 format with slot tree and asset references

---

## Slot Graph Visualization and Asset Roles - February 4, 2026

**New Features:** Added comprehensive visualization tools and asset role classification system.

**Changes Made:**

#### slot_graph.py - Visualization and Asset Roles
- Added `AssetRole` enum: `SOURCE` (extraction-only), `TARGET` (generated/exported), `PRESERVE` (original/copied), `INTERNAL` (processing artifacts)
- Added `asset_role: AssetRole` field to `SlotNode` dataclass with default `PRESERVE`
- Implemented `visualize()` method: Comprehensive tree visualization with filtering options (show_files, show_transforms, filter_role, markdown_output)
- Added role-based query methods: `get_slots_by_role()`, `get_exportable_slots()`, `get_source_slots()`
- Enhanced `print_tree()`: Now includes role indicator (S/T/P/I) in output
- Updated `SlotAwareManifestGenerator._walk_slot_tree()`: Filters out SOURCE and INTERNAL role slots from export manifest

#### engineswap.py - Asset Role Marking and CLI
- Added `_mark_asset_roles()` method: Automatically classifies slots based on patterns:
  - `SOURCE`: Files containing "engine_structure" in filename or slot type
  - `TARGET`: Injected or adapted slots (pickup_engine, pickup_transmission)
  - `PRESERVE`: Default for ecosystem slots (intake, management, internals)
- Added `visualize` CLI command with options:
  - `--show-files`: Display source file paths
  - `--show-transforms`: Show transformation history
  - `--filter-role`: Filter by asset role (source/target/preserve/internal)
  - `--markdown`: Output in markdown format (saves to file)

**Asset Role Classification Logic:**
```python
# SOURCE: Extraction-only, not exported
if "engine_structure" in filename or "engine_structure" in slot_type:
    slot.asset_role = AssetRole.SOURCE

# TARGET: Generated/adapted, exported
elif slot.is_injected or slot.disposition == Disposition.ADAPT:
    slot.asset_role = AssetRole.TARGET

# PRESERVE: Original ecosystem, copied as-is
else:
    slot.asset_role = AssetRole.PRESERVE
```

**Visualization Output Example:**
```
pickup_engine (T) [adapted from Camso_Engine]
├── Camso_engine_structure (S) [extraction only - mods/unpacked/camso/engine_structure.jbeam]
├── pickup_transmission (T) [adapted from Camso_Transmission]
├── Camso_Intake_3813e (P) [preserved - mods/unpacked/camso/intake.jbeam]
└── Camso_EngineManagement (P) [preserved]
```

**Benefits:**
- **Export Control:** SOURCE slots (engine structure) are extracted but not copied to export
- **Debugging:** Clear visibility into slot classifications and transformation state
- **Verification:** Easy confirmation that only necessary files appear in manifests
- **Development:** Faster iteration with visual feedback on graph structure

**CLI Usage:**
```bash
# Basic visualization
python engineswap.py visualize engine.jbeam pickup

# Detailed view with files and transforms
python engineswap.py visualize engine.jbeam pickup --show-files --show-transforms

# Filter to target slots only, save as markdown
python engineswap.py visualize engine.jbeam pickup --filter-role target --markdown
```

---

## Slot Replacement System - February 5, 2026

**New Feature:** Automatic slot replacement injection for SOURCE-only extraction slots.

### Problem Solved

When `Camso_engine_structure` is marked as SOURCE (extraction-only), we extract its physics nodes but the slot itself is excluded from the adapted engine's slots array. However, the **child slot** `Camso_engine_mesh` (which calls the visual mesh) must still be present.

### Implementation

#### New Utilities (slot_graph.py)

```python
# Suffix-agnostic slot matching
extract_slot_suffix("Camso_engine_structure_ec8ba")  # → ("Camso_engine_structure", "ec8ba")
apply_slot_suffix("Camso_engine_mesh", "ec8ba")       # → "Camso_engine_mesh_ec8ba"
match_slot_base("Camso_engine_mesh_ec8ba", "*engine_mesh")  # → True
```

#### Default Replacement Rules

```python
class SlotDispositionRules:
    DEFAULT_REPLACEMENTS = {
        "Camso_engine_structure": {
            "replacement_type": "Camso_engine_mesh",
            "description": "Engine Mesh",
            "options": {"coreSlot": True}
        },
    }
```

#### Configuration Override

Add to `swap_parameters.json`:
```json
{
  "slot_rules": {
    "replace_slots": {
      "Camso_engine_structure": {
        "replacement_type": "Camso_engine_mesh",
        "description": "Engine Mesh",
        "options": {"coreSlot": true}
      },
      "Custom_exhaust_manifold": {
        "replacement_type": "Custom_exhaust_outlet"
      }
    }
  }
}
```

#### Absorption Logic

When the replacement slot already exists in the graph (as a SOURCE child), `inject_replacement_slot()` performs **absorption**:

1. Re-parents the existing node to the source slot's parent (engine)
2. Changes disposition from whatever it was to `INJECT`
3. Changes asset role from `SOURCE` to `TARGET`
4. Preserves the suffix from the source slot

**Result:** No duplicate slot creation, proper hierarchy maintained.

### Verified Behavior

**Before fix:**
- `Camso_engine_structure` appeared in slots array (incorrect - it's SOURCE)
- `Camso_engine_mesh` was missing (the mesh wouldn't load)

**After fix:**
- `Camso_engine_structure` filtered from output (correct)
- `Camso_engine_mesh` injected with proper options (correct)

```json
"slots": [
    ["type","default","description"],
    ["Camso_engine_mesh","Camso_engine_mesh_ec8ba","Engine Mesh",{"coreSlot":true}],
    ["pickup_enginemounts","pickup_enginemounts","",{"coreSlot":true}],
    ...
]
```

---

## Drivetrain Adaptation Provenance + CLI Config Alignment - February 16, 2026

**Update summary:** Transfer case adaptation now produces traceable device-name remaps (derived from target analysis data), and the generated swap manifest may include a dedicated `drivetrain` section carrying those details. Documentation was aligned to the current CLI flags (config-first).

### swap_parameters.json (drivetrain selection)

These configuration fields control drivetrain adaptation behavior:

- `transmissions_to_adapt`: `"single"` or `"all"`
- `transfercase_to_adapt`: `"auto"` (decision engine selects target TC) or an explicit BeamNG TC part name
- `discard_aux_transfercase`: prunes vestigial FWD/RWD rangebox variants when safe

### Manifest additions (drivetrain provenance)

When transfer case adaptation runs, the manifest may include a top-level `drivetrain` block with traceability fields such as:

- `swap_strategy`, `selected_beamng_tc`, `adaptation_cost`
- `slots_pruned` (e.g., Camso driveshaft slots removed)
- `device_name_mapping` and `device_name_provenance` (why each mapping was derived)

This is intended to support debugging and fail-closed validation ("no hardcoded device names" gate).

### CLI alignment (config-first)

The CLI expects a single JSON config file via `--config` (defaults to `configs/swap_parameters.json`). Per-parameter CLI flags such as `--fore-aft-offset` are not part of the stable interface; solver tuning should be done by editing `solver_options` in the JSON file.

<!-- GROKDOC-PRUNE-REVAMP: This section contains RESOLVED issues mixed with active tracking.
Consider restructuring into "Resolved Issues History" subsection to preserve valuable architectural evolution. -->
## Resolved Issues History - Manifest Evolution

**Status:** ~~Identified, pending fix.~~ **RESOLVED**

### Issue: `copy_plan.generated_jbeam` Contains Source Paths

~~The manifest's copy plan shows paths to **donor** files, not the generated **adapted** files.~~

**FIXED:** Generator now computes and includes output paths.

### Solution Implemented

Added `output_base_path` parameter to `SlotAwareManifestGenerator`:

```python
generator = SlotAwareManifestGenerator(
    graph=self._slot_graph,
    jbeam_parser=JBeamParser,
    output_base_path=self.temp_path  # For computing generated file paths
)
```

Enhanced `_build_copy_plan()` to compute output paths using the same naming convention as engineswap.py:

```python
def _compute_output_path(self, source_file: Path) -> Optional[Path]:
    """Compute: {output_base_path}/{target_vehicle}_{source_stem}_adapted.jbeam"""
    source_stem = Path(source_file).stem
    output_filename = f"{self.graph.target_vehicle}_{source_stem}_adapted.jbeam"
    return self.output_base_path / output_filename
```

### New Manifest Fields

Each `generated_jbeam` entry now includes:

```json
{
  "path": "mods\\unpacked\\donor\\camso_engine_3813e.jbeam",
  "provides_slots": ["pickup_engine"],
  "disposition": "adapt",
  "output_path": "M:\\...\\pickup\\pickup_camso_engine_3813e_adapted.jbeam",
  "output_filename": "pickup_camso_engine_3813e_adapted.jbeam"
}
```

### Validation Method

Added `validate_generated_files()` method to verify computed paths match actual files:

```python
results = generator.validate_generated_files()
# Returns: {"valid": bool, "matched": [...], "missing": [...], "extra": [...]}
```

**Packaging utilities can now read `output_path` directly from the manifest.**

---

### Issue: INJECT Slots Appearing in Original Files

**Status:** RESOLVED

**Problem:** INJECT disposition slots (like engine_structure) were incorrectly appearing in `original_jbeam` copy instructions because they have `requires_generation=False` but their content is injected into adapted files.

**Solution:** Updated `_build_copy_plan()` logic to only include PRESERVE slots in original files:

```python
if entry.requires_generation:
    # ADAPT: we create an adapted version
    plan["generated_jbeam"].append(file_info)
elif entry.disposition == SlotDisposition.PRESERVE:
    # PRESERVE: copy original file as-is
    plan["original_jbeam"].append(file_info)
# INJECT: content is injected into adapted files, no copy needed
```

**Result:** INJECT slots no longer clutter copy instructions with unnecessary source files.

---

### Issue: Additional Generated Files Not Included

**Status:** RESOLVED

**Problem:** Files generated outside the slot tree (like sequential transmissions) weren't included in the manifest because the generator only knew about files in the slot dependency graph.

**Solutions:**

1. **Register generated files** in engineswap.py:
```python
if trans_output:
    print(f"    -> Generated: {trans_output.name}")
    if utility._slot_graph:
        utility._slot_graph.add_generated_file(trans_output)
```

2. **Include additional files** in manifest generator:
```python
# Add additional generated files not tracked in slot tree
for gen_file in self.graph.generated_files:
    if gen_file not in generated_paths:
        plan["generated_jbeam"].append({
            "path": "",  # No source file - generated separately
            "note": "additional_variant",
            "output_path": str(gen_file),
            "output_filename": gen_file.name
        })
```

**Result:** All generated files now appear in copy instructions, providing complete packaging guidance.

---

### Feature: Post-Transform Asset Resolution - February 5, 2026

**Status:** IMPLEMENTED

**Problem:** Asset file enumeration was scanning the entire mod folder, including:
- `ec8ba_bodymesh.dae` - vehicle body mesh (not needed for engine swap)
- 22 texture files including suspension, differential, etc. (not all needed)

**Solution:** Added `resolve_physical_assets()` method to `SlotAwareManifestGenerator` that:
1. Uses mesh names already captured in `copy_plan.asset_files.meshes`
2. Scans DAE file contents to find which contain referenced meshes
3. Returns only DAE files that provide meshes used by generated output

```python
def resolve_physical_assets(self, mod_root: Path, copy_plan: Dict) -> Dict[str, List[Dict]]:
    """
    Resolve mesh/texture/sound names from copy_plan to actual physical files.
    
    This method provides post-transform asset enumeration by:
    1. Using mesh names already captured in copy_plan.asset_files
    2. Scanning DAE files in mod_root for mesh name references
    3. Returning only DAE files that contain referenced meshes
    """
```

**Before vs After:**

| Asset Type | Before (Full Scan) | After (Post-Transform) |
|------------|-------------------|------------------------|
| Meshes | 2 files (bodymesh.dae, mesh.dae) | 1 file (mesh.dae only) |
| Textures | 22 files | 2 files (ec8ba_* prefix only) |

**Manifest Output:**
```json
{
  "asset_files": {
    "meshes": [
      {
        "name": "ec8ba_mesh",
        "path": "vehicles\\persh_crayenne_moracc\\ec8ba\\ec8ba_mesh.dae",
        "provides_meshes": ["ec8ba_engine0", "ec8ba_mainexhaustmesh281"]
      }
    ],
    "textures": [...],
    "sounds": [...]
  }
}
```

**Key Principle:** Uses existing manifest operation tracking rather than re-parsing generated files. Mesh names flow through the slot graph, and resolution matches them to physical files by scanning DAE content.

## Mod Packaging Implementation

### Overview
Added automated mod packaging system that creates complete, distributable mod packages from generated manifests.

### New Components

#### `mod_packager.py` - Standalone Packaging Utility
- **Architecture:** Class-based design with CLI interface
- **Features:**
  - Post-transform asset resolution using manifest data
  - Proper BeamNG directory structure maintenance
  - Extra asset discovery and inclusion
  - Dry-run validation and force overwrite options

#### Integration with engineswap.py
- **New CLI flags:** `--package`, `--package-dry-run`
- **Automatic packaging:** Optional integration after generation
- **Manifest integration:** Includes extra_assets config in manifest generation

### Path Structure Fixes

#### Art Folder Routing
**Problem:** `art/sound/` was placed in individual vehicle folders instead of mod package root

**Solution:** Route `art/` assets to `{mod_name}/art/` level for proper BeamNG resource loading

**Before:**
```
engineswaps/vehicles/pickup/art/sound/engine/...
```

**After:**
```
engineswaps/art/sound/engine/...
```

#### Donor Vehicle Path Stripping
**Problem:** Full donor paths like `vehicles/persh_crayenne_moracc/ec8ba/` were preserved

**Solution:** Strip donor vehicle folder, place assets directly under target vehicle:
- `vehicles/persh_crayenne_moracc/ec8ba/mesh.dae` → `ec8ba/mesh.dae`

### Mod Name Configuration

#### Moved from Hardcoded to Configurable
**Change:** `mod_name` parameter moved from hardcoded `"engineswaps"` to `swap_parameters.json`

**Benefits:**
- User control over mod package naming
- Support for themed mod collections
- Avoid naming conflicts

**Configuration:**
```json
{
  "mod_name": "engineswaps",
  "base_output_path": "M:\\BeamNG_Modding_Temp"
}
```

**Output Path:** `{base_output_path}/mods/unpacked/{mod_name}/vehicles/{target_vehicle}/`

### Extra Assets Configuration

#### New `extra_assets` Section
Added configurable inclusion of non-slot-based assets:

```json
"extra_assets": {
  "powertrain_lua": {
    "enabled": true,
    "description": "Copy lua/powertrain/*.lua files from donor mod"
  },
  "materials_json": {
    "enabled": true,
    "description": "Copy *.materials.json files matching mesh prefixes"
  }
}
```

#### Powertrain Lua Files
- **Source:** `vehicles/{donor}/lua/powertrain/*.lua`
- **Destination:** `vehicles/{target}/lua/powertrain/`
- **Files:** Engine behavior scripts (thermals, turbochargers, superchargers)

#### Materials JSON Files
- **Lookup:** `*.materials.json` files matching mesh prefixes
- **Placement:** Alongside mesh assets in target vehicle folder
- **Purpose:** Material definitions for 3D meshes

### Final Mod Structure
```
engineswaps/                          ← Configurable mod name
├── art/sound/engine/...              ← Sounds at mod root
├── vehicles/pickup/                  ← Target vehicle
│   ├── ec8ba/                        ← Stripped donor path
│   │   └── ec8ba_mesh.dae
│   ├── lua/powertrain/               ← Powertrain scripts
│   │   ├── camsoEngine.lua
│   │   └── camsoTurbocharger.lua
│   ├── ec8ba.materials.json          ← Materials
│   ├── ec8ba.png                     ← Textures
│   └── *.jbeam                       ← Generated files
```

### Schema Updates
Updated `swap_parameters.schema.json` to validate:
- `mod_name` format (alphanumeric + underscores/hyphens)
- `extra_assets` structure with powertrain_lua and materials_json objects