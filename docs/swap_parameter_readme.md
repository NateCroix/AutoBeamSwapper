# Swap Parameters Reference

This document describes all configurable parameters for the Transplant Mounting Solver (TMS).

---

## Overview

The swap parameters file (`swap_parameters.json`) allows users to fine-tune how the TMS positions a donor engine within the target vehicle's engine bay. Parameters can be:

1. **Set manually** by users who understand the geometry
2. **Populated by an AI agent** based on user intent
3. **Left at defaults** for automatic "best guess" positioning

---

## File Format

```json
{
  "$schema": "./schemas/swap_parameters.schema.json",
  "version": "1.0",
  "description": "Human-readable description of this swap configuration",
  
  "mod_name": "engineswaps",
  "base_output_path": "M:\\BeamNG_Modding_Temp",
  "base_vehicles_path": "M:\\BeamNG_Modding_Temp\\SteamLibrary_content_vehicles",
  "target_engine_file": null,
  
  "slot_rules": {
    "prune_slots": ["Camso_Nitrous"],
    "preserve_slots": ["Camso_Intake_3813e"],
    "force_adapt_slots": [],
    "inject_slots": [],
    "replace_slots": {}
  },
  
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
  },
  
  "transmissions_to_adapt": "single",
  "transfercase_to_adapt": "auto",
  "discard_aux_transfercase": true,
  
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
}
```

---

## Path Configuration

### `base_output_path`

| Property | Value |
|----------|-------|
| **Type** | `string` (absolute path) |
| **Default** | None (required for proper operation) |
| **CLI Override** | `--output` |

The root directory where generated mod files will be placed. The script builds the full output path as `{base_output_path}/mods/unpacked/engineswaps/vehicles/{target_vehicle}/`.

**Example:**
```json
"base_output_path": "M:\\BeamNG_Modding_Temp"
```

### `mod_name`

| Property | Value |
|----------|-------|
| **Type** | `string` |
| **Default** | `"engineswaps"` |
| **Format** | Alphanumeric characters, underscores, and hyphens only |

The name of the mod package folder. This becomes the root folder name in the output path: `{base_output_path}/mods/unpacked/{mod_name}/vehicles/{target_vehicle}/`.

**Description:**

Controls the mod package name for organization and distribution. The mod package contains all assets (vehicles, sounds, etc.) for the engine swap.

**Behavior:**

- Used as the folder name under `mods/unpacked/`
- Shared across all engine swaps in the same session
- Must be filesystem-safe (no spaces or special characters)

**Examples:**

```json
"mod_name": "engineswaps"           // Default - generic engine swaps
"mod_name": "cummins_diesel_swaps"  // Specific engine family
"mod_name": "custom_performance"    // Custom performance mods
```

**When to change:**

- For organizing different types of engine swaps
- When distributing mods with specific themes
- To avoid conflicts with other mod packages

### `base_vehicles_path`

| Property | Value |
|----------|-------|
| **Type** | `string` (absolute path) |
| **Default** | `SteamLibrary_content_vehicles` (dev fallback) |
| **CLI Override** | `--base-path` |

Path to BeamNG's base game vehicle files. TMS uses this to locate target vehicle engine geometry for node translation. This should point to an extracted copy of BeamNG's content vehicles folder.

**Example:**
```json
"base_vehicles_path": "M:\\BeamNG_Modding_Temp\\SteamLibrary_content_vehicles"
```

**For deployed usage (actual game files):**
```json
"base_vehicles_path": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\BeamNG.drive\\content\\vehicles"
```

### `target_engine_file`

| Property | Value |
|----------|-------|
| **Type** | `string` or `null` |
| **Default** | `null` |
| **Format** | Filename only (no path) |

Specifies the exact BeamNG target vehicle engine file to use for TMS node extraction, overriding automatic selection.

**Description:**

By default, TMS automatically selects the target vehicle's engine file (preferring non-"race" variants). This parameter allows manual specification when the automatic selection doesn't match the desired engine configuration.

