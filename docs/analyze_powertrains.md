# analyze_powertrains.py — Reference Documentation

Script for extracting, analyzing, and resolving complete powertrain and drivetrain chains from BeamNG base game vehicle assets.

**Location:** `scripts/analyze_powertrains.py`
**Python:** 3.12+ (project venv: `.venv/Scripts/python.exe`)
**Parser:** Embedded `JBeamParser` (98.6% success on 5,207 `.jbeam` files)

---

## Usage

### Full Mode — All Vehicles

```powershell
python scripts/analyze_powertrains.py
```

Scans the entire `SteamLibrary_content_vehicles/` tree. Produces reports covering every vehicle with transmission, transfer case, or transaxle files, plus a supplemental scan of all files containing `powertrain` arrays.

### Targeted Mode — Single Vehicle

```powershell
python scripts/analyze_powertrains.py -v pigeon
python scripts/analyze_powertrains.py -v etk800
python scripts/analyze_powertrains.py -v pickup
```

Analyzes one vehicle in isolation. Automatically resolves cross-folder dependencies (common/ folders, shared component families) and filters results to only include components reachable from that vehicle's slot chain. Outputs go to `docs/DrivetrainReports/targeted_<vehicle>/`.

### Options

| Flag | Effect |
|------|--------|
| `-v <name>` / `--vehicle <name>` | Targeted single-vehicle mode |
| `-o simple_traffic` | Include `simple_traffic/` vehicle variants (excluded by default) |

**Examples:**

```powershell
# Full mode, exclude simple_traffic (default)
python scripts/analyze_powertrains.py

# Full mode, include simple_traffic
python scripts/analyze_powertrains.py -o simple_traffic

# Targeted mode with simple_traffic included
python scripts/analyze_powertrains.py -v pickup -o simple_traffic
```

---

## Output Files

All outputs are written to `docs/DrivetrainReports/` (full mode) or `docs/DrivetrainReports/targeted_<vehicle>/` (targeted mode).

### `powertrain_report.json`

Primary structured output. Contains:

```
metadata
├── total_entries, total_vehicles, file_types breakdown
└── chain_resolution {entries_with_full_chain, entries_without_chain, total_resolved_components}
entries_by_vehicle
├── <vehicle_name>
│   └── [array of entry objects]
all_entries          (flat list of all entry objects)
property_lookup      (device property dicts, keyed by part_name)
```

Each **entry object** represents one part with a `powertrain` array in a transmission/transfercase/transaxle file:

| Field | Type | Description |
|-------|------|-------------|
| `vehicle` | string | Owning vehicle name |
| `filename` | string | Source `.jbeam` filename |
| `filepath` | string | Relative path from base |
| `is_common` | bool | `true` if from `common/` folder |
| `part_name` | string | JBeam part name (e.g. `pickup_transmission_6M`) |
| `slot_type` | string | SlotType this part fills |
| `info_name` | string | Human-readable name from `information.name` |
| `info_value` | any | Value from `information.value` |
| `info_authors` | string | Author attribution |
| `powertrain_summary` | array | `[type, name, inputName, inputIndex]` per device |
| `powertrain_full` | array | Same, with properties included |
| `slots` | array | Child slot definitions `[type, default, description, {options}]` |
| `drivetrain_chain` | object | Resolved downstream chain (see below) |

**`drivetrain_chain` object:**

| Field | Type | Description |
|-------|------|-------------|
| `components` | array | Downstream parts resolved via slot-chain + device-name linking |
| `full_torque_path` | array | BFS-ordered devices from engine to wheels |
| `full_chain_string` | string | Human-readable `type(name) -> type(name)` chain |
| `split_points` | array | Device names with multiple downstream consumers (e.g. differentials) |

Each **component** has: `slot_type`, `part_name`, `source_file`, `devices[]`.

### `powertrain_properties.json`

Flat dictionary keyed by `part_name`. Each value contains `filename`, `filepath`, `vehicle`, and `devices` — the device properties (gear ratios, torque limits, etc.) for quick programmatic lookup without traversing the full report.

### `powertrain_table.csv`

Flat CSV with one row per entry. Columns: vehicle, filename, filepath, is_common, part_name, slot_type, info_name, info_value, powertrain_summary, device_count, has_chain, chain_components.

### `powertrain_report.md`

Human-readable markdown. Groups entries by vehicle with column-aligned Component Map tables showing device type, name, input source, and index. Includes chain resolution summaries and parse failure diagnostics.

### `architecture_diagrams.md`

Mermaid flow diagrams for common drivetrain architecture patterns detected across (or within) vehicles:

- Standard Manual RWD
- Standard Automatic RWD
- FWD Transaxle
- 4WD with Transfer Case / Rangebox
- AWD Clutch-based (splitShaft)
- Electric Motor

Includes a summary table of pattern distribution and per-vehicle chain strings.

### `non_transfercase_chains.md`

