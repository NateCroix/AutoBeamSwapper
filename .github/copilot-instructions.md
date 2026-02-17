# BeamNG Engine Transplant Utility - Agent Operating Instructions (Refreshed)

This document defines how AI agents should operate in this workspace to maximize delivery quality, reduce rework, and maintain architectural coherence during the integration-heavy phase of development.

---

## Instruction Profile Selector

Default profile is this file: `.github/copilot-instructions.md`.

Use these variants when the task context warrants it:
- **Compact profile:** `.github/copilot-instructions.compact.md`
   - Use for low-risk, narrow-scope, high-iteration tasks.
- **Strict CI profile:** `.github/copilot-instructions.strict-ci.md`
   - Use for release hardening, high blast radius edits, parser/policy refactors, and regression-sensitive integration.

How to switch in practice:
1. In your prompt, explicitly instruct the agent to apply one profile for the current task.
2. Optionally paste the specific section(s) you want enforced.
3. For long sessions, restate the chosen profile when task type changes.

---

## Mission & Current Phase

**Primary mission:** Build a robust Automation/Camso → BeamNG transplant utility that produces structurally valid, driveable, and maintainable swaps across varied BeamNG vehicle architectures.

**Current phase:** Integration and hardening.
- The project is no longer in initial exploration.
- Core modules exist (`engineswap.py`, `slot_graph.py`, `mount_solver.py`, `analyze_powertrains.py`).
- Main risks now are cross-module mismatch, chain contamination, and incremental regressions.

---

## Conversational User-Agent Development Architectures (Project Memory Cache)

Use this as a **cached metacontext** from project transcripts and docs:

### What “best-outcome” collaboration looks like
1. Architecture-first reasoning before edits.
2. Small, phase-gated implementations with explicit validation.
3. Deterministic decisions for drivetrain strategy (including refusal paths).
4. Immediate doc sync when architectural behavior changes.
5. Avoiding broad speculative rewrites unless explicitly requested.

### Rework patterns to avoid
1. Long exploratory loops without narrowing criteria.
2. Repeated parser regex tweaks without a guardrail test set.
3. Prefix/folder heuristics that over-link unrelated common assets.
4. “Syntactically passing” fixes that are semantically incorrect.
5. Verbose status churn without concrete implementation progress.

### Recency bias rule (with architectural exemptions)
- Prefer the most recent approved behavior/docs as default.
- **Exemption:** If recent behavior conflicts with architectural invariants (slot ownership, slot chain topology, parser constraints, fail-closed swap strategy), prioritize invariants and trigger a decision gate.
- Never treat one local success as global truth without targeted + broader validation.

---

## Non-Negotiable Technical Conventions

### 1) JBeam Parsing Is Not Standard JSON
Always treat `.jbeam` as relaxed JSON-like syntax.

- Always use project `JBeamParser` implementations.
- Always consult `docs/jBeam_syntax.md` for format specifics.
- Never use naive `json.loads()` directly on raw `.jbeam` text.
- Protect URLs before line-comment stripping.
- Assume commas may be optional in many contexts.

### 2) Slot Compatibility Is Mandatory
- `slotType` compatibility governs loadability.
- Parent-child slot chains must remain coherent after transformations.
- Preserve donor ecosystem slots unless intentionally adapting/pruning with rationale.

### 3) Target Slot Types Must Be Dynamically Discovered
- **Never synthesize** target vehicle slot types via `f"{vehicle_name}_<suffix>"`.
- Family-architecture vehicles (e.g., etk800) use a family prefix (`etk`) that differs from the vehicle name.
- Always read actual slot entries from target engine files using `VehicleAnalyzer` discovery methods:
  - `find_engine_slot_type()` for engine slots
  - `find_mount_slot_type()` for enginemounts slots
- Family prefix derivation (`engine_slot_type.replace('_engine', '')`) is acceptable only as a search-path hint, never as a slot name source.
- See `docs/lessons_learned.md` "Family Prefix ≠ Vehicle Name" for the full cross-vehicle survey.

### 4) Single Source of Truth by Module Responsibility
- `engineswap.py`: orchestration, CLI, adaptation pipeline, packaging integration.
- `slot_graph.py`: slot dependency graph, transformation planning/execution, role-aware manifest logic.
- `mount_solver.py`: geometry extraction, translation, mount/beam generation.
- `analyze_powertrains.py`: target-chain discovery, cross-folder resolution, drivetrain cataloging.

Do not duplicate core logic across modules when an existing canonical implementation exists.

---

## BeamNG Architecture Taxonomy (Operational)

When analyzing/adapting, classify target vehicle architecture first:

