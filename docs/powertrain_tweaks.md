# Powertrain Tweaks Module — Agent Handoff Guide

## What It Does

`scripts/powertrain_tweaks.py` is a **standalone post-processing module** that applies configurable property modifications to adapted jbeam data dicts before they are written to disk. It runs after the core adaptation pipeline has finished its work (slot remapping, device injection, mount solving) and before `_write_jbeam_file()`.

The module is **fully isolated** — zero imports from `engineswap.py` or any other project module. It receives a plain `Dict[str, Any]`, mutates it in place, and returns audit records. This sandbox design lets you iterate rapidly on tweak functions without any risk of disturbing core pipeline logic.

---

## Architecture at a Glance

```
swap_parameters.json            engineswap.py                    powertrain_tweaks.py
┌─────────────────┐    ┌──────────────────────────┐    ┌────────────────────────────┐
│ powertrain_tweaks│───>│ _apply_powertrain_tweaks()│───>│ apply_tweaks()             │
│   enabled: true  │    │   builds TweakContext     │    │   dispatches via registry  │
│   engine: {...}  │    │   calls apply_tweaks()    │    │   returns List[TweakResult]│
│   transmission:{}│    │   logs results            │    │                            │
└─────────────────┘    └──────────────────────────┘    │ @register_tweak decorators  │
                                                        │ PowertrainDomain (shared)   │
                                                        └────────────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `apply_tweaks()` | Sole public entry point. Dispatches registered tweaks for the given component type. |
| `@register_tweak(component, key)` | Decorator that maps a config key to a handler function. |
| `TweakContext` | Frozen dataclass carrying upstream metadata (drive type, energy type, etc.) — read-only. |
| `TweakResult` | Audit record: what was attempted, whether it applied, what values changed (old→new). |
| `PowertrainDomain` | Static namespace of shared constants, physics models, structure helpers, and LUT utilities. |

### Integration Points in engineswap.py

`_apply_powertrain_tweaks()` is called at **three sites**, each immediately before `_write_jbeam_file()`:

1. `generate_adapted_jbeam()` → `component_type="engine"`
2. `generate_adapted_transmission()` → `component_type="transmission"`
3. `generate_adapted_transfercase()` → `component_type="transfercase"`

The import is wrapped in try/except — if the module is missing, tweaks silently disable.

---

## Configuration

Tweaks are configured in `configs/swap_parameters.json`:

```json
"powertrain_tweaks": {
    "enabled": true,
    "engine": {
        "requiredEnergyType": "diesel"
    },
    "transmission": {
        "tighter_tc_stall": 0.4,
        "modern_tcc_lockup": 3
    }
}
```

- **`enabled`**: Master switch. When `false`, no tweaks run.
- **Sub-objects** (`engine`, `transmission`, `transfercase`): Each key inside maps 1:1 to a registered tweak function. The value is passed as the `params` argument.
- The schema is defined in `configs/schemas/swap_parameters.schema.json`.

---

## Currently Implemented Tweaks

| Config Key | Component | Param | What It Does |
|------------|-----------|-------|--------------|
| `requiredEnergyType` | engine | `str` ("gasoline"/"diesel"/"compressedGas") | Replaces `mainEngine.requiredEnergyType` |
| `tighter_tc_stall` | transmission | `float` 0.0–1.0 | Dynamically scales `converterDiameter` and `converterStiffness` based on donor engine torque curve (ramp65/redline ratio), capped at +28% / +55% |
| `modern_tcc_lockup` | transmission | `int` gear number | Sets `torqueConverterLockupMinGear`, adjusts lockup RPM and range using dynamic engine redline from donor torque curve |

Transmission tweaks are **auto-guarded** — they only apply when a `torqueConverter` section exists in the data (i.e., automatic transmissions). Manual transmissions are skipped with a logged reason.

### Torque Converter Tweak Details

#### `tighter_tc_stall` — Dynamic Converter Tightening

**Targets:**
- `torqueConverter.converterDiameter` — increased (larger = tighter coupling, lower stall RPM)
- `torqueConverter.converterStiffness` — increased (stiffer = less slip at cruise)

**Physics rationale:** Camso converters are modeled with conservative (loose) stall characteristics. Real OEM converters are often tighter. Increasing diameter and stiffness reduces stall speed, producing less launch flare and quicker lockup feel at cruise, at the cost of slightly reduced low-speed torque multiplication.

**Scaling approach — torque-curve-aware:**

The scaling factors are dynamically derived from the donor engine's ramp65/redline ratio. Engines with a broad, low-onset torque curve (low ratio) receive more aggressive tightening; peaky engines (high ratio) receive less.

```
ramp65_redline_ratio = ramp65_torque_rpm / functional_redline

