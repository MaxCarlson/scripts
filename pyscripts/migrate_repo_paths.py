#!/usr/bin/env python3
"""
Repo Path Migration Tool

Finds and rewrites all references to scripts/, dotfiles/, and W11-powershell repos
across multiple platforms (Windows, WSL, Termux) to a unified location.

Usage:
    python migrate_repo_paths.py --target ~/repos --dry-run
    python migrate_repo_paths.py --target ~/repos --backup --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Import cross_platform utilities
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "modules"))
    from cross_platform.system_utils import SystemUtils
    from cross_platform.fs_utils import find_files_by_extension
    from cross_platform.debug_utils import write_debug, set_console_verbosity
except ImportError as e:
    print(f"Error: Failed to import cross_platform module: {e}", file=sys.stderr)
    print("Ensure you're running from the scripts repository.", file=sys.stderr)
    sys.exit(1)


@dataclass
class PathReference:
    """Represents a single path reference found in a file."""
    file_path: Path
    line_number: int
    line_content: str
    old_path: str
    variable_name: str | None = None
    context: str = ""  # PowerShell, Zsh, Python, etc.


@dataclass
class MigrationPlan:
    """Migration plan with all detected references."""
    current_locations: dict[str, Path] = field(default_factory=dict)  # repo_name -> current_path
    target_location: Path | None = None
    references: list[PathReference] = field(default_factory=list)
    files_to_update: set[Path] = field(default_factory=set)


class RepoPathMigrator:
    """Migrates repository paths across all config files and scripts."""

    # Repo names to search for
    REPO_NAMES = ["scripts", "dotfiles", "W11-powershell"]

    # Parent directory patterns
    PARENT_PATTERNS = [
        r"(?:~/|~\\|\$HOME[\\/]|\$env:USERPROFILE[\\/]|\$env:HOME[\\/])(Repos|src)[\\/]",
        r"(?:/home/[^/]+/|C:\\Users\\[^\\]+\\)(Repos|src)[\\/]",
    ]

    # PowerShell environment variable patterns
    PS_ENV_VARS = [
        "PWSH_REPO",
        "SCRIPTS_REPO",
        "DOTFILES_REPO",
        "W11_ROOT",
        "SCRIPTS",
        "PSCRIPTS",
        "DOTFILES_PATH",
    ]

    # Zsh/Bash environment variable patterns
    ZSH_ENV_VARS = [
        "DOTFILES",
        "SCRIPTS",
        "PROJECTS",
    ]

    def __init__(self, verbose: bool = False):
        """Initialize the migrator."""
        self.sys_utils = SystemUtils()
        self.verbose = verbose
        if verbose:
            set_console_verbosity("Debug")

        self.plan = MigrationPlan()

        # Detect current platform
        self.is_windows = self.sys_utils.is_windows()
        self.is_wsl = self.sys_utils.is_wsl2()
        self.is_termux = self.sys_utils.is_termux()

        write_debug(
            f"Platform: Windows={self.is_windows}, WSL={self.is_wsl}, Termux={self.is_termux}",
            channel="Information"
        )

    def detect_current_locations(self) -> dict[str, Path]:
        """Detect current locations of repos on this machine."""
        write_debug("Detecting current repository locations...", channel="Information")

        home = Path.home()
        search_dirs = []

        # Platform-specific search locations
        if self.is_windows:
            search_dirs = [
                home / "Repos",
                home / "src",
                Path("C:/Projects"),
            ]
        elif self.is_wsl or self.is_termux:
            search_dirs = [
                home / "repos",
                home / "src",
                home / "Repos",
                home,  # Termux might have them directly in home
            ]
        else:  # macOS, other Linux
            search_dirs = [
                home / "repos",
                home / "src",
                home / "Repos",
                home / "projects",
            ]

        locations = {}
        for repo_name in self.REPO_NAMES:
            for search_dir in search_dirs:
                candidate = search_dir / repo_name
                if candidate.exists() and candidate.is_dir():
                    locations[repo_name] = candidate.resolve()
                    write_debug(f"Found {repo_name} at: {candidate}", channel="Information")
                    break

                # Also check for W11-powershell without hyphen
                if repo_name == "W11-powershell":
                    alt_candidate = search_dir / "W11powershell"
                    if alt_candidate.exists() and alt_candidate.is_dir():
                        locations[repo_name] = alt_candidate.resolve()
                        write_debug(f"Found {repo_name} at: {alt_candidate}", channel="Information")
                        break

        if not locations:
            write_debug("No repositories detected!", channel="Warning")

        self.plan.current_locations = locations
        return locations

    def find_all_references(self) -> list[PathReference]:
        """Find all references to repo paths in config files and scripts."""
        write_debug("Scanning for repository path references...", channel="Information")

        references = []

        # Files to scan based on current locations
        for repo_name, repo_path in self.plan.current_locations.items():
            write_debug(f"Scanning {repo_name} at {repo_path}...", channel="Debug")

            # Scan different file types
            references.extend(self._scan_powershell_files(repo_path))
            references.extend(self._scan_shell_files(repo_path))
            references.extend(self._scan_python_files(repo_path))

        # Also scan home directory config files
        references.extend(self._scan_home_configs())

        self.plan.references = references
        write_debug(f"Found {len(references)} references", channel="Information")

        return references

    def _scan_powershell_files(self, root: Path) -> list[PathReference]:
        """Scan PowerShell files for path references."""
        references = []

        # Find all .ps1 and .psm1 files
        for ext in ["ps1", "psm1"]:
            try:
                result = find_files_by_extension(
                    root,
                    ext,
                    exclude_dir_globs=["node_modules", ".git", "__pycache__", "venv", ".venv"]
                )

                for file_path in result.matched_files:
                    references.extend(self._scan_file_content(file_path, "PowerShell"))
            except Exception as e:
                write_debug(f"Error scanning {ext} files: {e}", channel="Warning")

        return references

    def _scan_shell_files(self, root: Path) -> list[PathReference]:
        """Scan shell script files for path references."""
        references = []

        # Find shell scripts
        for ext in ["sh", "bash", "zsh"]:
            try:
                result = find_files_by_extension(
                    root,
                    ext,
                    exclude_dir_globs=["node_modules", ".git", "__pycache__", "venv", ".venv"]
                )

                for file_path in result.matched_files:
                    references.extend(self._scan_file_content(file_path, "Shell"))
            except Exception as e:
                write_debug(f"Error scanning {ext} files: {e}", channel="Warning")

        # Also scan files without extension (common for shell configs)
        for file_name in ["zshrc", "bashrc", "zprofile", "bash_profile", "profile"]:
            for file_path in root.rglob(file_name):
                if file_path.is_file():
                    references.extend(self._scan_file_content(file_path, "Shell"))

        return references

    def _scan_python_files(self, root: Path) -> list[PathReference]:
        """Scan Python files for path references."""
        references = []

        try:
            result = find_files_by_extension(
                root,
                "py",
                exclude_dir_globs=["node_modules", ".git", "__pycache__", "venv", ".venv", ".pytest_cache"]
            )

            for file_path in result.matched_files:
                references.extend(self._scan_file_content(file_path, "Python"))
        except Exception as e:
            write_debug(f"Error scanning Python files: {e}", channel="Warning")

        return references

    def _scan_home_configs(self) -> list[PathReference]:
        """Scan home directory config files."""
        references = []
        home = Path.home()

        # Config files to check in home directory
        config_files = [
            ".zshrc",
            ".bashrc",
            ".bash_profile",
            ".zprofile",
            ".profile",
        ]

        # PowerShell profiles
        if self.is_windows:
            ps_profile = Path.home() / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
            if ps_profile.exists():
                references.extend(self._scan_file_content(ps_profile, "PowerShell"))

        for config_file in config_files:
            file_path = home / config_file
            if file_path.exists():
                references.extend(self._scan_file_content(file_path, "Shell"))

        return references

    def _scan_file_content(self, file_path: Path, context: str) -> list[PathReference]:
        """Scan a single file for path references."""
        references = []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            write_debug(f"Error reading {file_path}: {e}", channel="Warning")
            return references

        # Patterns to search for
        patterns = []

        # Add parent directory patterns
        patterns.extend([
            # PowerShell patterns
            (r'\$HOME[\\/](Repos|src)[\\/](scripts|dotfiles|W11-powershell)', "PS_Path"),
            (r'\$env:USERPROFILE[\\/](Repos|src)[\\/](scripts|dotfiles|W11-powershell)', "PS_Path"),
            (r'C:\\Users\\[^\\]+\\(Repos|src)[\\/](scripts|dotfiles|W11-powershell)', "PS_Path"),

            # Zsh/Bash patterns
            (r'~/?(Repos|src)/(scripts|dotfiles|W11-powershell)', "Shell_Path"),
            (r'\$HOME/?(Repos|src)/(scripts|dotfiles|W11-powershell)', "Shell_Path"),
            (r'/home/[^/]+/(Repos|src)/(scripts|dotfiles|W11-powershell)', "Shell_Path"),

            # Environment variable assignments (PowerShell)
            (r'\$env:(PWSH_REPO|SCRIPTS_REPO|DOTFILES_REPO|W11_ROOT|SCRIPTS|PSCRIPTS|DOTFILES_PATH)\s*=\s*["\']?([^"\';\r\n]+)', "PS_Env"),
            (r'\$global:(PWSH_REPO|SCRIPTS_REPO|DOTFILES_REPO|SCRIPTS)\s*=\s*["\']?([^"\';\r\n]+)', "PS_Global"),

            # Environment variable assignments (Shell)
            (r'export\s+(DOTFILES|SCRIPTS|PROJECTS)=([^\s;]+)', "Shell_Export"),
            (r'^(DOTFILES|SCRIPTS|PROJECTS)=([^\s;#]+)', "Shell_Var"),
        ])

        for line_num, line in enumerate(lines, start=1):
            for pattern, var_type in patterns:
                for match in re.finditer(pattern, line):
                    # Extract the matched path
                    old_path = match.group(0)

                    # Try to extract variable name if it's an assignment
                    variable_name = None
                    if var_type in ["PS_Env", "PS_Global", "Shell_Export", "Shell_Var"]:
                        variable_name = match.group(1)

                    ref = PathReference(
                        file_path=file_path,
                        line_number=line_num,
                        line_content=line.rstrip(),
                        old_path=old_path,
                        variable_name=variable_name,
                        context=context
                    )
                    references.append(ref)

                    # Track files that need updating
                    self.plan.files_to_update.add(file_path)

        return references

    def create_migration_plan(self, target: Path) -> MigrationPlan:
        """Create a migration plan to the target location."""
        self.plan.target_location = target.expanduser().resolve()
        write_debug(f"Target location: {self.plan.target_location}", channel="Information")

        # Detect current locations
        self.detect_current_locations()

        # Find all references
        self.find_all_references()

        return self.plan

    def print_migration_plan(self):
        """Print the migration plan for user review."""
        print("\n" + "=" * 80)
        print("REPOSITORY PATH MIGRATION PLAN")
        print("=" * 80)

        print("\n📂 Current Locations:")
        for repo_name, repo_path in self.plan.current_locations.items():
            print(f"  {repo_name:20} → {repo_path}")

        print(f"\n🎯 Target Location: {self.plan.target_location}")

        print(f"\n📝 Found {len(self.plan.references)} references in {len(self.plan.files_to_update)} files")

        # Group by file
        files_by_context = {}
        for ref in self.plan.references:
            context = ref.context
            if context not in files_by_context:
                files_by_context[context] = set()
            files_by_context[context].add(ref.file_path)

        print("\n📋 Files to update by type:")
        for context, files in sorted(files_by_context.items()):
            print(f"  {context:15} {len(files)} files")

        # Show sample references
        print("\n🔍 Sample references (first 10):")
        for i, ref in enumerate(self.plan.references[:10], 1):
            rel_path = ref.file_path.relative_to(Path.home()) if ref.file_path.is_relative_to(Path.home()) else ref.file_path
            print(f"\n  {i}. {rel_path}:{ref.line_number}")
            print(f"     {ref.line_content[:100]}")
            if ref.variable_name:
                print(f"     Variable: {ref.variable_name}")

        if len(self.plan.references) > 10:
            print(f"\n  ... and {len(self.plan.references) - 10} more references")

        print("\n" + "=" * 80)

    def apply_migration(self, backup: bool = True, dry_run: bool = False) -> bool:
        """Apply the migration plan."""
        if not self.plan.target_location:
            print("Error: No target location set. Create a plan first.", file=sys.stderr)
            return False

        if dry_run:
            print("\n🔍 DRY RUN MODE - No changes will be made\n")

        # Create backup if requested
        if backup and not dry_run:
            self._create_backup()

        # Group references by file for efficient processing
        refs_by_file = {}
        for ref in self.plan.references:
            if ref.file_path not in refs_by_file:
                refs_by_file[ref.file_path] = []
            refs_by_file[ref.file_path].append(ref)

        # Process each file
        success_count = 0
        error_count = 0

        for file_path, refs in refs_by_file.items():
            try:
                if self._rewrite_file(file_path, refs, dry_run):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                write_debug(f"Error processing {file_path}: {e}", channel="Error")
                error_count += 1

        # Print summary
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Migration Summary:")
        print(f"  ✅ Successfully processed: {success_count} files")
        print(f"  ❌ Errors: {error_count} files")

        return error_count == 0

    def _create_backup(self):
        """Create backup of all files to be modified."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path.home() / f".repo_migration_backup_{timestamp}"
        backup_dir.mkdir(exist_ok=True)

        write_debug(f"Creating backup in: {backup_dir}", channel="Information")

        for file_path in self.plan.files_to_update:
            try:
                # Create relative path structure in backup
                if file_path.is_relative_to(Path.home()):
                    rel_path = file_path.relative_to(Path.home())
                else:
                    rel_path = file_path.name

                backup_path = backup_dir / rel_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(file_path, backup_path)
                write_debug(f"Backed up: {file_path}", channel="Debug")
            except Exception as e:
                write_debug(f"Error backing up {file_path}: {e}", channel="Warning")

        print(f"\n💾 Backup created: {backup_dir}")

    def _rewrite_file(self, file_path: Path, refs: list[PathReference], dry_run: bool) -> bool:
        """Rewrite a file with updated paths."""
        try:
            # Read file content
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            original_content = content

            # Determine path separators based on file type
            is_powershell = file_path.suffix in [".ps1", ".psm1"]
            separator = "\\" if is_powershell else "/"

            # Build replacement patterns
            for repo_name in self.REPO_NAMES:
                if repo_name not in self.plan.current_locations:
                    continue

                old_repo_path = self.plan.current_locations[repo_name]
                new_repo_path = self.plan.target_location / repo_name

                # Create various path representations
                old_patterns = self._generate_path_patterns(old_repo_path, is_powershell)
                new_path_str = self._format_path(new_repo_path, is_powershell)

                # Replace all patterns
                for old_pattern in old_patterns:
                    content = content.replace(old_pattern, new_path_str)

            # Write back if changed
            if content != original_content:
                if dry_run:
                    print(f"[DRY RUN] Would update: {file_path}")
                    return True

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                write_debug(f"Updated: {file_path}", channel="Information")
                return True
            else:
                write_debug(f"No changes needed: {file_path}", channel="Debug")
                return True

        except Exception as e:
            write_debug(f"Error rewriting {file_path}: {e}", channel="Error")
            return False

    def _generate_path_patterns(self, path: Path, is_powershell: bool) -> list[str]:
        """Generate various representations of a path for replacement."""
        patterns = []

        # Absolute path
        patterns.append(str(path))

        # With different separators
        if is_powershell:
            patterns.append(str(path).replace("/", "\\"))
        else:
            patterns.append(str(path).replace("\\", "/"))

        # Relative to home
        try:
            rel_to_home = path.relative_to(Path.home())
            if is_powershell:
                patterns.append(f"$HOME\\{rel_to_home}".replace("/", "\\"))
                patterns.append(f"$env:USERPROFILE\\{rel_to_home}".replace("/", "\\"))
            else:
                patterns.append(f"$HOME/{rel_to_home}".replace("\\", "/"))
                patterns.append(f"~/{rel_to_home}".replace("\\", "/"))
        except ValueError:
            pass

        return patterns

    def _format_path(self, path: Path, is_powershell: bool) -> str:
        """Format a path for the target system."""
        try:
            rel_to_home = path.relative_to(Path.home())
            if is_powershell:
                return f"$HOME\\{rel_to_home}".replace("/", "\\")
            else:
                return f"$HOME/{rel_to_home}".replace("\\", "/")
        except ValueError:
            # Can't make relative to home, use absolute
            if is_powershell:
                return str(path).replace("/", "\\")
            else:
                return str(path).replace("\\", "/")


