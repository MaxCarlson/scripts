"""scripts-help — interactive help browser and registry/README sync for the scripts repository."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts_help._repo_root import find_repo_root
from scripts_help.registry import (
    REGISTRY,
    OVERLAP_NOTES,
    EXCLUDED_SCRIPTS,
    collect_stale_items,
    read_live_version,
    find_readme,
    read_readme_version,
    collect_readme_drift,
)
from scripts_help.registry.versions import is_stale

# ── Drift collection ──────────────────────────────────────────────────────────

def _collect_registered_paths() -> set[str]:
    paths: set[str] = set()

    def _walk(node: dict) -> None:
        for item in node.get("items", []):
            paths.add(item["path"])
        for sub in node.get("subcategories", {}).values():
            _walk(sub)

    for cat in REGISTRY.values():
        _walk(cat)
    return paths


def _collect_registered_items() -> list[dict]:
    items: list[dict] = []

    def _walk(node: dict) -> None:
        items.extend(node.get("items", []))
        for sub in node.get("subcategories", {}).values():
            _walk(sub)

    for cat in REGISTRY.values():
        _walk(cat)
    return items


def _discover_cli_programs() -> set[str]:
    found: set[str] = set()
    repo = find_repo_root()

    pyscripts_dir = repo / "pyscripts"
    if pyscripts_dir.exists():
        for p in pyscripts_dir.glob("*.py"):
            if not p.name.startswith("_") and p.name != "help.py":
                found.add(f"pyscripts/{p.name}")

    modules_dir = repo / "modules"
    if modules_dir.exists():
        for mod in modules_dir.iterdir():
            if mod.is_dir() and not mod.name.startswith("_"):
                if (mod / "cli.py").exists() or (mod / "__main__.py").exists():
                    found.add(f"modules/{mod.name}")

    return found


def collect_drift() -> dict:
    """Return all detected drift across registry, READMEs, and discovered programs.

    Keys:
      "new"     — discovered programs not in the registry
      "stale"   — registry items whose live major/minor version is higher
      "deleted" — registry items whose path no longer exists
      "readme"  — items with README version issues (missing/no_tag/mismatch)
    """
    repo = find_repo_root()
    registered_paths = _collect_registered_paths()
    discovered = _discover_cli_programs()

    new_programs = sorted(discovered - registered_paths - EXCLUDED_SCRIPTS)
    stale_items = collect_stale_items(REGISTRY)

    deleted_items = []
    for item in _collect_registered_items():
        p = repo / item["path"]
        missing = not p.is_dir() if item["path"].startswith("modules/") else not p.is_file()
        if missing:
            deleted_items.append(item)

    readme_items = collect_readme_drift(REGISTRY, read_live_version)

    return {
        "new": new_programs,
        "stale": stale_items,
        "deleted": deleted_items,
        "readme": readme_items,
    }


# ── UI helpers ────────────────────────────────────────────────────────────────

_DIVIDER = "-" * 64
_HEADER  = "=" * 64


def _prompt(max_n: int, *, back: bool = False) -> int | None:
    hint = f"1-{max_n}"
    extras = "  b=back" if back else ""
    extras += "  q=quit"
    while True:
        try:
            raw = input(f"\n  [{hint}{extras}] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if raw == "q":
            sys.exit(0)
        if raw in ("b", "0") and back:
            return None
        try:
            n = int(raw)
            if 1 <= n <= max_n:
                return n
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {max_n}.")


def _header(title: str) -> None:
    print(f"\n{_HEADER}")
    print(f"  {title}")
    print(_HEADER)


def _wrap(text: str, width: int = 62, indent: str = "  ") -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(indent + candidate) > width and line:
            lines.append(indent + line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(indent + line)
    return "\n".join(lines)


# ── Warning display (browse mode startup) ────────────────────────────────────

def _print_warnings(drift: dict) -> None:
    width = 64

    if drift["stale"]:
        print()
        print("!" * width)
        print("  WARNING: registry entries may be out of date.")
        print("  Live major/minor version is higher than recorded:\n")
        for s in drift["stale"]:
            print(f"    * {s['name']}")
            print(f"      registry: {s['registry_version']}  |  live: {s['live_version']}")
        print()
        print("  Run: scripts-help sync  to update via AI.")
        print("!" * width)

    if drift["new"]:
        print()
        print("!" * width)
        print("  WARNING: programs not yet in the help registry:")
        for p in drift["new"]:
            print(f"    * {p}")
        print("  Run: scripts-help sync  to update via AI.")
        print("!" * width)

    if drift["deleted"]:
        print()
        print("!" * width)
        print("  WARNING: registry references paths that no longer exist:")
        for item in drift["deleted"]:
            print(f"    * {item['name']}  ({item['path']})")
        print("  Run: scripts-help sync  to update via AI.")
        print("!" * width)

    # Summarise README drift without itemising (avoids wall of text on first run)
    mismatch = [r for r in drift["readme"] if r["issue"] == "version_mismatch"]
    no_tag   = [r for r in drift["readme"] if r["issue"] == "no_version_tag"]
    if mismatch or no_tag:
        print()
        print("!" * width)
        print("  WARNING: README version issues detected:")
        if mismatch:
            print(f"    {len(mismatch)} version mismatch(es)")
        if no_tag:
            print(f"    {len(no_tag)} missing version tag(s)")
        print("  Run: scripts-help drift --readme  for details.")
        print("  Run: scripts-help sync  --readme  to update via AI.")
        print("!" * width)


# ── Drift report (drift subcommand) ──────────────────────────────────────────

def _print_drift_report(drift: dict, *, show_registry: bool = True,
                         show_readme: bool = True, verbose: bool = False) -> None:
    any_output = False

    if show_registry:
        reg_clean = not drift["new"] and not drift["stale"] and not drift["deleted"]
        if reg_clean:
            print("REGISTRY  clean")
        else:
            any_output = True
            print("REGISTRY DRIFT")
            print(_DIVIDER)
            if drift["new"]:
                print(f"  new programs ({len(drift['new'])}):")
                for p in drift["new"]:
                    print(f"    + {p}")
            if drift["stale"]:
                print(f"  stale versions ({len(drift['stale'])}):")
                for s in drift["stale"]:
                    print(f"    ~ {s['name']}")
                    print(f"      registry={s['registry_version']}  live={s['live_version']}")
            if drift["deleted"]:
                print(f"  deleted paths ({len(drift['deleted'])}):")
                for item in drift["deleted"]:
                    print(f"    - {item['name']}  ({item['path']})")

    if show_readme:
        mismatch = [r for r in drift["readme"] if r["issue"] == "version_mismatch"]
        no_tag   = [r for r in drift["readme"] if r["issue"] == "no_version_tag"]
        missing  = [r for r in drift["readme"] if r["issue"] == "missing"]
        readme_clean = not mismatch and not no_tag

        if show_registry:
            print()

        if readme_clean and (not missing or not verbose):
            msg = "README  clean"
            if missing:
                msg += f"  ({len(missing)} items have no README yet — run with -v to list)"
            print(msg)
        else:
            any_output = True
            print("README DRIFT")
            print(_DIVIDER)
            if mismatch:
                print(f"  version mismatch ({len(mismatch)}):")
                for r in mismatch:
                    print(f"    ~ {r['name']}")
                    print(f"      README={r['readme_version']}  program={r['program_version']}  ({r['readme_path']})")
            if no_tag:
                print(f"  missing version tag ({len(no_tag)}):")
                for r in no_tag:
                    print(f"    ? {r['name']}  ({r['readme_path']})")
            if missing:
                if verbose:
                    print(f"  no README ({len(missing)}):")
                    for r in missing:
                        print(f"    ! {r['name']}  ({r['path']})")
                else:
                    print(f"  no README: {len(missing)} items  (use -v to list)")


# ── AI prompt builder ─────────────────────────────────────────────────────────

_REGISTRY_REL = "modules/scripts_help/scripts_help/registry/registry.py"
_EXCLUDED_REL = "modules/scripts_help/scripts_help/registry/excluded.py"
_OVERLAPS_REL = "modules/scripts_help/scripts_help/registry/overlaps.py"

_REGISTRY_ITEM_TEMPLATE = """\
            {
                "name": "<display name>",
                "path": "<pyscripts/foo.py or modules/bar>",
                "desc": "<one-line description>",
                "help_cmd": ["python", "<pyscripts/foo.py or -m bar>", "--help"],
                "version": "<X.Y.Z from __version__ or pyproject.toml>",
            },\
