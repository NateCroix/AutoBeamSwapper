# analyze_powertrains.py — Integration Primer

Concise reference for programmatic invocation and parsing of `analyze_powertrains.py` outputs in the context of engine transplant chain resolution tasks. Target audience: downstream automation modules and documentation agents building broader integration guides.

---

## Invocation Patterns

### As a Subprocess

```python
import subprocess, json
from pathlib import Path

SCRIPT = Path("scripts/analyze_powertrains.py")
PYTHON = Path(".venv/Scripts/python.exe")

def run_targeted(vehicle: str) -> Path:
    """Run targeted analysis, return output directory."""
    subprocess.run([str(PYTHON), str(SCRIPT), "-v", vehicle], check=True)
    return Path(f"docs/DrivetrainReports/targeted_{vehicle}")
```

### As a Module (Recommended for Chain Resolution)

Import and drive the pipeline directly for fine-grained control over extraction, filtering, and chain resolution:

```python
import sys
sys.path.insert(0, "scripts")

from analyze_powertrains import (
    JBeamParser,
    SlotRegistry,
    DrivetrainChainBuilder,
    PowertrainExtractor,
    get_search_folders,
    PowertrainEntry,
    DrivetrainChain,
    DrivetrainComponent,
    PowertrainDevice,
)
```

---

## Core Integration Task: Resolving a Vehicle's Drivetrain Chains

The primary integration scenario is: *given a target vehicle name, resolve its complete powertrain chains from transmission to wheels, then use that chain data to plan adaptation mappings for user-generated (Camso) or third-party engine components.*

### Step-by-Step Chain Resolution

```python
from pathlib import Path
from analyze_powertrains import (
    SlotRegistry, DrivetrainChainBuilder, PowertrainExtractor,
    get_search_folders, _extract_powertrain_devices,
)

base_path = Path("SteamLibrary_content_vehicles")
vehicle = "pickup"

# 1. Resolve search folders (handles cross-folder dependencies)
folders = get_search_folders(base_path, vehicle)

# 2. Build and index the slot registry
registry = SlotRegistry(base_path)
for folder in folders:
    registry.index_folder(folder)

# 3. Extract primary entries (transmission/transfercase/transaxle)
extractor = PowertrainExtractor(base_path)
patterns = ['*transmission*.jbeam', '*transfercase*.jbeam',
            '*tranfercase*.jbeam', '*transaxle*.jbeam']
for folder in folders:
    for pattern in patterns:
        for f in folder.rglob(pattern):
            extractor.process_file(f)

# 4. Filter to reachable components (critical for correctness)
reachable = set()
for st, vehicles in extractor._common_to_vehicles.items():
    if vehicle in vehicles:
        reachable.add(st)

extractor.entries = [
    e for e in extractor.entries
    if not e.is_common or not e.slot_type or e.slot_type in reachable
]

# 5. Resolve drivetrain chains with reachability filter
chain_builder = DrivetrainChainBuilder(registry, allowed_common_slottypes=reachable)
for entry in extractor.entries:
    entry.drivetrain_chain = chain_builder.build_chain(entry)
```

### Accessing Chain Data

```python
for entry in extractor.entries:
    chain = entry.drivetrain_chain
    if not chain:
        continue

    # Chain string: "frictionClutch(clutch) -> manualGearbox(gearbox) -> ..."
    print(entry.part_name, "→", chain.get_chain_string())

    # Downstream components (driveshafts, differentials, halfshafts)
    for comp in chain.components:
        print(f"  {comp.slot_type}: {comp.part_name} ({comp.source_file})")
        for dev in comp.devices:
            print(f"    {dev.type}({dev.name}) ← {dev.inputName}[{dev.inputIndex}]")

    # Split points (multi-output devices, typically differentials)
    # Useful for detecting AWD/4WD architectures
    if chain.split_points:
        print(f"  Splits at: {chain.split_points}")

    # Full BFS-ordered torque path from engine to wheels
    for dev in chain.full_torque_path:
        print(f"  Path: {dev.type}({dev.name})")
```

---

## Data Structures for Downstream Consumption

### PowertrainEntry Fields Relevant to Adaptation