**Behavior:**

- `null` (default): Use automatic selection logic
- `"filename.jbeam"`: Search for this exact filename in standard locations (vehicle folder, common folder)
- If specified file not found: Log warning and fall back to automatic selection

**Examples:**

```json
"target_engine_file": null                           // Automatic selection
"target_engine_file": "pickup_engine_v8_5.5.jbeam"   // Specific V8 engine
"target_engine_file": "common_engine_i6_3.0.jbeam"   // Common folder engine
```

**When to use:**

- When automatic selection picks the wrong engine variant
- For vehicles with multiple engine options
- To ensure consistent engine geometry across swaps

---

## Slot Rules

The `slot_rules` section controls how individual slots are handled during the adaptation process. This uses the slot graph system for unified slot dependency management.

### `prune_slots`

| Property | Value |
|----------|-------|
| **Type** | `array` of `string` |
| **Default** | `[]` |
| **Format** | Slot type patterns (supports wildcards) |

Slots to completely remove from the adapted engine, including all their child dependencies.

**Examples:**
```json
"prune_slots": ["Camso_Nitrous", "Camso_Supercharger_*"]
```

**Use Case:** Remove unwanted features like nitrous systems or superchargers that aren't desired in the swap.

### `preserve_slots`

| Property | Value |
|----------|-------|
| **Type** | `array` of `string` |
| **Default** | `[]` |
| **Format** | Slot type patterns |

Slots to keep unchanged in their original donor namespace, overriding automatic adaptation patterns.

**Examples:**
```json
"preserve_slots": ["Camso_Intake_3813e", "Camso_EngineManagement_*"]
```

**Use Case:** Keep ecosystem slots (intake, engine management) in donor namespace for compatibility.

### `force_adapt_slots`

| Property | Value |
|----------|-------|
| **Type** | `array` of `string` |
| **Default** | `[]` |
| **Format** | Slot type patterns |

Slots to force adapt to target vehicle namespace, even if they would normally be preserved.

**Examples:**
```json
"force_adapt_slots": ["Camso_CustomSlot"]
```

**Use Case:** Override default patterns for specific slots that need vehicle-specific adaptation.

### `inject_slots`

| Property | Value |
|----------|-------|
| **Type** | `array` of `string` |
| **Default** | `[]` |
| **Format** | Slot type identifiers |

New slots to inject that don't exist in the donor files.

**Examples:**
```json
"inject_slots": ["pickup_enginemounts"]
```

**Use Case:** Add required slots like enginemounts that are provided by the target vehicle infrastructure.

### `replace_slots`

| Property | Value |
|----------|-------|
| **Type** | `object` |
| **Default** | `{}` |
| **Format** | Key-value pairs of slot type replacements |

Slot replacement rules that automatically substitute SOURCE slots with their asset-calling counterparts during adaptation.

**Description:**

The slot replacement system handles automatic substitution of extraction-only slots (marked as SOURCE) with their corresponding asset-calling versions. This ensures clean adapted output by replacing slots that would otherwise be removed during SOURCE filtering.

**Behavior:**

- Keys: Slot type patterns to replace (supports wildcards)
- Values: Replacement slot type patterns
- Uses suffix-agnostic matching for flexible pattern recognition
- Absorption logic prevents duplicate slots when replacements already exist
- Only applied to slots marked as SOURCE during asset role classification

**Examples:**

```json
"replace_slots": {
  "Camso_Engine_*": "pickup_engine_*",
  "Camso_Intake_*": "pickup_intake_*",
  "Camso_Exhaust_*": "pickup_exhaust_*"
}
```

**Use Case:** Automatically convert Camso-specific slot types to vehicle-appropriate equivalents, ensuring proper slot hierarchy and dependencies in the adapted engine.

---

## Solver Options

### `swpparam_FixMeshOffset`

