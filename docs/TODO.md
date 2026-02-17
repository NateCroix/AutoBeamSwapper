# Project TODO List


## Slot Graph Integration - COMPLETED (2026-02-04)

**Issue Resolved:** Fragmented slot handling across adaptation, parsing, and output phases led to inconsistent slot transformations and potential dependency breaks.

**Root Causes Addressed:**
1. Scattered slot operations in `EngineTransplantUtility` methods
2. No unified state management for slot dependencies
3. Inconsistent slot type and part name mappings
4. Lack of traceability for transformation operations

**Solution Implemented:**
- Created `slot_graph.py` module with graph-based slot dependency management
- Integrated slot graph into `engineswap.py` workflow (Phase 2 complete)
- Added disposition rules for configurable slot handling (preserve/adapt/prune/inject)
- Implemented protocol-based parser injection to avoid circular imports
- Added fallback behavior for graceful degradation when slot graph unavailable

**Key Features Delivered:**
- Unified slot state management with `SlotGraph` class
- Transformation pipeline: Build → Plan → Execute → Output
- Configurable disposition rules via `swap_parameters.json`
- Graph-aware JBeam writers and manifest generators
- Complete audit trail with transformation records

**Integration Points:**
- `EngineTransplantUtility.__init__()`: Added slot graph availability check
- `generate_adapted_jbeam()`: Builds slot graph after parsing
- `_create_adapted_part_name()`: Delegates to graph for consistency
- `generate_mod_manifest()`: Uses `SlotAwareManifestGenerator`

**Test Coverage:** All 8 slot_graph tests pass, integration verified with "Slot Graph: ENABLED" log message.

**Benefits:**
- Single source of truth for all slot operations
- Prevents dependency chain breaks
- Enables safe slot pruning and injection
- Provides full traceability of transformations
- Maintains backwards compatibility

---

## Slot-Aware Manifest Generation - COMPLETED (2026-02-04)

**Issue Resolved:** Manifest generation was pattern-based file scanning that included unnecessary files and lacked slot-aware asset discovery.

**Root Causes Addressed:**
1. Broad file scanning included potentially unused assets
2. No linkage between slots and their required meshes/textures
3. Pattern-based categorization didn't reflect actual slot dependencies
4. No pruning awareness for excluded slot assets

**Solution Implemented:**
- Completely rewrote `SlotAwareManifestGenerator` for v3.0 slot-centric manifest
- Added `SlotAssets` and `SlotManifestEntry` dataclasses for structured data
- Implemented asset extraction from jbeam flexbodies/props/sounds
- Added `_walk_slot_tree()` for graph traversal and dependency discovery
- Created `_build_copy_plan()` for categorized file organization
- Enhanced `engineswap.py` manifest integration with fallback support

**Key Features Delivered:**
- **Slot-Centric Organization:** Manifest organized around slots with asset traceability
- **Asset Discovery:** Parses jbeam files for mesh/texture/sound references per slot
- **Pruning Support:** Excluded files explicitly listed with pruning reasons
- **Copy Plan:** Clear distinction between original, generated, and excluded files
- **Dependency Visibility:** Slot tree structure exposed via children relationships
- **Backwards Compatibility:** Retained v2.0 format generation for legacy support

**Manifest Format v3.0:**
```json
{
  "version": "3.0",
  "required_slots": [{
    "slot_type": "pickup_engine",
    "disposition": "adapt",
    "source_file": "camso_engine_3813e.jbeam",
    "requires_generation": true,
    "assets": {"meshes": ["ec8ba_mesh.dae"]},
    "children": ["Camso_engine_structure"]
  }],
  "copy_plan": {
    "original_jbeam": [...],
    "generated_jbeam": [...],
    "excluded_files": [...]
  }
}
```

**Integration Points:**
- `EngineTransplantUtility.generate_mod_manifest()`: Primary path uses v3.0, fallback to v1.0
- New helper methods: `_discover_asset_files()`, `_generate_copy_instructions()`
- CLI output updated for v3.0 manifest statistics

**Verification:**
- Engine slotType adaptation: `Camso_engine_structure` → `pickup_engine`
- Engine mounts injection: `["pickup_enginemounts",...,{"coreSlot":true}]`
- Transmission adaptation: `Camso_Transmission` → `pickup_transmission`
- Manifest v3.0 format with complete slot tree and asset references

---
## Slot Graph Visualization and Asset Roles - COMPLETED (2026-02-04)

**Issue Resolved:** Need for visualization tools to debug slot graph transformations and asset role classification for proper export control.

**Root Causes Addressed:**
1. Lack of visibility into slot graph structure during development
2. No way to verify asset role assignments
3. Difficulty debugging transformation pipelines
4. No clear distinction between extraction-only vs exportable slots

**Solution Implemented:**
- Added `AssetRole` enum (SOURCE, TARGET, PRESERVE, INTERNAL) for export classification
- Added `asset_role` field to `SlotNode` dataclass
- Implemented `visualize()` method with comprehensive filtering options
- Added role-based filtering methods: `get_slots_by_role()`, `get_exportable_slots()`, `get_source_slots()`
- Enhanced `print_tree()` with role indicators
- Updated `SlotAwareManifestGenerator._walk_slot_tree()` to filter SOURCE/INTERNAL slots from export
- Added `_mark_asset_roles()` method in engineswap.py for automatic role assignment
- Implemented `visualize` CLI command with options for files, transforms, role filtering, and markdown output