Focuses on vehicles without transfer cases (simple RWD, FWD, EVs, micro-vehicles). Traces power flow from `mainEngine` through gearbox to wheels, identifies contributing files, and classifies architecture patterns.

---

## Script Architecture

### Execution Phases

#### Full Mode

```
Phase 1: Primary Extraction
    PowertrainExtractor.run_primary()
    → Scans *transmission*, *transfercase*, *transaxle* files
    → Expands common parts to owning vehicles via slot-chain BFS
    → Populates entries[] and property_lookup{}

Phase 2: Drivetrain Chain Resolution
    resolve_drivetrain_chains()
    → Per-vehicle: builds SlotRegistry, creates DrivetrainChainBuilder
    → For each entry: build_chain() → attach DrivetrainChain

Phase 3: Full Powertrain Chain Analysis
    PowertrainExtractor.run_full_scan()
    → Scans ALL .jbeam files containing "powertrain" arrays
    → Returns supplemental entries (non-primary parts with powertrain devices)

Report Generation
    → JSON, CSV, Markdown, Architecture Diagrams, Chain Analysis
```

#### Targeted Mode

```
run_targeted(vehicle_name):
    1. get_search_folders()        → resolve cross-folder dependencies
    2. SlotRegistry.index_folder() → index all parts from search folders
    3. PowertrainExtractor.process_file() → extract primary entries
    4. Filter entries by reachable_slottypes (slot-chain BFS)
    5. Filter property_lookup by reachable_slottypes
    6. DrivetrainChainBuilder.build_chain() with allowed_common_slottypes filter
    7. Build supplemental entries from registry (filtered)
    8. Generate reports
```

### Class Hierarchy

```
JBeamParser (static)
│   parse_jbeam(path) → dict
│   strip_comments(str) → str
│   add_missing_commas(str) → str
│
├── SlotRegistry
│       index_folder(path)
│       resolve_default_part(slot_type, name) → (part_name, data, file)
│       get_child_slots(part_name) → [(slot_type, default)]
│       .slot_providers    {slot_type → [(name, data, path)]}
│       .part_child_slots  {part_name → [(slot_type, default)]}
│       .powertrain_parts  {part_name → data}  (parts with powertrain arrays)
│
├── PowertrainExtractor
│       run_primary()           → populates self.entries
│       run_full_scan()         → returns supplemental entries
│       process_file(path)      → parse + classify + expand to vehicles
│       ._common_to_vehicles    {slot_type → [vehicle_names]}
│       .property_lookup        {part_name → {devices, filepath, vehicle}}
│
├── DrivetrainChainBuilder
│       build_chain(entry)      → DrivetrainChain
│       _resolve_child_slots()  → follow slot graph recursively
│       _device_name_linking()  → match device inputName across registry
│       _build_ordered_path()   → BFS torque path from mainEngine
│       _find_split_points()    → detect multi-consumer devices
│       ._allowed_common_slottypes  (Optional[Set[str]], targeted-mode filter)
│
└── Data Classes
        PowertrainDevice      (type, name, inputName, inputIndex, properties)
        DrivetrainComponent   (slot_type, part_name, source_file, devices)
        DrivetrainChain       (components, full_torque_path, split_points)
        PowertrainEntry       (vehicle, filename, part_name, slot_type, devices, drivetrain_chain, ...)
```

### Key Algorithms

#### Cross-Folder Resolution (`get_search_folders`)

BeamNG vehicles reference components across folder boundaries. Example: `etk800` uses engines from `common/etk/`, `pigeon` uses differentials from `common/pickup/`.

Resolution strategy:
1. Start with the vehicle's own folder (`<vehicle>/vehicles/<vehicle>/`)
2. Check for matching common subfolder (`common/vehicles/common/<vehicle>/`)
3. Scan vehicle's `.jbeam` files for references to other vehicle prefixes
4. Add those prefixes' vehicle folders, common subfolders, and engine subfolders
5. Always include `common/vehicles/common/cargo/` (shared utility parts)

#### Common-to-Vehicle Mapping (`_build_common_to_vehicles_map`)

Maps each powertrain slotType in common/ folders to the vehicles that actually use it. Prevents false attribution (e.g., pigeon does NOT use `pickup_engine` even though both share `common/pickup/`).

Three-phase slot-chain BFS:

1. **Phase 1 — Parse common subfolders:** Collect all powertrain slotTypes, ALL slotTypes, and build a directed parent→child slot graph from `slots`/`slots2` arrays.

2. **Phase 2 — Find entry points:** Text-search each vehicle's `.jbeam` files for common slotType strings to discover which common components each vehicle directly references.

3. **Phase 3 — BFS reachability:** From each vehicle's entry points, BFS through the slot graph collecting only transitively reachable powertrain slotTypes. A vehicle that references `pickup_differential_R` does NOT automatically inherit `pickup_engine` or `pickup_transmission` — only downstream components reachable through the slot chain.