| Property | Value |
|----------|-------|
| Type | `boolean` |
| Default | `false` |
| Options | `true`, `false` |

**Description:**

Controls whether the visual engine mesh position is corrected to align with the physics node centroid.

**Background:**

Camso/Automation engines often have their visual mesh offset from the physics nodes. This is done intentionally to tune vehicle center of gravity (CoG) while maintaining visual realism. The engine nodes might be positioned rearward (for better weight distribution) while the mesh stays in the visually correct location.

When transplanting to a BeamNG vehicle, this offset may cause visual misalignment.

**Behavior:**

- `false` (default): Preserve original Camso mesh offset. Engine visual may not align with where physics nodes indicate.
- `true`: Calculate and apply correction variables (`$EngineOffsetXVis`, `$EngineOffsetYVis`, `$EngineOffsetZVis`) to center the mesh on the translated physics nodes.

**When to use:**

- Set to `true` if the engine appears visually offset in the engine bay
- Leave `false` if original Camso positioning looks acceptable

---

### `swpparam_ShrinkOrExpand`

| Property | Value |
|----------|-------|
| Type | `enum` |
| Default | `"none"` |
| Options | `"none"`, `"shrink_engine_block"`, `"expand_engine_mounts"` |

**Description:**

Specifies how to handle interference when target vehicle's engine mount nodes (`em1l`, `em1r`, `tra1`) would be positioned inside the donor engine's bounding box.

**Background:**

The engine mount nodes must be OUTSIDE the engine block bounding box for proper physics. If a larger donor engine is placed such that its cube encompasses where the mount nodes need to be, the mounts will conflict with the engine.

**Behavior:**

- `"none"`: No automatic resolution. Log warning and proceed. May cause physics instability.
  
- `"shrink_engine_block"`: Scale the engine cube nodes inward (toward centroid) until all mount nodes are outside the bounding box. Subject to `max_shrink_percent` limit.
  
- `"expand_engine_mounts"`: Move conflicting mount nodes outward until they clear the engine cube. Subject to `max_mount_expansion_m` limit. Note: This changes where the engine attaches to the chassis.

**When to use:**

- Start with `"none"` and test in-game
- If engine "jitters" or explodes, try `"shrink_engine_block"`
- Use `"expand_engine_mounts"` as last resort (may affect handling)

**Visual Diagram:**

```
Before (interference):
┌───────────────┐
│  ENGINE CUBE  │
│     ·em1l     │ ← Mount INSIDE cube (BAD)
│               │
└───────────────┘

After shrink_engine_block:
  ┌───────────┐
  │  ENGINE   │
  │   CUBE    │
  └───────────┘
·em1l           ← Mount now OUTSIDE (GOOD)

After expand_engine_mounts:
┌───────────────┐
│  ENGINE CUBE  │
│               │
└───────────────┘
        ·em1l   ← Mount moved outward (GOOD)
```

---

### `swpparam_ForeAftOffset`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `0.0` |
| Unit | meters |
| Convention | `+` = rearward (toward trunk), `-` = forward (toward bumper) |

**Description:**

Additional longitudinal (Y-axis) offset applied to the engine position after the solver's base alignment.

**Background:**

The TMS first aligns flywheel planes between donor and target engines. This parameter allows fine-tuning that baseline position to:

- Adjust center of gravity (move engine rearward for better balance)
- Clear hood/firewall obstructions
- Align with visual reference points

**Behavior:**

Applied as the final step before interference checking. This offset moves ALL engine assembly nodes together.

**Examples:**

```json
"swpparam_ForeAftOffset": 0.0     // No adjustment
"swpparam_ForeAftOffset": 0.05    // Move engine 5cm rearward
"swpparam_ForeAftOffset": -0.03   // Move engine 3cm forward
```

**When to use:**

- Start at `0.0`
- If engine clips through firewall: use negative value
- If engine clips through radiator support: use positive value
- To shift CoG rearward: use positive value

---