**Key Features Delivered:**
- **Asset Role Classification:** Automatic marking based on filename patterns and slot types
- **Comprehensive Visualization:** Tree display with role indicators, file paths, and transformation history
- **CLI Integration:** `visualize` command with filtering options and markdown export
- **Export Control:** SOURCE slots (like engine structure) are extracted but not exported
- **Debugging Support:** Clear visibility into slot relationships and transformation state

**Visualization Output:**
```
pickup_engine (T) [adapted from Camso_Engine]
├── Camso_engine_structure (S) [extraction only]
├── pickup_transmission (T) [adapted from Camso_Transmission]
├── Camso_Intake_3813e (P) [preserved]
└── Camso_EngineManagement (P) [preserved]
```

**CLI Usage:**
```bash
python engineswap.py visualize engine.jbeam pickup --show-files --filter-role target --markdown
```

**Benefits:**
- **Debugging:** Clear visibility into slot graph structure and transformations
- **Verification:** Easy confirmation of asset role assignments
- **Export Control:** Prevents unnecessary files from being included in manifests
- **Development:** Faster iteration with visual feedback on graph state

---
## Manifest Packaging Enhancement - COMPLETED (2026-02-05)

**Issue Resolved:** Manifest was debug-only; needed actual output paths for production packaging utility.

**Root Causes Addressed:**
1. Manifest lacked computed output paths for file operations
2. Copy instructions showed source filenames instead of generated filenames
3. No validation that computed paths matched actual generated files

**Solutions Implemented:**
- Enhanced `SlotAwareManifestGenerator` with `output_base_path` parameter
- Added `_compute_output_path()` method using same logic as `engineswap.py`
- Extended `copy_plan.generated_jbeam` entries with `output_path` and `output_filename` fields
- Added `validate_generated_files()` method for path validation
- Updated copy instructions to display actual output filenames

**Benefits:**
- **Packaging-Ready:** Manifest now contains actual output paths for direct file operations
- **Validation:** Ensures computed paths match files on disk
- **Clear Instructions:** Copy instructions show final generated filenames
- **Consistency:** Same path computation logic used for generation and packaging

---
## Manifest Copy Plan Fixes - COMPLETED (2026-02-05)

**Issue Resolved:** Manifest copy instructions were inaccurate - showing unnecessary INJECT source files and missing additional generated files.

**Root Causes Addressed:**
1. INJECT disposition slots were incorrectly categorized as original files
2. Files generated outside slot tree weren't included in manifest
3. Copy instructions didn't provide complete packaging guidance

**Solutions Implemented:**
- Updated `_build_copy_plan()` logic to exclude INJECT slots from original files
- Added registration of generated files in engineswap.py workflow
- Enhanced manifest generator to include additional generated files
- Improved copy plan categorization by disposition type

**Benefits:**
- **Accurate Instructions:** Copy instructions only show necessary files
- **Complete Coverage:** All generated files included in packaging guidance
- **Clean Categorization:** Proper separation of PRESERVE vs INJECT vs ADAPT slots
- **Packaging Ready:** Manifest provides complete file operation guidance

---
## JBeamParser Compatibility Update — Planned (Post-Exhaust Solver)

**Origin:** During exhaust solver Phase 0 (2026-02-06), parsing real vehicle data across 6 vehicles revealed 3 parser failures and 1 format gap. Hotfixes were applied inline to unblock exploration; this TODO tracks the broader hardening pass and regression testing needed before these changes are considered production-stable.

### Changes Already Applied (hotfixed in `engineswap.py`)

1. **Block comment negative lookbehind (Pattern fix)**
   - **Problem:** Decorative line comments like `//**========**` matched the block comment regex (`/\*...\*/`) because `/*` appeared inside `//**`. The regex then ate all content until the next `*/`, corrupting the parse (barstow engine files).
   - **Fix:** `(?<!/)/\*[\s\S]*?\*/` — negative lookbehind prevents `/` + `/*` from triggering block comment mode.
   - **Affected vehicles:** barstow (all 4 engine files)

2. **Leading zeros in arrays (Pattern 17 expansion)**
   - **Problem:** Pattern 17 only handled `:0N` (key-value context). Array values like `[1000,06]` and `[1000,09]` also have leading zeros that break `json.loads()`.
   - **Fix:** Extended to handle `,0N` and `[0N` contexts: `re.sub(r'([,\[])0+([1-9])', r'\1\2', content)`.
   - **Affected vehicles:** barstow, covet

3. **Positive sign stripping (Pattern 18 — new)**
   - **Problem:** Some jbeam files use explicit `+` signs on positive numbers (e.g., `+9`, `+10`). Invalid JSON.
   - **Fix:** `re.sub(r'([,\[:\s])\+(\d)', r'\1\2', content)` — strips `+` before digits in numeric contexts.
   - **Affected vehicles:** covet (front engine files)