| Field | Use Case |
|-------|----------|
| `slot_type` | The slotType your adapted engine/transmission must match |
| `part_name` | Unique part identifier; use as lookup key |
| `devices` | The powertrain device array — type, connections, properties |
| `drivetrain_chain.components` | What connects downstream of this transmission |
| `drivetrain_chain.split_points` | Where power splits (AWD/4WD detection) |
| `is_common` | Whether this part lives in a shared common/ folder |

### PowertrainDevice Properties

Device properties contain transmission-specific tuning data useful for adaptation compatibility checks:

```python
# Access gear ratios, torque limits, etc.
for device in entry.devices:
    props = device.properties  # Dict[str, Any]
    # Common keys: gearRatios, maxTorque, friction, inertiaMoment, etc.
    if 'gearRatios' in props:
        ratios = props['gearRatios']
```

### Property Lookup (Bulk Access)

```python
# extractor.property_lookup is {part_name: {devices: {dev_name: {props}}}}
props = extractor.property_lookup.get("pickup_transmission_6M", {})
gear_data = props.get("devices", {}).get("gearbox", {})
```

---

## Adaptation Mapping Integration Points

### Determining Target Vehicle Architecture

Before generating an engine transplant, determine the target vehicle's drivetrain architecture:

```python
def classify_architecture(entry: PowertrainEntry) -> str:
    """Classify a transmission entry's drivetrain pattern."""
    chain = entry.drivetrain_chain
    if not chain:
        return "unknown"

    device_types = set()
    device_names = set()
    for dev in chain.full_torque_path:
        device_types.add(dev.type)
        device_names.add(dev.name)

    if "rangeBox" in device_types or "rangebox" in device_names:
        return "4wd_rangebox"
    if "splitShaft" in device_types:
        return "awd_clutch"
    if any("_F" in sp for sp in chain.split_points):
        return "awd_split"
    if "torqueConverter" in device_types:
        return "automatic"
    if "dctGearbox" in device_types:
        return "dct"
    if "electricMotor" in device_types:
        return "electric"
    if "centrifugalClutch" in device_types:
        return "centrifugal"
    return "manual_rwd"
```

### Extracting Required SlotTypes for Adaptation

When adapting a Camso engine for a target vehicle, the transplant utility needs to know which slotType the engine must present:

```python
def get_engine_slot_requirements(base_path: Path, vehicle: str) -> dict:
    """Extract the slot requirements an adapted engine must satisfy."""
    # Run chain resolution (abbreviated — see full pipeline above)
    folders = get_search_folders(base_path, vehicle)
    registry = SlotRegistry(base_path)
    for f in folders:
        registry.index_folder(f)

    # Find engine slot from registry
    engine_slots = [
        st for st in registry.slot_providers
        if 'engine' in st.lower() and vehicle.split('_')[0] in st.lower()
    ]

    # Find transmission slots that the engine must connect to
    trans_slots = [
        st for st in registry.slot_providers
        if 'transmission' in st.lower() and vehicle.split('_')[0] in st.lower()
    ]

    return {
        "engine_slottypes": engine_slots,
        "transmission_slottypes": trans_slots,
        "all_indexed_slottypes": list(registry.slot_providers.keys()),
    }
```

### Cross-Referencing Chain Components with Mod Parts

For third-party mod vehicles or Camso engine adaptations, validate that downstream drivetrain components exist:

```python
def validate_chain_compatibility(chain: DrivetrainChain, mod_registry: SlotRegistry) -> list:
    """Check which chain components a mod vehicle already provides."""
    missing = []
    for comp in chain.components:
        providers = mod_registry.slot_providers.get(comp.slot_type, [])
        if not providers:
            missing.append({
                "slot_type": comp.slot_type,
                "expected_part": comp.part_name,
                "role": "drivetrain_component",
            })
    return missing
```

---

## Output File Parsing

### Loading JSON Report

```python
import json
from pathlib import Path

def load_report(vehicle: str) -> dict:
    path = Path(f"docs/DrivetrainReports/targeted_{vehicle}/powertrain_report.json")
    with open(path) as f:
        return json.load(f)

report = load_report("pickup")

# Iterate entries
for entry in report["entries_by_vehicle"]["pickup"]:
    print(entry["part_name"], entry["slot_type"])

    # Chain components
    chain = entry.get("drivetrain_chain", {})
    for comp in chain.get("components", []):
        print(f"  → {comp['slot_type']}: {comp['part_name']}")
```

### Loading Properties