### `swpparam_UpDownOffset`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `0.0` |
| Unit | meters |
| Convention | `+` = upward, `-` = downward |

**Description:**

Additional vertical (Z-axis) offset applied to the engine position after the solver's base alignment.

**Background:**

The TMS aligns the engine floor plane with the target's floor plane. This parameter allows adjustment for:

- Hood clearance (raise engine)
- Oil pan clearance (raise engine)
- Lowered appearance (lower engine)
- CoG adjustment

**Behavior:**

Applied after floor plane alignment. Moves ALL engine assembly nodes together.

**Examples:**

```json
"swpparam_UpDownOffset": 0.0      // No adjustment
"swpparam_UpDownOffset": 0.02     // Raise engine 2cm
"swpparam_UpDownOffset": -0.01    // Lower engine 1cm
```

**When to use:**

- Start at `0.0`
- If oil pan clips through subframe: use positive value
- If engine clips through hood: use negative value
- For aesthetic lowered look: use negative value (carefully)

---

### `swpparam_LeftRightOffset`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `0.0` |
| Unit | meters |
| Convention | `+` = right (passenger side), `-` = left (driver side) |

**Description:**

Additional lateral (X-axis) offset applied to the engine position.

**Background:**

Most engine swaps should center the engine, but some scenarios require lateral adjustment:

- Asymmetric exhaust routing
- Steering component clearance
- Non-centered engine bay designs

**Behavior:**

Applied with other offsets. Rarely needed.

**Examples:**

```json
"swpparam_LeftRightOffset": 0.0    // Centered (default)
"swpparam_LeftRightOffset": 0.02   // Shift 2cm to passenger side
```

**When to use:**

- Almost always leave at `0.0`
- Only adjust if there's an asymmetric clearance issue

---

## Limits

These parameters control the maximum automatic adjustments the solver can make.

### `max_shrink_percent`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `15` |
| Unit | percent |

**Description:**

Maximum percentage the engine cube can be scaled down when using `shrink_engine_block` interference resolution.

**Rationale:**

Shrinking the engine cube too much would:
- Distort mass distribution
- Cause unrealistic physics behavior
- Make the engine visually smaller than its mesh

15% is a reasonable limit that handles minor interferences without major distortion.

---

### `max_mount_expansion_m`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `0.1` |
| Unit | meters |

**Description:**

Maximum distance mount nodes can be moved outward when using `expand_engine_mounts` interference resolution.

**Rationale:**

Moving mounts too far from their designed positions would:
- Change handling characteristics
- Create unrealistic long mount arms
- Potentially cause instability

0.1m (10cm) is enough to clear most interferences without excessive modification.

---

### `min_mount_clearance_m`

| Property | Value |
|----------|-------|
| Type | `float` |
| Default | `0.02` |
| Unit | meters |

**Description:**

Minimum gap required between mount nodes and engine cube boundary.

**Rationale:**

A small buffer prevents edge-case physics issues and allows for beam flex without immediate collision.

---

## Output Options

### `format`

| Property | Value |
|----------|-------|
| Type | `enum` |
| Default | `"embedded"` |
| Options | `"embedded"`, `"separate"` |

**Description:**

Controls how translated nodes are written to output files.

- `"embedded"`: Nodes/beams written directly into adapted engine .jbeam file (Cummins pattern)
- `"separate"`: Generate separate `{vehicle}_engine_structure.jbeam` file (Camso pattern)

**Recommendation:** Use `"embedded"` for better compatibility with BeamNG conventions.

---

### `generate_debug_visualization`

| Property | Value |
|----------|-------|
| Type | `boolean` |
| Default | `false` |

**Description:**

When `true`, generates additional visual markers in the output for debugging:
- Highlighted nodes for engine cube corners
- Colored spheres at mount positions
- Visible planes for flywheel/floor reference

Useful for troubleshooting but should be disabled for final output.

---

## Usage Examples

### Example 1: Default Configuration

