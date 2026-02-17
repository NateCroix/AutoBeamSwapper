# BeamNG Engine Transplant Utility - Agent Instructions (Compact)

This compact profile is for fast, routine development while preserving architectural safety.

## Mission
Build reliable Automation/Camso to BeamNG swaps with minimal rework and strong cross-module coherence.

## Phase Context
Project phase is integration and hardening, not greenfield exploration.

## Hard Rules
1. Treat JBeam as relaxed JSON-like syntax. Use project JBeamParser only.
2. Preserve slotType compatibility and parent-child slot chain integrity.
3. Respect module ownership boundaries:
   - engineswap.py: orchestration and packaging
   - slot_graph.py: slot graph truth and transformations
   - mount_solver.py: geometry and mount logic
   - analyze_powertrains.py: drivetrain discovery and reachability
4. Use fail-closed drivetrain behavior. Unsupported combinations remain REFUSE.

## Working Pattern
1. Classify target architecture first: direct, common-family, or mixed/submodel.
2. Implement smallest viable change at root cause.
3. Validate in order:
   - syntax/parse
   - targeted behavior run
   - broader regression if shared logic changed
4. Update docs in same task when architecture or policy changes.

## Decision Gate Triggers
Pause and ask user only when:
- module boundaries or project conventions would change,
- multiple valid strategies have meaningful trade-offs,
- fail-closed behavior would be relaxed,
- refactor spans parser, slot graph, and drivetrain policy together.

## Recency Rule
Prefer latest approved behavior/docs, except when conflicting with architectural invariants (slot ownership, chain topology, parser constraints, fail-closed policy). In that case, enforce invariants and raise a decision gate.

## Source-of-Truth Lookup Order
1. docs/lessons_learned.md
2. docs/jBeam_syntax.md
3. docs/analyze_powertrains.md
4. docs/DrivetrainSwapLogic_DevelopmentPhases.md
5. scripts implementations

## Communication Style
Be concise and progress-oriented. Avoid repetitive status loops and broad exploratory churn once confidence is sufficient to implement.

## Done Checklist
- Architecture classified
- Canonical parser/graph paths used
- Slot chain integrity preserved
- Validation ladder completed as needed
- Relevant docs updated
- Deferred risks explicitly listed
