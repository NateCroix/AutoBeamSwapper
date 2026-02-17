# Lessons Learned - Quick Reference for AI Agents

**Purpose:** Succinct index of proven patterns, critical conventions, and gotchas. Consult this FIRST before implementing changes.

---

## ⚡ Critical Conventions

### ⚠️ JBeam is NOT JSON

JBeam files look like JSON but have **critical differences**:

| Feature | Standard JSON | JBeam |
|---------|---------------|-------|
| Comments | ❌ Not allowed | ✅ `//` and `/* */` |
| Trailing commas | ❌ Invalid | ✅ Allowed |
| **ALL commas** | Required | **OPTIONAL** |
| Leading zeros | ❌ Invalid (`00`, `007`) | ✅ Allowed |
| Control chars in strings | ❌ Invalid | ✅ Sometimes present |

**NEVER use `json.loads()` directly on JBeam content.** Always use `JBeamParser.parse_jbeam()`.

### JBeam Parsing Strategy (Updated 2026-02-03)

The `JBeamParser` class uses a **URL-safe placeholder protection strategy**:

```python
# 1. Protect URL schemes (http://, https://, file://)
content = content.replace('https://', '<<<HTTPS_SCHEME>>>')

# 2. Remove block comments /* ... */ (with negative lookbehind for //**)
content = re.sub(r'(?<!/)/\*[\s\S]*?\*/', '', content, flags=re.DOTALL)

# 3. Remove line comments // (now safe since URLs protected)
content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)

# 4. Restore URL schemes
content = content.replace('<<<HTTPS_SCHEME>>>', 'https://')

# 5. Add missing commas using 18+ regex patterns
# 6. Remove trailing commas
# 7. Parse with json.loads()
```

**Key Patterns for Missing Commas:**
- Pattern 7: `"string" -0.5` → `"string", -0.5` (negative numbers)
- Pattern 12: `"str""str"` → `"str", "str"` (adjacent strings with `$` chars)
- Pattern 17: `:00` / `,06` / `[09` → strip leading zeros (expanded Feb 2026)
- Pattern 18: `+9` → `9` (strip positive signs, added Feb 2026)

**Block Comment Gotcha (Added Feb 2026):** Some vehicles (barstow) use `//**decorative line comments**` that look like block comment starts. The negative lookbehind `(?<!/)/\*` prevents `/*` preceded by `/` from matching as a block comment opener.

**Test Coverage:** 98.6% success on 5,207 base game files. Failures are base game authoring issues (control characters, malformed syntax).

### JBeam Output Formatting

| Rule | Implementation |
|------|----------------|
| Use tabs, not spaces | `"\t"` for all indentation |
| Align node coordinates | `f"{x:>10.6f}"` - 10 chars, 6 decimal places |
| Numeric tables inline per row | `[0, -3.5],` on single line |
| Simple objects inline | `{"authors":"X","name":"Y","value":Z}` |
| Property modifiers BEFORE nodes | `{"nodeWeight":33.0}` row, then node rows inherit |
| **Compact JSON separators** | Use `separators=(',',':')` - no spaces after colons |
| **Slots as single-line arrays** | Each slot row on one line, like nodes/beams |

**Canonical Property Modifier Order** (matches BeamNG convention):
```jbeam
{"selfCollision":false},
{"collision":true},
{"frictionCoef":0.5},
{"nodeMaterial":"|NM_METAL"},
{"nodeWeight":21.62},
{"group":"engine"},
```

**Use `JBeamWriter` class** (in engineswap.py) for ALL .jbeam output.

### Node Naming Maps

Single source of truth in `mount_solver.py` (validated Feb 2026, BeamNG numeric order):

```
engine2 → e1l   (Rear-Left-Bottom)
engine3 → e1r   (Rear-Right-Bottom)
engine1 → e2l   (Front-Left-Bottom)
engine0 → e2r   (Front-Right-Bottom)
engine6 → e3l   (Rear-Left-Top)
engine7 → e3r   (Rear-Right-Top)
engine5 → e4l   (Front-Left-Top)
engine4 → e4r   (Front-Right-Top)
```

Import from mount_solver when needed: `from mount_solver import EngineCube`

### Camso File Architecture

Camso engines ALWAYS split physics and logic:

