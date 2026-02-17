"""
Test the transmission file finding and extraction pipeline.
"""
from pathlib import Path
import sys

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from engineswap import EngineTransplantUtility, VehicleInfo, JBeamParser, TMS_AVAILABLE, VehicleArchitecture
from mount_solver import TargetVehicleExtractor

def main():
    print("=" * 70)
    print("TRANSMISSION EXTRACTION TEST")
    print("=" * 70)
    
    print(f"\nTMS_AVAILABLE: {TMS_AVAILABLE}")
    
    base_vehicles_path = Path(r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles")
    
    # Create utility
    util = EngineTransplantUtility(
        base_vehicles_path=base_vehicles_path,
        output_path=Path(r"M:\BeamNG_Modding_Temp\mods\unpacked\engineswaps\vehicles")
    )
    
    # Test finding transmission file
    target_vehicle = VehicleInfo(
        name="pickup",
        architecture=VehicleArchitecture.COMMON,
        base_path=base_vehicles_path / "pickup"
    )
    print(f"\nTarget vehicle: {target_vehicle.name}")
    print(f"Target architecture: {target_vehicle.architecture.value}")
    
    # Check if method exists
    if not hasattr(util, "_find_target_transmission_file"):
        print("ERROR: _find_target_transmission_file method not found!")
        return
    
    trans_file = util._find_target_transmission_file(target_vehicle)
    print(f"Found transmission file: {trans_file}")
    
    if trans_file:
        # Parse and extract
        data = JBeamParser.parse_jbeam(trans_file)
        if data:
            print(f"Parsed {len(data)} parts from file")
            
            extractor = TargetVehicleExtractor(data)
            trans_struct = extractor.extract_transmission_structure()
            
            if trans_struct and trans_struct.nodes:
                print(f"\nExtracted {len(trans_struct.nodes)} transmission nodes (all variants):")
                
                # Dedupe by name for display
                unique_nodes = {}
                for n in trans_struct.nodes:
                    if n.name not in unique_nodes:
                        unique_nodes[n.name] = n
                
                print(f"Unique nodes: {len(unique_nodes)}")
                for name, n in unique_nodes.items():
                    print(f"  {n.name}: ({n.position.x:.4f}, {n.position.y:.4f}, {n.position.z:.4f}) weight={n.weight}")
                
                if trans_struct.beam_properties:
                    print(f"\nBeam properties:")
                    print(f"  beamSpring: {trans_struct.beam_properties.beam_spring}")
                    print(f"  beamDamp: {trans_struct.beam_properties.beam_damp}")
                else:
                    print("\nNo beam properties found")
                
                print(f"\nConnected engine nodes: {trans_struct.connected_engine_nodes}")
            else:
                print("No transmission nodes found in structure")
        else:
            print("Failed to parse transmission file")
    else:
        print("Transmission file not found!")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
