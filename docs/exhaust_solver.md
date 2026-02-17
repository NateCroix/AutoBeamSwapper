# Exhaust Solver — Architecture & Implementation Plan

## Mission

Bridge a target BeamNG vehicle's exhaust system to the transplanted Camso engine by generating an **exhaust adapter** (`<vehicle>_exhaust_adapter`) — a lightweight jbeam part containing structural nodes and `isExhaust` beams that connects the adapted engine block to the target's existing exhaust pipes.

---

## Terminology

| Term | Definition |
|---|---|
| **exhaust(s)** | Files matching `*_exhaust*.jbeam` — the exhaust pipe assembly |
| **exhaust system** | All related/linked components making up the full path from engine to tailpipe |
| **exhaust system component** | Any exhaust-related part (header, manifold, downpipe, exhaust pipe) |
| **downstream\_exhaust\_component** | The intermediate part or parts (header/manifold/downpipe) that bridge engine → exhaust |
| **exhaust adapter** | The generated part (`<vehicle>_exhaust_adapter`) we produce to replace the downstream\_exhaust\_component. Slot name and slotType must match. |
| **isExhaust node** | An engine\_block node with `{"isExhaust":"mainEngine"}` — the exhaust thermal/sound origin |
| **isExhaust beam** | A beam with `{"isExhaust":"mainEngine"}` — carries thermal/sound propagation |

---

## Observed Data Patterns

### Camso Donor Engines

| Metric | Typical (86%) | Outlier — dual-bank mid-engine |
|---|---|---|
| isExhaust node count | **1** | **2** |
| isExhaust node location | `engine_block` group member (e.g. `engine2`) | `engine_Gearbox` nodes (e.g. `engine_Gearbox8`, `engine_Gearbox9`) |
| Node side | Positive-X (right/passenger) | Both sides (±X) |

After TMS translation, the isExhaust node name maps via `CAMSO_TO_BEAMNG_NODE_MAP` (e.g. `engine2` → `e1l`). The `isExhaust` property is preserved inline on the adapted output node. We are careful to only perform exhaust_solver on adapted / post-tms processed Camso engines.

Currently, the `Camso_exhaust` part (exhaust pipe nodes `exhaust_0`..`exhaust_N`) is **not** included in adapted output — only the engine cube nodes with their isExhaust attribute. The adapted engine has no exhaust slot, no exhaust pipe, and no exhaust beams. This is desirable becasue the Camso exhaust is assumed to lack compatability with the swap target vehicle.

### BeamNG Target Vehicle Exhaust Architectures

Four distinct slot-chain patterns observed:

#### Pattern A — Engine → Header → Exhaust *(most common)*
**Vehicles:** pickup, moonhawk, barstow

Engine defines a header/manifold slot (e.g. `pickup_header_v8`) as `coreSlot`. The header part defines 1-2 nodes (`exm1r`, `exm1l`) and hosts the exhaust slot (`pickup_exhaust_v8`). The exhaust part connects to header nodes via isExhaust beams.

```
Engine slots: ["pickup_header_v8", "pickup_header_v8", "Exhaust Manifolds", {"coreSlot":true}]
Header slots: ["pickup_exhaust_v8", "pickup_exhaust_v8", "Exhaust"]
```

#### Pattern A′ — Engine → Header (sibling: Exhaust)
**Vehicles:** moonhawk, barstow

Engine directly defines *both* a header slot *and* an exhaust slot as siblings. The header has no child exhaust slot — the exhaust connects to header nodes via physical attachment beams only.

```
Engine slots: ["moonhawk_header_v8_small", ..., {"coreSlot":true}]
              ["moonhawk_exhaust_v8", ..., "Exhaust"]
```

#### Pattern B — Engine → Intake → Header/Downpipe → Exhaust
**Vehicle:** covet

Engine only defines an intake slot. The intake part (or turbo variant filling the same slot) hosts the header/downpipe slot, which then hosts the exhaust slot.

```
Engine slots: ["covet_intake", "covet_intake", "Intake & Exhaust", {"coreSlot":true}]
  Intake slots: ["covet_header", "covet_header", "Exhaust Manifold", {"coreSlot":true}]
    Header slots: ["covet_exhaust", "covet_exhaust", "Exhaust"]
  OR (turbo variant):
  Turbo slots: ["covet_turbo_downpipe", ..., {"coreSlot":true}]
    Downpipe slots: ["covet_exhaust", "covet_exhaust", "Exhaust"]
```

#### Pattern C — Body/Frame → Exhaust *(decoupled from engine chain)*
**Vehicles:** vivace, fullsize (partial)

Exhaust slot lives on the body or frame, completely independent of the engine slot chain. Engine defines isExhaust nodes and intermediate downpipe nodes, but the exhaust part connects physically via attachment beams referencing engine nodes — not via slot parentage.

```
Engine: defines e3l (isExhaust), turbo part defines exd1 (downpipe node)
Body/Frame: ["vivace_exhaust", "vivace_exhaust", "Exhaust"]
Exhaust connects: ["exd1", "ex1", {"isExhaust":"mainEngine"}]  // physical, not slot chain
```

### Target Engine isExhaust Counts

| Vehicle | Engine | isExhaust Count | Nodes |
|---|---|---|---|
| moonhawk | V8 small / I6 | 1 | `e4r` |
| covet | 1.5L SOHC | 1 | `e3r` |
| vivace | 2.0L I4 | 1 | `e3l` |
| barstow | V8 small | 1 | `e4r` |
| pickup | 4.5L V8 | 2 | `e2r`, `e2l` |
| fullsize | 4.5L V8 | 2 | `e1l`, `e2r` |

### Header/Manifold Node Patterns

All observed headers use `exm1r` and/or `exm1l` naming. These nodes carry `afterFireAudioCoef`, `exhaustAudioMufflingCoef`, and `exhaustAudioGainChange` properties — critical for sound propagation. Vivace uses `exd1` (downpipe). All are typically in a vehicle-specific group (e.g. `pickup_header`, `covet_header`).

---

## Solver Strategy Selection