converterDiameter:
    diameter_ramp_extra  = DIAMETER_RAMP_SCALAR × (1 − ramp65_redline_ratio)
    diameter_increase    = min(params × diameter_ramp_extra, DIAMETER_MAX_INCREASE)
    new_diameter         = old_diameter × (1 + diameter_increase)
    → rounded to 14 decimal places

converterStiffness:
    stiffness_ramp_extra = (1 − ramp65_redline_ratio) + STIFFNESS_RAMP_SCALAR
    stiffness_increase   = min(params × stiffness_ramp_extra, STIFFNESS_MAX_INCREASE)
    new_stiffness        = old_stiffness × (1 + stiffness_increase)
    → floor-truncated to 1 decimal place
```

**Tuning knobs:**

These are exposed as `PowertrainDomain` class constants (`TC_DIAMETER_MAX_INCREASE`, etc.) so that tests can compute expected values dynamically. Update the constant on `PowertrainDomain` — both the tweak function and the test suite will pick up the new value automatically.

| Constant | Default | Purpose |
|----------|---------|----------|
| `TC_DIAMETER_MAX_INCREASE` | 0.28 | Hard cap on diameter increase fraction (+28%) |
| `TC_STIFFNESS_MAX_INCREASE` | 0.55 | Hard cap on stiffness increase fraction (+55%) |
| `TC_DIAMETER_RAMP_SCALAR` | 0.35 | Sensitivity of diameter scaling to torque broadness |
| `TC_STIFFNESS_RAMP_SCALAR` | 0.1 | Baseline stiffness floor added to ramp — ensures minimum tightening even for peaky engines |

**Fallback:** When no donor torque table is available on `TweakContext`, `diameter_ramp_extra` defaults to `DIAMETER_MAX_INCREASE` and `stiffness_ramp_extra` defaults to `STIFFNESS_MAX_INCREASE`, preserving the original fixed-scaling behavior.

**Example** (CAMSO engine, ramp65=2000, redline=5100, params=0.5):
```
ratio = 2000 / 5100 ≈ 0.3922
diameter_ramp_extra  = 0.35 × (1 − 0.3922) ≈ 0.2127
stiffness_ramp_extra = (1 − 0.3922) + 0.1  ≈ 0.7078

diameter_increase  = min(0.5 × 0.2127, 0.28) = 0.1064
stiffness_increase = min(0.5 × 0.7078, 0.55) = 0.3539

old_diameter=0.30 → new_diameter = 0.30 × 1.1064 ≈ 0.3319
old_stiffness=12.0 → new_stiffness = floor(12.0 × 1.3539 × 10) / 10 = 16.2
```

---

#### `modern_tcc_lockup` — Early TCC Engagement

**Targets:**
- `vehicleController.torqueConverterLockupMinGear` — set directly to `params`
- `vehicleController.torqueConverterLockupRPM` — raised proportional to engine redline headroom
- `vehicleController.torqueConverterLockupRange` — widened to accommodate RPM shift

**Physics rationale:** Modern transmissions lock the TCC much earlier than older designs — often by 2nd or 3rd gear — to improve fuel economy and reduce heat buildup. Camso transmissions typically default to lockup at gear 5+, which is unrealistically late. When lowering the lockup gear, engagement RPM and range are adjusted to avoid shudder and ensure smooth ramp-in.

**Formulas:**

```
MinGear:     set to params directly

LockupRPM:   new_RPM   = ((engine_redline − old_RPM) × LOCKUP_KNOB) + old_RPM
             → rounded to nearest integer

LockupRange: new_Range = RANGE_KNOB × ((new_RPM − old_RPM) + old_Range)
             → rounded to nearest integer
