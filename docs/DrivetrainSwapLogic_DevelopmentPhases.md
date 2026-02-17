## Drivetrain Swap Logic Preperations - pre-integration

We discovered that some types of Camso AWD transfercase require an additional "camso_advawd" .lua file located in:
`<vehiclename>/lua/controller/drivingDynamics/actuators`
Our work-in-progress transfercase swap logic will require this file be present in the mod folder to properly adapt Camso "Advanced Center Differential" AWD transfercase subtype. This feature's enablement should follow the existing swap_parameters argument; extra_assets > powertrain_lua > enabled: true/false

Additionally, we will add two additional arguments in swap_parameters.

New swap_parameters option: "transmissions_to_adapt" with options: " single, all" (pertains to Camso donor vehicle transmission ) **[IMPLEMENTED]**
- `"single"` prevents additional Camso "found" transmissions (like sequential variants) from being adapted and packaged; i.e. we only adapt the transmission that is referenced by-default in the provided /unaltered Camso engine slot.
- `"all"` works how things are right now - all found Camso transmissions are adapted and packaged with the mod.
- **Implementation:** `_identify_default_transmission()` in `engineswap.py` parses the engine file directly to extract the default transmission part name from the engine's `Camso_Transmission` child slot, then matches it against discovered transmission files. File-level filtering in the generate handler; slot graph analysis is unaffected.

New swap_parameters option: "transfercase_to_adapt" with options: "`<specified_part_name>`, `auto`"
- "`<specified_part_name>`" This is a provision for drivetrain swap logic. See TODO: "Proposed Drivetrain swap logic"
	the "specify" method is implied when a slot name is given; for example: `"transfercase_to_adapt": pickup_transfer_case_AWD` is a *specified* input.
- "`auto`" This automatically chooses the lowest-cost BeamNG target transfercase as the "context aware structure injection/duplication with best-effort donor property retention" transfercase candidate.

Review of required preparations:

"camso_advawd" lua controller packaged (if found in donor vehicle)
swap_parameters options "transmissions_to_adapt" and "transfercase_to_adapt"
provisions for swap_parameters "transfercase_to_adapt" "`<specified>`" argument which names a transfercase slot, used for transfercase decision strategy methods in our proposed drivetrain swap logic.



## Drivetrain Swap Logic Preperations - Proposed Drivetrain Swap Logic Decisions:


When initiating adaptation, we first inspect all available target vehicle transfercase types (with analyze_powertrains) and look for the lowest cost match to our Camso donor drivetype. If no direct match is found (i.e. AWD > AWD) then we look for the next lowest adaptation_cost candidate type according to the adaptation_cost table. Cost >98 = REFUSE

When the swap_parameters.json option "transfercase_to_adapt": = <some_specified_target_vehicle_transfercase_slotname>, we skip looking for the lowest cost match and instead use the swap decision strategy table to determine which swap strategy to use for the specified BeamNG transfercase (must belong to the target vehicle). This way, the adaptation_cost is also calculated, allowing us to REFUSE invalid combinations.

> adaptation_cost table:
DIRECT = 0
DIRECT_AWD = 0
MAKE_AWD = 1
MAKE_4WD = 2
MAKE_RWD = 3
MAKE_FWD = 4
SYNTH_TC = 5
REFUSE = 99

> Swap decision strategy lookup table:
| 			  | BeamNG RWD  | BeamNG FWD        | BeamNG AWD        | BeamNG 4WD        | BeamNG NO_TC (RWD) | BeamNG NO_TC (FWD) |
| ----------- | ----------- | ----------------- | ----------------- | ----------------- | ------------------ | ------------------ |
| Camso RWD   | DIRECT      | REFUSE            | MAKE_RWD          | MAKE_RWD          | SYNTH_TC           | REFUSE             |
| Camso FWD   | REFUSE      | DIRECT   			| MAKE_FWD 			| MAKE_FWD 			| REFUSE             | SYNTH_TC           |
| Camso AWD   | REFUSE		| REFUSE			| DIRECT_AWD      	| MAKE_AWD	        | REFUSE             | REFUSE             |
| Camso 4WD   | REFUSE		| REFUSE			| MAKE_4WD        	| DIRECT            | REFUSE             | REFUSE             |


> Swap decision strategies:

- DIRECT = We inject BeamNG axle slots (proposed retrieval of slot names via analyze_powertrains.py) into our Camso transfercase_adapted, keeping powertrain paths aligned. This retains Camso transfercase parameters while achieving a complete drivetrain chain. When "transfercase_to_adapt": = single , we remove the Camso Rangebox transfercase variant. 

- DIRECT_AWD = certain Camso AWD sub-variants may need additional consideration for DIRECT style injection. BeamNG also has different implementations of AWD. Could prove somewhat complicated ("splitshaft" to "differential" or vis-a-versa). Goal is to retain Camso AWD characteristics as much as is feasible. May also require additional Camso .lua / controllers.

- MAKE_AWD = We should be able to just connect our transfercase to the axles, omitting rangebox etc from the chain. We need to be careful to select the correct downstream BeamNG shaft / axle for injection (rangebox confusion - analyze_powertrains should help)

- MAKE_4WD = this might be more involved considering that Camso 4WD transfer cases call for "Camso_4wd_controller" slot. We will work on this later or change to "REFUSE" if this proves too cumbersome.

- MAKE_RWD = we only inject the rear axle BeamNG axle slot into powertrain, leaving the front axles dangling. Our RWD Camso transfercase lacks a center differential so this will work fine. Consider renaming the slot description and slot suffix (_AWD, _RWD) for UI purposes.

- MAKE_FWD = Functions similar to MAKE_RWD, i.e. we only connect two front axles, leaving the rears dangling. Consider renaming slot descriptor.

- SYNTH_TC = For target vehicles that lack a transfer case entirely (e.g., moonhawk, pigeon, barstow). These vehicles wire `torsionReactorR` directly to `inputName: "gearbox"`, bypassing the TC layer. We generate a synthetic "bridge" jbeam part that (1) provides a TC slot for the Camso transfercase to fill, and (2) rewires `torsionReactorR` from `inputName: "gearbox"` to `inputName: "transfercase"` so the stock driveshaft chain receives torque through the Camso TC. Only valid for Camso RWD→non-TC(RWD) and Camso FWD→non-TC(FWD) because passthrough shafts don't require downstream slot injection. Cost = 5 (higher than other strategies because we're fabricating a new powertrain layer).

- REFUSE = Refuse to process swap. The user must provide a more compatible Camso vehicle architecture. Refusal is also upheld regardless of "transfercase_to_adapt": <argument>


## Further Preparations

### Architectural Decisions (Resolved)

These questions were evaluated during planning and the resolutions are recorded here for reference:

**Q1: DIRECT_AWD sub-variant handling**
When Camso AWD uses one device type (e.g., `splitShaft` for on-demand) but the target BeamNG vehicle's AWD uses another (e.g., `differential` for `pickup_transfer_case_AWD`), what do we do?
> **Resolution: Keep Camso device type.** The donor AWD personality is preserved regardless of the target vehicle's native AWD implementation. Camso splitShaft stays splitShaft, differential stays differential. The Camso center coupling type defines the driving character of the swap — that's the point of an engine/drivetrain swap.

**Q2: Multiple BeamNG transfer case matches**
When a target vehicle has multiple compatible transfer case types (e.g., pickup has 4WD, AWD, and RWD), should we generate Camso adaptations for all or just the best match?
> **Resolution: Best match only.** Generate only the lowest-cost adaptation. The user can override via `transfercase_to_adapt` parameter to select a different (or specific) BeamNG transfer case target.