1. **Direct vehicle-specific engines**
   - Typical slot family: `{vehicle}_engine`.
   - Engine assets in vehicle folder.

2. **Common-family architecture**
   - Typical slot family: `{family}_engine`.
   - Assets in `common/vehicles/common/<family>/...`.

3. **Submodel/mixed architecture**
   - Dedicated vehicle folder + common family/manufacturer folders.
   - Linkage primarily through global slotType string matching and chain reachability, not folder naming assumptions.

---

## Decision Gates (Mandatory Pause Points)

Pause and ask user at these junctures before deep implementation:
1. A change would alter project conventions or module boundaries.
2. Multiple valid integration strategies exist with meaningful trade-offs.
3. A fix requires relaxing fail-closed behavior (e.g., turning REFUSE into permissive behavior).
4. A cross-cutting refactor may affect parser, slot graph, and drivetrain logic simultaneously.

If no gate is triggered, proceed autonomously with focused implementation.

---

## Integration Contract (Cross-Module)

### A) `analyze_powertrains.py` → `engineswap.py`
- Treat extracted target drivetrain data as authoritative for downstream slot injection decisions.
- Prevent chain contamination using reachability constraints (especially common-folder assets).

### B) `slot_graph.py` in adaptation pipeline
- Use graph state as slot transformation source-of-truth.
- Respect disposition rules (`preserve`, `adapt`, `inject`, `prune`, `remap`).
- `INJECT_SLOT` for enginemounts uses dynamically discovered `target_mount_slot_type`, threaded through `plan_and_execute_transformations`.
- Ensure output/manifests reflect final graph state and asset roles.

### C) `mount_solver.py` geometry integration
- Use canonical node name mapping from `mount_solver`.
- Maintain torque reaction and mount node integrity.
- Preserve physical plausibility over brittle one-off offsets.

---

## Drivetrain Strategy Policy (Fail-Closed)

Use decision tables and adaptation costs from project docs (`docs/DrivetrainSwapLogic_DevelopmentPhases.md`) as policy.

- Prefer lowest-cost valid strategy when auto-selecting.
- Respect explicit user-specified transfer case targets when valid.
- Keep unsupported/deferred combinations as `REFUSE` rather than forcing speculative adaptation.
- Preserve donor drivetrain personality where strategy allows.

---

## Validation Ladder (Required)

After non-trivial edits:
1. Syntax/parse validation for edited Python/JBeam outputs.
2. Targeted run focused on changed behavior.
3. Broader regression run if behavior affects shared logic.
4. Verify generated artifacts (reports/jbeam/manifest) for semantic correctness, not just command success.

Do not declare completion with only partial validation when broader impact is expected.

---

## Scope & Change Discipline

- Fix root cause, not superficial symptoms.
- Keep changes minimal and localized to task scope.
- Do not silently reformat unrelated code.
- Do not replace stable subsystems without user request.
- Do not add “nice-to-have” features during integration tasks.

---

## Documentation Sync Rule

When architectural behavior changes, update the relevant docs in the same task:
- `README.md` for high-level architecture/workflow changes.
- `docs/analyze_powertrains.md` for analyzer behavior/flags/output semantics.
- `docs/DrivetrainSwapLogic_DevelopmentPhases.md` for decision logic and strategy policy.
- `docs/lessons_learned.md` for durable gotchas and proven patterns.

---

## Anti-Redundancy Communication Style

Agent behavior should be concise and progress-oriented:
- Prefer short, high-signal updates.
- Avoid repeating unchanged plans.
- Stop searching once confidence threshold is met and implement.
- Convert repeated debug patterns into durable helper logic or documented guardrails.

---

## Project Standards Discovery Guidance

When uncertain, seek standards in this order:
1. `docs/lessons_learned.md`
2. `docs/jBeam_syntax.md`
3. `docs/analyze_powertrains.md`
4. `docs/DrivetrainSwapLogic_DevelopmentPhases.md`
5. Existing implementations in `scripts/`

Prefer internal project conventions over generic external heuristics.

---

## Practical Checklist Before Finishing a Task

- [ ] Classified target architecture before adaptation changes.
- [ ] Used canonical parser/writer/graph paths (no duplicate parallel logic).
- [ ] Preserved slot chain integrity and naming consistency.
- [ ] Validated targeted and, when needed, broader flows.
- [ ] Updated docs if behavior/policy changed.
- [ ] Summarized concrete outcomes + any deferred risks.

---

## Current Priority Focus

1. Robust cross-folder drivetrain resolution and integration safety.
2. Reliable swap strategy selection with explicit refusal paths.
3. Predictable packaging/manifests tied to actual transformed graph state.
4. Reduced rework through disciplined phase-gated implementation and validation.
