#!/usr/bin/env python3
"""
Agent Abilities CLI - Manage resources for AI coding agents.

Commands:
    abilities list              List registered resources
    abilities create <type> <name> --description "..."
    abilities add <path>        Add a resource from a file/directory
    abilities remove <name> --type <type>
    abilities sync              Sync resources to all CLIs
    abilities sync <cli>        Sync to specific CLI
    abilities scan <path>       Scan directory for resources
    abilities auto <path>       Scan and auto-register new resources
    abilities info <name> --type <type>
    abilities validate <path>   Validate a resource file
    abilities types             List available resource types
"""
import argparse
import json
import sys

from .manager import (
    list_resources,
    add_resource,
    remove_resource,
    create_resource,
    prune,
    sync_to_cli,
    sync_all_clis,
    scan_for_resources,
    auto_register_from_scan,
    get_resource_info,
    validate_resource,
    _resolve_strategy,
    CENTRAL_DIR,
    SOURCE_DIR,
    CLI_DIRS,
)
from .resource_types import RESOURCE_TYPES

TYPE_CHOICES = list(RESOURCE_TYPES.keys())


def cmd_list(args):
    """List all registered resources."""
    resources = list_resources(resource_type=args.type)

    if args.json:
        print(json.dumps(resources, indent=2))
        return 0

    if not resources:
        print(f"No resources registered in {CENTRAL_DIR}")
        print(f"\nAdd resources with: abilities add <path>")
        print(f"Or create new ones: abilities create <type> <name> --description '...'")
        print(f"Or scan for resources: abilities scan <path>")
        return 0

    by_type: dict = {}
    for r in resources:
        rtype = r.get("type", "unknown")
        by_type.setdefault(rtype, []).append(r)

    total = len(resources)
    print(f"Registered Resources ({total}):\n")

    for rtype, items in sorted(by_type.items()):
        print(f"  [{rtype.upper()}S] ({len(items)})")
        for r in items:
            name = r.get("registered_name", r.get("name", "unknown"))
            desc = str(r.get("description", "No description"))[:60]
            print(f"    {name}")
            print(f"      {desc}...")
            print(f"      -> {r.get('path')}")
        print()

    return 0


def cmd_create(args):
    """Create a new resource from template."""
    kwargs = {}
    if args.model:
        kwargs["model"] = args.model
    if args.tools:
        kwargs["tools"] = [t.strip() for t in args.tools.split(",")]
    if args.apply_to:
        kwargs["apply_to"] = args.apply_to
    if args.license:
        kwargs["license"] = args.license
    if args.with_refs:
        kwargs["with_refs"] = True
    if args.with_scripts:
        kwargs["with_scripts"] = True
    if args.events:
        kwargs["events"] = [e.strip() for e in args.events.split(",")]
    if args.tags:
        kwargs["tags"] = [t.strip() for t in args.tags.split(",")]
    if args.items:
        # Parse "type:path,type:path" format
        items = []
        for item_str in args.items.split(","):
            item_str = item_str.strip()
            if ":" in item_str:
                itype, ipath = item_str.split(":", 1)
                items.append({"type": itype.strip(), "path": ipath.strip()})
            else:
                items.append({"type": "agent", "path": item_str})
        kwargs["items"] = items

    success, msg, path = create_resource(
        resource_type=args.type,
        name=args.name,
        description=args.description,
        **kwargs,
    )
    print(msg)

    if success and args.register:
        ok, add_msg = add_resource(str(path), args.type)
        print(add_msg)

    return 0 if success else 1


def cmd_add(args):
    """Add a resource."""
    strategy = getattr(args, "strategy", "auto")
    success, msg = add_resource(args.path, args.type, args.name, strategy=strategy)
    print(msg)

    if success and args.sync:
        results = sync_all_clis()
        for r in results:
            print(f"  {r}")

    return 0 if success else 1


def cmd_remove(args):
    """Remove a resource."""
    if not args.type:
        print("Error: --type is required for remove")
        return 1

    success, msg = remove_resource(args.name, args.type)
    print(msg)
    return 0 if success else 1


