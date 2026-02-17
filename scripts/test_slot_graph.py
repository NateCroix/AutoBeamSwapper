"""
Test script for Slot Graph functionality.

Tests the core slot graph architecture with real donor files from the project.
"""

import sys
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

# Import JBeamParser from engineswap
from engineswap import JBeamParser

# Import slot_graph components
from slot_graph import (
    SlotGraphBuilder,
    SlotDispositionRules,
    SlotTransformationPlanner,
    SlotTransformationExecutor,
    SlotAwareJBeamWriter,
    SlotAwareManifestGenerator,
    SlotDisposition,
    SlotState,
    JBeamParserProtocol,
    ParserNotAvailableError,
    build_slot_graph,
    plan_and_execute_transformations,
)


def test_graph_building():
    """Test building a slot graph from donor files."""
    print("\n" + "=" * 70)
    print("TEST: Slot Graph Building")
    print("=" * 70)
    
    # Paths to donor files
    donor_dir = Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles\persh_crayenne_moracc")
    
    engine_file = donor_dir / "eng_3813e" / "camso_engine_3813e.jbeam"
    transmission_file = donor_dir / "ec8ba" / "camso_transmission_ec8ba.jbeam"
    transfercase_file = donor_dir / "ec8ba" / "camso_transfercase_ec8ba.jbeam"
    structure_file = donor_dir / "ec8ba" / "camso_engine_structure_ec8ba.jbeam"
    intake_file = donor_dir / "eng_3813e" / "camso_intakes_3813e.jbeam"
    
    # Build graph - now requires explicit parser injection
    builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
    
    files_to_add = [engine_file, transmission_file, transfercase_file, structure_file, intake_file]
    
    for f in files_to_add:
        if f.exists():
            slots_added = builder.add_donor_file(f)
            print(f"  Added {f.name}: {slots_added} slots")
        else:
            print(f"  SKIP {f.name}: not found")
    
    graph = builder.build()
    
    print(f"\n  Graph summary: {graph}")
    print(f"  Total slots: {len(graph.by_slot_type)}")
    print(f"  Total files: {len(graph.donor_files)}")
    
    # Print slot tree
    print(f"\n  Slot Tree:")
    graph.print_tree()
    
    return graph


def test_disposition_rules(graph):
    """Test disposition rule determination."""
    print("\n" + "=" * 70)
    print("TEST: Disposition Rules")
    print("=" * 70)
    
    rules = SlotDispositionRules()
    
    print(f"\n  Slot Dispositions:")
    for slot_type, node in sorted(graph.by_slot_type.items()):
        disposition = rules.determine_disposition(node, "pickup")
        icon = {
            SlotDisposition.ADAPT: "A",
            SlotDisposition.PRESERVE: "P",
            SlotDisposition.PRUNE: "X",
            SlotDisposition.INJECT: "I",
            SlotDisposition.REMAP_DEFAULT: "R",
        }.get(disposition, "?")
        print(f"    [{icon}] {slot_type} -> {node.default_part or '(none)'}")
    
    return rules


def test_transformation_planning(graph, rules):
    """Test transformation planning."""
    print("\n" + "=" * 70)
    print("TEST: Transformation Planning")
    print("=" * 70)
    
    planner = SlotTransformationPlanner(graph, "pickup", rules)
    transformations = planner.plan()
    
    print(f"\n  Planned {len(transformations)} transformations:")
    for t in transformations:
        print(f"    {t}")
    
    summary = planner.get_plan_summary()
    print(f"\n  Summary:")
    print(f"    By operation: {summary['by_operation']}")
    print(f"    By disposition: {summary['by_disposition']}")
    
    print(f"\n  Slot Type Mappings:")
    for old, new in summary['slot_type_mappings'].items():
        print(f"    {old} -> {new}")
    
    print(f"\n  Part Name Mappings:")
    for old, new in list(summary['part_name_mappings'].items())[:10]:  # First 10
        print(f"    {old} -> {new}")
    if len(summary['part_name_mappings']) > 10:
        print(f"    ... and {len(summary['part_name_mappings']) - 10} more")
    
    return transformations


def test_transformation_execution(graph):
    """Test transformation execution."""
    print("\n" + "=" * 70)
    print("TEST: Transformation Execution")
    print("=" * 70)
    
    executor = SlotTransformationExecutor(graph)
    executed = executor.execute_all()
    
    print(f"\n  Executed {executed} transformations")
    
    # Show transformed state
    print(f"\n  Transformed Slot Tree:")
    graph.print_tree()
    
    # Show state changes
    print(f"\n  Slot States After Execution:")
    for state in SlotState:
        count = len([n for n in graph.by_slot_type.values() if n.state == state])
        if count > 0:
            print(f"    {state.value}: {count}")
    
    return graph