```

Both RPM and Range adjustments are **unconditional** — they apply regardless of whether the new min gear is higher or lower than the original.

**Tuning knobs:**

| Constant | Default | Purpose |
|----------|---------|----------|
| `LOCKUP_KNOB` | 0.05 | Fraction of (redline − old_RPM) added to lockup RPM |
| `RANGE_KNOB` | 1.0 | Multiplier on the combined RPM-shift + old range |
| `FALLBACK_REDLINE` | 6500 | Used when no donor torque table is available |

**Dynamic redline:** The engine redline used in the formula is extracted dynamically from `ctx.donor_torque_table` via `extract_wot_curve()` → `functional_redline()`. This is the *operating* redline (highest RPM in the WOT curve), NOT `maxRPM` (which is the overspeed damage threshold — typically 12000 in Camso engines). Falls back to `FALLBACK_REDLINE` (6500) when no torque table is available.

**Example** (redline=5100, old_RPM=750, old_Range=850, params=3):
```
new_MinGear = 3
new_RPM     = ((5100 − 750) × 0.05) + 750 = 967.5 → 968
new_Range   = 1.0 × ((968 − 750) + 850) = 1068
```

---

## How to Add a New Tweak

### 1. Write the function

Add it anywhere in `powertrain_tweaks.py` (conventionally grouped by phase/component). Apply the decorator:

```python
@register_tweak("engine", "my_new_tweak")
def tweak_my_new_tweak(
    adapted_data: Dict[str, Any],
    params: <your_param_type>,
    ctx: TweakContext
) -> TweakResult:
    """Docstring explaining physics rationale and targets."""

    # Find the part/section you need
    result = PowertrainDomain.find_part_with_section(adapted_data, "mainEngine")
    if not result:
        return TweakResult(tweak_name="my_new_tweak", applied=False,
                           reason="mainEngine not found")

    part_name, part_data = result
    engine = part_data["mainEngine"]

    # Read → compute → mutate
    old_val = engine.get("someProperty", 0)
    new_val = old_val * params
    engine["someProperty"] = new_val

    return TweakResult(
        tweak_name="my_new_tweak",
        applied=True,
        mutations={"someProperty": (old_val, new_val)}
    )