### Step 1 — Count donor isExhaust nodes

Count nodes with `{"isExhaust":"mainEngine"}` in the **adapted** donor engine jbeam. This is `donor_isExhaust_count` (always 1 or 2 for Camso engines).

### Step 2 — Enumerate target engine candidates

Discover all engine jbeam files for the target vehicle:
- Vehicle-specific folder: `<base>/<vehicle>/vehicles/<vehicle>/*engine*.jbeam`
- Common folder: `<base>/common/vehicles/common/<vehicle>/*engine*.jbeam`
- Cross-folder references via `get_search_folders()` from `analyze_powertrains.py`

Filter out non-engine files (`*enginemounts*`, `*management*`).

### Step 3 — Count target isExhaust nodes per engine

For each target engine file, parse all parts and iterate `nodes` sections tracking the active `group`/`nodeGroup` modifier state. Count nodes with `{"isExhaust":"mainEngine"}` that belong to the engine\_block nodegroup (`*_engine` or `engine_block`).

**Filter:** Eliminate engines with >2 isExhaust nodes in the engine\_block group (rare race engines with complex multi-outlet manifold paths).

### Step 4 — Classify candidates

| Condition | List | Strategy |
|---|---|---|
| target isExhaust count == `donor_isExhaust_count` | `matching_candidates` | `matching_exhaust_solver` |
| target isExhaust count ≠ `donor_isExhaust_count` (but ≤2) | `mismatch_candidates` | `mismatch_exhaust_solver` |

**Priority:** If `matching_candidates` is non-empty → use `matching_exhaust_solver`.
Otherwise if `mismatch_candidates` is non-empty → use `mismatch_exhaust_solver`.
Otherwise → `no_exhaust_solver`.

---

## find\_some\_exhaust\_slot (shared logic)

For each candidate engine (from whichever list), find the **downstream\_exhaust\_component** — the part whose slot chain ultimately reaches an `exhaust` slot:

1. **Direct engine slots:** Scan the engine part's `slots` array for child slots matching exhaust-related patterns:
   - `*header*`, `*exhmanifold*`, `*downpipe*`, `*exhaust*`

2. **Intermediate-hosted exhaust slots (Pattern B):** If no direct exhaust component found on the engine, scan child slots of the engine's intake/turbo parts (recursively, within the same engine jbeam file). Prefer `downpipe` over `header` when both exist in the same chain — the downpipe represents the most downstream bridging point.

3. **For each candidate downstream\_exhaust\_component found:**
   - Parse its part data
   - Check if it defines a child `*exhaust*` slot
   - If yes → **this is our template**. Record:
     - The downstream\_exhaust\_component part name
     - Its nodes (positions, properties)
     - The exhaust slotType it loads (e.g. `pickup_exhaust_v8`)
   - If no → broaden search to other parts in the same engine jbeam file that may load an exhaust slot
   - If still no → eliminate this engine candidate and try the next

4. **Pattern C fallback (body/frame-hosted exhaust):** If no exhaust slot found in *any* engine's slot chain, scan the target vehicle's body/frame jbeam files for exhaust slots. If found, use the engine's existing exhaust bridge node (`exd1` or similar) as the downstream reference, and the body-hosted exhaust slotType as the target slot.

5. If no exhaust slot found across all candidates and body/frame → fall through to `no_exhaust_solver`.

---

## generate\_adapted\_exhaust\_component

### Common setup (both strategies)

1. Create a new jbeam part: `"<vehicle>_exhaust_adapter"`
   - `slotType`: `"<vehicle>_exhaust_adapter"` — **must match part name** (critical for BeamNG part loading)
   - `information`: `{"authors":"BeamNGCommunity","name":"Exhaust Adapter","value":200}` — **required** (parts without an information section cause game issues)
   - Hosts child exhaust slot: `["<vehicle>_exhaust_<>", "<vehicle>_exhaust_<>", "Exhaust"]` — matching the value found in the candidate downstream\_exhaust\_component
   - No flexbodies

2. Copy nodes from the candidate downstream\_exhaust\_component:
   - Retain original node names (`exm1r`, `exm1l`, etc.) and positions (x, y, z)
   - Override: `nodeWeight: 4.5`, `collision: false`, `group: "exhaust_adapter"`
   - **nodeWeight must be ≥3** — values below 3 (e.g., 0.5) cause physics instability and crashes in-game
   - Retain audio properties (`afterFireAudioCoef`, `exhaustAudioMufflingCoef`, `exhaustAudioGainChange`) if present

3. Generate **structural beams** from each exhaust adapter node to engine\_block nodes *without* `isExhaust`:
   - Borrow beam spring/damp/deform/strength from our BeamNG candidate downstream\_exhaust\_component when available. Use hardcoded defaults if not available.
   - **beamSpring is clamped** to `_MAX_BEAM_SPRING` (1616333) — target parts may carry values high enough to cause instant beam breakage on load
   - Purpose: physically anchor the exhaust bridge to the engine without interfering with the thermal/sound path
   - **Beam layout constraint:** The trailing beam property reset row (`{"beamPrecompression":1,...}`) must appear AFTER all beams (structural + isExhaust), not between them. Placing resets between beam groups causes in-game issues.

### matching\_exhaust\_solver — isExhaust beam wiring

Donor and target have the **same** isExhaust count. Generate direct connections:

- **Single isExhaust (1↔1):** One beam from the engine's isExhaust node to the adapted\_exhaust\_component node, with `{"isExhaust":"mainEngine"}`.

- **Dual isExhaust (2↔2):** Calculate Euclidean distance between each engine isExhaust node and each adapted\_exhaust\_component node. The two shortest-distance pairings become the isExhaust beams. Each connection made consumes those nodes, disallowing multiple connections to any single `isExhaust` node. Each beam gets `{"isExhaust":"mainEngine"}`.
  - *Beam order in the array determines exhaust flow direction.*

Result: straight direct connections — either one pipe or two independent pipes.

### mismatch\_exhaust\_solver — isExhaust beam wiring (Y-pipe)