```json
{
  "version": "1.0",
  "description": "Default automatic positioning",
  "solver_options": {
    "swpparam_FixMeshOffset": false,
    "swpparam_ShrinkOrExpand": "none",
    "swpparam_ForeAftOffset": 0.0,
    "swpparam_UpDownOffset": 0.0,
    "swpparam_LeftRightOffset": 0.0
  }
}
```

### Example 2: Large Engine Swap (Needs Shrinking)

```json
{
  "version": "1.0",
  "description": "Big block into compact car - needs shrink to clear mounts",
  "solver_options": {
    "swpparam_FixMeshOffset": true,
    "swpparam_ShrinkOrExpand": "shrink_engine_block",
    "swpparam_ForeAftOffset": 0.03,
    "swpparam_UpDownOffset": 0.02,
    "swpparam_LeftRightOffset": 0.0
  },
  "limits": {
    "max_shrink_percent": 20
  }
}
```

### Example 3: Fine-Tuned CoG Adjustment

```json
{
  "version": "1.0",
  "description": "Rear-biased CoG for drifting",
  "solver_options": {
    "swpparam_FixMeshOffset": false,
    "swpparam_ShrinkOrExpand": "none",
    "swpparam_ForeAftOffset": 0.08,
    "swpparam_UpDownOffset": -0.02,
    "swpparam_LeftRightOffset": 0.0
  }
}
```

---

## Command Line Usage

```bash
# Use default config (configs/swap_parameters.json)
python scripts/engineswap.py generate donor.jbeam pickup

# Use a custom swap_parameters.json
python scripts/engineswap.py generate donor.jbeam pickup --config path/to/swap_parameters.json

# Override common paths without editing JSON
python scripts/engineswap.py generate donor.jbeam pickup --base-path "D:\\BeamNG\\content\\vehicles" --output "D:\\BeamNG_Testing"

# Package the generated swap (or preview what would be copied)
python scripts/engineswap.py generate donor.jbeam pickup --package
python scripts/engineswap.py generate donor.jbeam pickup --package-dry-run

# Debug / introspection (slot graph visualization)
python scripts/engineswap.py visualize donor.jbeam pickup --show-files --show-transforms --filter-role target --markdown
```

Offsets and solver tuning are configured via JSON (`solver_options`, `limits`, etc.). For example, to move the engine 5cm rearward, set `solver_options.swpparam_ForeAftOffset` to `0.05` in `swap_parameters.json`.

---

## Drivetrain Adaptation Options

These options control how the Camso donor's drivetrain components (transmissions, transfer cases) are filtered and adapted during the swap.

### `transmissions_to_adapt`

| Property | Value |
|----------|-------|
| **Type** | `string` |
| **Values** | `"single"`, `"all"` |
| **Default** | `"single"` |

Controls how many Camso transmission files are adapted.

- `"single"`: Only adapt the transmission declared as default by the engine's child slot. Vestigial transmissions (sequential, race variants, etc.) that are not the engine's declared default are skipped.
- `"all"`: Adapt all discovered Camso transmission files.

**Rationale:** Camso vehicle folders often contain multiple transmission variants (automatic, sequential, racing) that are not part of the user's intended Automation export. The `"single"` mode ensures only the engine's declared default transmission is adapted.

### `transfercase_to_adapt`

| Property | Value |
|----------|-------|
| **Type** | `string` |
| **Values** | `"auto"`, `"<part_name>"` |
| **Default** | `"auto"` |

Controls transfer case selection strategy.

- `"auto"`: Selects the lowest-cost compatible target TC variant using the drivetrain swap decision engine.
- `"<part_name>"`: Specify a BeamNG TC part name (e.g., `"pickup_transfercase_4WD"`) for direct strategy lookup. The swap engine will use the specified part to determine the drivetrain strategy instead of evaluating all candidates.

### `discard_aux_transfercase`

| Property | Value |
|----------|-------|
| **Type** | `boolean` |
| **Default** | `true` |