"""

_README_TEMPLATE = """\
<!-- version: X.Y.Z -->
# <Program Name>

<One-paragraph description of what the program does.>

## Usage

```
<program> [options]
```

## Options

| Flag | Description |
|------|-------------|
| `-v/--verbose` | Enable verbose output |

## Examples

```bash
<example command>
```\
"""


def _build_update_prompt(drift: dict, *, registry: bool = True, readme: bool = True) -> str:
    repo = find_repo_root()
    registry_abs = repo / _REGISTRY_REL
    excluded_abs = repo / _EXCLUDED_REL
    overlaps_abs = repo / _OVERLAPS_REL

    sections: list[str] = []

    sections.append(textwrap.dedent(f"""\
        You are updating the scripts-help registry and/or READMEs in this repository.

        Key files:
            {registry_abs}   ← registry entries
            {excluded_abs}   ← shims/non-user scripts to suppress
            {overlaps_abs}   ← overlap/refactoring notes

        README convention:
            modules/<name>/README.md            — module READMEs
            pyscripts/readme/<stem>.md          — pyscript READMEs
            Every README must contain on one of its first 15 lines:
                <!-- version: X.Y.Z -->
            where X.Y.Z matches the program's current version.

        Read affected files before making any changes.
    """))

    if registry:
        if drift["new"]:
            lines = ["## NEW PROGRAMS — add a registry entry for each\n"]
            lines.append("For each program listed:")
            lines.append("  1. Read the file to understand what it does.")
            lines.append("  2. Choose the correct category/subcategory.")
            lines.append(f"  3. Add an entry using this template:\n{_REGISTRY_ITEM_TEMPLATE}")
            lines.append("  4. If it overlaps an existing entry, add a note to overlaps.py.")
            lines.append("")
            for p in drift["new"]:
                lines.append(f"  NEW: {p}")
            sections.append("\n".join(lines))

        if drift["stale"]:
            lines = ["## STALE REGISTRY VERSIONS — update version field and description if needed\n"]
            lines.append("For each entry:")
            lines.append("  1. Check the module's changelog or recent git log.")
            lines.append("  2. Update the \"version\" field to match the live version.")
            lines.append("  3. Update the description if the interface changed.")
            lines.append("")
            for s in drift["stale"]:
                lines.append(f"  STALE: {s['name']}")
                lines.append(f"         registry={s['registry_version']}  live={s['live_version']}")
            sections.append("\n".join(lines))

        if drift["deleted"]:
            lines = ["## DELETED PROGRAMS — remove these registry entries\n"]
            lines.append("  1. Remove the entry from registry.py.")
            lines.append("  2. Remove or update any overlaps.py references.")
            lines.append("")
            for item in drift["deleted"]:
                lines.append(f"  DELETED: {item['name']}  ({item['path']})")
            sections.append("\n".join(lines))

    if readme:
        mismatch = [r for r in drift["readme"] if r["issue"] == "version_mismatch"]
        no_tag   = [r for r in drift["readme"] if r["issue"] == "no_version_tag"]
        missing  = [r for r in drift["readme"] if r["issue"] == "missing"]

        if mismatch or no_tag:
            lines = ["## README VERSION SYNC — fix existing READMEs\n"]
            if mismatch:
                lines.append("Version mismatch — update the <!-- version: X.Y.Z --> tag:")
                for r in mismatch:
                    lines.append(f"  MISMATCH: {r['name']}")
                    lines.append(f"            README={r['readme_version']}  "
                                 f"program={r['program_version']}  ({r['readme_path']})")
                lines.append("")
            if no_tag:
                lines.append("Missing version tag — add <!-- version: X.Y.Z --> within the first 15 lines:")
                for r in no_tag:
                    prog_ver = r["program_version"] or "unknown"
                    lines.append(f"  NO TAG: {r['name']}  ({r['readme_path']})")
                    lines.append(f"          current program version: {prog_ver}")
                lines.append("")
            sections.append("\n".join(lines))

        if missing:
            lines = [f"## MISSING READMEs — create {len(missing)} new README file(s)\n"]
            lines.append("For each program, create a README at its canonical location:")
            lines.append("  modules/<name>/README.md      or")
            lines.append("  pyscripts/readme/<stem>.md")
            lines.append("")
            lines.append(f"Use this template:\n{_README_TEMPLATE}")
            lines.append("")
            lines.append("Programs needing READMEs:")
            for r in missing:
                prog_ver = r["program_version"] or "unknown"
                lines.append(f"  {r['name']}  ({r['path']})  version={prog_ver}")
            sections.append("\n".join(lines))

    sections.append(textwrap.dedent("""\
        ## VALIDATION

        After making registry changes, verify the registry loads:
            python -c "
            import sys; sys.path.insert(0, 'modules/scripts_help')
            from scripts_help.registry import REGISTRY
            total = sum(
                len(n.get('items', [])) + sum(len(s.get('items', [])) for s in n.get('subcategories', {}).values())
                for n in REGISTRY.values()
            )
            print(f'Registry OK: {total} items across {len(REGISTRY)} categories')
            "

        After making README changes, verify version tags parse correctly:
            python -c "
            import sys; sys.path.insert(0, 'modules/scripts_help')
            from scripts_help.registry import collect_readme_drift, REGISTRY, read_live_version
            drift = collect_readme_drift(REGISTRY, read_live_version)
            issues = [r for r in drift if r['issue'] != 'missing']
            print(f'README issues remaining: {len(issues)}')
            for r in issues: print(f'  {r[\"name\"]}: {r[\"issue\"]}')
            "

        Then run  scripts-help  to confirm everything looks correct.
    """))

    return "\n\n" + ("\n\n" + "─" * 60 + "\n\n").join(sections)


# ── AI launch helpers ─────────────────────────────────────────────────────────

def _ai_available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _offer_copy_prompt(prompt: str) -> None:
    print("\n  The update prompt:")
    print()
    print(_DIVIDER)
    print(prompt)
    print(_DIVIDER)
    try:
        if shutil.which("clip"):
            subprocess.run(["clip"], input=prompt.encode(), check=False)
            print("\n  (Copied to clipboard via clip)")
        elif shutil.which("pbcopy"):
            subprocess.run(["pbcopy"], input=prompt.encode(), check=False)
            print("\n  (Copied to clipboard via pbcopy)")
        elif shutil.which("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=prompt.encode(), check=False)
            print("\n  (Copied to clipboard via xclip)")
    except Exception:
        pass
    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def _launch_ai(cmd: str, prompt: str) -> None:
    print(f"\n  Launching {cmd} in the repo root...")
    print("  It will read the affected files and make targeted edits.")
    print("  Review and approve any file edits it proposes.\n")
    try:
        input("  Press Enter to continue (Ctrl-C to cancel)...")
    except (EOFError, KeyboardInterrupt):
        print()
        return
    try:
        repo = find_repo_root()
        os.chdir(str(repo))
        os.execvp(cmd, [cmd, prompt])
    except FileNotFoundError:
        print(f"\n  Error: '{cmd}' not found on PATH.")
    except Exception as exc:
        print(f"\n  Error launching {cmd}: {exc}")
        _offer_copy_prompt(prompt)


def _run_sync_menu(drift: dict, *, registry: bool = True, readme: bool = True,
                   dry_run: bool = False, copy: bool = False) -> None:
    """Interactive menu to offer AI sync. Used by both browse and sync subcommand."""
    has_registry_drift = registry and (drift["new"] or drift["stale"] or drift["deleted"])
    has_readme_drift = readme and drift["readme"]

    if not has_registry_drift and not has_readme_drift:
        print("  Nothing to sync — no drift detected.")
        return

    prompt = _build_update_prompt(drift, registry=registry, readme=readme)

    if dry_run:
        print(prompt)
        return
    if copy:
        _offer_copy_prompt(prompt)
        return

    _header("REGISTRY/README SYNC — AUTO-UPDATE OPTION")

    parts = []
    if has_registry_drift:
        reg_parts = []
        if drift["new"]:     reg_parts.append(f"{len(drift['new'])} new")
        if drift["stale"]:   reg_parts.append(f"{len(drift['stale'])} stale")
        if drift["deleted"]: reg_parts.append(f"{len(drift['deleted'])} deleted")
        parts.append("Registry: " + ", ".join(reg_parts))
    if has_readme_drift:
        rd_parts: dict[str, int] = {}
        for r in drift["readme"]:
            rd_parts[r["issue"]] = rd_parts.get(r["issue"], 0) + 1
        readme_summary = ", ".join(f"{v} {k}" for k, v in rd_parts.items())
        parts.append("README: " + readme_summary)

    print()
    for p in parts:
        print(f"  {p}")
    print()

    options: list[tuple[str, str]] = []
    if _ai_available("claude"):
        options.append(("Claude Code  (claude)", "claude"))
    if _ai_available("codex"):
        options.append(("Codex        (codex)", "codex"))

    if not options:
        print("  Neither 'claude' nor 'codex' found on PATH.")
        _offer_copy_prompt(prompt)
        return

    print("  Launch an AI assistant to fix the above:\n")
    for i, (label, _) in enumerate(options, 1):
        print(f"  {i}.  {label}")
    print(f"  {len(options) + 1}.  Copy the prompt to clipboard (update manually)")
    print(f"  {len(options) + 2}.  Skip")

    while True:
        try:
            raw = input(f"\n  [1-{len(options) + 2}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            choice = int(raw)
        except ValueError:
            continue
        if 1 <= choice <= len(options):
            _launch_ai(options[choice - 1][1], prompt)
            return
        if choice == len(options) + 1:
            _offer_copy_prompt(prompt)
            return
        if choice == len(options) + 2:
            return


# ── Browse UI helpers ─────────────────────────────────────────────────────────

def _show_overlap_notes() -> None:
    _header("REFACTORING / OVERLAP NOTES")
    print("  Programs with significant overlap — candidates for consolidation:\n")
    for i, note in enumerate(OVERLAP_NOTES, 1):
        print(f"  {i}. {note['group']}")
        for p in note["programs"]:
            print(f"       * {p}")
        print(_wrap(note["note"], width=64, indent="     "))
        print()
    try:
        input("  Press Enter to return to the main menu...")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def _find_readme_for_display(item: dict) -> Path | None:
    """Find README for browse display — canonical location first, then fallback scan."""
    repo = find_repo_root()
    p = find_readme(item, repo)
    if p:
        return p
    # Fallback: scan around the item path (non-standard locations)
    base = repo / item["path"]
    for candidate in [base.parent / "README.md", base / "README.md",
                       base.parent / "readme.md", base / "readme.md"]:
        if candidate.is_file():
            return candidate
    return None


def _render_in_glow(text: str) -> None:
    if shutil.which("glow"):
        try:
            subprocess.run(["glow", "-"], input=text.encode("utf-8"), check=False)
            return
        except Exception:
            pass
    print(text)


def _run_help_cmd(item: dict) -> None:
    repo = find_repo_root()
    resolved: list[str] = []
    after_m = False
    for part in item["help_cmd"]:
        if part == "python":
            resolved.append(sys.executable)
        elif part == "-m":
            after_m = True
            resolved.append(part)
        elif after_m or part.startswith("-"):
            resolved.append(part)
        else:
            candidate = repo / part
            resolved.append(str(candidate) if candidate.exists() else part)

    try:
        result = subprocess.run(resolved, capture_output=True, text=True,
                                cwd=str(repo), timeout=10)
        output = (result.stdout or "") + (result.stderr or "")
        print(output.strip() if output.strip() else "  (No help output available)")
    except FileNotFoundError:
        print("  (Could not locate the script or interpreter)")
    except subprocess.TimeoutExpired:
        print("  (Help command timed out after 10 s)")
    except Exception as exc:
        print(f"  (Error running help: {exc})")


def _show_program_help(item: dict) -> None:
    repo = find_repo_root()
    while True:
        _header(item["name"])
        print(f"  Path:   {item['path']}")
        cmd_display = item["help_cmd"][:-1]
        print(f"  Invoke: {' '.join(cmd_display)}")

        reg_ver = item.get("version")
        if reg_ver:
            live_ver = read_live_version(item["path"])
            if live_ver:
                stale_flag = "  [!] may be outdated" if is_stale(reg_ver, live_ver) else ""
                print(f"  Version: {live_ver}  (registry: {reg_ver}){stale_flag}")
            else:
                print(f"  Version: {reg_ver}  (recorded; live unreadable)")

        readme = _find_readme_for_display(item)
        has_glow = shutil.which("glow") is not None

        # README version sync status
        if readme:
            readme_ver = read_readme_version(readme)
            readme_rel = readme.relative_to(repo)
            if readme_ver is None:
                print(f"  README:  {readme_rel}  [no version tag]")
            elif reg_ver and readme_ver != (read_live_version(item["path"]) or reg_ver):
                print(f"  README:  {readme_rel}  [version {readme_ver} — out of sync]")
            else:
                print(f"  README:  {readme_rel}  (v{readme_ver})")

        print()
        print("  1.  Show --help output")
        if readme:
            glow_note = "  [rendered via glow]" if has_glow else ""
            readme_rel = readme.relative_to(repo)
            print(f"  2.  Open README  ({readme_rel}){glow_note}")

        max_opt = 2 if readme else 1
        choice = _prompt(max_opt, back=True)
        if choice is None:
            return

        print(_DIVIDER)
        print()

        if choice == 1:
            _run_help_cmd(item)
            print()
            try:
                input("  Press Enter to go back...")
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit(0)
        elif choice == 2 and readme:
            _render_in_glow(readme.read_text(encoding="utf-8", errors="replace"))
            # glow has its own pager — user already quit it, return to menu immediately


def _show_items(context: str, items: list[dict]) -> None:
    while True:
        _header(context)
        print("  Select a program:\n")
        for i, item in enumerate(items, 1):
            print(f"  {i:2}.  {item['name']}")
            print(f"        {item['desc']}")
        choice = _prompt(len(items), back=True)
        if choice is None:
            return
        _show_program_help(items[choice - 1])


def _show_subcategories(cat_name: str, cat: dict) -> None:
    subs = list(cat["subcategories"].keys())
    while True:
        _header(cat_name)
        print(f"  {cat['desc']}\n")
        print("  Select a subcategory:\n")
        for i, name in enumerate(subs, 1):
            print(f"  {i:2}.  {name}")
            print(f"        {cat['subcategories'][name]['desc']}")
        choice = _prompt(len(subs), back=True)
        if choice is None:
            return
        sub_name = subs[choice - 1]
        sub = cat["subcategories"][sub_name]
        _show_items(f"{cat_name}  >  {sub_name}", sub["items"])


def _main_menu(drift: dict) -> None:
    cats = list(REGISTRY.keys())
    OVERLAP_OPT = len(cats) + 1
    has_drift = (drift["new"] or drift["stale"] or drift["deleted"]
                 or any(r["issue"] != "missing" for r in drift["readme"]))
    UPDATE_OPT = len(cats) + 2 if has_drift else None
    max_opt = UPDATE_OPT or OVERLAP_OPT

    while True:
        _header("SCRIPTS & MODULES HELP BROWSER")
        print("  What do you want to do?\n")
        for i, name in enumerate(cats, 1):
            print(f"  {i:2}.  {name}")
            print(f"        {REGISTRY[name]['desc']}")
        print()
        print(f"  {OVERLAP_OPT:2}.  Refactoring / Overlap Notes")
        print(f"        Programs with significant overlap — candidates for consolidation")

        if UPDATE_OPT:
            drift_parts = []
            if drift["new"]:     drift_parts.append(f"{len(drift['new'])} new")
            if drift["stale"]:   drift_parts.append(f"{len(drift['stale'])} stale")
            if drift["deleted"]: drift_parts.append(f"{len(drift['deleted'])} deleted")
            rd = [r for r in drift["readme"] if r["issue"] != "missing"]
            if rd:
                drift_parts.append(f"{len(rd)} readme")
            print(f"  {UPDATE_OPT:2}.  Sync Registry / READMEs via AI  [{', '.join(drift_parts)}]")
            print(f"        Launch Claude or Codex to fix detected drift")

        choice = _prompt(max_opt)

        if choice == OVERLAP_OPT:
            _show_overlap_notes()
        elif choice == UPDATE_OPT:
            _run_sync_menu(drift)
        else:
            cat_name = cats[choice - 1]
            cat = REGISTRY[cat_name]
            if "subcategories" in cat:
                _show_subcategories(cat_name, cat)
            else:
                _show_items(cat_name, cat["items"])


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_browse(args) -> None:
    drift = collect_drift()
    _print_warnings(drift)
    _main_menu(drift)


def cmd_drift(args) -> None:
    registry_only = getattr(args, "registry_only", False)
    readme_only   = getattr(args, "readme_only", False)
    verbose       = getattr(args, "verbose", False)
    quiet         = getattr(args, "quiet", False)

    show_registry = not readme_only
    show_readme   = not registry_only

    drift = collect_drift()

    if not quiet:
        _print_drift_report(drift, show_registry=show_registry,
                            show_readme=show_readme, verbose=verbose)

    has_drift = False
    if show_registry and (drift["new"] or drift["stale"] or drift["deleted"]):
        has_drift = True
    if show_readme and drift["readme"]:
        has_drift = True
    sys.exit(1 if has_drift else 0)


def cmd_sync(args) -> None:
    registry_only = getattr(args, "registry_only", False)
    readme_only   = getattr(args, "readme_only", False)
    dry_run       = getattr(args, "dry_run", False)
    copy          = getattr(args, "copy", False)

    show_registry = not readme_only
    show_readme   = not registry_only

    drift = collect_drift()
    _run_sync_menu(drift, registry=show_registry, readme=show_readme,
                   dry_run=dry_run, copy=copy)


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts-help",
        description="Interactive help browser and registry/README sync for the scripts repository.",
    )
    parser.set_defaults(func=cmd_browse)

    subs = parser.add_subparsers(dest="subcmd", metavar="subcommand")

    # browse
    p_browse = subs.add_parser("browse", help="Interactive help browser (default)")
    p_browse.set_defaults(func=cmd_browse)

    # drift
    p_drift = subs.add_parser(
        "drift",
        help="Show registry and/or README drift report",
        description="Print a drift report. Exits 0 if clean, 1 if drift found.",
    )
    p_drift.add_argument("-g", "--registry-only", action="store_true",
                         help="Show only registry drift")
    p_drift.add_argument("-r", "--readme-only", action="store_true",
                         help="Show only README drift")
    p_drift.add_argument("-v", "--verbose", action="store_true",
                         help="List all items missing READMEs (default: count only)")
    p_drift.add_argument("-q", "--quiet", action="store_true",
                         help="No output; use exit code only (0=clean, 1=drift)")
    p_drift.set_defaults(func=cmd_drift)

    # sync
    p_sync = subs.add_parser(
        "sync",
        help="Launch AI assistant to fix detected drift",
        description="Offer to launch Claude Code or Codex to update the registry and/or READMEs.",
    )
    p_sync.add_argument("-g", "--registry-only", action="store_true",
                        help="Sync only registry drift")
    p_sync.add_argument("-r", "--readme-only", action="store_true",
                        help="Sync only README drift")
    p_sync.add_argument("-n", "--dry-run", action="store_true",
                        help="Print the AI prompt without launching anything")
    p_sync.add_argument("-C", "--copy", action="store_true",
                        help="Copy prompt to clipboard instead of launching AI")
    p_sync.set_defaults(func=cmd_sync)

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