Donor and target have **different** isExhaust counts. Generate a collector/splitter:

- **All** engine isExhaust nodes connect to **all** adapted\_exhaust\_component nodes, each beam with `{"isExhaust":"mainEngine"}`.
  - Camso 1 → target 2: one engine node → two header nodes (reverse Y-pipe / splitter)
  - Camso 2 → target 1: two engine nodes → one header node (Y-pipe / collector)
  - *Beam order determines flow direction.*

Result: Y-pipe geometry that adapts any one-to-many or many-to-one isExhaust count difference.

### Slot injection into engine\_adapted

After generating the adapted\_exhaust\_component as a complete jbeam part dict:

1. Add a new slot entry to the adapted engine's `slots` array:
   ```
   ["<vehicle>_exhaust_adapter", "<vehicle>_exhaust_adapter", "Exhaust Adapter", {"coreSlot": true}]
   ```
   The slot name and default value must both be `<vehicle>_exhaust_adapter` — matching the part's `slotType`.
2. The exhaust adapter is either:
   - Written as a separate part within the adapted engine jbeam file, OR
   - Written as a standalone jbeam file alongside the adapted engine

3. Register the new part with the slot graph (if active).

### no\_exhaust\_solver

No target exhaust found. Log a warning. Leave placeholder for future development (potential exhaust pipe generation from scratch or manual exhaust specification via config).

---

## Module Architecture Decision

**Decision: Standalone `exhaust_solver.py` module** called from `engineswap.py`.

### Rationale (vs. integrating into mount\_solver.py)

| Factor | Standalone `exhaust_solver.py` | Inside `mount_solver.py` |
|---|---|---|
| **Separation of concerns** | Exhaust logic has zero overlap with mount alignment | Pollutes mount module with unrelated exhaust concepts |
| **Scope containment** | Testable in isolation | Changes to exhaust risk regressions in mount solving |
| **Data flow** | Receives adapted engine data + parses target files independently | Direct access to TMS internals — tighter coupling |
| **Jbeam parsing** | Needs its own node/beam extraction (group-aware, isExhaust-aware) | `mount_solver` extractors filter on `engine*` prefix — not reusable as-is |
| **Reusable from mount\_solver** | `Vec3` for distance calculations, `BeamProperties` for beam property formatting | N/A |
| **Integration pattern** | Mirrors TMS: called → returns result → engineswap injects into jbeam | Would need internal hook points |

### Integration contract with engineswap.py

**Inputs the solver needs:**
- Adapted engine jbeam data (post-TMS: nodes with translated positions, isExhaust preserved inline)
- Target vehicle info (name, base path for file discovery)
- Donor isExhaust count (from adapted engine parsing)