```python
def load_properties(vehicle: str) -> dict:
    path = Path(f"docs/DrivetrainReports/targeted_{vehicle}/powertrain_properties.json")
    with open(path) as f:
        return json.load(f)

props = load_properties("pickup")
# props["pickup_transmission_6M"]["devices"]["gearbox"] → {gearRatios, ...}
```

---

## Constraints & Assumptions

1. **`SteamLibrary_content_vehicles/`** must be populated with extracted BeamNG base game vehicle files. This is a dev-environment path; production usage should parameterize it.

2. **JBeam ≠ JSON.** All `.jbeam` parsing must go through `JBeamParser.parse_jbeam()`. Do not use `json.loads()` on raw `.jbeam` content.

3. **Reachability filtering is mandatory** in targeted mode. Without it, vehicles sharing common/ prefixes inherit unrelated components (e.g., pigeon would inherit pickup_transmission, pickup_transfer_case).

4. **`allowed_common_slottypes`** must be passed to `DrivetrainChainBuilder` in targeted mode. Omitting it allows the device-name linking stage to pull unreachable common parts into chains via shared device names (e.g., `"gearbox"` output matched by both pigeon_driveshaft and pickup_transfer_case).

5. **Chain resolution is per-entry.** Each transmission/transfercase entry gets its own chain. The same downstream components (driveshafts, differentials) will appear in multiple chains when multiple transmission variants exist for one vehicle.

6. **Third-party mod vehicles** will require their `.jbeam` files to be placed in the search path or a custom `SlotRegistry` to be built for their asset tree. The existing `get_search_folders()` logic only handles base game directory conventions.

---

## Extension Points for Mod Vehicle Support

The current architecture indexes base game vehicles from `SteamLibrary_content_vehicles/`. To support arbitrary mod vehicles:

1. **Custom search folders.** Bypass `get_search_folders()` and supply folder paths directly to `SlotRegistry.index_folder()`.

2. **Custom SlotRegistry.** Build a registry from the mod's `vehicles/<mod_vehicle>/` tree. The registry's `slot_providers`, `part_child_slots`, and `powertrain_parts` dicts can then be queried for slot compatibility analysis.

3. **Chain builder reuse.** `DrivetrainChainBuilder` is registry-agnostic — it works with any `SlotRegistry` instance. Pass a mod-specific registry and the chain resolution logic applies identically.

4. **Skip common-to-vehicles mapping.** Mod vehicles won't have `_common_to_vehicles` data. Set `allowed_common_slottypes=None` (full-mode behavior) or build a custom reachability set if the mod uses shared component folders.

```python
# Example: Index a third-party mod vehicle
mod_path = Path("mods/unpacked/MyMod/vehicles/my_car")
mod_registry = SlotRegistry(mod_path.parent.parent)
mod_registry.index_folder(mod_path)

# Build chains for any powertrain parts found
builder = DrivetrainChainBuilder(mod_registry)
for part_name, part_data in mod_registry.powertrain_parts.items():
    # Create a minimal entry and resolve its chain
    devices = _extract_powertrain_devices(part_data.get("powertrain", []))
    entry = PowertrainEntry(
        vehicle="my_car", filename="", filepath="", is_common=False,
        part_name=part_name,
        slot_type=part_data.get("slotType", ""),
        info_name="", info_value="", info_authors="",
        parent_slot_name="", devices=devices, slots=[],
    )
    entry.drivetrain_chain = builder.build_chain(entry)
```

---

## BeamNG Powertrain Structures & Conventions — Knowledge Reference

This section captures accumulated knowledge about how BeamNG.drive structures its powertrain `.jbeam` data across the base game vehicle library. It is written as a heuristic guide — not a formal specification — distilled from exhaustive analysis of every base-game vehicle's drivetrain files. Use it to predict file layout for untested vehicles, diagnose chain-resolution failures, and inform decisions when building engine-swap adapters.

### Why This Section Exists

The `analyze_powertrains.py` pipeline was developed iteratively through trial-and-error against real game data. Along the way, many assumptions about file layout, device naming, and slot wiring proved wrong or incomplete. This section records the corrected understanding so that:

- Future agents or developers don't repeat the same discovery cycle.
- Users troubleshooting a failed chain resolution can narrow the problem quickly.
- Predictions about newly released vehicles can be made with reasonable confidence.

---

### BeamNG Universal Device Naming Conventions