### New Format: `slots2` (Modern BeamNG Vehicles)

**Discovery:** Modern vehicles (vivace, fullsize) use a `"slots2"` key alongside or instead of `"slots"`. Different array structure:

| Format | Key | Entry Structure |
|--------|-----|-----------------|
| Legacy | `"slots"` | `[slotType, default, description]` |
| Modern | `"slots2"` | `[name, allowTypes[], denyTypes[], default, description, {props}]` |

**Current state:** `exhaust_solver.py` handles both formats via `_get_combined_slots()` / `_is_slot_header()` / `_extract_slot_fields()` helpers. These are **not yet** in the main `JBeamParser` class or available to other modules.

**Action needed:** Promote `slots2`-aware helpers into `JBeamParser` (or a shared utility) so `slot_graph.py`, `analyze_powertrains.py`, and `engineswap.py` can use them uniformly. Currently each module that inspects slots only looks at the `"slots"` key.

### TODO Items

- [ ] **Regression test parser changes against full corpus** — Run the 3 hotfixed patterns against all 5,207+ base game jbeam files to verify no regressions. Previous coverage was 98.6%; confirm it holds or improves.
- [ ] **Promote `slots2` helpers to shared location** — Move `_get_combined_slots()`, `_is_slot_header()`, `_extract_slot_fields()` from `exhaust_solver.py` into `JBeamParser` or a new `jbeam_utils.py` so all slot-inspecting code handles both formats.
- [ ] **Update `slot_graph.py` for `slots2`** — `SlotGraphBuilder` currently reads `part_data.get('slots', [])`. Must also scan `slots2` using the shared helpers.
- [ ] **Update `analyze_powertrains.py` for `slots2`** — Powertrain chain discovery uses slot inspection that may miss `slots2`-only parts.
- [ ] **Update `engineswap.py` slot adaptation for `slots2`** — Slot injection/transformation methods assume legacy format; must handle both when modifying target vehicle parts.
- [ ] **Document Pattern 18 in `jBeam_syntax.md`** — Add positive sign stripping and expanded leading zero patterns to syntax reference.
- [ ] **Investigate `pickup_frame_crewlongbed_heavy.jbeam`** — Consistently fails parsing (char 34 error). Determine if this is a base game authoring issue or a parser gap.

**Priority:** Medium — hotfixes work, but the `slots2` gap is a latent risk for any module inspecting modern vehicle slots. Schedule after exhaust solver Phase 2/3.

**Dependencies:** None for regression testing. `slots2` promotion blocks on deciding where shared helpers live (inline in `JBeamParser` vs separate `jbeam_utils.py` — related to JSON5 Parser Rewrite Phase 1 extraction decision).

---
## Comment Preservation - Partially Implemented

**Current State:**
- Added `RawJBeamContent` dataclass to store both raw file content and parsed data
- Added `JBeamParser.parse_jbeam_with_raw()` method to load both
- Added `get_section_raw()` method to extract raw sections with comments

**Limitation:**
- Current implementation still strips comments during JSON parsing
- Full comment preservation would require surgical text modifications rather than JSON serialization
- Comments in modified sections (slotType, slots, nodes, beams) will be lost
- Comments in unmodified child parts could be preserved by copying raw text

**Future Enhancement:**
- For unmodified parts (Camso_Turbo, Camso_EngineManagement, etc.), copy raw text instead of serializing parsed data
- Only serialize sections that were actually modified
- This would preserve comments in ~90% of the file content

**Priority:** Low (formatting is now much improved, comments are nice-to-have)

---

## JSON5 Parser Rewrite - Planned (Multi-Phase)

**Goal:** Implement a comment-preserving parser without disrupting the stable core workflow. Make parser slot-type aware for easier implentation of targeted operations / metadata additions.

**Rationale:**
- Current `JBeamParser` strips comments during `json.loads()` - they cannot be recovered
- Comment preservation requires tracking positions and re-emitting during output
- This is architectural change with high regression risk if done inline
- Solution: Build standalone modules that can be validated independently

### Phase 1: Extract Existing Parser to Standalone Module

**Objective:** Move `JBeamParser` to `scripts/jbeam_parser.py` without changing functionality.

**Steps:**
1. Create `scripts/jbeam_parser.py` containing:
   - `JBeamParser` class (copy from engineswap.py)
   - All static methods: `strip_comments()`, `remove_trailing_commas()`, `add_missing_commas()`, `parse_jbeam()`
   - Extraction methods: `extract_slot_type()`, `extract_engine_characteristics()`
2. Update `engineswap.py`:
   - `from jbeam_parser import JBeamParser`
   - Remove inline class definition
3. Update `mount_solver.py`:
   - `from jbeam_parser import JBeamParser`
   - (Currently uses its own parsing - may need refactoring)
4. Validate: Run full test suite, compare output files byte-for-byte

**Deliverable:** Functionally identical behavior, parser now in dedicated module.

**Risk:** Low - pure refactor, no logic changes.

### Phase 2: Build JSON5 Parser as Separate Module