```

That's it. The registry wiring and dispatch happen automatically.

### 2. Add the config key

In `swap_parameters.json`, add the key under the matching component:

```json
"engine": {
    "my_new_tweak": 0.5
}
```

And add matching schema validation in `configs/schemas/swap_parameters.schema.json`.

### 3. Add tests

In `scripts/test_powertrain_tweaks.py`, create synthetic data dicts and test your function directly. No file I/O needed — everything runs on in-memory dicts. Add the test name to the `tests` list at the bottom of the runner.

---

## How to Modify an Existing Tweak

1. Find the function by its `@register_tweak` decorator (search for the config key).
2. The `params` argument is whatever the user puts in config — validate it early and return a non-applied `TweakResult` with a clear reason on invalid input.
3. The `adapted_data` dict mirrors the jbeam file structure: top-level keys are part names, values are dicts containing sections like `"mainEngine"`, `"torqueConverter"`, `"vehicleController"`, etc.
4. **Always record mutations** as `{property_path: (old_value, new_value)}` in the `TweakResult` — this drives the audit output.
5. Run `python test_powertrain_tweaks.py` after changes to validate.

---

## PowertrainDomain — Shared Toolkit

Before writing custom helpers, check if `PowertrainDomain` already provides what you need:

### Structure Navigation
- `find_part_with_section(data, key)` → finds first part containing a section
- `find_all_parts_with_section(data, key)` → finds all matching parts
- `get_nested(data, *keys)` → safe deep dict access
- `set_nested(data, *keys, value)` → safe deep dict set

### Physics Models
- `is_automatic_transmission(data)` → checks for `torqueConverter` section
- `effective_turbo_inertia(jbeam_val)` → converts jbeam inertia to effective kg·m²
- `pressure_rate_to_response_time(rate)` → approximate spool-down time constant
- `stall_speed_factor(diameter, stiffness)` → qualitative stall indicator
- `lockup_engagement_rpm(base_rpm, range)` → full-lock RPM estimate

### LUT Utilities (for pressurePSI tables, torque curves, etc.)
- `scale_lut_values(lut, col, factor)` → multiply a column
- `offset_lut_values(lut, col, offset)` → add constant to a column
- `clamp_lut_values(lut, col, min, max)` → clamp a column
- `interpolate_lut(lut, x)` → linear interpolation

All return new lists (non-mutating). Add new shared helpers here, not inside individual tweak functions.

### Torque Table Extraction (for donor engine performance data)
- `detect_torque_table_format(table)` → `"camso_5col"` / `"beamng_2col"` / `None` — auto-detects column layout, skips header rows
- `extract_wot_curve(table)` → `[[rpm, torque], ...]` — filters to throttle=100 (Camso) or returns all data rows (BeamNG); handles both formats
- `functional_redline(wot_curve)` → `float` — highest RPM in the WOT curve (operating redline, NOT `maxRPM` overspeed threshold)
- `peak_torque(wot_curve)` → `(rpm, torque_nm)` — row with maximum torque value
- `ramp65_torque_rpm(wot_curve)` → `float` — lowest RPM where torque exceeds 65% of peak (power band entry point)

These helpers handle both Camso 5-column and BeamNG 2-column formats transparently. All operate on the raw `ctx.donor_torque_table` forwarded via `TweakContext`, available to engine, transmission, and transfercase tweaks identically.

---

## Donor Engine Data Pipeline

The donor engine's raw torque table and idle RPM are cached by `engineswap.py` during the engine adaptation pass and forwarded to **all** tweak calls (engine, transmission, and transfercase) via `TweakContext`. This means transmission tweaks have access to engine performance data without any additional file I/O.

### TweakContext Fields (engine data)

| Field | Type | Source |
|-------|------|--------|
| `donor_torque_table` | `Optional[List[List[Any]]]` | `mainEngine.torque` — raw rows, cached as-is |
| `donor_idle_rpm` | `Optional[float]` | `mainEngine.idleRPM` |

### Torque Table Format Variance

The raw table is cached **format-agnostically**. Two formats exist in practice:

**Camso 5-column** (most common in this project):
```
Header: ["throttle", "rpm", "torque", "FuelUsed", "Pressure"]
Row:    [100, 3400, 325.69, 0.012, 2.41]
```
- 101 throttle levels (0–100), each with a full RPM sweep
- Throttle=100 rows are the WOT (wide-open throttle) curve
- Throttle=0 rows show engine braking (negative torque above idle)
- `Pressure` > 1.0 indicates forced induction (boost)

**BeamNG 2-column** (stock vehicles):
```
Header: ["rpm", "torque"]
Row:    [3400, 325.69]
```
- Single WOT curve, no throttle indexing

### Implemented PowertrainDomain Helpers

The following helpers parse the raw cached torque table. They handle **both formats** by detecting column count:

1. **`detect_torque_table_format(table)`** → `"camso_5col"` or `"beamng_2col"` or `None`
   - Checks the first data row's length (skips header rows where any element is a string)
   - 5+ columns → Camso; 2 columns → BeamNG

2. **`extract_wot_curve(table)`** → `List[List[float]]` as `[[rpm, torque], ...]`
   - Camso: filters to throttle=100 rows, extracts columns [1] and [2]
   - BeamNG: extracts columns [0] and [1] directly
   - Skips header rows automatically

3. **`functional_redline(wot_curve)`** → `Optional[float]`
   - Returns the highest RPM value in the WOT curve
   - This is the *operating* redline — NOT `maxRPM` (which is 12000 overspeed damage threshold in Camso engines and is meaningless for transmission context)

4. **`peak_torque(wot_curve)`** → `Optional[Tuple[float, float]]` as `(rpm, torque_nm)`
   - Finds the row with maximum torque value

5. **`ramp65_torque_rpm(wot_curve)`** → `Optional[float]`
   - Returns the lowest RPM at which torque exceeds 65% of peak torque
   - Represents the entry point of the engine's usable power band
   - Relevant for lockup engagement, shift scheduling, and turbo spool targets

**Deferred:** `extract_throttle_curve(table, throttle_pct)` — extract curve at a specific throttle percentage from Camso tables. Not yet needed by current tweaks.

### Usage Pattern

Identical for engine, transmission, and transfercase tweaks:

```python
if ctx.donor_torque_table:
    wot = PowertrainDomain.extract_wot_curve(ctx.donor_torque_table)
    redline = PowertrainDomain.functional_redline(wot)                  # e.g. 5100.0
    peak_torque_rpm, peak_torque = PowertrainDomain.peak_torque(wot)    # e.g. (3400.0, 325.0)
    ramp65_torque_rpm = PowertrainDomain.ramp65_torque_rpm(wot)         # e.g. 2000.0
    idle = ctx.donor_idle_rpm                                           # e.g. 500.0