**Q3: MAKE_4WD strategy feasibility**
Camso 4WD requires a `Camso_4wd_controller` with vehicle-specific shaft disconnect lists. Can this work on non-4WD BeamNG vehicles?
> **Resolution: Defer (REFUSE for now).** MAKE_4WD is set to REFUSE=99 in the initial implementation. The 4WD controller requires shaft name remapping (disconnect lists reference Camso-internal shaft names like `wheelaxleFR`/`wheelaxleFL`). This will be implemented in a later phase once we have shaft name mapping infrastructure. Note: DIRECT (4WD→4WD) still works because the Camso 4WD controller's disconnect targets happen to use standardized BeamNG shaft names.

**Q4: transferCase vs transfercase capitalization**
Camso exports use `transferCase` (camelCase) in powertrain arrays while BeamNG uses `transfercase` (lowercase).
> **Resolution: Derived structural adaptation.** Device name mappings are **derived at runtime** from Phase 1 analysis data (`swap_decision["selected_tc"]["devices"]`) using structural positional matching — matching donor and target devices by `(device_type, inputName)` role pairs. This follows the slot graph's "analyze → populate mapping → consume mapping" pattern, ensuring device name adaptation is context-aware and traceable rather than hardcoded. The mapping produces provenance records documenting which donor device maps to which target device and why. This approach naturally handles casing differences and also catches structural renames (e.g., 4WD's `frontDriveShaft` → `transfercase_F`) that simple case normalization would miss.
>
> **FWD segmented path:** FWD donors map their root device (`frontDriveShaft`) to the target TC's differential device (not the root rangeBox), because the FWD shaft semantically occupies the center coupling role. Camso native rangebox variant parts (`Camso_TransferCase_FWD_rangebox_*`) are unaffected — their `rangeBox` device structurally matches the target's `rangebox` naturally.

### Updated Decision Tables (Post-Resolution)

> adaptation_cost table (updated):
```
DIRECT     = 0
DIRECT_AWD = 0
MAKE_AWD   = 1
MAKE_4WD   = 99  ← deferred, treated as REFUSE
MAKE_RWD   = 3
MAKE_FWD   = 4
SYNTH_TC   = 5   ← synthetic transfer case injection for non-TC vehicles
REFUSE     = 99
```

> Swap decision strategy lookup table (updated):
| 			  | BeamNG RWD  | BeamNG FWD        | BeamNG AWD        | BeamNG 4WD        | BeamNG NO_TC (RWD) | BeamNG NO_TC (FWD) |
| ----------- | ----------- | ----------------- | ----------------- | ----------------- | ------------------ | ------------------ |
| Camso RWD   | DIRECT      | REFUSE            | MAKE_RWD          | MAKE_RWD          | SYNTH_TC           | REFUSE             |
| Camso FWD   | REFUSE      | DIRECT   			| MAKE_FWD 			| MAKE_FWD 			| REFUSE             | SYNTH_TC           |
| Camso AWD   | REFUSE		| REFUSE			| DIRECT_AWD      	| MAKE_AWD	        | REFUSE             | REFUSE             |
| Camso 4WD   | REFUSE		| REFUSE			| REFUSE (deferred)	| DIRECT            | REFUSE             | REFUSE             |

Note: `NO_TC` is not a drive type per se — it describes the target vehicle's **architecture** (no transfercase slot exists). The vehicle IS RWD or FWD; it simply achieves this via direct gearbox→driveshaft wiring without a TC layer. Only simple Camso RWD/FWD transfercases can be injected into these vehicles via SYNTH_TC because they are passthrough shafts. AWD/4WD Camso transfercases require downstream slot injection that non-TC vehicles cannot provide.

### Non-TC Vehicle Analysis (28 vehicles, from analyze_powertrains)

Out of 52 BeamNG vehicles analyzed, **28 lack a transfer case entirely**. Their powertrain chain goes directly from `gearbox` to `torsionReactorR` (RWD) or `differential_F` (FWD transaxle), bypassing the transfercase layer.

**Key wiring difference (confirmed via analyze_powertrains chain resolution):**

| Architecture | torsionReactorR `inputName` | Chain |
|---|---|---|
| TC-equipped (pickup, etki, legran) | `"transfercase"` | gearbox → transfercase → torsionReactorR → driveshaft → diff |
| Non-TC RWD (moonhawk, pigeon, etc.) | `"gearbox"` | gearbox → torsionReactorR → driveshaft → diff |
| Non-TC FWD (transaxle — autobello) | N/A (direct gearbox→diff_F) | gearbox → differential_F → halfshafts |

**Driveable non-TC road vehicles (realistic swap targets):**
moonhawk, barstow, bluebuck, burnside, fullsize, midsize, miramar, nine, racetruck, pigeon, wigeon

**Why this matters:** Camso ALWAYS exports a transfercase. When injecting a Camso TC into a non-TC vehicle, two problems arise:

1. **Dual consumers on gearbox output:** Both the injected Camso `transferCase` device and the stock `torsionReactorR` declare `inputName: "gearbox"`. This creates an unintended torque split.
2. **Dead-end transfercase output:** The Camso TC outputs as `transferCase` (or `transfercase`), but nothing in the stock vehicle consumes that device name — the stock driveshaft chain bypasses it.

**Solution — SYNTH_TC (Synthetic Transfer Case injection):**
Generate a synthetic "virtual transfercase" jbeam part that acts as a passthrough shaft, claiming `inputName: "gearbox"` and outputting as device name `transfercase`. This part is loaded alongside the Camso TC to convert the non-TC vehicle into a TC-equipped architecture. The Camso TC then connects normally via `inputName: "transfercase"` (or the existing naming from its powertrain array).

The synthetic TC also **rewires the stock driveshaft chain**: it includes a powertrain override that changes the stock `torsionReactorR` from `inputName: "gearbox"` to `inputName: "transfercase"`, ensuring the existing driveshaft/differential chain receives torque through the Camso TC rather than bypassing it.

**Cummins mod precedent:** The Cummins reference mod targets moonhawk (a non-TC vehicle) but avoids this problem entirely — it only replaces engine + transmission, keeping the stock driveshaft untouched with its `gearbox` wiring. Our Camso adaptation is fundamentally different because we inject a transfercase that must intercept the powertrain chain.

**Casing hazard:** Camso uses `transferCase` (camelCase) while BeamNG stock uses `transfercase` (lowercase). The synthetic TC must bridge this naming difference. The SYNTH_TC strategy should normalize the Camso TC output device name to match what the synthetic rewiring expects.

**Scope:** SYNTH_TC is limited to Camso RWD→NO_TC(RWD) and Camso FWD→NO_TC(FWD) because the Camso passthrough shaft can simply relay torque without needing downstream slot injection. AWD/4WD Camso transfercases require front+rear child slot injection that non-TC vehicles don't provide.

**analyze_powertrains capability note:** The `non_transfercase_chains.md` report (generated by `analyze_powertrains.py`) fully traces non-TC vehicle chains, resolving the exact device names, input wiring, and source files for every component from engine to wheels. This data is available for SYNTH_TC generation via the existing `run_targeted()` and `DrivetrainChainBuilder.build_chain()` integration — we simply need to target the transmission entry (not a TC entry) to get the full chain including the `torsionReactorR` wiring details.

**SYNTH_TC transmission coordination insight:** Since we own `transmission_adapted`, the adapted transmission and `transfercase_adapted` can be thought of as a coordinated package that inserts without interference into non-TC vehicles. Rather than needing to override stock vehicle parts to rewire the powertrain chain, we control the transmission's output device name — if `transmission_adapted` outputs as `transfercase` instead of `gearbox`, the Camso TC connects naturally via `inputName: "transfercase"` and the stock `torsionReactorR` (which expects `inputName: "gearbox"`) stops consuming the transmission output. This "transmission-as-bridge" approach is doubly effective because it avoids the dual-consumer conflict entirely through device naming rather than part overrides.