#### Drivetrain Chain Building (`DrivetrainChainBuilder.build_chain`)

Hybrid slot-chain + device-name linking algorithm:

1. **Seed:** Collect all powertrain devices from the transmission entry itself.
2. **Slot-chain walk:** Recursively follow child slots from the transmission part. For each child slot with a drivetrain keyword (`driveshaft`, `differential`, `halfshaft`, `transfer_case`, `axle`, `transaxle`, `finaldrive`), resolve the default part and collect its devices.
3. **Device-name linking fallback:** Iterate all powertrain parts in the registry. A candidate part is linked if any of its devices take `inputName` from a known device in the chain, AND the candidate does not redefine existing device names (preventing variant conflicts).
4. **Ordered path:** BFS from `mainEngine` input through the collected devices produces the full torque path.
5. **Split detection:** Devices with multiple downstream consumers are marked as split points (differentials, transfer cases).

**Targeted-mode filtering:** When `allowed_common_slottypes` is set, both `_resolve_child_slots()` and `_device_name_linking()` skip common-folder parts whose slotType is not in the allowed set. This prevents chain contamination from unreachable common parts (e.g., pigeon's chain won't include `pickup_transfer_case` parts even though they exist in the indexed common/pickup folder).

#### Entry Filtering (Targeted Mode)

After primary extraction in `run_targeted()`:

1. Build `reachable_slottypes` set from `_common_to_vehicles` mapping for the target vehicle.
2. Filter `extractor.entries` — drop common entries whose slotType is not reachable.
3. Filter `extractor.property_lookup` — drop common property entries with unreachable slotTypes.
4. Pass `reachable_slottypes` as `allowed_common_slottypes` to `DrivetrainChainBuilder`.
5. Filter supplemental entries from registry — same reachability check.

---

## BeamNG Vehicle Engine Architectures

The script handles three distinct patterns found across BeamNG's base game:

### 1. Direct Vehicle-Specific

- **SlotType:** `{vehicle}_engine` (e.g., `moonhawk_engine`)
- **Files:** In the vehicle's own folder
- **Example:** moonhawk, legran, bolide
- **Complexity:** Low — no cross-folder resolution needed

### 2. Common Folder

- **SlotType:** `{family}_engine` (e.g., `pickup_engine`)
- **Files:** In `common/vehicles/common/{family}/`
- **Example:** pickup, van, roamer (share `pickup_*` components)
- **Complexity:** Medium — requires cross-folder prefix detection

### 3. Submodel .pc Architecture

- **SlotType:** `{namespace}_engine` (e.g., `etk_engine`)
- **Files:** In `common/vehicles/common/{namespace}/` with `.pc` submodel configs
- **Example:** etk800, etki, etkc (share `etk_*` components)
- **Complexity:** High — namespace ≠ vehicle name, requires `.pc` config awareness

---

## Conventions & Edge Cases

### Duplicate Entries

In full mode, a common-folder part like `pickup_transmission_6M` appears once per owning vehicle (pickup, roamer, van, etc.). Each copy has `vehicle` set to the respective owner and `is_common: true`. In targeted mode, only the target vehicle's copy appears.

### File Type Classification

The `file_types` metadata field counts entries by source file keyword:

| Pattern in filename | Label |
|---------------------|-------|
| `transmission` | `transmission` |
| `transfercase` / `tranfercase` | `transfercase` |
| `transaxle` | `transaxle` |
| None of the above | Numeric filename pattern (e.g., `1300`) |

### simple_traffic Filtering

Files under `simple_traffic/` directories are excluded by default. These are simplified AI-traffic vehicle definitions that duplicate powertrain configurations at lower fidelity. Use `-o simple_traffic` to include them.

### SlotRegistry Scope

In full mode, each vehicle gets its own `SlotRegistry` scoped to its search folders during chain resolution. In targeted mode, a single registry covers all search folders for the target vehicle. The registry indexes **all** parts it encounters — the `allowed_common_slottypes` filter on the chain builder prevents unreachable parts from contaminating chain results.

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Vehicle not found | Name mismatch | Check `SteamLibrary_content_vehicles/` for exact folder name |
| 0 entries | No transmission/transfercase files in search path | Verify vehicle has powertrain files; check logs for search folders |
| False common entries in targeted mode | Slot-chain BFS entry points missing | Verify vehicle's `.jbeam` files reference the expected common slotTypes |
| Chain includes wrong vehicle's parts | `allowed_common_slottypes` not propagated | Ensure `DrivetrainChainBuilder` receives the filter set |
| Parse failures | JBeam authoring issues | Check `parse_failures` in markdown report; 1.4% failure rate is expected |

### Debug Logging

Set `logging.DEBUG` level to see:
- Filtered unreachable common entries (count per run)
- Filtered unreachable property_lookup entries
- Cross-vehicle prefix detection results
- Slot-chain BFS traversal details