**Objective:** Create `scripts/jbeam_parser_json5.py` with comment-aware parsing.

**Architecture:**
```python
@dataclass
class ParsedJBeam:
    """Container for parsed data with comment metadata."""
    data: Dict[str, Any]           # Standard parsed dict
    comments: Dict[str, List[str]] # Path → associated comments
    raw_content: str               # Original file for fallback
    file_path: Path
    
class JBeamParserJson5:
    """JSON5-style parser that tracks comment positions."""
    
    @classmethod
    def parse(cls, file_path: Path) -> ParsedJBeam:
        """Parse .jbeam file, preserving comment locations."""
        ...
    
    @classmethod
    def serialize(cls, parsed: ParsedJBeam) -> str:
        """Re-emit .jbeam with comments restored."""
        ...
```

**Implementation Notes:**
- Use character-by-character parsing to track positions
- Associate comments with the JSON element that follows them
- Handle both `//` line comments and `/* */` block comments
- Store comment associations by JSON path (e.g., `"Camso_Turbo.turbocharger.pressurePSI"`)
- Trailing commas and relaxed syntax handled natively (JSON5 spec)

**Deliverable:** Standalone parser that can be tested in isolation.

**Risk:** Medium - new code, but isolated from core workflow.

### Phase 3: Validation via Dual-Parser Comparison

**Objective:** Prove functional equivalence before integration.

**Validation Script (`scripts/test_parser_comparison.py`):**
```python
def compare_parsers(file_path: Path) -> bool:
    """Compare output of both parsers for equivalence."""
    # Parse with both
    old_result = JBeamParser.parse_jbeam(file_path)
    new_result = JBeamParserJson5.parse(file_path)
    
    # Data must be identical
    assert old_result == new_result.data
    
    # Round-trip test: serialize and re-parse
    serialized = JBeamParserJson5.serialize(new_result)
    reparsed = JBeamParserJson5.parse_from_string(serialized)
    assert new_result.data == reparsed.data
    
    return True
```

**Test Corpus:**
- All files in `mods/unpacked/Cummins/`
- All files in `mods/unpacked/persh_crayenne_moracc/`
- Sample BeamNG original files from `SteamLibrary_content_vehicles/`
- Edge cases: deeply nested, unusual comments, empty sections

**Deliverable:** 100% test pass rate on corpus.

**Risk:** Low - validation only, no production changes.

### Phase 4: Integration with Fallback

**Objective:** Integrate JSON5 parser with graceful fallback.

**Implementation in `engineswap.py`:**
```python
# Try JSON5 parser first, fall back to legacy
try:
    from jbeam_parser_json5 import JBeamParserJson5
    USE_JSON5_PARSER = True
except ImportError:
    USE_JSON5_PARSER = False

def parse_jbeam_file(file_path: Path):
    if USE_JSON5_PARSER:
        try:
            return JBeamParserJson5.parse(file_path)
        except Exception as e:
            logger.warning(f"JSON5 parser failed, falling back: {e}")
    return JBeamParser.parse_jbeam(file_path)
```

**Configuration in `swap_parameters.json`:**
```json
{
    "parser": {
        "use_json5": true,
        "preserve_comments": true,
        "fallback_on_error": true
    }
}
```

**Deliverable:** New parser active with automatic fallback.

**Risk:** Low - fallback ensures no breakage.

### Phase 5: Comment Preservation in Output

**Objective:** Update `JBeamWriter` to re-emit preserved comments.

**Changes to `JBeamWriter`:**
- Accept `ParsedJBeam` or `Dict` (backwards compatible)
- When `ParsedJBeam` provided, emit associated comments
- Handle modified sections: comments may not apply after TMS translation
- Configuration flag: `preserve_comments: true/false`

**Edge Cases:**
- Comments on deleted sections: drop silently
- Comments on modified nodes: emit with warning annotation
- New sections (TMS-generated nodes): no comments expected

**Deliverable:** Generated files include original comments where applicable.

**Risk:** Medium - touches output formatting, needs careful testing.

---

### Summary Timeline

| Phase | Description | Dependencies | Effort | Risk |
|-------|-------------|--------------|--------|------|
| 1 | Extract to standalone | None | Low | Low |
| 2 | Build JSON5 parser | Phase 1 | Medium | Medium |
| 3 | Validation testing | Phases 1-2 | Low | Low |
| 4 | Integration + fallback | Phases 1-3 | Low | Low |
| 5 | Comment preservation | Phases 1-4 | Medium | Medium |

**Total estimated scope:** Medium-Large, but de-risked by phased approach.

**When to start:** After core transplant workflow is stable (structure slot chain fixed, TMS validated on multiple vehicles).

**Priority:** Low-Medium (nice-to-have, but properly architected for future implementation)

---

## TMS Mesh Handling - Not Yet Implemented

**Problem:**
- `swpparam_FixMeshOffset` parameter exists but `_compute_mesh_offset()` returns Vec3(0,0,0)
- Mesh flexbody positions/slots are not processed during output generation
- Current implementation only translates physics nodes, not visual meshes

**Impact:**
- `fix_mesh_offset=false`: Meshes don't follow translated nodes (visual misalignment)
- `fix_mesh_offset=true`: No correction applied despite parameter setting