```

Both torque converter tweaks consume this pipeline:
- **`tweak_tighter_tc_stall`** extracts the WOT curve, functional redline, and ramp65 torque RPM to compute the `ramp65_redline_ratio` that drives dynamic scaling of converter diameter and stiffness.
- **`tweak_modern_tcc_lockup`** extracts the functional redline to compute lockup RPM adjustment, falling back to 6500 when no torque table is available.

---

## Best Practices

### Architecture Rules
1. **No imports from project modules.** The module must remain self-contained. All upstream data arrives via `TweakContext` and the `adapted_data` dict.
2. **Pure dict-in / dict-out.** No file I/O, no path handling, no jbeam parsing. You receive a fully-parsed dict and mutate it.
3. **One decorator = one config key.** Each tweakable behavior maps to exactly one `@register_tweak` entry with a clear config-driven parameter.

### Function Design
4. **Validate params early.** Return `TweakResult(applied=False, reason=...)` immediately on invalid input. Never raise exceptions for bad config values.
5. **Guard preconditions explicitly.** If your tweak only applies to automatics, turbocharged engines, etc., check and return early with a descriptive reason. See `is_automatic_transmission()` as a template.
6. **Record all mutations.** Every property you change must appear in `TweakResult.mutations` as `(old_value, new_value)`. This is the audit trail — the pipeline relies on it for logging.
7. **Document the physics.** Each tweak function's docstring should explain *why* the modification makes physical sense, what jbeam properties are targeted, and what the parameter range means. Future agents and users will rely on this.

### Domain Knowledge
8. **Use `PowertrainDomain` for shared logic.** Don't duplicate constants, navigation helpers, or unit conversions in tweak functions. If you need a new helper that would benefit multiple tweaks, add it to `PowertrainDomain`.
9. **Understand where sections live.** In Camso jbeam:
   - `mainEngine`, `turbocharger` → in engine component data
   - `torqueConverter`, `vehicleController` → in transmission component data (but `torqueConverter` can appear in transfercase files as a rangebox drivability hack — **not** a real automatic)
   - Device arrays (`powertrain`) → may span multiple parts within the same file

### Testing
10. **Test with synthetic dicts, not real files.** Build minimal dicts that contain only the sections your tweak needs. See existing fixtures (`make_engine_data`, `make_transmission_data`) as templates.
11. **Test the skip paths.** Verify that your tweak correctly returns `applied=False` when preconditions aren't met (missing sections, wrong transmission type, zero-value params, etc.).
12. **Run the full suite** (`python test_powertrain_tweaks.py`) after any change — all 50 tests should pass.

### Scope Discipline
13. **Don't modify the core pipeline.** If you need additional upstream data in `TweakContext`, coordinate with the core pipeline maintainer to add it — don't reach into `engineswap.py` yourself.
14. **Don't silently inject new config keys.** Any new tweak must have a corresponding schema entry in `swap_parameters.schema.json` and should default to inactive (omitted from config = not applied).

---

## Planned Future Tweaks (Deferred)

| Phase | Config Key | Complexity | Notes |
|-------|-----------|------------|-------|
| C | `fix_turbo_transient` | Medium | LUT manipulation on `pressurePSI`, scalar on `inertia`/`pressureRatePSI`. Domain helpers already exist. |
| D | `convert_to_turbodiesel` | Medium-High | Compound: forces `requiredEnergyType=diesel` + modifies vacuum/boost behavior. Depends on Phase C LUT work. |
| E | `modern_tcc_unlock` | High (deferred) | Force-unlock TCC near WOT below torque peak. May require custom `.lua` controller generation — out of scope for dict-only tweaks. |

Consult `docs/TODO.md` for the latest status of each phase.
