"""
Mod Packager - Automated Asset Packaging from Manifest

This module reads a generated engine swap manifest and copies all required
files to the output folder, maintaining proper directory structure for
BeamNG resource loading.

USAGE:
    # Validate manifest (check all source files exist)
    python mod_packager.py validate manifest.json
    
    # Dry run (show what would be copied)
    python mod_packager.py package manifest.json --dry-run
    
    # Execute packaging
    python mod_packager.py package manifest.json
    
    # Force overwrite existing files
    python mod_packager.py package manifest.json --force

PACKAGING STRATEGY:
    - Original JBeam: Copy to output root (vehicle-specific parts)
    - Meshes: Preserve path relative to mod_root
    - Textures: Preserve path relative to mod_root
    - Sounds: Preserve path relative to mod_root

Author: BeamNG Engine Swap Utility
Version: 1.0.0
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path
from enum import Enum
import json
import shutil
import logging
import argparse

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class AssetCategory(Enum):
    """Category of asset being packaged."""
    JBEAM_ORIGINAL = "jbeam_original"
    JBEAM_GENERATED = "jbeam_generated"
    MESH = "mesh"
    TEXTURE = "texture"
    SOUND = "sound"
    LUA = "lua"
    MATERIAL_JSON = "material_json"


class CopyStatus(Enum):
    """Status of a copy operation."""
    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED = "skipped"      # File already exists
    FAILED = "failed"
    DRY_RUN = "dry_run"


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class CopyPlan:
    """
    Plan for copying a single file.
    
    Attributes:
        source: Absolute path to source file
        destination: Absolute path to destination
        category: Type of asset (jbeam, mesh, texture, sound)
        relative_path: Path relative to mod_root (for reference)
        status: Current status of copy operation
        error: Error message if failed
    """
    source: Path
    destination: Path
    category: AssetCategory
    relative_path: str = ""
    status: CopyStatus = CopyStatus.PENDING
    error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "category": self.category.value,
            "relative_path": self.relative_path,
            "status": self.status.value,
            "error": self.error,
        }


@dataclass
class PackageResult:
    """
    Result of packaging operation.
    
    Attributes:
        success: Overall success (all required files copied)
        total_files: Total files in plan
        copied: Files successfully copied
        skipped: Files skipped (already exist)
        failed: Files that failed to copy
        dry_run: Whether this was a dry run
        copy_plans: Detailed list of all copy operations
    """
    success: bool = True
    total_files: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    copy_plans: List[CopyPlan] = field(default_factory=list)
    
    def get_summary(self) -> str:
        """Generate human-readable summary."""
        mode = "[DRY RUN] " if self.dry_run else ""
        status = "SUCCESS" if self.success else "FAILED"
        
        lines = [
            f"{mode}Packaging {status}",
            f"  Total files: {self.total_files}",
            f"  Copied: {self.copied}",
            f"  Skipped: {self.skipped}",
            f"  Failed: {self.failed}",
        ]
        
        if self.failed > 0:
            lines.append("\nFailed files:")
            for plan in self.copy_plans:
                if plan.status == CopyStatus.FAILED:
                    lines.append(f"  - {plan.source.name}: {plan.error}")
        
        return "\n".join(lines)
    
    def get_by_category(self) -> Dict[str, int]:
        """Get counts by category."""
        counts = {}
        for plan in self.copy_plans:
            cat = plan.category.value
            if plan.status == CopyStatus.SUCCESS:
                counts[cat] = counts.get(cat, 0) + 1
        return counts


# ============================================================================
# MAIN PACKAGER CLASS
# ============================================================================

class ModPackager:
    """
    Main class for packaging mod assets from manifest.
    
    Reads a generated manifest and copies all required files to the
    output folder, maintaining proper directory structure.
    
    Usage:
        packager = ModPackager(manifest_path, workspace_root)
        
        # Validate sources exist
        errors = packager.validate()
        
        # Plan copies (dry run)
        result = packager.execute(dry_run=True)
        
        # Execute copies
        result = packager.execute(overwrite=False)
    """
    
    def __init__(self, manifest_path: Path, workspace_root: Optional[Path] = None):
        """
        Initialize packager.
        
        Args:
            manifest_path: Path to manifest JSON file
            workspace_root: Root of workspace (for resolving relative paths).
                           Defaults to searching up from manifest for 'mods' folder parent.
        """
        self.manifest_path = Path(manifest_path).resolve()
        
        # Infer workspace root from manifest location
        if workspace_root:
            self.workspace_root = Path(workspace_root).resolve()
        else:
            # Search upward for the 'mods' folder, workspace is its parent
            # manifest is at: {workspace}/mods/unpacked/engineswaps/vehicles/{target}/manifest.json
            current = self.manifest_path.parent
            while current.parent != current:
                if current.name == "mods":
                    self.workspace_root = current.parent
                    break
                current = current.parent
            else:
                # Fallback: use manifest parent's parent^5
                self.workspace_root = self.manifest_path.parent.parent.parent.parent.parent.parent
        
        self.manifest: Dict[str, Any] = {}
        self.output_folder: Path = self.manifest_path.parent  # vehicles/{target}/
        
        # Mod package root is parent of vehicles/ (e.g., engineswaps/)
        # This is where art/ folder must live for BeamNG resource loading
        # manifest at: .../engineswaps/vehicles/{target}/manifest.json
        self.mod_package_root: Path = self.output_folder.parent.parent  # engineswaps/
        
        self._copy_plans: List[CopyPlan] = []
    
    def load_manifest(self) -> Dict[str, Any]:
        """
        Load and parse manifest JSON.
        
        Returns:
            Parsed manifest dictionary
            
        Raises:
            FileNotFoundError: If manifest doesn't exist
            json.JSONDecodeError: If manifest is invalid JSON
        """
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {self.manifest_path}")
        
        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            self.manifest = json.load(f)
        
        logger.info(f"Loaded manifest v{self.manifest.get('version', 'unknown')}")
        logger.info(f"  Target vehicle: {self.manifest.get('target_vehicle')}")
        logger.info(f"  Mod root: {self.manifest.get('mod_root')}")
        
        return self.manifest
    
    def plan_copies(self) -> List[CopyPlan]:
        """
        Build copy plan from manifest.
        
        Returns:
            List of CopyPlan objects for all files to copy
        """
        if not self.manifest:
            self.load_manifest()
        
        self._copy_plans = []
        mod_root = Path(self.manifest.get("mod_root", ""))
        
        # === ORIGINAL JBEAM FILES ===
        # Copy to output root (these are preserved vehicle parts like intakes)
        for jbeam_info in self.manifest.get("copy_plan", {}).get("original_jbeam", []):
            source_path = jbeam_info["path"]
            # If path is already absolute or starts with mods/, use as-is relative to workspace
            source = self._resolve_source_path(source_path)
            # Copy to output folder root
            destination = self.output_folder / source.name
            
            self._copy_plans.append(CopyPlan(
                source=source,
                destination=destination,
                category=AssetCategory.JBEAM_ORIGINAL,
                relative_path=source_path,
            ))
        
        # === MESH FILES ===
        # Strip donor vehicle folder, keep child folders directly under target
        for mesh_info in self.manifest.get("asset_files", {}).get("meshes", []):
            source = self._resolve_source_path(mesh_info["full_path"])
            relative_path = mesh_info.get("path", "")
            
            # Strip vehicles/<donor>/ prefix for cleaner output structure
            cleaned_path = self._strip_donor_vehicle_path(relative_path)
            destination = self.output_folder / cleaned_path
            
            self._copy_plans.append(CopyPlan(
                source=source,
                destination=destination,
                category=AssetCategory.MESH,
                relative_path=cleaned_path,
            ))
        
        # === TEXTURE FILES ===
        for tex_info in self.manifest.get("asset_files", {}).get("textures", []):
            source = self._resolve_source_path(tex_info["full_path"])
            relative_path = tex_info.get("path", "")
            
            # Strip vehicles/<donor>/ prefix for cleaner output structure
            cleaned_path = self._strip_donor_vehicle_path(relative_path)
            destination = self.output_folder / cleaned_path
            
            self._copy_plans.append(CopyPlan(
                source=source,
                destination=destination,
                category=AssetCategory.TEXTURE,
                relative_path=cleaned_path,
            ))
        
        # === SOUND FILES ===
        # Sounds go to mod package root (art/ must be at engineswaps/ level, not inside vehicles/)
        for sound_info in self.manifest.get("asset_files", {}).get("sounds", []):
            source = self._resolve_source_path(sound_info["full_path"])
            relative_path = sound_info.get("path", "")
            
            # art/ paths go to mod package root (engineswaps/)
            destination = self.mod_package_root / relative_path
            
            self._copy_plans.append(CopyPlan(
                source=source,
                destination=destination,
                category=AssetCategory.SOUND,
                relative_path=relative_path,
            ))
        
        # === EXTRA ASSETS (configured in manifest) ===
        self._discover_extra_assets()
        
        logger.info(f"Planned {len(self._copy_plans)} file copies")
        return self._copy_plans
    
    def _resolve_source_path(self, path_str: str) -> Path:
        """
        Resolve a source path from manifest to absolute path.
        
        Handles both relative paths (to workspace) and paths that already
        include the mods/ prefix.
        
        Args:
            path_str: Path string from manifest
            
        Returns:
            Absolute Path object
        """
        path = Path(path_str)
        
        # If already absolute, use as-is
        if path.is_absolute():
            return path
        
        # Resolve relative to workspace root
        resolved = self.workspace_root / path
        
        return resolved
    
    def _strip_donor_vehicle_path(self, relative_path: str) -> str:
        """
        Strip donor vehicle folder from relative path for cleaner output structure.
        
        Transforms paths like:
            vehicles/persh_crayenne_moracc/ec8ba/mesh.dae -> ec8ba/mesh.dae
            art/sound/engine/xxx/sound.wav -> art/sound/engine/xxx/sound.wav (unchanged)
        
        This ensures assets nest directly under the target vehicle folder without
        including the donor vehicle's folder hierarchy.
        
        Args:
            relative_path: Path relative to mod_root
            
        Returns:
            Cleaned relative path with donor vehicle folder stripped
        """
        parts = Path(relative_path).parts
        
        # Check if path starts with "vehicles/<something>/"
        # Strip "vehicles/<donor_name>/" prefix, keep child folders
        if len(parts) >= 2 and parts[0] == "vehicles":
            return str(Path(*parts[2:])) if len(parts) > 2 else ""
        
        return relative_path
    
    def _discover_extra_assets(self) -> None:
        """
        Discover and plan copies for extra assets defined in manifest config.
        
        Handles:
        - powertrain_lua: Copy lua/powertrain/*.lua from donor to target
        - actuator_lua: Copy lua/controller/drivingDynamics/actuators/*.lua from donor
        - materials_json: Copy *.materials.json files matching mesh prefixes
        
        These are configured via extra_assets in swap_parameters.json and
        stored in the manifest at generation time.
        """
        extra_config = self.manifest.get("extra_assets", {})
        mod_root = Path(self.manifest.get("mod_root", ""))
        target_vehicle = self.manifest.get("target_vehicle", "")
        
        if not mod_root or not target_vehicle:
            logger.warning("Missing mod_root or target_vehicle - skipping extra assets")
            return
        
        # Resolve mod_root to absolute path
        mod_root_abs = self._resolve_source_path(str(mod_root))
        
        # === POWERTRAIN LUA FILES ===
        lua_config = extra_config.get("powertrain_lua", {})
        if lua_config.get("enabled", False):
            # Find lua/powertrain/*.lua in donor mod's vehicles folder
            lua_pattern = mod_root_abs / "vehicles" / "*" / "lua" / "powertrain" / "*.lua"
            lua_files = list(mod_root_abs.glob("vehicles/*/lua/powertrain/*.lua"))
            
            for lua_file in lua_files:
                # Destination: {target_vehicle}/lua/powertrain/{filename}
                destination = self.output_folder / "lua" / "powertrain" / lua_file.name
                
                self._copy_plans.append(CopyPlan(
                    source=lua_file,
                    destination=destination,
                    category=AssetCategory.LUA,
                    relative_path=f"lua/powertrain/{lua_file.name}",
                ))
            
            if lua_files:
                logger.info(f"Found {len(lua_files)} powertrain lua files")
        
        # === ACTUATOR LUA FILES ===
        actuator_config = extra_config.get("actuator_lua", {})
        if actuator_config.get("enabled", False):
            # Find lua/controller/drivingDynamics/actuators/*.lua in donor mod
            actuator_files = list(mod_root_abs.glob(
                "vehicles/*/lua/controller/drivingDynamics/actuators/*.lua"
            ))
            
            for lua_file in actuator_files:
                # Destination: {target_vehicle}/lua/controller/drivingDynamics/actuators/{filename}
                rel = f"lua/controller/drivingDynamics/actuators/{lua_file.name}"
                destination = self.output_folder / rel
                
                self._copy_plans.append(CopyPlan(
                    source=lua_file,
                    destination=destination,
                    category=AssetCategory.LUA,
                    relative_path=rel,
                ))
            
            if actuator_files:
                logger.info(f"Found {len(actuator_files)} actuator lua files")
        
        # === MATERIALS JSON FILES ===
        mat_config = extra_config.get("materials_json", {})
        if mat_config.get("enabled", False):
            # For each mesh, look for {prefix}.materials.json in the mesh's texture folder
            meshes = self.manifest.get("asset_files", {}).get("meshes", [])
            
            for mesh_info in meshes:
                mesh_full_path = mesh_info.get("full_path", "")
                if not mesh_full_path:
                    continue
                
                mesh_path = self._resolve_source_path(mesh_full_path)
                
                # Extract mesh prefix (e.g., "ec8ba" from "ec8ba_mesh.dae")
                mesh_name = mesh_path.stem  # "ec8ba_mesh"
                prefix = mesh_name.split("_")[0]  # "ec8ba"
                
                # Look for {prefix}.materials.json in parent's parent folder
                # (mesh is in ec8ba/, materials.json is in persh_crayenne_moracc/)
                materials_file = mesh_path.parent.parent / f"{prefix}.materials.json"
                
                if materials_file.exists():
                    # Destination: same level as mesh subfolder (with textures)
                    destination = self.output_folder / f"{prefix}.materials.json"
                    
                    self._copy_plans.append(CopyPlan(
                        source=materials_file,
                        destination=destination,
                        category=AssetCategory.MATERIAL_JSON,
                        relative_path=f"{prefix}.materials.json",
                    ))
                    
                    logger.info(f"Found materials file: {materials_file.name}")
    
    def validate(self) -> List[str]:
        """
        Validate that all source files exist.
        
        Returns:
            List of error messages (empty if all valid)
        """
        if not self._copy_plans:
            self.plan_copies()
        
        errors = []
        for plan in self._copy_plans:
            if not plan.source.exists():
                errors.append(f"Source not found: {plan.source}")
        
        if errors:
            logger.warning(f"Validation found {len(errors)} missing files")
        else:
            logger.info(f"Validation passed: all {len(self._copy_plans)} source files exist")
        
        return errors
    
    def execute(self, dry_run: bool = False, overwrite: bool = False) -> PackageResult:
        """
        Execute the packaging operation.
        
        Args:
            dry_run: If True, only report what would be copied
            overwrite: If True, overwrite existing destination files
            
        Returns:
            PackageResult with detailed status
        """
        if not self._copy_plans:
            self.plan_copies()
        
        result = PackageResult(
            total_files=len(self._copy_plans),
            dry_run=dry_run,
            copy_plans=self._copy_plans,
        )
        
        for plan in self._copy_plans:
            try:
                # Check source exists
                if not plan.source.exists():
                    plan.status = CopyStatus.FAILED
                    plan.error = "Source file not found"
                    result.failed += 1
                    continue
                
                # Check destination exists
                if plan.destination.exists() and not overwrite:
                    plan.status = CopyStatus.SKIPPED
                    result.skipped += 1
                    continue
                
                # Dry run - just mark as would-be-copied
                if dry_run:
                    plan.status = CopyStatus.DRY_RUN
                    result.copied += 1  # Would be copied
                    continue
                
                # Create destination directory
                plan.destination.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                shutil.copy2(plan.source, plan.destination)
                plan.status = CopyStatus.SUCCESS
                result.copied += 1
                
                logger.debug(f"Copied: {plan.source.name} -> {plan.destination}")
                
            except Exception as e:
                plan.status = CopyStatus.FAILED
                plan.error = str(e)
                result.failed += 1
                logger.error(f"Failed to copy {plan.source}: {e}")
        
        result.success = result.failed == 0
        return result
    
    def get_copy_summary(self) -> Dict[str, List[str]]:
        """
        Get summary of planned copies by category.
        
        Returns:
            Dict mapping category to list of filenames
        """
        if not self._copy_plans:
            self.plan_copies()
        
        summary = {}
        for plan in self._copy_plans:
            cat = plan.category.value
            if cat not in summary:
                summary[cat] = []
            summary[cat].append(plan.source.name)
        
        return summary


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Package mod assets from manifest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate manifest (check all source files exist)
  python mod_packager.py validate manifest.json
  
  # Dry run (show what would be copied)
  python mod_packager.py package manifest.json --dry-run
  
  # Execute packaging
  python mod_packager.py package manifest.json
  
  # Force overwrite existing files
  python mod_packager.py package manifest.json --force
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate manifest sources exist")
    validate_parser.add_argument("manifest", type=Path, help="Path to manifest JSON")
    validate_parser.add_argument("--workspace", type=Path, help="Workspace root (optional)")
    
    # Package command  
    package_parser = subparsers.add_parser("package", help="Package mod assets from manifest")
    package_parser.add_argument("manifest", type=Path, help="Path to manifest JSON")
    package_parser.add_argument("--dry-run", action="store_true", help="Show what would be copied")
    package_parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    package_parser.add_argument("--workspace", type=Path, help="Workspace root (optional)")
    package_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    # Summary command
    summary_parser = subparsers.add_parser("summary", help="Show packaging summary")
    summary_parser.add_argument("manifest", type=Path, help="Path to manifest JSON")
    summary_parser.add_argument("--workspace", type=Path, help="Workspace root (optional)")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if getattr(args, 'verbose', False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s"
    )
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Create packager
    workspace = getattr(args, 'workspace', None)
    packager = ModPackager(args.manifest, workspace)
    
    try:
        if args.command == "validate":
            packager.load_manifest()
            errors = packager.validate()
            
            if errors:
                print(f"\n{len(errors)} validation errors:")
                for err in errors[:10]:
                    print(f"  - {err}")
                if len(errors) > 10:
                    print(f"  ... and {len(errors) - 10} more")
                return 1
            else:
                print(f"\nValidation PASSED: {len(packager._copy_plans)} files ready to package")
                return 0
        
        elif args.command == "package":
            packager.load_manifest()
            result = packager.execute(dry_run=args.dry_run, overwrite=args.force)
            
            print(f"\n{result.get_summary()}")
            
            # Show category breakdown
            by_cat = result.get_by_category()
            if by_cat:
                print("\nBy category:")
                for cat, count in sorted(by_cat.items()):
                    print(f"  {cat}: {count}")
            
            return 0 if result.success else 1
        
        elif args.command == "summary":
            packager.load_manifest()
            summary = packager.get_copy_summary()
            
            print(f"\nPackaging Summary for: {packager.manifest.get('target_vehicle')}")
            print(f"Output folder: {packager.output_folder}")
            print()
            
            total = 0
            for cat, files in sorted(summary.items()):
                print(f"{cat} ({len(files)} files):")
                for f in files[:5]:
                    print(f"  - {f}")
                if len(files) > 5:
                    print(f"  ... and {len(files) - 5} more")
                total += len(files)
                print()
            
            print(f"Total: {total} files to package")
            return 0
    
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Invalid manifest JSON: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    exit(main())
