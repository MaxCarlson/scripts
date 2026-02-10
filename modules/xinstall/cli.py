from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from tool_install_manager.manager import (
    apply_actions,
    build_isin_report,
    detect_installers,
    ensure_tool_installed,
    guard_against_shadow_install,
    installer_install_commands,
    plan_uninstall_duplicates,
    tool_status,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tim",
        description="Cross-platform helper to detect how tools are installed (winget/pipx/uv/dpkg/brew) and safely install/upgrade without shadowing.",
    )

    p.add_argument("-a", "--apply", action="store_true", help="Execute planned commands (default is dry-run).")
    p.add_argument("-y", "--yes", action="store_true", help="Assume yes for prompts.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")
    p.add_argument(
        "-r",
        "--root_dir",
        default=None,
        help="Override notebook root directory (where INSTALLED.md and installed.json live).",
    )

    sub = p.add_subparsers(dest="subcmd", required=True)

    isin = sub.add_parser("isin", help="Abbreviated tool install report (paths + managers).")
    isin.add_argument("toolname", help="Command name to inspect (e.g., rg).")
    isin.add_argument("-p", "--package_name", default=None, help="Package name/id if different from command.")
    isin.add_argument("--cleanup", action="store_true", help="Offer uninstall plan for duplicates.")

    installers = sub.add_parser("installers", help="Installer discovery and setup.")
    installers_sub = installers.add_subparsers(dest="installers_cmd", required=True)

    installers_list = installers_sub.add_parser("list", help="List installers available on this machine.")
    installers_list.add_argument("-j", "--json", action="store_true", help="Emit JSON-like output.")

    installers_install = installers_sub.add_parser("install", help="Install a missing installer (prints plan unless --apply).")
    installers_install.add_argument(
        "-i",
        "--installer_name",
        required=True,
        help="Installer to install (pipx|uv|brew|scoop|choco|cargo|rustup).",
    )

    tool = sub.add_parser("tool", help="Tool ownership, guardrails, and installation.")
    tool_sub = tool.add_subparsers(dest="tool_cmd", required=True)

    tool_status_p = tool_sub.add_parser("status", help="Show how a tool is likely managed and how to upgrade it.")
    tool_status_p.add_argument("-c", "--command_name", required=True, help="Command to check (e.g., rg, ruff).")
    tool_status_p.add_argument("-p", "--package_name", default=None, help="Package name/id if different from command.")

    tool_guard_p = tool_sub.add_parser("guard", help="Warn/block if you are about to shadow-install an existing tool.")
    tool_guard_p.add_argument("-c", "--command_name", required=True, help="Command you are about to install.")
    tool_guard_p.add_argument(
        "-m",
        "--install_method",
        required=True,
        help="Your intended install method (manual|winget|pipx|uv|brew|apt|pkg|scoop|choco|cargo).",
    )

    tool_ensure_p = tool_sub.add_parser("ensure", help="Install tool if missing using best manager for this OS (prints plan unless --apply).")
    tool_ensure_p.add_argument("-c", "--command_name", required=True, help="Command to ensure exists (e.g., rg).")
    tool_ensure_p.add_argument("-p", "--package_name", default=None, help="Package name/id if different from command.")
    tool_ensure_p.add_argument("-m", "--preferred_manager", default=None, help="Force a manager (winget|apt|pkg|brew|pipx|uv|cargo|scoop|choco).")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    notebook_root = Path(args.root_dir).expanduser() if args.root_dir else None

    if args.subcmd == "installers":
        if args.installers_cmd == "list":
            info = detect_installers()
            if args.json:
                print(info)
            else:
                present = [k for k, v in info.items() if v]
                missing = [k for k, v in info.items() if not v]
                print("Present installers/tools:")
                for k in sorted(present):
                    print(f"  - {k}")
                print("\nMissing installers/tools:")
                for k in sorted(missing):
                    print(f"  - {k}")
            return 0

        if args.installers_cmd == "install":
            actions = installer_install_commands(args.installer_name)
            if not actions:
                print(f"No supported install plan for installer '{args.installer_name}'. (It may already be OS-provided.)")
                return 0
            return apply_actions(actions, apply=bool(args.apply), assume_yes=bool(args.yes), verbose=bool(args.verbose))

        return 2

    if args.subcmd == "isin":
        report = build_isin_report(command_name=args.toolname, package_name=args.package_name)
        print(f"Tool: {report.command_name}")
        if report.primary_path:
            print(f"Primary (PATH order): {report.primary_path}")
        else:
            print("Primary (PATH order): NOT FOUND")
        if report.all_paths:
            print("All paths:")
            for pth in report.all_paths:
                print(f"  - {pth}")
        else:
            print("All paths: (none)")

        if report.candidates:
            print("Managers:")
            for cand in report.candidates:
                extra = []
                if cand.package_id:
                    extra.append(f"id={cand.package_id}")
                if cand.upgrade_hint:
                    extra.append(f"upgrade={cand.upgrade_hint}")
                if cand.uninstall_hint:
                    extra.append(f"uninstall={cand.uninstall_hint}")
                suffix = f" ({', '.join(extra)})" if extra else ""
                print(f"  - {cand.manager:8s} conf={cand.confidence:.2f} :: {cand.evidence}{suffix}")
        else:
            print("Managers: (none detected)")

        if report.recommended:
            print(f"Recommended manager: {report.recommended.manager}")

        if report.duplicate_paths or report.duplicate_managers:
            print("Duplicates: detected (multiple paths or managers).")
            if args.cleanup:
                actions = plan_uninstall_duplicates(report)
                if not actions:
                    print("No uninstall actions available.")
                    return 0
                return apply_actions(actions, apply=bool(args.apply), assume_yes=bool(args.yes), verbose=bool(args.verbose))
        return 0

    if args.subcmd == "tool":
        if args.tool_cmd == "status":
            st = tool_status(command_name=args.command_name, package_name=args.package_name)
            print(f"Command: {st.command_name}")
            print(f"Package: {st.package_name}")
            if st.executable_paths:
                print("Paths:")
                for p in st.executable_paths:
                    print(f"  - {p}")
            else:
                print("Paths: NOT FOUND")
            if not st.candidates:
                print("Candidates: (none)")
                return 0
            print("\nCandidates:")
            for c in st.candidates:
                extras = []
                if c.package_id:
                    extras.append(f"id={c.package_id}")
                if c.upgrade_hint:
                    extras.append(f"upgrade={c.upgrade_hint}")
                if c.uninstall_hint:
                    extras.append(f"uninstall={c.uninstall_hint}")
                if c.reinstall_hint:
                    extras.append(f"reinstall={c.reinstall_hint}")
                extra_s = f" ({', '.join(extras)})" if extras else ""
                print(f"  - {c.manager:8s} conf={c.confidence:.2f} :: {c.evidence}{extra_s}")
            if st.recommended:
                print(f"\nRecommended manager: {st.recommended.manager}")
                if st.recommended.upgrade_hint:
                    print(f"Recommended upgrade:\n  {st.recommended.upgrade_hint}")
            return 0

        if args.tool_cmd == "guard":
            return guard_against_shadow_install(
                command_name=args.command_name,
                install_method=args.install_method,
                assume_yes=bool(args.yes),
            )

        if args.tool_cmd == "ensure":
            return ensure_tool_installed(
                command_name=args.command_name,
                package_name=args.package_name,
                preferred_manager=args.preferred_manager,
                apply=bool(args.apply),
                assume_yes=bool(args.yes),
                verbose=bool(args.verbose),
                notebook_root_dir=notebook_root,
            )

        return 2

    return 2