def cmd_sync(args):
    """Sync resources to CLI directories."""
    strategy = getattr(args, "strategy", "auto")
    if args.cli:
        success, msg = sync_to_cli(args.cli, strategy=strategy)
        print(msg)
        return 0 if success else 1
    else:
        results = sync_all_clis()
        for r in results:
            print(r)
        return 0


def cmd_scan(args):
    """Scan directory for resources."""
    resources = scan_for_resources(args.path)

    if args.json:
        print(json.dumps(resources, indent=2))
        return 0

    if not resources:
        print(f"No resources found in {args.path}")
        return 0

    by_type: dict = {}
    for r in resources:
        rtype = r.get("type", "unknown")
        by_type.setdefault(rtype, []).append(r)

    print(f"Found {len(resources)} resources in {args.path}:\n")

    for rtype, items in sorted(by_type.items()):
        print(f"  [{rtype.upper()}S]")
        for r in items:
            name = r.get("name", "unknown")
            registered = "+" if r.get("is_registered") else "-"
            desc = str(r.get("description", ""))[:50]
            print(f"    [{registered}] {name}")
            print(f"        {desc}...")
            print(f"        {r.get('path')}")
        print()

    unregistered = [r for r in resources if not r.get("is_registered")]
    if unregistered:
        print(f"To register {len(unregistered)} new resources: abilities auto {args.path}")

    return 0


def cmd_auto(args):
    """Auto-register resources from scan."""
    results = auto_register_from_scan(args.path)

    if not results:
        print("No new resources to register.")
        return 0

    for r in results:
        print(r)

    if args.sync:
        print("\nSyncing to CLIs...")
        sync_results = sync_all_clis()
        for r in sync_results:
            print(f"  {r}")

    return 0


def cmd_info(args):
    """Show resource details."""
    if not args.type:
        for type_key in TYPE_CHOICES:
            info = get_resource_info(args.name, type_key)
            if info:
                args.type = type_key
                break
        else:
            print(f"Resource '{args.name}' not found (try --type)")
            return 1
    else:
        info = get_resource_info(args.name, args.type)

    if not info:
        print(f"Resource '{args.name}' not found in {args.type}s")
        return 1

    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print(f"Type: {info.get('type', args.type)}")
    print(f"Name: {info.get('name', args.name)}")
    print(f"Path: {info.get('path')}")
    if info.get("description"):
        print(f"\nDescription:\n  {info['description']}")
    if info.get("model"):
        print(f"Model: {info['model']}")
    if info.get("tools"):
        print(f"Tools: {info['tools']}")
    if info.get("applyTo"):
        print(f"Applies to: {info['applyTo']}")

    return 0


def cmd_validate(args):
    """Validate a resource file."""
    is_valid, errors = validate_resource(args.path)

    if is_valid:
        print(f"VALID: {args.path}")
        return 0
    else:
        print(f"INVALID: {args.path}")
        for err in errors:
            print(f"  - {err}")
        return 1


def cmd_prune(args):
    """Remove broken symlinks from central registry and CLI directories."""
    messages = prune(prune_clis=not args.central_only)

    if not messages:
        print("Nothing to prune -- all symlinks are healthy.")
        return 0

    for msg in messages:
        print(msg)
    print(f"\nPruned {len(messages)} broken symlink(s).")
    return 0