BeamNG uses **consistent device names** across virtually all base-game vehicles. Knowing these names is essential for chain resolution because device-name linking (`DrivetrainChainBuilder._device_name_linking()`) wires components together by matching an upstream device's output name to a downstream device's `inputName`.

| Canonical Name | Device Type(s) | Role |
|---|---|---|
| `clutch` | `frictionClutch` | Connects engine flywheel to gearbox. Sometimes declared in a separate flywheel part rather than the transmission file itself. |
| `torqueConverter` | `torqueConverter` | Replaces `clutch` in automatic transmissions. |
| `gearbox` | `manualGearbox`, `automaticGearbox`, `dctGearbox`, `sequentialGearbox`, `cvtGearbox` | Transmission internals. Always named `gearbox` regardless of type. |
| `transfercase` | `shaft`, `splitShaft`, `differential` | Routes torque to one or both axles. The device *type* varies by AWD/FWD/RWD strategy, but the *name* is always `transfercase`. |
| `transfercase_F` | `shaft` | Front-axle output shaft in 4WD systems (often disconnectable). |
| `driveshaft` | `shaft` | Longitudinal propeller shaft in RWD/AWD layouts. |
| `differential_F` | `differential` | Front axle differential. |
| `differential_R` | `differential` | Rear axle differential. |
| `torsionReactorF` | `torsionReactor` | Front-axle torque reaction device. |
| `torsionReactorR` | `torsionReactor` | Rear-axle torque reaction device. |
| `wheelaxleFL/FR/RL/RR` | `shaft` | Half-shaft stubs connecting differential to wheel hubs. |
| `rearMotor` / `frontMotor` | `electricMotor` | Independent electric drive motors (root devices with `inputName:"dummy"`). |

**Key insight:** Because device *names* are universal, the classifier and chain builder can rely on name substrings (`_F`, `_R`, `transfercase`) for positional inference. The device *type* tells you what the component does mechanically; the *name* tells you where it sits in the vehicle.

---

### The Transfer Case — Most Overloaded Concept

The name `transfercase` is used for three mechanically distinct arrangements, distinguished only by device *type*:

| Scenario | Device Type | Key Properties | Vehicles |
|---|---|---|---|
| **FWD-only** | `shaft` | `outputPortOverride:[2]` — locks output to port 2 (front axle only) | Covet, Pessima (FWD), Vivace (FWD) |
| **RWD-only** | `shaft` | No override — default output goes to port 1 (rear) | Pessima (RWD variant) |
| **AWD viscous/clutch** | `splitShaft` | `splitType:"viscous"`, `primaryOutputID:2` — splits torque between two outputs | Pessima AWD, Vivace AWD |
| **AWD center diff** | `differential` | `diffType:"lsd"` or `"locked"` — acts as center differential | SBR AWD, Pessima Race AWD |
| **4WD rangebox** | Separate `rangeBox` device feeds the `differential` named `transfercase` | `differential` with `diffType:"locked"` downstream of `rangeBox` | Pickup, D-Series |

**Practical implication:** When the chain builder encounters a device named `transfercase`, it cannot assume the layout is 4WD; it must check the device type and properties to determine the torque-routing strategy.

---

### The TorsionReactor — Silent Chain Link

`torsionReactor` devices do not transmit torque mechanically. They provide **chassis reaction torque** (the force that makes the vehicle body twist when the engine delivers power). Every `torsionReactor` references `torqueReactionNodes` — physical nodes on the chassis/subframe.

Despite having no mechanical effect on power flow, torsionReactors are **mandatory chain links** because they appear in `powertrain` arrays between real devices. Ignoring them breaks chain resolution.

**Position patterns:**
- In **RWD** vehicles, `torsionReactorR` sits between `gearbox` output and `driveshaft` input.
- In **FWD** vehicles, `torsionReactorF` sits between `transfercase` output and `differential_F` input.
- In **AWD** vehicles, both `torsionReactorF` and `torsionReactorR` appear on their respective axle paths.
- In **mid-engine RWD** (Bolide), the torsionReactor may be **absent entirely** — the gearbox connects directly to `differential_R`.

**Where torsionReactors live in files:** They are typically declared in the differential or driveshaft file, **not** in the transmission file. This means a chain starting at the transmission entry won't "see" the torsionReactor until the chain builder resolves the downstream differential/driveshaft slot.

---