**Recommended Solution:**
1. Implement `_compute_mesh_offset()` in mount_solver.py:
   - Extract original mesh position from donor jbeam flexbody `pos` property
   - Calculate original mesh→centroid offset
   - Return negated offset to center mesh on translated nodes

2. Add mesh handling to engineswap.py output generation:
   - Extract flexbody definitions from donor jbeam
   - Update flexbody `pos` or generate `$EngineOffsetX/Y/Z` variables
   - Apply translation or translation+correction based on `fix_mesh_offset` setting
   - Handle both `embedded` and `separate` output formats

**Priority:** Medium (TMS works for physics, mesh alignment is visual polish)

---

## Archive - Completed Features

### JBeamParser Improvements - COMPLETED (2026-02-03)

**Issue Resolved:** Parser was corrupting strings like `"ec8ba_engine0"` → `"ec8ba_engine0, "` due to naive regex patterns matching digits inside quoted strings.

**Root Causes Fixed:**
1. Comment stripping pattern failed on `"string" //comment` (space before //)
2. Pattern 7 didn't handle negative numbers (`"str" -0.5`)
3. Pattern 12 didn't handle strings with `$` characters
4. Leading zeros (`"spring":00`) caused parse failures

**Solution Implemented:**
- URL-safe placeholder protection for comment stripping
- Updated Pattern 7: `"[a-zA-Z0-9_]*")\s(-?[0-9\[])` handles negative numbers
- Updated Pattern 12: `"[a-zA-Z0-9_$.]*"` handles Lua variable references
- Added Pattern 17: `:0+([0-9])` → `:\1` fixes leading zeros

**Test Coverage:** 98.6% success on 5,207 JBeam files (base game + Camso mod)

**Remaining 1.4% Failures:** BeamNG authoring issues (control characters in strings, malformed syntax like `":,"`)

---

### Slot Graph Integration - COMPLETED (2026-02-04)

**Issue Resolved:** Fragmented slot handling across adaptation, parsing, and output phases led to inconsistent slot transformations and potential dependency breaks.

**Root Causes Addressed:**
1. Scattered slot operations in `EngineTransplantUtility` methods
2. No unified state management for slot dependencies
3. Inconsistent slot type and part name mappings
4. Lack of traceability for transformation operations

**Solution Implemented:**
- Created `slot_graph.py` module with graph-based slot dependency management
- Integrated slot graph into `engineswap.py` workflow (Phase 2 complete)
- Added disposition rules for configurable slot handling (preserve/adapt/prune/inject)
- Implemented protocol-based parser injection to avoid circular imports
- Added fallback behavior for graceful degradation when slot graph unavailable

**Key Features Delivered:**
- Unified slot state management with `SlotGraph` class
- Transformation pipeline: Build → Plan → Execute → Output
- Configurable disposition rules via `swap_parameters.json`
- Graph-aware JBeam writers and manifest generators
- Complete audit trail with transformation records

**Integration Points:**
- `EngineTransplantUtility.__init__()`: Added slot graph availability check
- `generate_adapted_jbeam()`: Builds slot graph after parsing
- `_create_adapted_part_name()`: Delegates to graph for consistency
- `generate_mod_manifest()`: Uses `SlotAwareManifestGenerator`

**Test Coverage:** All 8 slot_graph tests pass, integration verified with "Slot Graph: ENABLED" log message.

**Benefits:**
- Single source of truth for all slot operations
- Prevents dependency chain breaks
- Enables safe slot pruning and injection
- Provides full traceability of transformations
- Maintains backwards compatibility

---

### Slot-Aware Manifest Generation - COMPLETED (2026-02-04)

**Issue Resolved:** Manifest generation was pattern-based file scanning that included unnecessary files and lacked slot-aware asset discovery.

**Root Causes Addressed:**
1. Broad file scanning included potentially unused assets
2. No linkage between slots and their required meshes/textures
3. Pattern-based categorization didn't reflect actual slot dependencies
4. No pruning awareness for excluded slot assets

**Solution Implemented:**
- Completely rewrote `SlotAwareManifestGenerator` for v3.0 slot-centric manifest
- Added `SlotAssets` and `SlotManifestEntry` dataclasses for structured data
- Implemented asset extraction from jbeam flexbodies/props/sounds
- Added `_walk_slot_tree()` for graph traversal and dependency discovery
- Created `_build_copy_plan()` for categorized file organization
- Enhanced `engineswap.py` manifest integration with fallback support

**Key Features Delivered:**
- **Slot-Centric Organization:** Manifest organized around slots with asset traceability
- **Asset Discovery:** Parses jbeam files for mesh/texture/sound references per slot
- **Pruning Support:** Excluded files explicitly listed with pruning reasons
- **Copy Plan:** Clear distinction between original, generated, and excluded files
- **Dependency Visibility:** Slot tree structure exposed via children relationships
- **Backwards Compatibility:** Retained v2.0 format generation for legacy support

**Manifest Format v3.0:**
```json
{
  "version": "3.0",
  "required_slots": [{
    "slot_type": "pickup_engine",
    "disposition": "adapt",
    "source_file": "camso_engine_3813e.jbeam",
    "requires_generation": true,
    "assets": {"meshes": ["ec8ba_mesh.dae"]},
    "children": ["Camso_engine_structure"]
  }],
  "copy_plan": {
    "original_jbeam": [...],
    "generated_jbeam": [...],
    "excluded_files": [...]
  }
}
```

**Integration Points:**
- `EngineTransplantUtility.generate_mod_manifest()`: Primary path uses v3.0, fallback to v1.0
- New helper methods: `_discover_asset_files()`, `_generate_copy_instructions()`
- CLI output updated for v3.0 manifest statistics

**Verification:**
- Engine slotType adaptation: `Camso_engine_structure` → `pickup_engine`
- Engine mounts injection: `["pickup_enginemounts",...,{"coreSlot":true}]`
- Transmission adaptation: `Camso_Transmission` → `pickup_transmission`
- Manifest v3.0 format with complete slot tree and asset references

---

### Slot Graph Visualization and Asset Roles - COMPLETED (2026-02-04)

**Issue Resolved:** Need for visualization tools to debug slot graph transformations and asset role classification for proper export control.

**Root Causes Addressed:**
1. Lack of visibility into slot graph structure during development
2. No way to verify asset role assignments
3. Difficulty debugging transformation pipelines
4. No clear distinction between extraction-only vs exportable slots

**Solution Implemented:**
- Added `AssetRole` enum (SOURCE, TARGET, PRESERVE, INTERNAL) for export classification
- Added `asset_role` field to `SlotNode` dataclass
- Implemented `visualize()` method with comprehensive filtering options
- Added role-based filtering methods: `get_slots_by_role()`, `get_exportable_slots()`, `get_source_slots()`
- Enhanced `print_tree()` with role indicators
- Updated `SlotAwareManifestGenerator._walk_slot_tree()` to filter SOURCE/INTERNAL slots from export
- Added `_mark_asset_roles()` method in engineswap.py for automatic role assignment
- Implemented `visualize` CLI command with options for files, transforms, role filtering, and markdown output

**Key Features Delivered:**
- **Asset Role Classification:** Automatic marking based on filename patterns and slot types
- **Comprehensive Visualization:** Tree display with role indicators, file paths, and transformation history
- **CLI Integration:** `visualize` command with filtering options and markdown export
- **Export Control:** SOURCE slots (like engine structure) are extracted but not exported
- **Debugging Support:** Clear visibility into slot relationships and transformation state

**Visualization Output:**
```
pickup_engine (T) [adapted from Camso_Engine]
├── Camso_engine_structure (S) [extraction only]
├── pickup_transmission (T) [adapted from Camso_Transmission]
├── Camso_Intake_3813e (P) [preserved]
└── Camso_EngineManagement (P) [preserved]
```

**CLI Usage:**
```bash
python engineswap.py visualize engine.jbeam pickup --show-files --filter-role target --markdown
```

**Benefits:**
- **Debugging:** Clear visibility into slot graph structure and transformations
- **Verification:** Easy confirmation of asset role assignments
- **Export Control:** Prevents unnecessary files from being included in manifests
- **Development:** Faster iteration with visual feedback on graph state

---

### Manifest Packaging Enhancement - COMPLETED (2026-02-05)

**Issue Resolved:** Manifest was debug-only; needed actual output paths for production packaging utility.

**Root Causes Addressed:**
1. Manifest lacked computed output paths for file operations
2. Copy instructions showed source filenames instead of generated filenames
3. No validation that computed paths matched actual generated files

**Solutions Implemented:**
- Enhanced `SlotAwareManifestGenerator` with `output_base_path` parameter
- Added `_compute_output_path()` method using same logic as `engineswap.py`
- Extended `copy_plan.generated_jbeam` entries with `output_path` and `output_filename` fields
- Added `validate_generated_files()` method for path validation
- Updated copy instructions to display actual output filenames

**Benefits:**
- **Packaging-Ready:** Manifest now contains actual output paths for direct file operations
- **Validation:** Ensures computed paths match files on disk
- **Clear Instructions:** Copy instructions show final generated filenames
- **Consistency:** Same path computation logic used for generation and packaging

---

### Manifest Copy Plan Fixes - COMPLETED (2026-02-05)

**Issue Resolved:** Manifest copy instructions were inaccurate - showing unnecessary INJECT source files and missing additional generated files.

**Root Causes Addressed:**
1. INJECT disposition slots were incorrectly categorized as original files
2. Files generated outside slot tree weren't included in manifest
3. Copy instructions didn't provide complete packaging guidance

**Solutions Implemented:**
- Updated `_build_copy_plan()` logic to exclude INJECT slots from original files
- Added registration of generated files in engineswap.py workflow
- Enhanced manifest generator to include additional generated files
- Improved copy plan categorization by disposition type

**Benefits:**
- **Accurate Instructions:** Copy instructions only show necessary files
- **Complete Coverage:** All generated files included in packaging guidance
- **Clean Categorization:** Proper separation of PRESERVE vs INJECT vs ADAPT slots
- **Packaging Ready:** Manifest provides complete file operation guidance

---


### Proposed Drivetrain swap logic 

*Note that we will also refuse transverse > longitudinal as well as longitudinal > transverse swaps in upstream logic; simplifying the overall scope of adaptation.*



#### Camso AWD Sub-variants 

> legend: "**Camso Name**": `PowertrainType` with {`ParameterType`} *notes*

- **On-Demand Center Coupling**: `"splitShaft"` with `"splitType": "locked"`
    *may require `camso_dse_drivemodes_<>.jbeam` or generated `electronicSplitShaftLock` controller*

- **Viscous Center Differential**: `"differential"` with `"diffType": "viscous"`

- **Helical Center Differential**: `"differential"` with `"diffType": "lsd"`

- **Advanced Center Differential**: `"differential"` with `"diffType": "lsd"` *Requires `camso_advawd.lua` controller*


## Drivetrain swap logic


### Drivetrain swap Preperations and upstream enhancements
- see "DrivetrainSwapLogic_DevelopmentPhases.md"
- [ ] Dissimilar engine orientation refusal: implement refuse transverse > longitudinal as well as longitudinal > transverse swaps in engine_swap.py / mount_solver.py logic; simplifying the overall scope of adaptation.



## In-Game Debugging (2026-02-12)

Issues discovered during in-game testing of generated mods.

### Missing Axle Slots (AWD Swaps)

**Status:** Fixed (2026-02-12)

**Root Cause:** Architectural mismatch — Camso AWD donors route front/rear torque via child slots (`Camso_driveshaft_front/rear`), which Phase 5 correctly prunes. However, the target BeamNG TC defines the front output as a powertrain-level device entry (`["shaft", "transfercase_F", "transfercase", 2, {...}]`). After pruning the child slots, no powertrain entry existed for the front output shaft.

**Fix:** Three-part implementation in Phase 5:
1. **Phase 1 properties serialization:** `analyze_target_powertrain()` now includes full device `properties` dict in TC device entries, enabling verbatim injection of target device parameters.
2. **Unmatched target device detection:** `_derive_device_name_mapping()` now identifies target TC devices that have no structural or type-only match in the donor. Includes type-only fallback matching for cross-topology strategies (e.g., MAKE_AWD where chain positions differ) and a connectivity guard that only flags devices whose TYPE is entirely absent from the donor.
3. **Conditional device injection:** `_apply_tc_strategy_adaptations()` injects missing powertrain entries into the center diff part for AWD donors only (DIRECT_AWD, MAKE_AWD). A connectivity filter ensures only devices whose `inputName` references a device already defined in the part (post-rename) are injected — preventing insertion of unrelated chain elements (e.g., `rangebox`).

**Scope:** AWD donors for DIRECT_AWD and MAKE_AWD strategies. Does not apply to 4WD donors (which already have `frontDriveShaft` as a powertrain device) or RWD/FWD donors.

**Validation:** 15/15 Phase 5 tests pass, including dedicated tests for DIRECT_AWD injection, MAKE_AWD injection with over-injection prevention, and 4WD/FWD no-injection guards. Phase 3 (19/19) and Phase 4 (11/11) regression clean.

---

### Slot Name / Filename Mismatch Prevents Auto-Loading

**Status:** Open - potentially dictated by game logic - requires further investigation.

**Observed:** When the mod is loaded in-game, the adapted engine does not automatically pull in its core slot components (transmission, and transmission-cascaded transfer case) into the configuration tree. 
**Observed - in-game:** Manually removing the `_adapted` suffix from generated .jbeam files did not produce the expected automatic loading behavior. 

**Suspected Root Cause (potentially invalid):** Generated `.jbeam` files have `_adapted` in their filenames, but the slot names *within* the files remain unchanged from Camso defaults. We don't know yet if BeamNG's slot resolution expects the part name declared in the file to match what the parent slot references. It could be that the filename/partname disconnect prevents the auto-cascade, but we are largely unsure. 

**Expected Fix Complexity:** Likely trivial to correct, though whatever chosen approach needs care to avoid upstream issues depending on which naming side is adjusted (filenames vs internal slot names).

---

## Future Enhancements

- [X]> Exhaust system solver / generate exhaust adapter
    see exhaust_solver.md

- [X]> Drivetrain solver
	Working on limited examples, needs thorough in-game validation across various Camso > BeamNG swap combinations.

- [X]> Compatibility with original vehicle transmissions
	Our mod structure inserts our new Camso transmission in a perfectly compatable format that allows interchangability with BeamNG original transmissions (sans texture overlap - unavoidable) 

- [X]> during package operation, read the engine mesh file and grab filenames for child meshes to also move in the same folder engine mesh gets placed

- [X]> implement the swap_parameters `"transmissions_to_adapt": "single",` option that restricts Camso transmission adaptation to the "single" default transmission named in the Camso engine slot. (default=ON)
        *works to prune vestigial transmission parts found in Camso vehicle folders - otherwise Camso sequential transmissions etc get loaded, these are not normally user-intended components of the Automation export)*
        **Implemented:** `_identify_default_transmission()` parses the engine file to find the default transmission part name from the engine's child slot, then filters `trans_files` to only adapt that file. Falls back to "all" if default cannot be resolved.