**Output the solver returns:**
- `ExhaustSolverResult` dataclass:
  - `strategy: str` — which solver ran (`matching`, `mismatch`, `no_exhaust`)
  - `adapted_part: Optional[Dict[str, Any]]` — the complete jbeam part dict for the adapted\_exhaust\_component
  - `exhaust_slot_entry: Optional[List]` — the slot array entry to inject into the engine's slots
  - `target_exhaust_slot_type: Optional[str]` — the downstream exhaust slot that will load the target's exhaust pipes
  - `candidate_engine: Optional[str]` — which target engine was used as template
  - `candidate_profile: Optional[EngineExhaustProfile]` — full profile of chosen engine
  - `donor_isExhaust_count: int`
  - `target_isExhaust_count: int`
  - `pattern: str` — exhaust architecture pattern (A, A', B, C, no_exhaust)
  - `warnings: List[str]`

**Call site in engineswap.py:** After TMS geometry injection (~L2413), before slot transformation. The solver result's `adapted_part` gets added to the output jbeam data, and `exhaust_slot_entry` gets inserted into the engine's slots.

### Reusable components from existing modules

| Component | Source | Usage in exhaust\_solver |
|---|---|---|
| `Vec3` | `mount_solver.py` | Euclidean distance for dual-isExhaust pairing |
| `BeamProperties.to_property_dict()` | `mount_solver.py` | Format beam spring/damp/deform for generated beams |
| `get_search_folders()` | `analyze_powertrains.py` | Discover target vehicle jbeam file locations |
| `JBeamParser.parse_jbeam()` | `engineswap.py` (via import) | Parse target engine/exhaust files |
| `CAMSO_TO_BEAMNG_NODE_MAP` | `mount_solver.py` / `engineswap.py` | Know which BeamNG node names carry isExhaust |
| `SlotGraphBuilder` | `slot_graph.py` | Optionally: trace engine → exhaust slot chains for complex architectures |

---

## Implementation Phases

### Phase 0 — Exploration & Data Validation ✅ COMPLETE
**Goal:** Validate architecture assumptions against real data. Build a standalone diagnostic script.
**Status:** ALL PASS — 6/6 vehicles, 4/4 patterns confirmed. See "Phase 0 — Validation Results" below.
**Artifacts:** `scripts/test_exhaust_discovery.py` (~992 lines), 3 JBeamParser fixes in `engineswap.py`.

### Phase 1 — Core Exhaust Solver Module ✅ COMPLETE
**Goal:** Build `exhaust_solver.py` with extraction and strategy selection logic.
**Status:** ALL PASS — 56/56 tests. Extraction, classification, and strategy selection fully implemented.
**Artifacts:** `scripts/exhaust_solver.py` (~1069 lines), `scripts/test_exhaust_solver.py` (56 tests).

- ✅ `ExhaustSolverResult` dataclass (integration contract with `candidate_profile`, `pattern`)
- ✅ `count_donor_isExhaust_nodes()` — parse adapted engine, return count + node details
- ✅ `find_engine_files()` / `find_exhaust_files()` / `find_body_frame_files()` — dual-path discovery (vehicle + common)
- ✅ Group-aware node parsing with isExhaust detection (`extract_isExhaust_nodes()`)
- ✅ `classify_candidates()` → matching/mismatch/empty lists
- ✅ `trace_exhaust_chain()` — cross-file merged data, dual slots/slots2, Pattern C body/frame fallback
- ✅ `classify_pattern()` — A, A', B, C, no_exhaust
- ✅ `select_strategy()` — full pipeline: profile → classify → select → ExhaustSolverResult
- ✅ 56 unit + integration tests across 8 test classes

### Phase 2 — Exhaust Component Generation ✅ COMPLETE
**Goal:** `generate_adapted_exhaust_component()` — produce jbeam part data.

**Artifacts:** `scripts/exhaust_solver.py` (Phase 2 functions ~L990–1430), `scripts/test_exhaust_solver.py` (40 Phase 2 tests)

**Deliverables:**
- [x] `_extract_part_nodes_full()` — node extraction with inline property preservation (audio props)
- [x] `_extract_beam_properties_from_part()` — beam modifier extraction with `_DEFAULT_BEAM_PROPS` fallback
- [x] `generate_adapted_nodes()` — copies downstream nodes with overrides (`nodeWeight=4.5`, `collision=False`, `group="exhaust_adapter"`)
- [x] `generate_structural_beams()` — each adapted node → every non-isExhaust engine cube node, with borrowed beam properties
- [x] `generate_matching_isExhaust_beams()` — 1↔1 direct connection; 2↔2 minimum-total-distance pairing with node consumption
- [x] `generate_mismatch_isExhaust_beams()` — all↔all Y-pipe (every donor to every downstream)
- [x] `generate_slot_entry()` — `["<vehicle>_exhaust_adapter", "<vehicle>_exhaust_adapter", "Exhaust Adapter", {"coreSlot": True}]`
- [x] `generate_adapted_exhaust_component()` — full orchestrator: extracts nodes+beams from candidate, generates all components, builds complete part dict with child exhaust slot and `information` section
- [x] `select_strategy()` updated: calls `generate_adapted_exhaust_component()` when `donor_isExhaust_nodes` provided (backward compatible)
- [x] 40 Phase 2 tests: unit + integration covering all generation paths, 5 real vehicles (pickup, moonhawk, barstow, covet, fullsize)
- [x] 96/96 total tests pass (56 Phase 1 + 40 Phase 2)

**Known Limitations:**
- Pattern A' with sibling-only chains (no header with nodes) produces `adapted_part=None` — correctly warns rather than generating a broken component. Covet mid-engine (1.5\_R) is the only observed case.
- `_select_best_candidate()` for mismatch uses pattern priority + alphabetical ordering, not minimum delta from donor count. Acceptable for Phase 2; revisit if real-world mismatch selection needs refinement.

**In-Game Debugging Fixes (Post-Phase 3):**
- **nodeWeight ≥ 3 required:** Initial value of 0.5 caused physics instability and game crashes. Changed to 4.5.
- **collision: False:** Adapter nodes should not collide.
- **`information` section required:** Parts without an `information` dict cause game recognition issues.
- **Slot name/type must match:** Previously slotType was generic `adapted_exhaust_component` while part name was `<vehicle>_adapted_exhaust_component`. Now both are `<vehicle>_exhaust_adapter`.
- **Trailing beam reset position:** The trailing beam property reset row must appear AFTER all beams (structural + isExhaust), not between the two beam groups.
- **beamSpring cap (`_MAX_BEAM_SPRING = 1616333`):** Target exhaust parts sometimes carry very high beamSpring values (e.g., 11163370 from pickup I6 header). These cause instant beam breakage on load. The solver now clamps beamSpring to 1616333 while still borrowing the value from the target when it's within range. Applied in `_extract_beam_properties_from_part()` and as a `min()` guard in `generate_structural_beams()`.

### Phase 3 — Integration with engineswap.py ✅ COMPLETE
**Goal:** Wire the solver into the main adaptation pipeline.
**Status:** ALL PASS — 12/12 integration tests. Full pipeline wired and validated.
**Artifacts:** Integration code in `scripts/engineswap.py`, `scripts/test_exhaust_integration.py` (12 tests).

- ✅ Import + graceful fallback (`EXHAUST_SOLVER_AVAILABLE` flag) with lazy parser resolution to avoid circular import
- ✅ Call solver from `generate_adapted_jbeam()` after TMS geometry injection
- ✅ `_extract_isExhaust_from_adapted()` helper extracts donor isExhaust nodes from in-memory adapted engine data
- ✅ Inject returned `adapted_part` into the output jbeam data
- ✅ Inject returned `exhaust_slot_entry` into engine's slots array (after slot graph transformation)
- ✅ Slot graph registration — adapted exhaust part included in same output file, registered via existing path
- ✅ Integration tests with real Camso → BeamNG swap pairs (pickup, moonhawk, barstow, vivace, multi-donor)
- ✅ `_last_exhaust_result` stored on utility for downstream manifest/reporting use
- 🔄 In-game validation: partial verification, further testing required
- ✅ Post-integration debugging fixes applied (nodeWeight, information section, naming, beam reset position)

**Validated swap pairs (12 tests):**
- 3813e → pickup (2-node matching, Pattern A, component generated)
- 3813e → moonhawk (1-node, Pattern A', solver runs)
- 3813e → barstow (1-node, Pattern A', solver runs)
- 66a66/camsonav6 → pickup (gearbox-isExhaust promotion + matching)
- 3813e → vivace (Pattern C, handled gracefully)
- 4 unit tests for `_extract_isExhaust_from_adapted()` helper

**Circular import fix:** exhaust_solver.py imports JBeamParser from engineswap.py.
When engineswap imports exhaust_solver first, a circular dependency occurs. Resolved
with lazy `_get_parser()` binding — parser resolved on first function call, not at
import time.

**Known limitation:** No orientation check (transverse vs longitudinal) exists yet.
Swaps between transverse Camso engines and longitudinal targets (or vice versa) are
not refused. This is deferred to a dedicated orientation refusal feature.

### Phase 4 — Edge Cases & Hardening
**Goal:** Handle all observed patterns robustly.

- Pattern C handling (body/frame-hosted exhausts — vivace, fullsize)
- Pattern B handling (intake-nested headers/downpipes — covet)
- Engines with no exhaust system at all (electric, stripped race configs)
- Config integration (`swap_parameters.json` — enable/disable, candidate engine selection preferences)
- Comprehensive regression tests across all vehicle architectures

---

## Open Questions — RESOLVED

_All 4 original open questions were resolved during Phase 0 exploration. See the "Open Questions — Resolution" table in the Phase 0 Validation Results section below for answers._

---

## Phase 0 — Validation Results

**Status: COMPLETE — ALL PASS (6/6 vehicles, 4/4 patterns)**

### Validated Vehicle Matrix

| Vehicle | isExhaust Count | Pattern | Exhaust SlotType Found | Notes |
|---|---|---|---|---|
| pickup | 2 (e2r, e2l) | **A** | `pickup_exhaust_v8` | Cross-file: header in v8\_4.5 file, referenced from v8\_5.5/6.9. I6 also Pattern A. Diesel is A'. |
| moonhawk | 1 (e4r) | **A'** | `moonhawk_exhaust_v8` / `moonhawk_exhaust_i6` | Header exists but has no exhaust child slot; exhaust is sibling on engine. |
| covet | 1 (e3r) | **B** | `covet_exhaust` | Front engines (SOHC/DOHC/2.0): intake → header → exhaust. Mid-engine R variant is A'. |
| fullsize | 2 (e1l, e2r) | **C** | `fullsize_exhaust` (on frame) | Engine → header (leaf, no exhaust child). Exhaust on frame as sibling of engine. |
| vivace | 1 (e3l) | **C** | `vivace_exhaust` (on body) | Engine has NO header/manifold child slots. Exhaust on body. Uses `slots2` format. |
| barstow | 1 (e4r) | **A'** | `barstow_exhaust_v8` / `barstow_exhaust_i6` | Required parser fixes (decorated line comments, leading zeros). |

### Critical Findings

**1. Cross-file resolution is mandatory.** Engine parts reference header/manifold parts defined in other jbeam files within the same vehicle (e.g., pickup_header_v8 is defined in engine\_v8\_4.5.jbeam but referenced from engine\_v8\_5.5.jbeam). The solver must build a merged parsed-data dict from all engine + exhaust files before tracing chains.

**2. `slots2` format must be handled.** Modern vehicles (vivace, fullsize) use `"slots2"` key (not `"slots"`). The format is `[name, allowTypes[], denyTypes[], default, description, {props}]` vs legacy `[slotType, default, description]`. Both formats must be scanned.

**3. Pattern C has two sub-variants:**
- **Fullsize:** Engine → header (exm1r/exm1l, leaf node with NO exhaust child). Exhaust is on frame as sibling. The header exists but doesn't chain to exhaust.
- **Vivace:** Engine has NO header/manifold at all. Exhaust is purely on the body.

**4. Pattern A' headers are exhaust-chain leaf nodes.** In moonhawk/barstow, headers have bridge nodes (exm1r, exm1l) but no exhaust child slot — the exhaust is loaded as a direct sibling slot on the engine.

**5. Covet demonstrates both A' and B patterns.** Front engines use Pattern B (intake-nested). Mid-engine R variant uses A' (sibling exhaust slot).

### Open Questions — Resolution

| # | Question | Resolution |
|---|---|---|
| 1 | Pattern C: adapted\_exhaust\_component needed? | **For fullsize (sub-variant with header):** Yes — generate bridge connecting isExhaust nodes to exm1r/exm1l. Stock exhaust connects physically to these nodes. **For vivace (no header):** Potentially not needed — if adapted engine preserves isExhaust node position, stock exhaust may beam-connect directly. Phase 3 in-game validation needed. |
| 2 | Multiple target engines: selection preference? | Prefer engines matching donor isExhaust count (matching strategy). All engines within a vehicle share the same exhaust pattern, so any with count match works. |
| 3 | Exhaust audio properties? | Copy from target's downstream\_exhaust\_component header nodes. All headers consistently use `afterFireAudioCoef`, `exhaustAudioMufflingCoef`, `exhaustAudioGainChange`. |
| 4 | Pattern A' handling? | Detect by checking if engine has sibling exhaust slot. If so, adapted\_exhaust\_component should NOT host the exhaust slot — only provide bridge nodes/beams. The engine's existing exhaust slot loads the exhaust directly. Slot entry injection should be to the engine's slots as a `coreSlot` bridge only. |

### Parser Improvements Made During Phase 0

Three `JBeamParser` enhancements committed to `engineswap.py`:
1. **Negative lookbehind for block comments:** `//**decorative comments**` no longer matched as block comment starts. Pattern: `(?<!/)/\*[\s\S]*?\*/`.
2. **Leading zero fix in arrays:** `[1000,06]` → `[1000,6]`. Extended Pattern 17 to handle `,0N` and `[0N` contexts.
3. **Positive sign stripping:** `+9` → `9`. New Pattern 18 strips explicit `+` from numbers.

---

## Agent Handoff — Context & Continuation Guide

*Last updated: 2026-02-16*

This section captures operational context, in-game debugging learnings, and known gaps to enable a different agent to continue work effectively.

### Current State Summary

The exhaust solver is **functionally complete through Phase 3** with in-game debugging fixes applied. It generates a working exhaust adapter part that loads in BeamNG without crashes. The primary pipeline path (Pattern A, matching strategy) is validated in-game for the pickup vehicle with Camso engine 34607.

**Test inventory:** 109 tests (97 in `test_exhaust_solver.py` + 12 in `test_exhaust_integration.py`). All pass.

**Module size:** `exhaust_solver.py` ~1615 lines. Self-contained with lazy import of `JBeamParser` from `engineswap.py` to avoid circular dependency.

### Architecture & Key Design Decisions

1. **Standalone module pattern:** `exhaust_solver.py` is called from `engineswap.py` after TMS geometry injection. It receives adapted engine data (post-translation) and target vehicle info, returns a result dict that `engineswap.py` injects into the output jbeam. This mirrors the TMS pattern — solver returns data, orchestrator injects.

2. **Candidate selection strategy:** The solver profiles ALL target vehicle engines, counts their isExhaust nodes, and classifies them as `matching` (same count as donor) or `mismatch` (different count). Matching candidates are preferred. Within each class, Pattern A > A' > B > C priority is applied, then alphabetical tie-breaking.

3. **Beam property borrowing with safety caps:** Structural beam properties (spring, damp, deform, strength) are borrowed from the target's downstream exhaust component (the header it replaces). This preserves the vehicle's original structural feel. However, `beamSpring` is clamped to `_MAX_BEAM_SPRING` (1616333) because target headers can carry values high enough to cause instant beam breakage on load. The `_DEFAULT_BEAM_PROPS` dict provides fallback values when no beam modifiers are found in the target component.

4. **Node naming convention:** Exhaust adapter nodes reuse the same names as the target's downstream component nodes (`exm1r`, `exm1l`, etc.). This allows the target's exhaust pipes (which reference these nodes by name in their isExhaust beams) to connect without modification.

5. **isExhaust beam wiring:** Two strategies exist:
   - **Matching (N↔N):** Direct connections. For dual-node (2↔2), minimum-total-distance pairing via `_euclidean_distance()` is used, with node consumption to prevent double-assignment.
   - **Mismatch (N↔M):** All-to-all Y-pipe connections. Every donor isExhaust node connects to every downstream node.

6. **Slot naming identity rule (in-game learned):** The slot entry name, slotType, and part key must all be the same string (`<vehicle>_exhaust_adapter`). BeamNG requires this for proper part loading.

### Techniques & Methodologies

**Cross-file merged data:** The solver builds a merged parsed-data dict from ALL engine + exhaust jbeam files for a target vehicle (`build_merged_vehicle_data()`). This is critical because engine parts frequently reference header/manifold parts defined in separate files. Chain tracing operates on this merged dict.

**Group-aware node extraction:** JBeam property modifier rows (dicts) affect all subsequent nodes. `extract_isExhaust_nodes()` tracks `group`/`nodeGroup` state as it iterates, so it correctly identifies which `isExhaust` nodes belong to the engine\_block group vs. other groups (intake, gearbox, etc.).

**Lazy parser import:** `exhaust_solver.py` needs `JBeamParser` from `engineswap.py`, but `engineswap.py` imports `exhaust_solver.py`. A `_get_parser()` function resolves the parser on first call, not at import time, breaking the circular dependency.

**isExhaust promotion (upstream dependency):** Some Camso engines place `isExhaust` on gearbox nodes (`engine_Gearbox8/9`), not engine cube nodes. `mount_solver.py` has `_promote_gearbox_isExhaust()` which transfers the property to the nearest eligible engine cube node before TMS processing. The exhaust solver depends on this being done correctly — it only looks for isExhaust on adapted (post-TMS) engine cube nodes.

### In-Game Validated Output Structure

The verified working exhaust adapter part structure (pickup, Camso 34607):

```jbeam
"pickup_exhaust_adapter": {
    "information": {"authors":"BeamNGCommunity","name":"Exhaust Adapter","value":200},
    "slotType": "pickup_exhaust_adapter",
    "slots": [
        ["type","default","description"],
        ["pickup_exhaust_i6","pickup_exhaust_i6","Exhaust"]
    ],
    "nodes": [
        ["id", "posX", "posY", "posZ"],
        {"selfCollision":false},
        {"collision":false},
        {"frictionCoef":0.5},
        {"nodeMaterial":"|NM_METAL"},
        {"nodeWeight":4.5},
        {"group":"exhaust_adapter"},
        ["exm1r", -0.3, -0.7, 0.43, {<audio props>}],
        {"group":"none"}
    ],
    "beams": [
        ["id1:", "id2:"],
        {"deformLimitExpansion":1.2},
        {"beamPrecompression":1,"beamType":"|NORMAL","beamLongBound":1.0,"beamShortBound":1.0},
        {"beamSpring":1616333,"beamDamp":130.43},
        {"beamDeform":90000,"beamStrength":"FLT_MAX"},
        ["exm1r", "e1r"],
        ... structural beams (adapter node → each non-isExhaust engine cube node) ...
        ["e1l", "exm1r", {"isExhaust":"mainEngine"}],
        {"beamPrecompression":1,"beamType":"|NORMAL","beamLongBound":1.0,"beamShortBound":1.0}
    ]
}
```

Key layout rules:
- `information` section at top (mandatory)
- `slotType` matches part key
- Node modifier rows BEFORE node data rows (one property per row)
- Group reset `{"group":"none"}` AFTER all nodes
- Beam property modifiers before structural beams
- isExhaust beams AFTER structural beams
- Trailing beam reset AFTER all beams (structural + isExhaust)

### Known Gaps & Untested Paths

1. **Pattern A' adapter generation:** When the target engine has a sibling exhaust slot (moonhawk, barstow), the header is a leaf node with no exhaust child. Currently `_get_best_exhaust_slot_info()` prefers chains with nodes, but if no chain with nodes is found, the A' path may return `adapted_part=None`. The solver warns but does not crash. **Untested in-game** for A' vehicles.

2. **Pattern B (covet front engines):** Intake-nested chain (engine → intake → header → exhaust). The solver traces through the intake/turbo slot to find the header. Pattern B classification and chain tracing are tested, but **no in-game validation** has been performed.

3. **Pattern C (vivace, fullsize):** Body/frame-hosted exhausts decoupled from engine chain. The solver correctly identifies these but the adapter generation path for Pattern C is **not validated in-game**. Vivace has no header at all; fullsize has a leaf header.

4. **Mismatch strategy (Y-pipe):** The all-to-all wiring for count-mismatched engines is implemented and unit-tested, but **not validated in-game**. Unknown whether BeamNG handles multiple isExhaust beams per pair correctly for sound/thermal propagation.

5. **Multi-bank engines (dual isExhaust):** Camso dual-bank engines (c9a0e, camsonav6) have 2 isExhaust nodes. When paired with a 2-node target (pickup V8), the matching strategy generates 2 isExhaust beams. This path is unit-tested and integration-tested, but **only the single-node pickup I6 path has been validated in-game** (Camso 34607 has 1 isExhaust after TMS).

6. **beamDamp / beamDeform caps:** Only beamSpring has an upper limit. It's possible that beamDamp or beamDeform from target headers could also be problematic, but no in-game issues have been observed yet.

7. **Exhaust sound verification:** The adapter carries audio properties (`afterFireAudioCoef`, `exhaustAudioMufflingCoef`, etc.) from the target header. Whether these produce correct sound propagation through the adapted chain has **not been explicitly verified** — only crash-free loading has been confirmed.

8. **Orientation mismatch refusal:** No check exists for transverse vs longitudinal engine orientation. A transverse Camso engine swapped into a longitudinal target (or vice versa) would produce geometrically incorrect exhaust routing. This is a broader project-level gap, not exhaust-solver-specific.

### Constants Reference

| Constant | Value | Purpose |
|---|---|---|
| `_MAX_BEAM_SPRING` | 1616333 | Upper limit for beamSpring in exhaust adapter beams |
| `_DEFAULT_BEAM_PROPS` | `{beamSpring: 5010000, beamDamp: 90, beamDeform: 90000, beamStrength: "FLT_MAX"}` | Fallback when target header has no beam modifiers |
| `_AUDIO_PROPS` | `{afterFireAudioCoef, afterFireVisualCoef, afterFireVolumeCoef, afterFireMufflingCoef, exhaustAudioMufflingCoef, exhaustAudioGainChange}` | Audio properties preserved from target header nodes |
| `EXHAUST_SLOT_PATTERNS` | `[*exhaust*, *header*, *exhmanifold*, *downpipe*]` | Glob patterns for identifying exhaust-related slots |

### File & Function Map

| File | Key Functions | Purpose |
|---|---|---|
| `scripts/exhaust_solver.py` | `select_strategy()`, `generate_adapted_exhaust_component()` | Core solver entry points |
| `scripts/exhaust_solver.py` | `build_merged_vehicle_data()`, `trace_exhaust_chain()` | Target vehicle analysis |
| `scripts/exhaust_solver.py` | `generate_adapted_nodes()`, `generate_structural_beams()` | Part structure generation |
| `scripts/exhaust_solver.py` | `generate_matching_isExhaust_beams()`, `generate_mismatch_isExhaust_beams()` | isExhaust wiring strategies |
| `scripts/exhaust_solver.py` | `_extract_beam_properties_from_part()` | Beam property borrowing with clamping |
| `scripts/engineswap.py` ~L2460-2530 | Integration call site | Calls solver, injects result into output jbeam |
| `scripts/engineswap.py` | `_extract_isExhaust_from_adapted()` | Extracts donor isExhaust nodes from in-memory adapted data |
| `scripts/test_exhaust_solver.py` | 97 tests across 14 test classes | Unit + integration tests for solver |
| `scripts/test_exhaust_integration.py` | 12 tests across 6 test classes | Pipeline integration tests |

---

## Phase 5 — Engine Ecosystem Bridge Node Search ✅ COMPLETE

*Supersedes original "Pattern A' Direct Exhaust Replication" plan — see rationale below.*

### Problem Statement

Pattern A' vehicles (moonhawk, barstow, etk800) have the exhaust slot as a **direct sibling** on the engine — not hosted by a header/manifold child. The existing adapter approach (Phases 1-3) handles A' when the engine has a downstream header component with bridge nodes (`exm1r`, `exm1l`). However, some A' vehicles have their manifold/bridge nodes only in **separately-loaded engine sub-parts** (intake, turbo), not in the engine or header parts themselves.

**etk800 example:** The `exm1r` node is defined in `etk_intake_i4_2.0_petrol_turbo`, a child slot of the engine. The exhaust part's primary isExhaust beam connects `[ex1r, exm1r, {isExhaust:"mainEngine"}]`. When a Camso engine replaces the etk engine, the Camso intake system does NOT define `exm1r`. The stock exhaust part's isExhaust beam references a node that doesn't exist, breaking the exhaust gas path chain.

### Discovery: Bridge Nodes Are Always Present

Cross-vehicle research revealed that `exm1r`/`exm1l` bridge nodes exist in **every** A' vehicle — they're just hosted by different parts depending on the vehicle architecture. Three distinct hosting patterns were identified:

| Hosting Pattern | Bridge node location | Vehicles |
|---|---|---|
| **Header-hosted** | engine -> header/manifold slot | moonhawk, barstow, pickup (petrol), fullsize, wendover, nine, bluebuck, burnside, bastion |
| **Intake-hosted** | engine -> intake/turbo slot | **ETK**, miramar, scintilla V10, sunburst2, van diesel, pickup diesel |
| **Engine-direct** | in engine part itself | autobello, racetruck, pigeon, nine I4 flathead |

The existing adapter approach (Phase 2) correctly extracts bridge nodes from header-hosted parts (Pattern A' Bridged). It failed for intake-hosted parts because the search was scoped only to exhaust/header slot chains.

### Solution: Ecosystem Bridge Node Search (Implemented)

Instead of the originally planned "exhaust part replication" approach, the fix expands WHERE bridge nodes are searched. The existing adapter generation logic is fully reusable — only the node discovery needed widening.

**New function: `_find_bridge_nodes_in_engine_ecosystem()`**

When `generate_adapted_exhaust_component()` finds no nodes in the standard downstream component (header/exhaust chain), it now falls back to searching ALL engine child parts for nodes matching the `exm*` bridge node pattern (`_BRIDGE_NODE_PATTERN = r'^exm\d+[rl]?$'`).

Search process:
1. Get all child slots of the engine part
2. Skip exhaust-related slots (already searched by standard path)
3. For each non-exhaust slot (intake, turbo, etc.), find parts filling that slot
4. Extract nodes from each part, filter to `exm*` matches
5. Return found bridge nodes + beam properties from the containing part

**Integration point** in `generate_adapted_exhaust_component()`:
```python
downstream_nodes = _extract_part_nodes_full(merged_data, ds_component_name)

if not downstream_nodes:
    # A' Direct fallback -- bridge nodes may be in intake/turbo sub-parts
    bridge_nodes, eco_beam_props, eco_part = (
        _find_bridge_nodes_in_engine_ecosystem(
            merged_data, candidate_profile.engine_name,
        )
    )
    if bridge_nodes:
        downstream_nodes = bridge_nodes
        ds_component_name = eco_part  # beam props extracted from this part
```

Once bridge nodes are found, the rest of the adapter generation (structural beams, isExhaust wiring, slot entry, node copying) proceeds identically to the standard path.

### Why This Supersedes Exhaust Part Replication

The original Phase 5 plan proposed replicating the entire stock exhaust part with remapped beams. This was based on the incorrect assumption that bridge nodes didn't exist for A' Direct vehicles. In reality:

1. **Bridge nodes always exist** — they're just in intake parts instead of header parts
2. **The adapter approach works** — once we find the bridge nodes, the same adapter pattern that works for pickup/moonhawk/barstow works for etk800
3. **Much simpler** — one new ~50-line function vs. 4 new functions + full part replication logic
4. **Lower risk** — no new part structure, no beam remapping, reuses proven adapter generation

### Validated Output (etk800 i4 2.0)

```
[EXH] Strategy: matching | Candidate: etk_engine_i4_2.0 | Pattern: A'
[EXH] Found bridge nodes ['exm1r'] in engine ecosystem part
      'etk_intake_i4_2.0_petrol_turbo' (slotType 'etk_intake_i4_2.0_petrol')
[EXH] Generated etk800_exhaust_adapter: 1 nodes, 7 structural beams,
      1 isExhaust beams, hosts slot 'etk_exhaust_i4_2.0_petrol'
```

Generated adapter structure:
```jbeam
"etk800_exhaust_adapter": {
    "information": {"authors":"BeamNGCommunity","name":"Exhaust Adapter","value":200},
    "slotType": "etk800_exhaust_adapter",
    "slots": [["type","default","description"],
              ["etk_exhaust_i4_2.0_petrol","etk_exhaust_i4_2.0_petrol","Exhaust"]],
    "nodes": [["id","posX","posY","posZ"],
              {"selfCollision":false},{"collision":false},
              {"frictionCoef":0.5},{"nodeMaterial":"|NM_METAL"},
              {"nodeWeight":4.5},{"group":"exhaust_adapter"},
              ["exm1r", -0.200000, -0.900000, 0.270000],
              {"group":"none"}],
    "beams": [["id1:","id2:"],
              {"deformLimitExpansion":1.2},
              {"beamPrecompression":1,"beamType":"|NORMAL","beamLongBound":1.0,"beamShortBound":1.0},
              {"beamSpring":1616333,"beamDamp":125},
              {"beamDeform":90000,"beamStrength":"FLT_MAX"},
              ["exm1r","e1r"],["exm1r","e2l"],["exm1r","e2r"],
              ["exm1r","e3l"],["exm1r","e3r"],["exm1r","e4l"],["exm1r","e4r"],
              ["e1l","exm1r",{"isExhaust":"mainEngine"}],
              {"beamPrecompression":1,"beamType":"|NORMAL","beamLongBound":1.0,"beamShortBound":1.0}]
}
```

### Bridge Node Hosting Taxonomy (Reference)

Full cross-vehicle research data for `exm1r`/`exm1l` node locations:

| Vehicle | Engine(s) | Nodes | Host Part | Host Slot Type | Category |
|---|---|---|---|---|---|
| **ETK** i4 2.0P | etk_engine_i4_2.0 | exm1r | etk_intake_i4_2.0_petrol_turbo | etk_intake_i4_2.0_petrol | **Intake** |
| **ETK** i4 2.0D | etk_engine_i4_2.0_diesel | exm1r | etk_intake_i4_2.0_diesel_turbo | etk_intake_i4_2.0_diesel | **Intake** |
| **ETK** i6 3.0P | etk_engine_i6_3.0 | exm1r | etk_intake_i6_3.0_petrol | etk_intake_i6_3.0_petrol | **Intake** |
| **ETK** i6 3.0D | etk_engine_i6_3.0_diesel | exm1r | etk_intake_i6_3.0_diesel_turbo | etk_intake_i6_3.0_diesel | **Intake** |
| **ETK** V8 4.4P | etk_engine_v8_4.4 | exm1r+exm1l | etk_intake_v8_4.4_petrol_ttSport | etk_intake_v8_4.4_petrol | **Intake** |
| **miramar** SOHC/DOHC | multiple | exm1r | intake variants | miramar_intake_* | **Intake** |
| **sunburst2** 1.6/2.0/2.5 | multiple | exm1r+exm1l | engine intake turbo parts | sunburst2_engine_*_intake | **Intake** |
| **scintilla** V10 | 5.0L V10 | exm1r+exm1l | scintilla_intake_5.0_stock | scintilla_intake_5.0 | **Intake** |
| **pickup** V8 diesel | 6.0D | exm1r | intake variants | pickup_intake_v8_diesel | **Intake** |
| **van** V8 diesel | 6.0D | exm1r | intake variants | van_intake_v8_diesel | **Intake** |
| moonhawk V8 | multiple | exm1r+exm1l | header parts | moonhawk_header_v8_* | Header |
| barstow V8/I6 | multiple | exm1r+exm1l | exhmanifold parts | barstow_header_* | Header |
| pickup V8/I6 petrol | 4.5/4.1 | exm1r+exm1l | header parts | pickup_header_* | Header |
| fullsize V8 | 4.5 | exm1r+exm1l | exhmanifold | fullsize_header | Header |
| vivace | all | none | N/A | N/A | None (Pattern C) |

### Test Results

- **188 passed**, 1 skipped, 5 errors (pre-existing graph fixtures), 12 subtests
- No regressions from baseline (184 -> 188 passed, gain from A' Direct now succeeding)
- etk800 generation produces complete exhaust adapter matching proven pickup adapter structure