| File | Contains |
|------|----------|
| `camso_engine_<X>.jbeam` | Engine logic, torque, thermal (NO nodes) |
| `camso_engine_structure_<X>.jbeam` | Physics nodes, beams, mesh/exhaust slots |

**Structure file provides:**
- engine0-7 nodes (physics cube)
- engine_Gearbox8-11 nodes
- All inter-node beams
- Mesh slot → visual model
- Exhaust slot → exhaust system

⚠️ Neutralizing structure slot (`default: ""`) breaks mesh/exhaust loading.

### BeamNG Exhaust Architecture Patterns (Added Feb 2026)

Four distinct patterns discovered via Phase 0 exploration. The solver must handle all:

| Pattern | Topology | Example Vehicles |
|---------|----------|------------------|
| **A** | Engine → Header → Exhaust (header hosts exhaust slot) | pickup V8/I6 |
| **A'** | Engine has sibling exhaust slot (header is leaf node) | moonhawk, barstow |
| **B** | Engine → Intake → Header/Downpipe → Exhaust (nested chain) | covet front engines |
| **C** | Body/Frame hosts exhaust, decoupled from engine chain | vivace (body), fullsize (frame) |

**Cross-file resolution required:** Header parts may be defined in different jbeam files than the engine referencing them. Always build merged parsed-data dict from all engine + exhaust files before tracing chains.

### Exhaust Adapter Part Requirements (Added Feb 2026)

Generated exhaust adapter parts (`<vehicle>_exhaust_adapter`) must meet these in-game-validated constraints:

| Requirement | Value | Rationale |
|---|---|---|
| **nodeWeight** | ≥ 3 (currently 4.5) | Values < 3 cause physics instability and crashes |
| **collision** | `false` | Adapter nodes should not collide |
| **beamSpring** | Capped at 1616333 | Target headers can carry very high values causing instant beam breakage |
| **information section** | Required | Parts without `information` dict are not recognized by BeamNG |
| **Slot name = slotType = part key** | `<vehicle>_exhaust_adapter` | All three must match for proper slot loading |
| **Trailing beam reset** | After ALL beams | Must not be placed between structural and isExhaust beam groups |

### `slots` vs `slots2` Format (Added Feb 2026)

Legacy and modern BeamNG vehicles use different slot key names:

| Format | Key | Row Structure | Used By |
|--------|-----|---------------|---------|
| Legacy | `"slots"` | `[slotType, default, description]` | pickup, moonhawk, barstow, covet |
| Modern | `"slots2"` | `[name, allowTypes[], denyTypes[], default, description, {props}]` | vivace, fullsize |

Both can appear in the same vehicle (e.g., fullsize uses `slots` in engine parts, `slots2` in frame). Always scan both keys.

### Family Prefix ≠ Vehicle Name (Added Feb 2026)

BeamNG family-architecture vehicles (e.g., etk800) use a **family prefix** for drivetrain slot types that differs from the vehicle name:

| Attribute | etk800 (family) | pickup (direct) |
|-----------|-----------------|-----------------|
| `vehicle_name` | `etk800` | `pickup` |
| `engine_slot_type` | `etk_engine` | `pickup_engine` |
| `mount_slot_type` | `etk_enginemounts` | `pickup_enginemounts` |
| Engine files in | `common/etk/` | `common/pickup/` |

**NEVER synthesize slot types via `f"{vehicle_name}_<suffix>"`** — this produces non-existent slots for family vehicles. Instead, **always read actual slot entries from target engine files** using dynamic discovery methods:
- `VehicleAnalyzer.find_engine_slot_type()` → engine slots
- `VehicleAnalyzer.find_mount_slot_type()` → enginemounts slots
- Family prefix derivation: `engine_slot_type.replace('_engine', '')`

This bug pattern has appeared four times (engine files, exhaust files, exhaust slot type, engine mount slot type). Each fix followed the same corrective pattern: replace string concatenation with actual file reads.

---

## 🔧 Proven Patterns

### Dynamic Slot Type Discovery (Canonical Pattern)

**Always discover target vehicle slot types by reading actual game files.** Never synthesize via string concatenation.

```python
# WRONG — synthesizes a name that may not exist
mount_slot_type = f"{vehicle_name}_enginemounts"  # etk800_enginemounts ✗

# RIGHT — reads actual slot entries from target engine files
mount_slot_type = analyzer.find_mount_slot_type(vehicle_name, engine_slot_type)
# Discovers: etk_enginemounts ✓ (from etk_engine_i4_2.0_diesel.jbeam)
```