- [X]> implement swap_parameters `"discard_aux_transfercase": true` option that prunes the vestigal Camso "rangebox-variant" FWD / RWD transfercase part. (default=true)           
    *`"<target>_Camso_TransferCase_<>WD_rangebox_<hash>"` transfercase parent slot commonly found as an auxiliary transfer case option within Camso FWD and RWD transfercase.jbeam files*
    **Implemented:** `_identify_default_transfercase()` resolves the transmission's declared default TC part (immune from pruning). Parts matching `_(FWD|RWD)_rangebox_` regex are pruned unless they are the primary. `_fix_transmission_tc_default()` post-fixes the adapted transmission file when the slot graph's stale default pointed to a discarded rangebox variant. Config: `"discard_aux_transfercase": true` in swap_parameters.json.

- [ ]> Interference resolution testing with real-world edge cases

- [ ]> Support for transverse engine orientations (FWD vehicles) and refusal for dissimilar engine orientations. see "DrivetrainSwapLogic_DevelopmentPhases.md"


## inter-slot modifications and tweaks / powertrain parameter fixes / realisim enhancements

- [?]> Automatic radiator scaling based on donor engine power output
    *(should not be needed - Camso engines Presumed to have appropriately scaled radiator properties)*

- [?]> Thermal balance validation
    *(see above)*