### Camso Test Export Inventory (10 exports cataloged)

| Mod Folder | Camso Hash | Drive Type | AWD Subtype | Center Device | Has Controller Lua? |
|---|---|---|---|---|---|
| `script_test_rwd` | 79971 | RWD | — | shaft | No |
| `mid_longitudinal_rearwd` | c9a0e | RWD | — | shaft | No |
| `tranv_mr` | 0fd31 | RWD | — | shaft | No |
| `testy623` | 58d60 | FWD | — | shaft | No |
| `jerp_chadiator_lockers` | 036a5 | 4WD | — | locked differential | Delegated to Camso_4wd_controller |
| `ondemandawd` | 036a5 | AWD | On-Demand | splitShaft | electronicSplitShaftLock |
| `viscousawd_clutched` | 036a5 | AWD | Viscous | differential (viscous) | No |
| `advancedawd_electricdiffs` | 036a5 | AWD | Advanced | differential (lsd) | camso_advawd |
| `testcvt` | 98cb0 | AWD | Helical | differential (lsd) | No |
| `tranv_mr_awd_dct` | 0fd31 | AWD | Helical | differential (lsd) | No |

Note: `persh_crayenne_moracc` (ec8ba, our current donor) = Helical AWD, same structure as `testcvt`.

### BeamNG Target Vehicle Transfer Case Inventory (from powertrain reports)

**pickup** (slotType: `pickup_transfer_case`):
| Part Name | Drive Type | Center Device | Has Rangebox | Input From |
|---|---|---|---|---|
| `pickup_transfer_case_4WD` (default) | 4WD | differential (locked) | Yes | rangebox:1 |
| `pickup_transfer_case_4WD_race` | 4WD | differential (locked) | Yes | rangebox:1 |
| `pickup_transfer_case_4WD_offroad` | 4WD | differential (locked) | Yes | rangebox:1 |
| `pickup_transfer_case_AWD` | AWD | differential (lsd) | No | gearbox:1 |
| `pickup_transfer_case_RWD` | RWD | shaft (passthrough) | No | gearbox:1 |

The pickup's powertrain chain downstream of `transfercase`:
- Output 1 → `torsionReactorR` → `driveshaft` → `differential_R` → rear wheels (via driveshaft_R slots)
- Output 2 → `shaft(transfercase_F)` → `torsionReactorF` → `driveshaft_F` → `differential_F` → front wheels (via driveshaft_F slots)

**etki** (slotType: `etki_transfer_case`):
| Part Name | Drive Type | Center Device | Input From |
|---|---|---|---|
| `etki_transfer_case_RWD` | RWD | shaft | gearbox:1 |
| `etki_transfer_case_AWD` | AWD | splitShaft | gearbox:1 |
| `etki_transfer_case_AWD_race` | AWD | differential (lsd) | gearbox:1 |

---

## Implementation Plan

### Overview

The drivetrain swap logic integrates `analyze_powertrains.py` as a module to resolve the target vehicle's powertrain chain, classify both donor and target drivetrain types, select the optimal swap strategy, and generate an adapted transfercase file with BeamNG axle slots injected into the Camso transfercase structure.

