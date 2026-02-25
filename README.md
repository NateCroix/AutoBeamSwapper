# AutoBeamSwapper Camso -> BeamNG Engine Transplant Utility (Alpha)

This project is a Python-based utility for adapting Automation/Camso engine content to BeamNG original (or mod) vehicles.

It is currently in alpha: core workflows run and it might produce working swaps, coverage is still expanding as more combinations are tested. 

Development documentation for each module is included for those who would like to expand on this work, forgive the disorginization (see DEV-README.md)

## Credits to 

BeamNG modding community

bhowiebkr Jbeam to Json parser https://github.com/bhowiebkr

FakeCarGuy Cummins engine mod https://www.beamng.com/resources/authors/fakecarguy.370181/


## What this project does

At a high level, the utility:

1. Parses donor engine/drivetrain content from unpacked mods.
2. Inspects target BeamNG vehicle architecture and slot chains.
3. Adapts slot types and part names to target vehicle conventions.
4. Injects geometry/mounting data needed for physical fitment.
5. Generates packaged output under the project `mods/unpacked/engineswaps/vehicles/` tree where "engineswaps" can be configured as any "mod_name" in swap_parameters.json

## What this project is not (yet)

This is not a one-click installer yet. For alpha, it is a command-line workflow for local testing and iteration.

It does not directly install generated mods into your BeamNG user folder, and it does not read BeamNG assets from your game install unless you manually unpack/copy them into this workspace.

Transverse engine orientations and rear engine layouts are largeley untested

## Requirements

- **Python:** `>= 3.12`
- **OS support (alpha docs):** Windows
- **Disk space:** use a sandbox workspace with **~50 GB free** (approximate size of full unpacked BeamNG vehicle assets + generated outputs)
- **BeamNG content:** unpacked base content must be made available in `SteamLibrary_content_vehicles/` (BYOBEAMS)
- **Automation game:** Automation/Camso vehicles exported using Automation's BeamNG exporter
- **Donor content:** unpacked donor mod with Camso/Automation-style `.jbeam` files
- **Git:** optional but recommended


## Workspace model (sandbox-first)

Use this project in a dedicated sandbox folder, not directly inside your BeamNG install or BeamNG user folder.

- Import base BeamNG assets locally into `SteamLibrary_content_vehicles/`
- Import donor mods locally into `mods/unpacked/`
- Generate adapted output locally under `mods/unpacked/<mod_name>/`
- Manually copy tested results into your BeamNG mods folder when you are ready

This keeps experiments reversible and avoids accidental changes to game files.

## BYOBEAMS (required)

We do not ship BeamNG base assets in this repository, you must add them yourself (BYOBEAMS)

Before running swaps, populate `SteamLibrary_content_vehicles/` with unpacked BeamNG vehicle content, including `common/` for all target vehicles you plan to swap into.

It is fine (and actually reccomended) to unpack *everything* from BeamNG's content/vehicles folder here (if you have the drive space). Our script ignores "simple_traffic" and "props" assets by default.

These BeamNG assets are usually found in: `<disk>/SteamLibrary/steamapps/common/BeamNG.drive/content/vehicles` Best / easiest method is to just unpack everything you find here to the `SteamLibrary_content_vehicles` folder

You can probably also use this script to swap Automation / Camso engines into existing mods. You would just place unpacked mods here. Our script should treat them like BeamNG vehicles, as long as BeamNG conventions are followed.

Minimum expectation (for each swap target you use):
- `SteamLibrary_content_vehicles/common/vehicles/common/<target_vehicle>/`
- `SteamLibrary_content_vehicles/<target_vehicle>/`

## Automation / Camso Exports (Donor)

Copy your unpacked Automation exports to `/mods/unpacked` or create a folder such as `/mods/donors`

After you copied this over, copy the path to your donor `*engine.jbeam` file and provide that when running the script:

```powershell
python scripts/engineswap.py generate "mods/unpacked/exportname/vehicles/exportname/eng_1234a/camso_engine_1234a.jbeam" <target> <options>
```


## Dependencies

Dependencies are managed through `requirements.txt`.

For this alpha snapshot, dependency installation is intentionally light, but the same command is kept so setup stays consistent as packages are pinned over time.

Install with:

```powershell
pip install -r requirements.txt
```

## Before you run a swap: configure swap_parameters first

Open `configs/swap_parameters.json` before running `engineswap.py`.

This file controls the key behavior of each swap run (paths, solver behavior, slot/disposition rules, packaging behavior, and related options). It is the first file to validate if output is not what you expected.

At minimum, confirm:

- `base_output_path`
- `base_vehicles_path`
- `mod_name` (if you want a custom output package name)
- `target_engine_file` (optional override; leave `null` for auto-detect)

Detailed field reference: `docs/swap_parameter_readme.md`.







## 1) Setup:

If you want the shortest path to “ready to run,” use this first:
Clone this repo to `somedir/BeamNG_Modding_Temp`

```powershell
cd BeamNG_Modding_Temp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
pip install -r requirements.txt
python scripts/engineswap.py --help
```

If `--help` shows the command list, your environment is ready.

If PowerShell blocks script activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

If you prefer global Python, skip venv activation and use your system `python`.


### 2) Install dependencies if needed

```powershell
pip install -r requirements.txt
```

### 3) Copy unpacked BeamNG assets and Automation donor files

 - populate `SteamLibrary_content_vehicles/` with unpacked BeamNG vehicle content
 - populate Automation exports folder (`/mods/unpacked` or a created folder such as `/mods/donors`) with unpacked Automation export content


### 4) Configure swap parameters

readme at `docs\swap_parameter_readme.md`

Open and adjust:

- `configs/swap_parameters.json`
- configure path settings
- solver/swap behavior used by your scenario
- mounts / offsets (Camso engines often sit unnaturally low in the vehicle)
- any desired powertrain tweaks


### 5) Run your first generate command (pickup)

```powershell
python scripts/engineswap.py generate "path/to/camso_engine_12345.jbeam" pickup --show-files --show-transforms --package
```

Expected result:

- Adapted files and manifest generated under `mods/unpacked/engineswaps/vehicles/pickup/`
- Console summary showing transformed slot/files and packaging output
- No automatic install into BeamNG user folders (copy is manual)

If you change donor/target combinations, revisit `configs/swap_parameters.json` first.


### 6) Copy to BeamNG manually

Treat this project folder as a build sandbox; deployment into the game is a separate manual step.

After validating output, copy the generated "modname" folder (default = "engineswaps") from this workspace into your BeamNG user mods path (for example, `C:/Users/owner/AppData/Local/BeamNG/BeamNG.drive/current/mods/unpacked`) or  (`Documents/BeamNG.drive/mods/unpacked/`)

Activating/deactivating mods in BeamNG mods UI tracks all swaps within "modname" folder. If you want seperation between different generations of swaps, use different "modname" (configure in swap_parameters.json)


### 7) If the swap doesn't work, welcome to the team. JK use 

```powershell
python scripts/analyze_powertrains.py -v pickup
```
*(changing "pickup" to the swap target vehicle name i.e. "pigeon" or "etk800")*

Reports are written to `docs/DrivetrainReports/targeted_pickup/`

you can also run without the "-v vehicle" to generate a report on *all* vehicles in `SteamLibrary_content_vehicles` (this will take awhile)
*This generates an all-inclusive powertrain report in `docs/DrivetrainReports/`*






## Architecture overview (logic-first)

The codebase is intentionally split into modules with clear ownership.

- `scripts/engineswap.py`
  - Main orchestrator and CLI
  - Runs donor/target analysis, adaptation pipeline, and packaging
  - `VehicleAnalyzer` dynamically discovers target slot types (engine, mounts) from game files

- `scripts/slot_graph.py`
  - Slot dependency graph and transformation state
  - Tracks preserve/adapt/inject/prune/remap behavior
  - Drives manifest and slot-aware export behavior

- `scripts/mount_solver.py`
  - Geometric adaptation for engine mounting
  - Node translation and mount/beam generation

- `scripts/analyze_powertrains.py`
  - Target drivetrain chain discovery across dedicated/common folders
  - Transfer case/axle chain reporting and architecture extraction

### Why this matters

BeamNG powertrain assets are not uniform across vehicles.

Some vehicles keep most assets locally; others split across common/manufacturer folders and rely on slot chain reachability. The project architecture above is designed to handle those differences without hard-coding one vehicle family model.

## Repository layout

```text
configs/                         Runtime and solver configuration
docs/                            Technical docs, reports, and project notes
mods/unpacked/engineswaps/       Generated output target
scripts/                         Python implementation and tests
SteamLibrary_content_vehicles/   Unpacked BeamNG base content reference
```

## Known alpha limitations (short version)

- Regression coverage is still growing across donor/target combinations.
- Some drivetrain combinations intentionally fail closed (`REFUSE`) when unsafe/unsupported.
- Tooling and docs are currently Windows-first.

## Recommended docs after this README

- `docs/swap_parameter_readme.md` — config fields and tuning
- `docs/analyze_powertrains.md` — powertrain analysis utility
- `docs/DrivetrainSwapLogic_DevelopmentPhases.md` — drivetrain strategy logic
- `docs/lessons_learned.md` — practical gotchas and proven patterns
- `docs/jBeam_syntax.md` — JBeam syntax constraints

## Contributing feedback (alpha)

If you test this in the community, useful feedback includes:

- donor vehicle/mod used
- target BeamNG vehicle
- command run
- generated manifest path
- error logs or in-game behavior notes

This data helps prioritize stabilization and installer packaging.

## License

MIT