### swap_parameters powertrain property tweaks:

**Implementation:** `scripts/powertrain_tweaks.py` — standalone post-processing module with registry pattern, `TweakContext`/`TweakResult` audit trail, `PowertrainDomain` shared physics/navigation namespace. Integrated at 3 call sites in `engineswap.py` (engine, transmission, transfercase) immediately before `_write_jbeam_file()`. Config in `swap_parameters.json` → `"powertrain_tweaks"` section. 29 unit tests in `test_powertrain_tweaks.py`.

**Guard:** Transmission torque converter tweaks are auto-guarded — only apply to automatic transmissions (detected by presence of `torqueConverter` section in the adapted data). Manual transmissions (clutch-based) are skipped. The `torqueConverter` sometimes found in transfercase files is a drivability hack for rangebox variants and is NOT treated as an automatic transmission indicator.

- [X]> Engine_adapted "requiredEnergyType" transform *(Phase A — implemented)*
    Config: `"engine": {"requiredEnergyType": "diesel"}` — validates against {gasoline, diesel, compressedGas}

- [ ]> Engine_adapted "convert_to_turbodiesel" tweak - remodels engine vacuum / turbo boost to mimic diesel's lack of throttle / vacuum (LUT mods) *(Phase D — deferred)*
    *(in Camso engine: invoke "fix_turbo_transient" with + "convert_to_turbodiesel" option - pressurePSI table modifications) (force requiredEnergyType = diesel)