Prunes vestigial Camso rangebox-variant transfer case parts from FWD and RWD donors.

**Background:** Camso FWD and RWD `transfercase.jbeam` files commonly contain two parts sharing the same `slotType: "Camso_TransferCase"`:
- **Primary**: `Camso_TransferCase_<FWD|RWD>_<hash>` — simple shaft pass-through
- **Rangebox variant**: `Camso_TransferCase_<FWD|RWD>_rangebox_<hash>` — adds a `rangeBox` powertrain device for hi/lo range selection, plus controllers and stabilization overrides

The rangebox variant is rarely user-intended and adds unnecessary complexity to the adapted mod. When enabled, this option:
1. Identifies the **primary TC** from the donor transmission's slot declaration (immune from pruning)
2. Prunes parts matching the `_(FWD|RWD)_rangebox_` pattern, provided they are NOT the primary
3. Post-fixes the adapted transmission file if the slot graph's default pointed to a discarded part

**Safety:** The primary TC (declared as default in the transmission's slot) is always preserved. Parts are matched by regex pattern `_(FWD|RWD)_rangebox_` — AWD and 4WD transfer cases are not affected. If the primary TC cannot be identified, pruning is disabled entirely to avoid false positives.

---

## Extra Assets Configuration

The `extra_assets` section controls the inclusion of additional asset types that are not automatically discovered through slot-based manifest generation. These assets are copied from the donor mod using specific lookup patterns.

### `powertrain_lua`

| Property | Value |
|----------|-------|
| **Type** | `object` |
| **Default** | `{"enabled": true, "description": "Copy lua/powertrain/*.lua files from donor mod"}` |

Controls copying of Lua powertrain scripts required for engine functionality in BeamNG.

**Description:**

Camso engines require Lua scripts for powertrain behavior (turbochargers, superchargers, thermals, etc.). These files are located in `vehicles/{donor_vehicle}/lua/powertrain/` and are copied to `vehicles/{target_vehicle}/lua/powertrain/`.

**Configuration:**

```json
"powertrain_lua": {
  "enabled": true,
  "description": "Copy lua/powertrain/*.lua files from donor mod"
}
```

**Files copied:**
- `camsoEngine.lua` - Main engine behavior
- `camsoEngineThermals.lua` - Thermal management
- `camsoSupercharger.lua` - Supercharger behavior
- `camsoTurbocharger.lua` - Turbocharger behavior

### `materials_json`

| Property | Value |
|----------|-------|
| **Type** | `object` |
| **Default** | `{"enabled": true, "description": "Copy *.materials.json files matching mesh prefixes"}` |

Controls copying of materials definition files that accompany mesh assets.

**Description:**

BeamNG uses `.materials.json` files to define material properties for 3D meshes. These files are matched to mesh files by prefix (e.g., `ec8ba.materials.json` accompanies `ec8ba_mesh.dae`).

**Configuration:**

```json
"materials_json": {
  "enabled": true,
  "description": "Copy *.materials.json files matching mesh prefixes"
}
```

**Lookup logic:**
- Scans for `*.materials.json` files in the same directory as mesh assets
- Matches files where the stem matches mesh prefixes (e.g., `ec8ba.materials.json` for `ec8ba_*` meshes)

---

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Engine falls through ground | Mount nodes inside engine cube | Set `swpparam_ShrinkOrExpand: "shrink_engine_block"` |
| Engine jitters violently | Mount interference or beam conflict | Check interference, try shrink option |
| Engine clips through hood | Engine positioned too high | Set negative `swpparam_UpDownOffset` |
| Engine clips through firewall | Engine positioned too far back | Set negative `swpparam_ForeAftOffset` |
| Visual mesh offset from engine bay | Camso visual offset preserved | Set `swpparam_FixMeshOffset: true` |
| Engine very small visually | Shrink too aggressive | Reduce `max_shrink_percent` |

---

*Last Updated: February 16, 2026*