**Discovery methods on `VehicleAnalyzer`:**
- `find_engine_slot_type(vehicle_name)` → `"etk_engine"`
- `find_mount_slot_type(vehicle_name, engine_slot_type)` → `"etk_enginemounts"`

**Family prefix derivation (for downstream use only, never for slot synthesis):**
```python
prefix = engine_slot_type.replace('_engine', '')  # "etk"
```

**Search path order:** vehicle-specific → common/vehicle → common/family

### SlotType Adaptation

```python
# Primary part: change slotType to target vehicle
adapted_part_data['slotType'] = f"{target_vehicle.name}_engine"

# Child slots: preserve Camso ecosystem (don't change)
# Example: Camso_Intake_3813e stays as-is
```

### TMS Geometry Injection

```python
# 1. Extract from donor structure file (NOT main engine)
# 2. Translate nodes using solver result
# 3. Convert Camso names → BeamNG names
# 4. Emit property modifiers ONCE, then node rows
# 5. Generate beam connections
```

### Property Modifier Convention

**CORRECT:**
```jbeam
"nodes": [
    ["id", "posX", "posY", "posZ"],
    {"nodeWeight": 33.0109},
    {"group": "engine"},
    ["e1l", 0.25, -1.2, 0.48]  // inherits nodeWeight + group
]
```

**WRONG:**
```jbeam
"nodes": [
    ["e1l", 0.25, -1.2, 0.48, {"nodeWeight": 33.0109}]  // redundant per-node
]
```

---

## ⚠️ Gotchas

### Structure Slot Chain

The `Camso_engine_structure` slot loads a FILE that contains:
- Physics nodes
- Beams
- **Child slots for mesh and exhaust**

Setting `default: ""` prevents ALL of these from loading, not just nodes.

### TorqueReactionNodes

Must reference actual node names in the file. After TMS translation:
- Before: `["engine1", "engine2", "engine3"]`
- After: `["e2l", "e1l", "e1r"]`

### Copy Before Modify

Always deep copy part data before modifying:
```python
import copy
adapted_data = copy.deepcopy(donor_data)
```

### Path References

`SteamLibrary_content_vehicles` is a dev-environment path. Production deployment needs configurable paths.

---

## 📁 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `engineswap.py` | Orchestration, CLI, file I/O, slot adaptation, workflow integration, manifest generation, asset role marking |
| `slot_graph.py` | Unified slot dependency management, transformation pipeline, disposition rules, manifest generation, visualization |
| `mount_solver.py` | Geometry extraction, alignment calculation, node translation |
| `JBeamParser` | Reading .jbeam (strip comments, fix JSON) |
| `JBeamWriter` | Writing .jbeam (formatting, alignment) |
| `SlotAwareJBeamWriter` | Graph-aware JBeam slot section generation |
| `SlotAwareManifestGenerator` | Graph-aware mod manifest creation with asset discovery |
| `SlotAssets` | Per-slot asset reference tracking (meshes, textures, sounds) |
| `SlotManifestEntry` | Complete slot manifest data structure |
| `AssetRole` | Enum for classifying slot export behavior (SOURCE, TARGET, PRESERVE, INTERNAL) |

---

## 🔄 Adding New Translation Modules

1. **Extractor class** - Parse donor file, extract geometry
2. **Solver class** - Calculate transformation (translation, rotation, scale)
3. **Use JBeamWriter** - Write output with consistent formatting
4. **Update manifest** - Add category to `generate_mod_manifest()`
5. **Document** - Add pattern to this file

---

## 📋 Checklist Before Committing Changes

- [ ] Used `JBeamWriter._write_jbeam_file()` for all output
- [ ] Node names use BeamNG convention (e1l-e4r) not Camso (engine0-7)
- [ ] Property modifiers emitted once, not per-node
- [ ] Tabs for indentation, not spaces
- [ ] Deep copied data before modifying
- [ ] Imported node maps from single source (mount_solver.py)
- [ ] Updated relevant documentation

---

## 🏗️ Architectural Principles (February 2026)

### Target Alterations to Meld with Existing Scaffolding

The slot graph system is designed for **modularity and extensibility**. When adding new transformations:

1. **Use existing disposition rules** - Don't create parallel systems
2. **Hook into `_mark_asset_roles()`** - Central place for classification logic
3. **Follow slot replacement pattern** - For assets requiring extraction + injection
4. **Leverage suffix-agnostic matching** - Donor suffixes (`_ec8ba`) vary per vehicle

### Slot Replacement Convention

When extracting assets from a SOURCE slot, **inject the replacement slot** that calls that asset:

```python
# In SlotDispositionRules.DEFAULT_REPLACEMENTS:
"Camso_engine_structure": {
    "replacement_type": "Camso_engine_mesh",  # Slot that CALLS the extracted mesh
    "description": "Engine Mesh",
    "options": {"coreSlot": True}
}
```

**Absorption Logic:** If the replacement slot already exists in the graph (as a child of the SOURCE slot), the system:
1. Re-parents it to the SOURCE slot's parent (the engine)
2. Changes disposition to `INJECT`
3. Changes role to `TARGET`

This ensures the mesh slot appears in the adapted engine's slots array without creating duplicates.

### Manifest Evolution: From Debug to Packaging

**EVOLVED:** The manifest now serves dual purposes - debugging during development AND production packaging. The v3.0 format includes computed output paths for direct file operations:

- **Debug Purpose:** Captures slot graph state post-transformation for validation
- **Debug Purpose:** Captures slot graph state post-transformation for validation
- **Packaging Purpose:** Provides complete file manifest with output paths for automated mod building
- **Path Computation:** Manifest generator computes output paths using same logic as file generation
- **Validation:** `validate_generated_files()` ensures computed paths match actual files on disk

<!-- GROKDOC-PRUNE-VERIFICATION: Check if workflow phase descriptions reflect current manifest/packaging integration. -->
### Workflow Phases

1. **Graph Building** - Parse donor, build slot tree
2. **Role Marking** - Classify slots (SOURCE/TARGET/PRESERVE), inject replacements
3. **Slot Transformations** - Apply disposition rules, remap defaults
4. **JBeam Generation** - Write adapted files using graph state
5. **Manifest Generation** - Capture final state with output paths for packaging

---

*Last Updated: 2026-02-16 (dynamic mount slot discovery, beamSpring cap + exhaust adapter handoff documentation)*

---

## 📋 Documentation Patch Notes (Pending)

### 2026-02-16 — Dynamic Engine Mount Slot Discovery (engineswap.py, slot_graph.py)

**Problem:** Engine mount slot injection synthesized slot type as `f"{vehicle_name}_enginemounts"` — two locations: `_inject_engine_mount_slot()` in engineswap.py and `_plan_required_injections()` in slot_graph.py. For family-architecture vehicles like etk800 this produced `etk800_enginemounts`, which does not exist. The actual slot is `etk_enginemounts` (family prefix).

**Root cause:** Same category of vehicle-name-vs-family-prefix mismatch previously fixed for engine file discovery, exhaust file discovery, and exhaust slot type derivation. String-concatenation synthesis ignores the actual target ecosystem.

**Cross-vehicle survey (enginemounts slot types):**

| Vehicle | Mount Slot Type | vehicle_name == prefix? |
|---|---|---|
| pickup | `pickup_enginemounts` | Yes |
| moonhawk | `moonhawk_enginemounts` | Yes |
| barstow | `barstow_enginemounts` | Yes |
| covet | `covet_enginemounts` | Yes |
| vivace | `vivace_enginemounts` | Yes |
| fullsize | `fullsize_enginemounts` | Yes |
| wendover | `wendover_enginemounts` | Yes |
| **etk800** | **`etk_enginemounts`** | **No** |

**Fix — Fully dynamic slot discovery (not prefix synthesis):**

1. **`VehicleAnalyzer.find_mount_slot_type()`** — New method reads actual slot entries from target engine `.jbeam` files. Searches vehicle-specific, common/vehicle, and common/family paths. Returns the first `*enginemounts*` slot type found.

2. **`VehicleInfo.mount_slot_type`** — New field populated during `analyze_vehicle()`.

3. **`SlotTransformationPlanner`** — Accepts `target_mount_slot_type` parameter, used by `_plan_required_injections()` for INJECT_SLOT operations. Falls back to prefix-based derivation if discovery returns None.

4. **`_inject_engine_mount_slot()`** — Now receives the discovered mount slot type directly instead of synthesizing from vehicle name.