- [ ]> Engine_adapted "fix_turbo_transient" tweak (drivability realism enhancement) (float 0.0 - 1.0 ; 1 being laggiest) (LUT / property array mods) *(Phase C — deferred)*
    *(in Camso engine: apply calculated offsets/scalars to turbocharger inertia, pressureRatePSI, apply offset function (req math) to pressurePSI table)

- [X]> Transmission_adapted "tighter_tc_stall" tweak (drivability realism enhancement) (float 0.0 - 1.0 ; 1 being tightest) *(Phase B — implemented)*
    Config: `"transmission": {"tighter_tc_stall": 0.4}` — scales converterDiameter (×1.0+f×0.30) and converterStiffness (×1.0+f×1.50). Auto-trans guarded.

- [X]> Transmission_adapted "modern_tcc_lockup" tweak (drivability realism enhancement) (int gear # input for minlockup) (2 = 2nd gear etc) *(Phase B — implemented)*
    Config: `"transmission": {"modern_tcc_lockup": 3}` — sets torqueConverterLockupMinGear directly, adjusts LockupRPM (-50/gear_delta) and LockupRange (+100/gear_delta). Auto-trans guarded.

- [ ]? Transmission_adapted "modern_tcc_unlock" tweak (drivability realism enhancement) (float 0.0 - 1.0) force unlock converter when "under the curve" near WOT *(Phase E — deferred, may require lua controller)*
    *(needs more research - may require custom .lua torque converter controller to selectively unlock TCC when certian conditions exist (i.e. RPM <60% peak torque curve @ WOT))



## Script usage microfeatures

- [X] When we expand_engine_mounts, the console should print the expansion offsets. We recall this was a prior behavior, ensure this is the case


## Dev environment path considerations
Worth mentioning that this entire project directory is a working-copy clone of beamNG's installed file structures. When development of these scripts are finished, they will ideally be deployed and pointed at actual game files, so any use of paths that reference the parent folder OR the folder "SteamLibrary_content_vehicles" will break when deployed.



## VScode extensions

- Look in to JBeam LSP Parser : https://github.com/webdevred/jbeam_edit/releases/tag/v0.0.5 / https://marketplace.visualstudio.com/items?itemName=webdevred.jbeam-lsp