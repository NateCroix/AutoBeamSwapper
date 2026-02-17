# BeamNG Engine Transplant Utility - Agent Instructions (Strict CI / Integration Hardening)

This strict profile is for release prep, regression control, and high-risk integration windows.

## Operating Objective
Deliver deterministic, auditable changes with explicit proof of correctness across architecture boundaries.

## Non-Negotiable Controls
1. No speculative rewrites. Implement only scoped, root-cause fixes.
2. No parallel duplicate logic when a canonical module path exists.
3. No permissive fallback that weakens fail-closed drivetrain policy.
4. No completion claim without validation evidence proportional to blast radius.

## Required Pre-Implementation Contract
Before editing:
1. Identify affected modules and ownership boundary.
2. Identify architecture class impacted: direct, common-family, mixed/submodel.
3. State expected integration touchpoints among:
   - analyze_powertrains.py
   - engineswap.py
   - slot_graph.py
   - mount_solver.py
4. If change crosses policy or boundaries, trigger decision gate.

## Decision Gates (Mandatory)
Must pause for user decision if any condition is true:
- convention or module responsibility changes,
- two or more plausible strategies with non-trivial trade-offs,
- fail-closed REFUSE behavior would be relaxed,
- parser and drivetrain policy both change in same task.

## Implementation Discipline
1. Prefer minimum-diff edits.
2. Preserve existing public interfaces unless user asks otherwise.
3. Keep slot-chain semantics and naming stability.
4. Prevent cross-folder contamination via reachability-constrained resolution.

## Validation Ladder (Mandatory)
Run and report all applicable levels:
1. syntax/parse validation,
2. targeted behavior run focused on changed path,
3. broader regression when shared code path or policy touched,
4. artifact semantics check (report, jbeam, manifest consistency).

If any layer cannot be run, explicitly state why and what compensating check was used.

## Documentation Synchronization
If behavior/policy/architecture changed, update docs in same task:
- README.md
- docs/analyze_powertrains.md
- docs/DrivetrainSwapLogic_DevelopmentPhases.md
- docs/lessons_learned.md

## Evidence-Oriented Completion Format
Completion report must include:
1. What changed
2. Why this path was chosen
3. Validation executed and outcomes
4. Known risks and deferred items
5. Decision gates encountered and outcomes

## Recency Rule With Architectural Exemption
Prefer latest approved behavior/docs by default. If latest conflicts with architectural invariants, invariants win and a decision gate is mandatory.

## Anti-Rework Requirements
- Avoid repeated exploratory searches without narrowing hypothesis.
- Convert repeated debugging patterns into reusable guardrails or doc updates.
- Do not extrapolate from one local success to global correctness without broader validation.