**Core principle:** The Camso transfercase retains its internal powertrain devices (the center coupling that defines the donor's driving character). We only modify the **child slot references** — replacing Camso's driveshaft child slots (`Camso_driveshaft_front`, `Camso_driveshaft_rear`) with the target vehicle's downstream axle/driveshaft slot references obtained from `analyze_powertrains`.

### Phase 0: Preparations (Config & Asset Pipeline)

**0.1 — New swap_parameters options**

Add to `configs/swap_parameters.json`:
```json
{
  "transmissions_to_adapt": "all",
  "transfercase_to_adapt": "auto"
}
```

- `transmissions_to_adapt`:
  - `"single"` — Only adapt the transmission referenced by-default in the Camso engine's slot hierarchy
  - `"all"` — Adapt all found Camso transmissions (current behavior, remains default)

- `transfercase_to_adapt`:
  - `"auto"` — Automatically select the lowest-cost BeamNG transfercase match (default)
  - `"<part_name>"` — Specify a BeamNG transfer case part name (e.g., `"pickup_transfer_case_AWD"`); triggers the swap decision strategy lookup for that specific part, then REFUSE if incompatible

**0.2 — Schema updates**

Update `configs/schemas/swap_parameters.schema.json` with new property definitions and validation patterns.

**0.3 — camso_advawd.lua packaging**

Extend `extra_assets` discovery to also find controller lua files at:
`<donor_vehicle>/lua/controller/drivingDynamics/actuators/*.lua`

Currently `_discover_extra_assets()` only handles `lua/powertrain/*.lua`. Add a second glob pattern for actuator controller lua files. These are required when the donor uses Advanced AWD (or other controller-dependent AWD subtypes).

**0.4 — 4WD controller .jbeam packaging**

When a Camso 4WD transfercase references a `Camso_4wd_controller` child slot, the controller's .jbeam file (e.g., `camso_4x4_controllers.jbeam`) must also be included in the mod package. This is already handled by the existing slot graph traversal (original jbeam files from child slots are tracked), but verify this works for the 4WD case.

### Phase 1: Target Vehicle Powertrain Analysis Integration

**1.1 — Import analyze_powertrains as module**

```python
from analyze_powertrains import SlotRegistry, DrivetrainChainBuilder, PowertrainExtractor
```

Invoke within `EngineTransplantUtility` after target vehicle identification:
```python
# Build slot registry from target vehicle content
registry = SlotRegistry(content_path / "vehicles" / "common", content_path / "vehicles" / target_vehicle)
registry.index_all()

# Resolve powertrain chains
chain_builder = DrivetrainChainBuilder(registry)
chains = chain_builder.resolve_chains()

# Extract structured data
extractor = PowertrainExtractor(chains, registry)
entries = extractor.extract_entries()
```

**1.2 — Extract transfer case catalog**

Filter `entries` to find all parts whose slotType matches `{target_vehicle}_transfer_case` (or the vehicle's known transfer case slotType pattern). For each:
- Part name (e.g., `pickup_transfer_case_AWD`)
- SlotType (e.g., `pickup_transfer_case`)
- Powertrain devices (list of `[type, name, inputName, inputIndex]`)
- Downstream drivetrain components (from resolved chain data)

**1.3 — Classify BeamNG transfer case drive type**

Implement `classify_beamng_drive_type(entry)` heuristic:

```python
def classify_beamng_drive_type(powertrain_devices):
    """Classify a BeamNG transfer case entry as RWD, FWD, AWD, or 4WD."""
    device_types = [d[0] for d in powertrain_devices]  # ['rangeBox', 'differential', 'shaft']
    has_rangebox = 'rangeBox' in device_types
    has_differential = 'differential' in device_types
    has_split_shaft = 'splitShaft' in device_types
    
    # Check for front output shaft in powertrain
    has_front_output = any(d[1] in ('transfercase_F', 'driveshaft_F', 'frontDriveShaft') 
                          for d in powertrain_devices if d[0] == 'shaft')
    
    if has_rangebox and has_differential:
        return '4WD'   # rangeBox + locked differential = 4WD
    elif has_differential or has_split_shaft:
        if has_front_output:
            return 'AWD'  # center diff/splitShaft with both axle outputs
        else:
            return 'RWD'  # unlikely but defensive
    elif not has_front_output:
        return 'RWD'   # simple shaft passthrough, rear-only
    else:
        return 'FWD'   # simple shaft passthrough, front-only (no BeamNG examples known)
```

**1.4 — Extract downstream axle slot references**

For the selected BeamNG transfer case, identify the immediate downstream slot connections:
- **Rear output:** The first child slot whose powertrain chain connects via `transfercase:1` (output index 1). Typically a driveshaft_R slot.
- **Front output:** The first child slot whose powertrain chain connects via `transfercase:2` (output index 2). Typically a driveshaft_F slot.

These slot references become the injection targets. We use the `DrivetrainChain.components` list from `analyze_powertrains` — each component records its `slot` name and `slotType`, allowing us to identify which BeamNG slot immediately follows the transfercase in the powertrain chain.

**Key data to extract per output:**
```python
@dataclass
class AxleSlotRef:
    slot_type: str       # e.g., "pickup_driveshaft_R"
    default_part: str    # e.g., "pickup_driveshaft_R"
    description: str     # e.g., "Rear Driveshaft"
    output_index: int    # 1 = rear, 2 = front
```

**1.5 — Non-TC vehicle fallback classification**

When `analyze_target_powertrain()` returns `None` (0 reachable TC entries), the target vehicle has **no transfer case slot**. In this case, classify the vehicle's native drivetrain architecture by inspecting its transmission chain data (available via `analyze_powertrains` supplemental entries or `non_transfercase_chains` report):

```python
def classify_non_tc_architecture(vehicle_name, base_path):
    """Classify a non-TC vehicle as NO_TC_RWD or NO_TC_FWD.
    
    Uses analyze_powertrains to trace the transmission chain and detect
    whether the vehicle's gearbox output flows to rear wheels (RWD)
    or front wheels (FWD).
    """
    # Already have registry + extractor from Phase 1 — reuse them.
    # Check the transmission entry's resolved chain for torsionReactorR 
    # (RWD) or differential_F (FWD transaxle).
    # 
    # Key heuristics from non_transfercase_chains analysis:
    # - torsionReactorR with inputName:"gearbox" → RWD
    # - differential_F with inputName:"gearbox" → FWD (transaxle)
    # - Both torsionReactorR + torsionReactorF present → ambiguous 
    #   (check if front devices are "dangling" in the chain)
```

This classification determines which `NO_TC_*` column to use in the swap decision strategy lookup. The result is used by `select_best_match()` in Phase 3 when the TC catalog is empty.

### Phase 2: Camso Donor Drive Type Classification ✅ COMPLETE

**Status:** Implemented in `engineswap.py` — `analyze_donor_powertrain()`, `_classify_camso_part_drive_type()`, `_classify_camso_awd_subvariant()`, `_extract_camso_part_summary()`. Validated 10/10 against all Camso test exports.

**2.1 — Parse Camso transfercase structure** ✅

`analyze_donor_powertrain(donor_engine_path)` finds the TC file via `_find_donor_transfercase_file()`, parses with `JBeamParser`, separates parts by slotType (`Camso_TransferCase` vs `Camso_differential_center`), and extracts structured summaries (devices, child slots, controllers, notable properties).

**analyze_powertrains reuse evaluation:** `PowertrainExtractor` was considered but rejected for Camso classification — it's designed for BeamNG base game conventions (lowercase `transfercase`, `_common_to_vehicles` filtering). Instead, the **output format and methodology** were mirrored: `analyze_donor_powertrain()` produces a catalog dict symmetrical to `analyze_target_powertrain()` so Phase 3 receives uniform inputs from both sides.

**2.2 — Classification heuristic** ✅

Two-tier approach in `_classify_camso_part_drive_type()`:

**Tier 1 — Part name pattern** (Camso convention, reliable):
```
Camso_TransferCase_RWD_<hash> → RWD
Camso_TransferCase_FWD_<hash> → FWD
Camso_TransferCase_AWD_<hash> → AWD
Camso_TransferCase_4x4_<hash> → 4WD
```

**Tier 2 — Structural analysis fallback** (if name doesn't match):
- `Camso_differential_center` child slot → AWD
- `Camso_4wd_controller` child slot → 4WD
- `rangeBox` + locked `differential` devices → 4WD
- `frontDriveShaft` device name → FWD
- `transferCase` shaft device → RWD

**Gap fixed vs old `DonorDriveTypeExtractor`:** FWD exports have no `Camso_driveshaft_front` slot (commented out), so the old extractor would return UNKNOWN. The new classifier detects FWD via the `frontDriveShaft` powertrain device name and the part name pattern.

**2.3 — AWD sub-variant classification (informational, with implementation implications)** ✅

For AWD types, further classify the center coupling. All AWD subtypes map to the same `DIRECT_AWD` swap strategy and adaptation cost (0), but the **actual implementation** of DIRECT_AWD may require sub-variant-aware logic:

**Device type mismatch scenario:** A Camso on-demand AWD uses `splitShaft` (a clutch-based device with `lockTorque`, `defaultClutchRatio`), while a BeamNG target like `pickup_transfer_case_AWD` uses `differential` (with `diffType:"lsd"`, `lsdLockCoef`). These are fundamentally different BeamNG powertrain device types with different property schemas. The Camso center coupling is preserved as-is (per our core design principle), so the mismatch doesn't prevent the swap — but downstream connections (output port indexing, driveshaft naming) may differ between `splitShaft` and `differential` devices. Phase 5 implementation should check whether the Camso device's output port conventions match what the injected BeamNG axle slots expect.

**Where this matters (Phase 5+):**
- `splitShaft` uses `primaryOutputID` to designate which port gets priority torque
- `differential` uses output indices 1 (rear) and 2 (front) by convention
- Controller lua files (e.g., `camso_advawd.lua`, `electronicSplitShaftLock`) reference the center device by name — these must be packaged (already handled by Phase 0.3)
- Viscous AWD has no active controller; on-demand AWD has `electronicSplitShaftLock`; advanced AWD has `camso_advawd` — each may interact differently with BeamNG's drivingDynamics system

| Child `Camso_differential_center` powertrain device | Sub-variant |
|---|---|
| `splitShaft` | On-Demand |
| `differential` with `diffType: "viscous"` | Viscous |
| `differential` with `diffType: "lsd"` + `camso_advawd` controller | Advanced |
| `differential` with `diffType: "lsd"` + no controller | Helical |

### Phase 3: Swap Decision Engine ✅ COMPLETE

**Status:** Implemented and validated. 19/19 test cases passed (auto mode: 4 donor types × pickup + non-TC vehicles; specified mode: valid/invalid/incompatible; cross-family TC: roamer).

**Implementation:** `engineswap.py` — module-level `SWAP_STRATEGY` and `ADAPTATION_COST` constants, plus class methods `select_swap_strategy()`, `_evaluate_auto_strategy()`, `_evaluate_specified_strategy()`, `_evaluate_no_tc_strategy()`. Integrated into generate command with decision logging output.

**3.1 — Strategy lookup**

```python
SWAP_STRATEGY = {
    ('RWD', 'RWD'): 'DIRECT',
    ('RWD', 'FWD'): 'REFUSE',
    ('RWD', 'AWD'): 'MAKE_RWD',
    ('RWD', '4WD'): 'MAKE_RWD',
    ('RWD', 'NO_TC_RWD'): 'SYNTH_TC',
    ('RWD', 'NO_TC_FWD'): 'REFUSE',
    ('FWD', 'RWD'): 'REFUSE',
    ('FWD', 'FWD'): 'DIRECT',
    ('FWD', 'AWD'): 'MAKE_FWD',
    ('FWD', '4WD'): 'MAKE_FWD',
    ('FWD', 'NO_TC_RWD'): 'REFUSE',
    ('FWD', 'NO_TC_FWD'): 'SYNTH_TC',
    ('AWD', 'RWD'): 'REFUSE',
    ('AWD', 'FWD'): 'REFUSE',
    ('AWD', 'AWD'): 'DIRECT_AWD',
    ('AWD', '4WD'): 'MAKE_AWD',
    ('AWD', 'NO_TC_RWD'): 'REFUSE',
    ('AWD', 'NO_TC_FWD'): 'REFUSE',
    ('4WD', 'RWD'): 'REFUSE',
    ('4WD', 'FWD'): 'REFUSE',
    ('4WD', 'AWD'): 'REFUSE',    # MAKE_4WD deferred
    ('4WD', '4WD'): 'DIRECT',
    ('4WD', 'NO_TC_RWD'): 'REFUSE',
    ('4WD', 'NO_TC_FWD'): 'REFUSE',
}

ADAPTATION_COST = {
    'DIRECT': 0, 'DIRECT_AWD': 0, 'MAKE_AWD': 1, 'SYNTH_TC': 5,
    'MAKE_RWD': 3, 'MAKE_FWD': 4, 'REFUSE': 99,
}
```

**3.2 — Auto-selection mode (`transfercase_to_adapt: "auto"`)**

```python
def select_best_match(camso_type, beamng_tc_catalog, target_arch='TC'):
    """Find lowest-cost BeamNG transfer case match.
    
    target_arch: 'TC' if vehicle has transfer cases, 
                 'NO_TC_RWD'/'NO_TC_FWD' if vehicle lacks TC.
    """
    if target_arch.startswith('NO_TC'):
        # Non-TC vehicle: use SYNTH_TC strategy lookup
        strategy = SWAP_STRATEGY.get((camso_type, target_arch), 'REFUSE')
        cost = ADAPTATION_COST[strategy]
        if cost < 99:
            return (cost, strategy, None)  # No BeamNG TC part to reference
        return None  # REFUSE
    
    candidates = []
    for beamng_tc in beamng_tc_catalog:
        beamng_type = classify_beamng_drive_type(beamng_tc)
        strategy = SWAP_STRATEGY.get((camso_type, beamng_type), 'REFUSE')
        cost = ADAPTATION_COST[strategy]
        if cost < 99:
            candidates.append((cost, strategy, beamng_tc))
    
    if not candidates:
        return None  # REFUSE all — no compatible target
    
    candidates.sort(key=lambda x: x[0])
    return candidates[0]  # (cost, strategy, beamng_transfer_case)
```

**3.3 — Specified mode (`transfercase_to_adapt: "<part_name>"`)**

Validate that the named part exists in the target vehicle's transfer case catalog. Compute strategy and cost. If REFUSE, halt with error message explaining incompatibility.

**3.4 — Decision logging**

Print/log the decision for user visibility:
```
[DRIVETRAIN] Camso donor: AWD (Helical subtype)
[DRIVETRAIN] Target vehicle 'pickup' transfer case catalog:
  - pickup_transfer_case_4WD    → 4WD  → strategy: MAKE_AWD    (cost: 1)
  - pickup_transfer_case_AWD    → AWD  → strategy: DIRECT_AWD  (cost: 0)  ← SELECTED
  - pickup_transfer_case_RWD    → RWD  → strategy: REFUSE      (cost: 99)
[DRIVETRAIN] Selected: pickup_transfer_case_AWD via DIRECT_AWD strategy
```

### Phase 4: Axle Slot Extraction ✅ COMPLETE

> **Status:** Implemented and validated — 11/11 test cases passing (test_phase4.py)
> **Methods:** `extract_injection_targets()`, `_classify_chain_component_position()`
> **Integration:** Phase 4 output section added to generate command
>
> **Critical Architecture Finding:** BeamNG transfer case parts have ZERO direct child slots.
> Downstream driveshaft/differential/wheeldata slots are declared by the vehicle's FRAME
> (via `slots2`), not by the TC part itself. The TC connects to driveshafts purely through
> powertrain device naming (e.g., `torsionReactorR` has `inputName: "transfercase"`).
> This means Phase 5 should PRUNE Camso driveshaft child slots rather than inject BeamNG
> equivalents, but the code accommodates TCs that DO declare direct child slots via the
> `tc_has_direct_child_slots` / `direct_child_count` fields.
>
> **Shared Slot Tree Discovery:** For vehicles like etki, RWD and AWD TC variants share
> identical chain_components (8 each) because the chain resolver walks the slot tree, not
> the powertrain connections. An RWD TC using `shaft` (pass-through) reports front slots
> that exist in the tree but aren't actively powered. This is correct — Phase 5 needs to
> know where front slots EXIST regardless of current TC drive type.
>
> **Classification Heuristic:** `torsionReactorR` in device names → rear position;
> `driveshaft_F` in device names → front position; all other devices (differential_R,
> wheelaxle*, halfshaft*, spindle*) → skipped as deeper components.
>
> **Return Format:**
> ```python
> {
>     "rear_slots": [...],    # {slot_type, default_part, position, devices}
>     "front_slots": [...],
>     "tc_has_direct_child_slots": bool,
>     "direct_child_count": int,
>     "tc_devices": [...],
>     "strategy": str,
>     "selected_tc": str
> }
> ```

**4.1 — Identify injection slot targets from BeamNG chain data**

Using the selected BeamNG transfer case's resolved drivetrain chain data (from Phase 1.4), extract the immediate downstream slot connections. These are the BeamNG slots that must appear as child slots in the adapted Camso transfercase.

For each transfer case type, identify which child slots provide the first downstream powertrain connection:

**Example — pickup_transfer_case_AWD:**
- Output 1 (rear): first slot providing `torsionReactorR`/`driveshaft` → slotType `pickup_driveshaft_R` (or `van_driveshaft_R`)
- Output 2 (front): first slot providing `transfercase_F`→`driveshaft_F` → slotType `pickup_driveshaft_F` (or `van_driveshaft_F`, `pickup_driveshaft_SFA`)

The `analyze_powertrains` resolved chain already splits these out in the `Resolved Drivetrain Components` section. We look for components whose powertrain devices include the device immediately downstream of the transfercase output.

**4.2 — Slot reference normalization**

The extracted slot references may have multiple valid part names for the same slotType. We only need the slotType and a sensible default:

```python
@dataclass
class InjectionTarget:
    slot_type: str       # BeamNG slotType, e.g., "pickup_driveshaft_R"
    default_part: str    # Default part to reference, e.g., "pickup_driveshaft_R"
    description: str     # Human label, e.g., "Rear Driveshaft"
    position: str        # "rear" or "front"
```

For RWD-only strategies (MAKE_RWD), only the rear target is needed.
For FWD-only strategies (MAKE_FWD), only the front target is needed.
For AWD/4WD strategies, both targets are needed.

### Phase 5: Strategy-Specific TC Adaptation (Slot Pruning + Device Compatibility) ✅ COMPLETE

> **Key Correction (from Phase 4 findings):** The original plan described "injecting BeamNG axle slots" into the Camso TC. This was based on the assumption that BeamNG TCs declare downstream driveshaft child slots. **They don't.** BeamNG TCs have ZERO direct child slots — all downstream driveshaft/differential/wheeldata slots are declared by the vehicle's FRAME (via `slots2`). The TC connects to driveshafts purely through powertrain device naming.
>
> **Corrected approach:** Phase 5 PRUNES Camso driveshaft child slots (removes them) rather than replacing them with BeamNG equivalents. The BeamNG vehicle's native frame already provides the downstream driveshaft infrastructure. The Camso TC retains its internal powertrain devices (center coupling, rangebox, etc.) and connects to the BeamNG driveshaft chain via derived device name adaptation.
>
> **Implementation (completed):** Four static helper methods added + `generate_adapted_transfercase()` refactored:
> - `_prune_driveshaft_slots()` — removes slot entries matching given slotType strings from slots/slots2 arrays
> - `_derive_device_name_mapping()` — **derives** device name renames from Phase 1 analysis data using structural positional matching by `(device_type, inputName)` role pairs, with transitive resolution for chain dependencies and FWD segmented fallback; returns `{renames, provenance}` for traceability
> - `_normalize_powertrain_device_names()` — applies a rename mapping to powertrain arrays, config sections, and controller entries (generic consumer of the derived mapping)
> - `_apply_tc_strategy_adaptations()` — orchestrator dispatching pruning + derived device adaptation by strategy; emits provenance-annotated summary
> - Validated: 14/14 tests (8 unit + 6 integration), Phase 3 regression 19/19, Phase 4 regression 11/11
>
> **Rework note (architectural):** Initial implementation used hardcoded `{"transferCase": "transfercase"}` device name normalization. This was reworked to derive mappings from `swap_decision["selected_tc"]["devices"]` (Phase 1 target TC topology data) using structural positional matching. This follows the slot graph's "analyze → populate mapping → consume mapping" pattern, making device name adaptation context-aware, traceable, and resilient to vehicles with unexpected naming conventions.
>
> **Derived mappings by drive type (verified):**
> | Drive Type | Mappings Derived | Matching Method | Devices Injected |
> |---|---|---|---|
> | AWD | `transferCase→transfercase` (1) | structural: differential(inputName='gearbox') | `transfercase_F` (front output shaft from target) |
> | RWD | `transferCase→transfercase` (1) | structural: shaft(inputName='gearbox') | (none) |
> | 4WD | `transferCase→transfercase` + `frontDriveShaft→transfercase_F` (2) | structural: full chain positional | (none - already has front shaft device) |
> | FWD | `frontDriveShaft→transfercase` (1) | FWD segmented: maps to target differential | (none) |
>
> **AWD device injection (added during in-game debugging):** Camso AWD donors route front/rear torque via child slots, which Phase 5 correctly prunes. However, the target BeamNG TC defines the front output as a powertrain-level device entry. After pruning, `_derive_device_name_mapping()` detects target devices with no donor equivalent (by type), and `_apply_tc_strategy_adaptations()` injects them into the center diff part. A connectivity filter ensures only devices whose `inputName` references a device defined in the part (post-rename) are injected. For MAKE_AWD (cross-topology), a type-only fallback matcher handles different chain positions.

This phase refactors the existing `generate_adapted_transfercase()` method to integrate Phase 3 (swap decision) and Phase 4 (injection targets / chain data), applying strategy-specific slot pruning and device name validation.

#### Existing Code Baseline

`generate_adapted_transfercase()` (~130 lines) already exists at line ~3827. It currently:
- Reads `_last_donor_drive_type` to decide whether to inject geometry nodes
- Parses the donor TC jbeam file
- For parts with `"transfer"` in slotType: renames part, remaps slotType to `{target}_transfer_case`
- For other parts (e.g., center diff): deep copies without renaming
- Writes output file

**Gaps to address:**
- Does NOT call `_transform_slots_with_graph()` (engine and transmission do)
- Does NOT use Phase 3 swap decision or Phase 4 axle data
- Does NOT prune Camso driveshaft child slots
- TC slotType is hardcoded rather than derived from swap decision
- AWD center diff parts pass through verbatim (no slot pruning on the inner part)

#### Camso TC Structures by Drive Type (from donor file analysis)

| Drive Type | Structure | Driveshaft Slots Present | Front Drive Mechanism |
|---|---|---|---|
| **RWD** | Flat (single part) | `Camso_driveshaft_rear` (1 slot) | None |
| **FWD** | Flat (single part) | **None** (all commented out) | Powertrain device `frontDriveShaft` |
| **AWD** | Two-tier (wrapper + center diff) | `Camso_driveshaft_front` + `Camso_driveshaft_rear` on **center diff** | Center device output index 2 |
| **4WD** | Flat (single part) | `Camso_driveshaft_rear` (1 slot) + `Camso_4wd_controller` (coreSlot) | Powertrain device `frontDriveShaft` with `canDisconnect:true` |

#### Powertrain Device Name Adaptation (Derived Structural Matching) ✅ RESOLVED

**Problem:** Camso uses `transferCase` (camelCase) as its center device name. BeamNG downstream components use `inputName: "transfercase"` (lowercase). Additionally, 4WD TCs have a `frontDriveShaft` device that must match the target's front shaft name (`transfercase_F` on pickup), and FWD TCs use `frontDriveShaft` as their root device which must map to the target's center coupling role.

**Solution — Derived structural positional matching:** `_derive_device_name_mapping()` reads the target TC's device topology from `swap_decision["selected_tc"]["devices"]` (populated by Phase 1 analysis). It builds a role lookup keyed by `(device_type, inputName)` pairs, then walks the donor powertrain arrays matching each device by its structural role. Transitive resolution ensures that if device A is renamed, any downstream device referencing A via `inputName` is resolved through the rename chain.

**Why not hardcoded normalization:** Hardcoding `{"transferCase": "transfercase"}` would miss the 4WD `frontDriveShaft→transfercase_F` rename and would break if a target vehicle used non-standard device naming. The derived approach adapts to whatever the target analysis data reports, following the slot graph's "analyze → populate mapping → consume mapping" traceability pattern.

**FWD segmented path:** FWD donors have a single powertrain device (`frontDriveShaft`) that plays the center coupling role. The structural matcher maps it to the target TC's **differential** device (not the root rangeBox), because FWD's shaft semantically occupies the torque-splitting position. Camso native rangebox variant parts are unaffected — their `rangeBox` device naturally matches the target's `rangebox`.

**Provenance tracking:** Each derived rename is recorded with `{donor_name, target_name, source_part, target_part, reason}`, enabling downstream validation and debugging.

**5.1 — DIRECT (RWD→RWD)**

The simplest case. Camso RWD TC has a single `Camso_driveshaft_rear` child slot.

**Actions:**
1. **Prune** `Camso_driveshaft_rear` slot from the TC part's `slots` array
2. **Derive + apply** device name mapping: `_derive_device_name_mapping()` reads target TC topology from `swap_decision` and maps `transferCase` → target's shaft device name (typically `transfercase`)
3. **Remap** top-level slotType: `Camso_TransferCase` → `{target}_transfer_case`
4. **Rename** part: `{target}_Camso_TransferCase_RWD_{hash}`
5. **Update** information section with descriptive name

The derived mapping ensures the Camso TC's output device name matches what the BeamNG vehicle's frame-declared `torsionReactorR` expects as `inputName`.

**Rangebox variant (if `transfercase_to_adapt: "all"`):** The `Camso_TransferCase_RWD_rangebox_*` variant is also adapted — same pruning applies. Its rangeBox device adds 2hi/2lo gear selection.

**5.2 — DIRECT (4WD→4WD)**

Camso 4WD TC has `Camso_driveshaft_rear` + `Camso_4wd_controller` (coreSlot) + hardcoded `frontDriveShaft` powertrain shaft.

**Actions:**
1. **Prune** `Camso_driveshaft_rear` slot from the TC part's `slots` array
2. **Keep** `Camso_4wd_controller` slot (coreSlot, provides driveModes)
3. **Keep** `frontDriveShaft` powertrain device as-is (it reads from `transferCase:2`)
4. **Derive + apply** device name mapping: structural positional matching produces 2 mappings for 4WD — center differential rename (`transferCase`→`transfercase`) and front shaft rename (`frontDriveShaft`→`transfercase_F`). Transitive resolution ensures downstream `inputName` references stay coherent.
5. **Remap** slotType, rename part, update info

**4WD controller shaft references:** The `Camso_4wd_controller` declares `frontDriveShaft`, `wheelaxleFR`, `wheelaxleFL` in its disconnect lists. These are standard BeamNG device names that should match the target vehicle's actual shaft names. If the target vehicle uses different names (e.g., `driveshaft_F` instead of `frontDriveShaft`), the controller won't function correctly. Phase 4 chain data can verify this. Note: the `frontDriveShaft` rename in the powertrain array is handled by the derived mapping; controller disconnect list references may need separate consideration in Phase 6.

**5.3 — DIRECT_AWD (AWD→AWD)**

Camso AWD uses a two-tier structure. Driveshaft slots are on the **center diff part**, not the wrapper.

```
Camso_TransferCase_AWD_<hash>          (wrapper, no powertrain)
  └─ Camso_differential_center_<hash>  (center diff + driveshaft child slots)
       ├─ Camso_driveshaft_front       → PRUNE (remove)
       └─ Camso_driveshaft_rear        → PRUNE (remove)
```

**Actions:**
1. **Wrapper part:** Remap slotType `Camso_TransferCase` → `{target}_transfer_case`. Keep `Camso_differential_center` child slot as-is (coreSlot, internal ecosystem).
2. **Center diff part:** Prune BOTH `Camso_driveshaft_front` and `Camso_driveshaft_rear` from its `slots` array.
3. **Keep** center diff powertrain devices (differential/splitShaft with Camso personality — lsd, viscous, on-demand, etc.)
4. **Keep** center diff controllers (electronicSplitShaftLock, camso_advawd, etc.)
5. **Derive + apply** device name mapping on center diff: `transferCase` → target's differential device name (derived from `swap_decision["selected_tc"]["devices"]`)
6. **Rename** wrapper part. Center diff part name can stay (internal ecosystem).

**Decision preserved:** Keep Camso's center device type (splitShaft, viscous, lsd) — the donor's AWD personality is the point of the swap.

6. **Inject** missing front output shaft: after pruning and renaming, `_apply_tc_strategy_adaptations()` injects `["shaft", "transfercase_F", "transfercase", 2, {properties}]` into the center diff powertrain array. Properties are sourced verbatim from Phase 1 target TC analysis data. This entry is required because Camso AWD routes front torque via child slots (now pruned), but BeamNG expects a powertrain-level device for the front driveshaft chain.

**Injection provenance:** Recorded with `donor_name: None` to distinguish from rename operations, enabling downstream validation.

**AWD sub-variant notes:**
- Helical (differential lsd, no controller): simplest — just prune slots
- Viscous (differential viscous, no controller): same as helical
- On-demand (splitShaft + electronicSplitShaftLock controller): prune slots, preserve controller
- Advanced (differential lsd + camso_advawd controller): prune slots, preserve controller; `camso_advawd.lua` must be packaged (Phase 0.3 handles this)

**5.4 — MAKE_RWD (RWD→AWD target, RWD→4WD target)**

Camso RWD TC has only a rear driveshaft slot. Same pruning as DIRECT RWD.

**Actions:**
1. **Prune** `Camso_driveshaft_rear` from the TC part
2. **Remap** slotType to `{target}_transfer_case`
3. **Update** info: append " (RWD Swap)" for UI clarity

The Camso RWD TC is a shaft passthrough to the rear. When filling a TC slot designed for AWD/4WD, the front driveshaft infrastructure (declared by the BeamNG frame) simply receives no torque input — the front wheels spin freely. This is physically correct for an RWD conversion.

**No additional front-side adaptation needed:** The BeamNG vehicle's front driveshaft+differential+halfshaft parts remain structurally present (they're frame-declared) but receive zero torque because the Camso TC has no front output.

**5.5 — MAKE_FWD (FWD→AWD target, FWD→4WD target)**

Camso FWD TC has **no driveshaft child slots** (all commented out in exports). However, the TC's powertrain device name needs adaptation.

**Actions:**
1. **No slot pruning needed** (no active driveshaft child slots exist)
2. **Derive + apply** device name mapping via FWD segmented path: `_derive_device_name_mapping()` maps `frontDriveShaft` → target TC's differential device name (typically `transfercase`), because FWD's root shaft semantically occupies the center coupling role. Camso native rangebox variant parts are unaffected — their `rangeBox` device naturally matches the target's `rangebox`.
3. **Remap** slotType to `{target}_transfer_case`
4. **Update** info: append " (FWD Swap)" for UI clarity

The rear driveshaft infrastructure receives no torque (no rear output from the Camso FWD TC).

**Resolved:** The FWD TC's `frontDriveShaft` device outputs from `gearbox:1`. In a TC-equipped vehicle, the downstream chain expects input from `transfercase`, not `gearbox`. The derived device name mapping renames `frontDriveShaft` → `transfercase` (the target's differential device), which resolves this connection.

**5.6 — MAKE_AWD (AWD→4WD target)**

The Camso AWD center differential drives both axles. Same pruning as DIRECT_AWD.

**Actions:**
1. **Prune** both driveshaft slots from the center diff part
2. **Keep** AWD center coupling (Camso's AWD personality replaces the 4WD locked diff + rangebox)
3. **Derive + apply** device name mapping via type-only fallback: the 4WD target has a different chain structure (`differential→rangebox→gearbox`) than the AWD donor (`differential→gearbox`). Strict `(type, inputName)` matching fails. The type-only fallback detects that the donor has exactly one unrenamed `differential` device and the target has one `differential` → infers `transferCase→transfercase`.
4. **Inject** front output shaft: same as DIRECT_AWD — `transfercase_F` is injected into the center diff powertrain. The target's `rangebox` is NOT injected because its `inputName` (`gearbox`) doesn't reference a device defined in the center diff part — a principled connectivity filter.
5. **Remap** wrapper slotType to `{target}_transfer_case`
6. **Update** info

The BeamNG 4WD target vehicle natively uses a rangebox + locked diff. The Camso AWD center diff replaces this entire assembly with a continuous center coupling. The target vehicle effectively becomes AWD instead of 4WD.

The downstream driveshaft slots (front + rear) are identical between the target vehicle's 4WD and AWD TC variants (confirmed by Phase 4 data — both share the same chain_components). So the Camso AWD TC connects to the same infrastructure regardless.

**5.7 — SYNTH_TC (RWD→NO_TC, FWD→NO_TC) — DEFERRED**

> **Scope decision:** SYNTH_TC is the most complex strategy, requiring synthetic jbeam generation and powertrain rewiring for non-TC vehicles. It should be implemented as a separate phase after the core TC-equipped strategies (5.1–5.6) are validated. For now, SYNTH_TC generates a warning message and skips TC adaptation.

For non-TC target vehicles (moonhawk, pigeon, barstow, etc.):
- No TC slot exists in the vehicle's slot hierarchy
- The stock driveshaft chain wires directly to `gearbox` (not `transfercase`)

**Planned approach (deferred implementation):**

The adapted transmission already outputs as device name `gearbox`. The Camso TC takes `inputName: "gearbox"`. In a TC-equipped vehicle, the TC's output device (`transferCase`/`transfercase`) feeds the downstream chain. For non-TC vehicles:

**Option A — Transmission-bridge approach:** Since we control `transmission_adapted`, we can rename the transmission's output device from `gearbox` to something like `gearbox_out`, then have the Camso TC take `inputName: "gearbox_out"` and output as `gearbox`. This way the stock driveshaft chain (which expects `inputName: "gearbox"`) receives torque through the inserted TC without needing rewiring of stock parts.

**Option B — Powertrain override approach:** Generate a synthetic jbeam part that overrides the stock `torsionReactorR` to change its `inputName` from `"gearbox"` to `"transfercase"`, allowing the Camso TC to intercept the chain.

Resolution and implementation deferred to a later phase.

#### Strategy Implementation Summary

| Strategy | Donor Type | Target Type | Slot Pruning | Device Adaptation (Derived) | Notes |
|---|---|---|---|---|---|
| DIRECT | RWD | RWD TC | Prune `Camso_driveshaft_rear` | `transferCase` → target's shaft device name | Simplest; 1 derived mapping |
| DIRECT | 4WD | 4WD TC | Prune `Camso_driveshaft_rear` | Full chain: `transferCase` → target diff + `frontDriveShaft` → target front shaft | 2 derived mappings; keep `Camso_4wd_controller` |
| DIRECT_AWD | AWD | AWD TC | Prune both driveshaft slots (on center diff) | `transferCase` → target's diff device name | Two-tier; keep center coupling; 1 derived mapping |
| MAKE_RWD | RWD | AWD/4WD TC | Prune `Camso_driveshaft_rear` | Same as DIRECT RWD | Front axle undriven |
| MAKE_FWD | FWD | AWD/4WD TC | None (no active slots) | `frontDriveShaft` → target's diff device (segmented path) | Rear axle undriven; 1 derived mapping |
| MAKE_AWD | AWD | 4WD TC | Prune both driveshaft slots (on center diff) | Same as DIRECT_AWD | Replaces rangebox+locked diff |
| SYNTH_TC | RWD/FWD | NO_TC | TBD | TBD | **Deferred** |

### Phase 6: Integration & Validation

> **Note:** The original plan had separate Phase 6 (file generation) and Phase 7 (integration). These are merged because `generate_adapted_transfercase()` already exists — Phase 5 refactors it, and the integration work is straightforward.
>
> **Standing directive:** All adaptation operations in Phase 6 must follow the **traceability philosophy** established during Phase 5 rework: derive mappings and transformations from upstream analysis data (Phase 1/3/4 pipeline outputs) rather than hardcoding values. Every adaptation should be traceable back to its data source via provenance records or logged derivation paths.

**6.1 — Refactor `generate_adapted_transfercase()` signature** ✅ COMPLETE

Signature updated with `swap_decision` and `injection_targets` parameters:
```python
def generate_adapted_transfercase(self,
                                  donor_file: Path,
                                  target_vehicle: VehicleInfo,
                                  swap_decision: Optional[Dict] = None,
                                  injection_targets: Optional[Dict] = None) -> Optional[Path]:
```

If `swap_decision` is None, fall back to legacy behavior (backward compatibility). When provided, use the strategy to determine which pruning actions to apply, and the `selected_tc["devices"]` topology to derive device name mappings.

**6.2 — Integrate into generate command pipeline** ✅ COMPLETE

The generate command handler already calls `generate_adapted_transfercase()` in a loop over TC files. The call site passes Phase 3 and Phase 4 results. Phase 5 summary is stored to `self._last_tc_adaptation_summary` and swap decision to `self._last_swap_decision` for manifest consumption:

```python
# Existing: transfer_files = list(donor_dir.glob("**/camso_transfercase*.jbeam"))
for tc_file in transfer_files:
    tc_output = utility.generate_adapted_transfercase(
        tc_file, vehicle,
        swap_decision=swap_decision,        # From Phase 3
        injection_targets=injection_targets  # From Phase 4
    )
```

**Traceability requirement:** The `swap_decision` dict must include the full `selected_tc` entry (with `devices` array from Phase 1 analysis), not just the part name string. The `devices` array is the source-of-truth for `_derive_device_name_mapping()` — without it, device adaptation falls back to no-op and logs a warning.

**6.3 — Slot graph integration** ✅ COMPLETE

`_transform_slots_with_graph()` added to TC primary part processing, after geometry injection and before Phase 5 pruning — matching the engine and transmission pattern. The slot graph has correct mappings:
- ADAPT: `Camso_TransferCase` → `{target}_transfer_case`
- PRESERVE: `Camso_differential_*`, `Camso_driveshaft_*`

The PRESERVE classification for driveshaft slots is still correct — they're preserved (kept as internal ecosystem) when the slot graph processes them, but Phase 5's explicit pruning removes them from the output before slot graph even sees them.

Slot graph dispositions are logged alongside Phase 5's pruning/adaptation summary. Full transformation pipeline visible in generate output.

**6.4 — Information section conventions** ✅ COMPLETE

```
Part name format: {target}_Camso_TransferCase_{DriveType}_{hash}
Info name format: "Camso {AWDSubType} {DriveType} Transfer Case"
```

Examples:
- `pickup_Camso_TransferCase_AWD_ec8ba` → "Camso Helical AWD Transfer Case"
- `pickup_Camso_TransferCase_RWD_79971` → "Camso RWD Transfer Case"
- `pickup_Camso_TransferCase_4WD_036a5` → "Camso 4WD Transfer Case"

**6.5 — Manifest additions (with provenance)** ✅ COMPLETE

Manifest includes `drivetrain` section. The `device_name_mapping` and `device_name_provenance` fields are populated directly from `_derive_device_name_mapping()` output, providing full traceability of every device rename:

```json
{
  "drivetrain": {
    "donor_drive_type": "AWD",
    "donor_awd_subtype": "Helical",
    "swap_strategy": "DIRECT_AWD",
    "adaptation_cost": 0,
    "selected_beamng_tc": "pickup_transfer_case_AWD",
    "slots_pruned": ["Camso_driveshaft_front", "Camso_driveshaft_rear"],
    "device_name_mapping": {"transferCase": "transfercase"},
    "device_name_provenance": [
      {
        "donor_name": "transferCase",
        "target_name": "transfercase",
        "source_part": "Camso_differential_center_ec8ba",
        "target_part": "pickup_transfer_case_AWD",
        "reason": "structural: differential(inputName='gearbox')"
      }
    ],
    "phase4_rear_chain_slots": 15,
    "phase4_front_chain_slots": 6
  }
}
```

**6.6 — Validation checklist** ✅ COMPLETE (45/45 tests: Phase 3 19/19, Phase 4 11/11, Phase 5 15/15)

Before declaring an adaptation successful:
- [ ] Adapted transfercase slotType matches target vehicle's transfer case slot
- [ ] Camso driveshaft child slots are REMOVED (not present in output)
- [ ] Powertrain device names are adapted via derived mapping (not hardcoded) and compatible with BeamNG downstream chain
- [ ] Device name provenance records are present and traceable to Phase 1 analysis data
- [ ] For AWD: both wrapper and center diff parts are present in output; center diff slots pruned
- [ ] For 4WD+DIRECT: `Camso_4wd_controller` slot preserved (coreSlot); 2 device mappings derived
- [ ] For Advanced AWD: `camso_advawd.lua` is included in extra_assets
- [ ] Strategy-specific: MAKE_RWD has no front output; MAKE_FWD device mapped via segmented path
- [ ] Information section reflects accurate drive type labeling
- [ ] No hardcoded device names in the adaptation path — all renames derived from `swap_decision["selected_tc"]["devices"]`

### Implementation Priority / Sequencing

```
Sprint 1: Phase 0 (config/packaging prep) ✅
Sprint 2: Phase 1 + Phase 2 (analysis integration + classification) ✅
Sprint 3: Phase 3 (decision engine) ✅
Sprint 4: Phase 4 (axle/chain slot extraction) ✅
Sprint 5: Phase 5 (strategy-specific pruning + derived device adaptation) ✅
Sprint 6: Phase 6 (integration, manifest, validation) ✅
```

Each sprint should be independently testable:
- Sprint 1: Verify new config options parse correctly, camso_advawd.lua is found ✅
- Sprint 2: Run against pickup, verify catalog extraction and drive type classification matches powertrain reports ✅
- Sprint 3: Run decision engine against all 10 test exports × pickup, verify strategy+cost matches lookup table ✅
- Sprint 4: Verify correct slot references extracted from each BeamNG transfer case type ✅
- Sprint 5: Verify driveshaft slots pruned, device names derived from target TC topology (not hardcoded), provenance records populated; 14/14 tests, 19/19 Phase 3 regression, 11/11 Phase 4 regression ✅
- Sprint 6: Full pipeline test: testcvt→pickup (Helical AWD → pickup AWD = DIRECT_AWD), verify mod package includes adapted TC, manifest includes device_name_mapping + provenance, no hardcoded device names in adaptation path ✅