def cmd_types(args):
    """List available resource types."""
    print("Available Resource Types:\n")
    for key, rtype in RESOURCE_TYPES.items():
        print(f"  {key}")
        print(f"    {rtype.description}")
        if rtype.extension:
            print(f"    File pattern: *{rtype.extension}")
        if rtype.is_folder:
            print(f"    Structure: {rtype.subdir}/<name>/{rtype.entry_file}")
        print(f"    Source dir: {SOURCE_DIR / rtype.subdir}")
        print(f"    Required fields: {', '.join(rtype.required_frontmatter)}")
        if rtype.optional_frontmatter:
            print(f"    Optional fields: {', '.join(rtype.optional_frontmatter)}")
        print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manage resources for AI coding agents (agents, prompts, instructions, skills, hooks, collections)",
        prog="abilities",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # list
    p_list = subparsers.add_parser("list", aliases=["ls"], help="List registered resources")
    p_list.add_argument("-t", "--type", choices=TYPE_CHOICES, help="Filter by type")
    p_list.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    p_list.set_defaults(func=cmd_list)

    # create
    p_create = subparsers.add_parser("create", aliases=["new"], help="Create a new resource from template")
    p_create.add_argument("type", choices=TYPE_CHOICES, help="Resource type")
    p_create.add_argument("name", help="Resource name (kebab-case)")
    p_create.add_argument("-d", "--description", required=True, help="Description")
    p_create.add_argument("-m", "--model", help="AI model (agents/prompts)")
    p_create.add_argument("--tools", help="Comma-separated tools list (agents/prompts)")
    p_create.add_argument("--apply-to", help="File glob pattern (instructions)")
    p_create.add_argument("--license", help="License type (skills)")
    p_create.add_argument("--with-refs", action="store_true", help="Create references/ dir (skills)")
    p_create.add_argument("--with-scripts", action="store_true", help="Create scripts/ dir (skills)")
    p_create.add_argument("--events", help="Comma-separated event list for hooks (sessionStart, sessionEnd, etc.)")
    p_create.add_argument("--tags", help="Comma-separated tag list (collections)")
    p_create.add_argument("--items", help="Comma-separated items as type:path (collections)")
    p_create.add_argument("-r", "--register", action="store_true", help="Auto-register after creating")
    p_create.set_defaults(func=cmd_create)

    # add
    p_add = subparsers.add_parser("add", help="Register an existing resource")
    p_add.add_argument("path", help="Path to resource file or skill directory")
    p_add.add_argument("-t", "--type", choices=TYPE_CHOICES, help="Resource type (auto-detected if omitted)")
    p_add.add_argument("-n", "--name", help="Override resource name")
    p_add.add_argument("-s", "--sync", action="store_true", help="Sync to CLIs after adding")
    p_add.add_argument("--strategy", choices=["symlink", "copy", "auto"], default="auto",
                       help="Link strategy: symlink (Unix), copy (Windows), auto (default)")
    p_add.set_defaults(func=cmd_add)

    # remove
    p_remove = subparsers.add_parser("remove", aliases=["rm"], help="Remove a resource")
    p_remove.add_argument("name", help="Resource name")
    p_remove.add_argument("-t", "--type", choices=TYPE_CHOICES, required=True, help="Resource type")
    p_remove.set_defaults(func=cmd_remove)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync resources to CLI directories")
    p_sync.add_argument("cli", nargs="?", choices=list(CLI_DIRS.keys()), help="Specific CLI (default: all)")
    p_sync.add_argument("--strategy", choices=["symlink", "copy", "auto"], default="auto",
                        help="Link strategy: symlink (Unix), copy (Windows), auto (default)")
    p_sync.set_defaults(func=cmd_sync)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory for resources")
    p_scan.add_argument("path", help="Directory to scan")
    p_scan.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    p_scan.set_defaults(func=cmd_scan)

    # auto
    p_auto = subparsers.add_parser("auto", help="Scan and auto-register new resources")
    p_auto.add_argument("path", help="Directory to scan")
    p_auto.add_argument("-s", "--sync", action="store_true", help="Sync to CLIs after registering")
    p_auto.set_defaults(func=cmd_auto)

    # info
    p_info = subparsers.add_parser("info", help="Show resource details")
    p_info.add_argument("name", help="Resource name")
    p_info.add_argument("-t", "--type", choices=TYPE_CHOICES, help="Resource type")
    p_info.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    p_info.set_defaults(func=cmd_info)

    # validate
    p_validate = subparsers.add_parser("validate", aliases=["check"], help="Validate a resource")
    p_validate.add_argument("path", help="Path to resource file or skill directory")
    p_validate.set_defaults(func=cmd_validate)

    # prune
    p_prune = subparsers.add_parser("prune", aliases=["clean"], help="Remove broken symlinks")
    p_prune.add_argument("--central-only", action="store_true", help="Only prune central registry, skip CLI dirs")
    p_prune.set_defaults(func=cmd_prune)

    # types
    p_types = subparsers.add_parser("types", help="List available resource types")
    p_types.set_defaults(func=cmd_types)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