### File Separation Conventions

BeamNG follows a consistent pattern for splitting powertrain components across files:

| Component | Typical File | Shares File With |
|---|---|---|
| Transmission (clutch + gearbox) | `{vehicle}_transmission.jbeam` or `{vehicle}_transaxle.jbeam` | Transfer case definition (in most vehicles) |
| Transfer case | Same file as transmission (usually) | Exception: Vivace puts it in a separate `{vehicle}_transfercase.jbeam` |
| Front differential | `{vehicle}_differential_F.jbeam` | Front torsionReactor, front halfshafts |
| Rear differential | `{vehicle}_differential_R.jbeam` | Rear torsionReactor, rear driveshaft, rear halfshafts |
| Driveshaft | Inside `{vehicle}_differential_R.jbeam` (usually) | Exception: Moonhawk has driveshaft as a sub-slot of differential_R |
| Electric motor(s) | `{vehicle}_electric_motor.jbeam` | Motor-specific differentials, reduction gears |

**Why this matters for chain resolution:** The chain builder must cross file boundaries to build complete chains. It does this by:
1. Finding the entry's declared `slots` → looking up which parts *provide* those slotTypes in the `SlotRegistry`.
2. Following device-name input references across those part boundaries.

If the `SlotRegistry` hasn't indexed the file containing downstream parts, the chain will terminate early.

---

### Slot Naming & Slot Hierarchy Patterns

Engine and drivetrain slot names follow predictable patterns that encode the target vehicle and component role:

| Pattern | Meaning | Examples |
|---|---|---|
| `{vehicle}_engine` | Direct engine slot for vehicle-specific engines | `moonhawk_engine`, `bolide_engine` |
| `{family}_engine` | Engine slot shared across a vehicle family | `pickup_engine` (shared by pickup + D-Series) |
| `{vehicle}_transmission` | Transmission slot | `covet_transmission`, `pessima_transmission` |
| `{vehicle}_transaxle` | Transaxle slot (FWD or mid-engine) | `sbr_transaxle`, `vivace_transaxle` |
| `{vehicle}_transfercase` | Transfer case slot | `vivace_transfercase`, `pessima_transfercase` |
| `{vehicle}_differential_F` | Front differential slot | `covet_differential_F` |
| `{vehicle}_differential_R` | Rear differential slot | `moonhawk_differential_R` |
| `{vehicle}_flywheel` | Flywheel slot (sometimes carries clutch definition) | `vivace_flywheel` |

**Slot hierarchy depth:** The typical chain is 3–5 levels deep:
```
engine_slot → transmission_slot → [transfercase_slot →] differential_slot → [driveshaft_slot]
```

**Cross-vehicle slot sharing:** Some vehicles share drivetrain components via the `vehicles/common/` folder system. The `pickup` and `van` families are the most prominent examples — they share engines, transmissions, and differentials via `vehicles/common/pickup/`. The `_build_common_to_vehicles_map()` function resolves which common-folder files belong to which vehicles by tracing slot chains from vehicle root `.pc` files.

---

### Drive Layout Identification Heuristics

When classifying a vehicle's drive layout from its powertrain data, these rules reliably distinguish the major patterns:

1. **If a device named `transfercase` exists AND a `rangeBox` device exists** → **4WD with rangebox** (traditional truck/SUV 4WD).

2. **If a device named `transfercase` exists AND is type `splitShaft`** → **AWD clutch-based** (viscous or electronically controlled center coupling).

3. **If a device named `transfercase` exists AND is type `differential`** → **AWD center differential** (permanent AWD with open/LSD center diff).

4. **If a device named `transfercase` exists AND is type `shaft` with `outputPortOverride:[2]`** → **FWD transaxle** (front-wheel drive, rear axle disconnected).

5. **If no `transfercase` device exists AND `differential_R` is present** → **Simple RWD** (rear-wheel drive, no transfer case).

6. **If no `transfercase` device exists AND `differential_F` is present but not `differential_R`** → **FWD direct-drive** (rare in base game).

7. **If `electricMotor` devices with `inputName:"dummy"` exist** → **Electric** drive (motors are root devices, no upstream engine).