def test_jbeam_writer(graph):
    """Test JBeam slot output generation."""
    print("\n" + "=" * 70)
    print("TEST: JBeam Slot Writer")
    print("=" * 70)
    
    writer = SlotAwareJBeamWriter(graph)
    
    # Find a part to generate slots for
    if graph.root and graph.root.default_part:
        part_name = graph.root.default_part
        print(f"\n  Generating slots for: {part_name}")
        
        slots = writer.generate_slots_section(part_name)
        print(f"  Generated {len(slots) - 1} slot entries (+ header)")
        
        print(f"\n  Slots array:")
        for slot in slots:
            print(f"    {slot}")
    
    # Test slot type mapping
    print(f"\n  Adapted slot type examples:")
    for original in ["Camso_Engine", "Camso_Transmission", "Camso_TransferCase"]:
        adapted = writer.get_adapted_slot_type(original)
        print(f"    {original} -> {adapted}")
    
    return writer


def test_manifest_generation(graph):
    """Test manifest generation."""
    print("\n" + "=" * 70)
    print("TEST: Manifest Generation")
    print("=" * 70)
    
    generator = SlotAwareManifestGenerator(graph)
    manifest = generator.generate()
    
    print(f"\n  Manifest version: {manifest['version']}")
    print(f"  Target vehicle: {manifest['target_vehicle']}")
    
    print(f"\n  Statistics:")
    for key, value in manifest['statistics'].items():
        print(f"    {key}: {value}")
    
    print(f"\n  Validation:")
    validation = manifest['validation']
    print(f"    Valid: {validation['valid']}")
    print(f"    Errors: {validation['error_count']}")
    print(f"    Warnings: {validation['warning_count']}")
    
    if validation['warnings']:
        print(f"\n  Warnings:")
        for w in validation['warnings'][:5]:  # First 5
            print(f"    - {w}")
        if len(validation['warnings']) > 5:
            print(f"    ... and {len(validation['warnings']) - 5} more")
    
    print(f"\n  Required files: {len(manifest['copy_plan']['original_jbeam']) + len(manifest['copy_plan']['generated_jbeam'])}")
    print(f"  Pruned files: {len(manifest['copy_plan']['excluded_files'])}")
    
    return manifest


def test_with_pruning():
    """Test graph with explicit slot pruning."""
    print("\n" + "=" * 70)
    print("TEST: Pruning Configuration")
    print("=" * 70)
    
    # Build fresh graph
    donor_dir = Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\persh_crayenne_moracc\vehicles\persh_crayenne_moracc")
    engine_file = donor_dir / "eng_3813e" / "camso_engine_3813e.jbeam"
    
    if not engine_file.exists():
        print("  SKIP: Engine file not found")
        return
    
    builder = SlotGraphBuilder("pickup", jbeam_parser=JBeamParser)
    builder.add_donor_file(engine_file)
    graph = builder.build()
    
    # Configure pruning
    config = {
        "slot_rules": {
            "prune_slots": ["Camso_Supercharger_3813e", "Camso_Nitrous"],
        }
    }
    
    rules = SlotDispositionRules(config)
    planner = SlotTransformationPlanner(graph, "pickup", rules)
    planner.plan()
    
    # Show what will be pruned
    prune_count = len([n for n in graph.by_slot_type.values() 
                       if n.disposition == SlotDisposition.PRUNE])
    print(f"\n  Slots marked for pruning: {prune_count}")
    
    # Execute
    executor = SlotTransformationExecutor(graph)
    executor.execute_all()
    
    # Show result
    pruned = [n for n in graph.by_slot_type.values() if n.state == SlotState.PRUNED]
    print(f"  Slots actually pruned: {len(pruned)}")
    for n in pruned:
        print(f"    - {n.slot_type}")


def test_protocol_compliance():
    """Test that JBeamParser conforms to JBeamParserProtocol."""
    print("\n" + "=" * 70)
    print("TEST: Protocol Compliance")
    print("=" * 70)
    
    # Check protocol conformance
    is_protocol = isinstance(JBeamParser, type) and hasattr(JBeamParser, 'parse_jbeam')
    print(f"  JBeamParser has parse_jbeam: {hasattr(JBeamParser, 'parse_jbeam')}")
    print(f"  Protocol check passed: {is_protocol}")
    
    # Test error on missing parser
    try:
        builder = SlotGraphBuilder("pickup", jbeam_parser=None)
        builder.add_donor_file(Path("test.jbeam"))
        print("  ERROR: Should have raised ParserNotAvailableError")
    except ParserNotAvailableError as e:
        print(f"  Correctly raised ParserNotAvailableError: {e}")


def main():
    """Run all tests."""
    print("=" * 70)
    print("SLOT GRAPH TEST SUITE")
    print("=" * 70)
    
    # Test 0: Protocol compliance
    test_protocol_compliance()
    
    # Test 1: Build graph
    graph = test_graph_building()
    
    if len(graph.by_slot_type) == 0:
        print("\nERROR: No slots found - check file paths")
        return
    
    # Test 2: Disposition rules
    rules = test_disposition_rules(graph)
    
    # Test 3: Transformation planning
    test_transformation_planning(graph, rules)
    
    # Test 4: Execute transformations
    test_transformation_execution(graph)
    
    # Test 5: JBeam writer
    test_jbeam_writer(graph)
    
    # Test 6: Manifest generation
    test_manifest_generation(graph)
    
    # Test 7: Pruning
    test_with_pruning()
    
    print("\n" + "=" * 70)
    print("ALL TESTS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