def main():
    """Main entry point."""
    # Fix Windows console encoding
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="Migrate repository paths across all config files and scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would change
  python migrate_repo_paths.py -t ~/repos -n

  # Create backup and apply migration
  python migrate_repo_paths.py -t ~/repos -b --apply

  # Apply without backup (not recommended)
  python migrate_repo_paths.py -t ~/repos --apply
        """
    )

    parser.add_argument(
        "-t", "--target",
        required=True,
        type=Path,
        help="Target directory where all repos will be located (e.g., ~/repos)"
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    parser.add_argument(
        "-b", "--backup",
        action="store_true",
        default=True,
        help="Create backup before making changes (default: True)"
    )
    parser.add_argument(
        "--no-backup",
        action="store_false",
        dest="backup",
        help="Skip creating backup"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration (required to make actual changes)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Create migrator
    migrator = RepoPathMigrator(verbose=args.verbose)

    # Create migration plan
    print("🔍 Analyzing current repository configuration...")
    plan = migrator.create_migration_plan(args.target)

    # Print plan
    migrator.print_migration_plan()

    # Apply if requested
    if args.apply:
        if not args.dry_run:
            confirm = input("\n⚠️  Proceed with migration? (yes/no): ")
            if confirm.lower() != "yes":
                print("Migration cancelled.")
                return 0

        success = migrator.apply_migration(backup=args.backup, dry_run=args.dry_run)
        return 0 if success else 1
    else:
        print("\n💡 To apply this migration, run with --apply flag")
        print(f"   Example: python {Path(__file__).name} -t {args.target} --apply")
        return 0


if __name__ == "__main__":
    sys.exit(main())