**Critical caveat for chain resolution:** The chain resolver *always* finds differentials downstream (that's its job). So checking `'differential' in device_types` will be True for every fully-resolved chain, making it useless for FWD-vs-RWD classification. Instead, check differential device **names**: if the chain contains `differential_F` but not `differential_R`, it's FWD; if it contains `differential_R`, it's RWD or AWD.

---

### Common Chain-Resolution Failure Modes

When `DrivetrainChainBuilder.build_chain()` returns an incomplete or unexpected chain, check these causes in order:

#### 1. SlotRegistry didn't index the right folders

**Symptom:** Chain terminates at the transmission — no differential or driveshaft resolved.

**Cause:** The downstream differential file lives in a folder that wasn't passed to `SlotRegistry.index_folder()`. Common culprits:
- `vehicles/common/{family}/` folders not indexed for a vehicle that uses shared components.
- A mod vehicle's support files in a separate directory.

**Fix:** Ensure all folders containing potential slot providers are indexed. In targeted mode, `get_search_folders()` handles this for base game vehicles, but mod vehicles need manual folder registration.

#### 2. SlotType mismatch

**Symptom:** Chain terminates at a slot boundary — the registry finds no provider for a required slotType.

**Cause:** The slotType declared in the part's `slots` array doesn't match any part's `slotType` field. This happens when:
- A vehicle uses a unique prefix that doesn't match common-folder parts (e.g., `etki_differential_R` vs `etk_differential_R`).
- A mod renames slotTypes without renaming the corresponding part files.

**Fix:** Inspect the part's `slots` array and search the registry's `slot_providers` dict for the expected slotType. Correct the slotType or add a wrapper part.

#### 3. Device-name linking failure

**Symptom:** Chain has all the right components but devices aren't connected — `full_torque_path` is empty or fragmented.

**Cause:** `_device_name_linking()` matches devices by `inputName` ↔ upstream device `name`. If a downstream part references a device name that doesn't exist in any upstream part, the link fails silently.

**Common triggers:**
- The clutch device (`clutch`) is provided by a flywheel part that wasn't resolved because the flywheel slot wasn't in the reachable set.
- A torsionReactor references `gearbox` output but the gearbox device was named something non-standard.

**Fix:** Dump `entry.devices` and each `component.devices` to inspect the exact `name` and `inputName` values. Look for spelling mismatches or missing intermediary parts.

#### 4. engine_props contamination

**Symptom:** Ghost entries appear for a non-existent "vehicle" named `engine_props`.

**Cause:** The `SteamLibrary_content_vehicles/common/engine_props/` folder contains shared engine property files. If globbing patterns aren't filtered, this folder is treated as a vehicle.

**Fix:** Already handled in `analyze_powertrains.py` with explicit `engine_props` exclusion at 5 points. If you encounter this, verify the exclusion guards are in place.

#### 5. Cross-vehicle prefix contamination

**Symptom:** A targeted vehicle's output includes parts from unrelated vehicles (e.g., pigeon analysis shows pickup transmission components).

**Cause:** In common-folder architectures, multiple vehicle families share the same `vehicles/common/` subtree. Without proper filtering, the chain builder follows *all* slot providers in the registry, including ones that belong to other vehicles.

**Fix:** Use `allowed_common_slottypes` filtering. The `run_targeted()` function computes a `reachable_slottypes` set by BFS-walking the target vehicle's slot tree, then passes this to `DrivetrainChainBuilder` so it only follows slots that the target vehicle can actually reach.

---

### Lessons Learned During Development

These are the most impactful discoveries made while building and refining the analysis pipeline:

1. **Prefix-based filtering doesn't work.** Early attempts to filter common-folder components by vehicle-name prefix (e.g., "if filename starts with `pickup_`, it belongs to pickup") failed because naming conventions aren't consistent. The `van` family uses `pickup_` prefixed files; `etk800` uses `etk_` prefixed files shared with `etkc`. Only slot-chain BFS — tracing which slotTypes a vehicle's root `.pc` file can reach — produces correct vehicle-to-component mappings.

2. **`property_lookup` is a contamination vector.** The `DrivetrainChainBuilder` maintains a `property_lookup` dict for resolving transmission properties (gear ratios, etc.) from shared component files. In targeted mode, this dict must be filtered against `reachable_slottypes`, or it will pull properties from other vehicles' files and inject them into the wrong chains.

3. **Common-to-vehicles mapping requires two-phase resolution.** Phase 1 walks each vehicle's slot tree to find direct references to common-folder slotTypes. Phase 2 extends this by BFS-walking the *common-folder parts' own slots* to discover transitive dependencies (e.g., a common transmission's slot for a common differential). Both phases are needed; Phase 1 alone misses transitive common-on-common references.

4. **The "simple_traffic" vehicle pollutes full-mode output.** `simple_traffic` is a simplified physics placeholder, not a real vehicle. Its presence doubles entry counts for vehicles like Vivace and Scintilla. The `-o` flag filters it out, but it's excluded by default in non-`-o` runs. Running with the flag `-o simple_traffic` exclusively analyzes these simple_traffic assets, ignoring primary vehicles.

5. **`engine_props` is not a vehicle.** The `common/engine_props/` folder contains shared engine visual prop templates. It must be excluded at every stage: file globbing, vehicle iteration, process/resolve guards. Missing any one exclusion point re-introduces the contamination.

6. **JBeam is not JSON.** JBeam files support C-style comments, optional commas, and leading zeros. Naive `json.loads()` calls will fail on the majority of game files. Always use the project's `JBeamParser` which handles URL-safe comment stripping, 17 comma-insertion regex patterns, and trailing comma removal.

---

### Predicting Structures of New / Untested Vehicles

Based on the patterns observed across the entire base game library, new BeamNG vehicles are highly likely to follow these conventions:

**If the vehicle is a sedan/hatchback/coupe:**
- FWD layout with `shaft` transfercase (`outputPortOverride:[2]`), or AWD with `splitShaft` transfercase.
- Files: `{vehicle}_transaxle.jbeam`, `{vehicle}_differential_F.jbeam`, optional `{vehicle}_differential_R.jbeam` for AWD variants.
- Device names: standard (`clutch`, `gearbox`, `transfercase`, `differential_F`).

**If the vehicle is a truck/SUV:**
- RWD or 4WD layout. 4WD uses `rangeBox` → `differential` (named `transfercase`) → two output paths.
- Likely uses `vehicles/common/{family}/` folder for shared components.
- Files: `{family}_transmission.jbeam` in common folder, `{vehicle}_differential_R.jbeam` in vehicle folder.

**If the vehicle is a sports car:**
- RWD (front-engine) or MR (mid-engine rear-drive). Mid-engine cars use `{vehicle}_transaxle.jbeam` with no transfercase — gearbox outputs directly to `differential_R`.
- AWD sports variants use `differential`-type transfercase (center diff, not viscous coupling).

**If the vehicle is electric:**
- Independent `electricMotor` devices per axle (`rearMotor`, `frontMotor`), each with `inputName:"dummy"`.
- No clutch, no gearbox in the traditional sense — may have a single-speed reduction gear.
- All electric drivetrain components often in a single `{vehicle}_electric_motor.jbeam` file.

**If the vehicle uses DCT:**
- `dctGearbox` device. No separate clutch device (DCT has internal clutches).
- `gearbox` inputs directly from `mainEngine`, not from `clutch`.
- Otherwise follows the same downstream pattern as manual transmissions.

**File organization prediction:** New vehicles increasingly use the `slots2` format (with `allowTypes`/`denyTypes` arrays) rather than the older `slots` format (with simple `type`/`default` pairs). The analysis pipeline handles both transparently.

---

### Quick Diagnostic Checklist

When an analysis run produces unexpected results, work through this checklist:

| Check | How | Expected |
|---|---|---|
| Are all vehicle folders indexed? | Verify `get_search_folders()` output includes common folders | Should list vehicle folder + all common/{family} folders |
| Is the target vehicle in `_common_to_vehicles` map? | Print `_common_to_vehicles` for common-folder files | Target vehicle should appear for its family's common files |
| Are reachable slotTypes correct? | Print `reachable_slottypes` set in `run_targeted()` | Should include transmission, differential, driveshaft slotTypes |
| Is `engine_props` excluded? | Check `process_file()` early return | Should skip files in `engine_props/` |
| Is `simple_traffic` filtered? | Check `-o` flag or default exclusion | Should not appear unless raw output requested |
| Are chains complete? | Check `drivetrain_chain.full_torque_path` | Should show `mainEngine → ... → wheelaxle` |
| Are device names standard? | Print `entry.devices[*].name` | Should match canonical names table above |
| Is property_lookup filtered? | Check `allowed_common_slottypes` was passed | Should only contain slotTypes reachable from target vehicle |