5. **Threading:** `analyze_vehicle()` → `_build_slot_graph()` → `plan_and_execute_transformations()` → `SlotTransformationPlanner.__init__()`.

**Pattern established:** All slot type derivation for target vehicle ecosystems should read from actual game data files, not synthesize via string concatenation. This is now the fourth instance of this pattern being applied (engine, exhaust files, exhaust slot type, engine mounts).

**Tests:** 188 passed (no regressions). etk800: `etk_enginemounts` correctly discovered and injected. pickup: `pickup_enginemounts` correctly discovered (direct architecture unaffected).

**Problem:** First in-game test of generated exhaust adapter revealed multiple issues causing crashes and part loading failures.

**Fixes applied (4 items):**

1. **nodeWeight ≥ 3 required:** Initial value of 0.5 caused physics instability and game crashes. Changed to 4.5. BeamNG requires adapter nodes to have substantial weight — lightweight bridge nodes become numerically unstable under engine vibration.

2. **`information` section required:** Parts without an `information` dict (`{"authors":"BeamNGCommunity","name":"Exhaust Adapter","value":200}`) are not properly recognized by BeamNG's part system. This section is mandatory for all jbeam parts.

3. **Slot name/type must match:** Previously slotType was generic `adapted_exhaust_component` while part name was `<vehicle>_adapted_exhaust_component` — a mismatch. Renamed to `<vehicle>_exhaust_adapter` for both slotType and part name. The slot entry, slot type, and part key must all use the same string.

4. **Trailing beam reset position:** The trailing beam property reset row (`{"beamPrecompression":1,"beamType":"|NORMAL","beamLongBound":1.0,"beamShortBound":1.0}`) was placed between structural and isExhaust beams. Must appear AFTER all beams (structural + isExhaust). Interleaving property resets between beam groups causes in-game issues.

**Naming convention change:**
- Old: `adapted_exhaust_component` (slot type), `<vehicle>_adapted_exhaust_component` (part name), `"Exhaust Bridge"` (description)
- New: `<vehicle>_exhaust_adapter` (slot type = part name), `"Exhaust Adapter"` (description)
- Node group: `adapted_exhaust_component` → `exhaust_adapter`

**Tests:** 108 tests pass (96 exhaust_solver + 12 integration). In-game verified — part loads, no crashes, correct beam layout.

### 2026-02-15 — Gearbox `isExhaust` Promotion Fix (mount_solver.py)

**Problem:** Some Camso engines (c9a0e, camsonav6/036a5) place `{"isExhaust":"mainEngine"}` on `engine_Gearbox8`/`engine_Gearbox9` nodes instead of engine cube nodes (`engine0-7`). During TMS adaptation, gearbox nodes are popped from the engine cube for mass redistribution. The `isExhaust` property was silently lost, producing adapted engines with 0 isExhaust nodes.

**Fix:** Added `DonorEngineExtractor._promote_gearbox_isExhaust()` — called during `extract()` before gearbox nodes are separated. Transfers `isExhaust` from gearbox nodes to the nearest eligible engine cube node.

**Eligibility constraints:**
1. **Floor-plane Z match** (within 0.15m of the gearbox node's Z) — exhaust stays on engine bottom, not top.
2. **Not `engine_intake`** — avoids nodes with `"engine_intake"` in their `engineGroup`.
3. **Not already carrying `isExhaust`** — prevents double-assignment.

**Concrete mappings validated:**
- c9a0e: `engine_Gearbox8 → engine3` (→ e1r), `engine_Gearbox9 → engine2` (→ e1l)
- 036a5 (camsonav6): same pattern, slightly different distances

**Affected inventory:** 2 out of 14 Camso engines in `mods/unpacked/`. The remaining 12 already place `isExhaust` on engine block nodes and are unaffected (no-op path).

**Tests:** 9 new tests in `test_mount_solver.py` — 7 unit (mock data) + 2 integration (real c9a0e/036a5 files). 106 total tests pass, no regressions.

**Docs to update (by documentation agent):**
- `docs/lessons_learned.md` — Add entry under relevant section (Camso engine structure gotcha)
- `docs/exhaust_solver.md` — Note in Phase 2 known limitations removal or revision (gearbox engines now produce correct isExhaust counts)
- `README.md` — If mount_solver section exists, note the promotion capability
