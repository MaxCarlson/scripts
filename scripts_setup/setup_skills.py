#!/usr/bin/env python3
"""
Discover SKILL.md files in scripts/modules/ and symlink their parent
directories into each supported CLI's skills directory.

Idempotent: only creates missing symlinks or replaces broken ones.
Never overwrites a non-symlink file/directory of the same name.

Supported targets:
  ~/.claude/skills/
  ~/.codex/skills/
  ~/.cursor/skills/
"""
import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import shared helpers from scripts_setup/setup_utils.py
# ---------------------------------------------------------------------------
try:
    from scripts_setup.setup_utils import create_symlink, _log_info, _log_success, _log_warning, _log_error
except ImportError:
    # Fallback when run standalone (not installed as a package)
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here.parent))
    from scripts_setup.setup_utils import create_symlink, _log_info, _log_success, _log_warning, _log_error


CLI_SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".codex" / "skills",
    Path.home() / ".cursor" / "skills",
]


def discover_skills(modules_dir: Path, verbose: bool = False) -> list[Path]:
    """Find all skill directories (folders containing SKILL.md) under modules_dir."""
    skills: list[Path] = []
    if not modules_dir.is_dir():
        _log_warning(f"Modules directory does not exist: {modules_dir}", verbose)
        return skills

    for skill_md in sorted(modules_dir.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        # Skip anything inside .egg-info, __pycache__, .git, refs, templates
        parts_str = str(skill_dir)
        if any(skip in parts_str for skip in (".egg-info", "__pycache__", ".git", "/refs/", "/templates/")):
            _log_info(f"Skipping non-skill SKILL.md: {skill_md}", verbose)
            continue
        skills.append(skill_dir)
        _log_info(f"Discovered skill: {skill_dir.name} ({skill_dir})", verbose)

    return skills


def symlink_skills(skills: list[Path], verbose: bool = False) -> tuple[int, int]:
    """Symlink discovered skills into each CLI skills directory.

    Returns (created_count, skipped_count).
    """
    created = 0
    skipped = 0

    for cli_dir in CLI_SKILL_DIRS:
        cli_dir.mkdir(parents=True, exist_ok=True)

        for skill_dir in skills:
            dest = cli_dir / skill_dir.name

            # If dest exists and is NOT a symlink, skip (don't clobber user files)
            if dest.exists() and not dest.is_symlink():
                _log_warning(
                    f"Skipping {dest}: exists and is not a symlink (won't overwrite user file)",
                    verbose,
                )
                skipped += 1
                continue

            # If dest is a symlink, only replace if broken or pointing elsewhere
            if dest.is_symlink():
                try:
                    current_target = dest.resolve()
                    expected_target = skill_dir.resolve()
                    if current_target == expected_target:
                        _log_info(f"Already linked: {dest.name} in {cli_dir}", verbose)
                        skipped += 1
                        continue
                except OSError:
                    # Broken symlink - will be replaced by create_symlink
                    pass

            if create_symlink(skill_dir, dest, verbose=verbose):
                created += 1
            else:
                skipped += 1

    return created, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover and symlink SKILL.md-based skills from scripts/modules/ to CLI skill directories."
    )
    parser.add_argument(
        "-m", "--modules-dir",
        type=Path,
        default=None,
        help="Root modules directory to scan (default: <scripts>/modules/)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    scripts_dir = Path(__file__).resolve().parents[1]
    modules_dir = args.modules_dir or (scripts_dir / "modules")

    skills = discover_skills(modules_dir, verbose=args.verbose)

    if not skills:
        _log_info("No skills discovered.", args.verbose)
        print("No SKILL.md files found in modules/. Nothing to link.")
        return

    print(f"Discovered {len(skills)} skill(s): {', '.join(s.name for s in skills)}")

    created, existing = symlink_skills(skills, verbose=args.verbose)

    if created:
        _log_success(f"Created {created} new skill symlink(s).", args.verbose)
    if existing:
        _log_info(f"{existing} skill symlink(s) already up to date.", args.verbose)
    if not created and not existing:
        print("No skill symlinks created or updated.")


if __name__ == "__main__":
    main()
