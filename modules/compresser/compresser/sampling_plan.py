"""Deterministic sample designs over immutable inventory populations."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math

from .estimation_models import (
    EstimationBudget,
    EstimationPlan,
    PopulationMember,
    PopulationView,
    RecipeQuota,
    RecipeSpec,
    StratumPlan,
    current_runtime_identity,
    design_digest,
)


def _size_strata(members: tuple[PopulationMember, ...]) -> dict[str, list[PopulationMember]]:
    bases: dict[tuple[str, str], list[PopulationMember]] = defaultdict(list)
    for member in members:
        bases[(member.group, member.codec_class)].append(member)
    strata: dict[str, list[PopulationMember]] = {}
    for (group, codec_class), values in sorted(bases.items()):
        known: dict[int, list[PopulationMember]] = defaultdict(list)
        unknown = []
        for member in values:
            if member.size_bytes is None:
                unknown.append(member)
            else:
                known[int(math.log2(max(1, member.size_bytes)))].append(member)
        bins = [(band, sorted(rows, key=lambda row: row.identity.casefold())) for band, rows in sorted(known.items())]
        if len(values) < 8:
            bins = [(min((band for band, _ in bins), default=0), values)]
        while len(bins) > 1 and (len(bins) > 4 or any(len(rows) < 8 for _, rows in bins)):
            index = min(range(len(bins)), key=lambda current: (len(bins[current][1]), bins[current][0]))
            neighbor = 1 if index == 0 else index - 1 if index == len(bins) - 1 else (
                index - 1 if len(bins[index - 1][1]) <= len(bins[index + 1][1]) else index + 1
            )
            low, high = sorted((index, neighbor))
            merged = sorted((*bins[low][1], *bins[high][1]), key=lambda row: row.identity.casefold())
            bins[low : high + 1] = [(bins[low][0], merged)]
        for band, rows in bins:
            suffix = "all" if len(values) < 8 else str(band)
            strata[f"{group}|{codec_class}|log2:{suffix}"] = rows
        if unknown:
            strata[f"{group}|{codec_class}|unknown-size"] = unknown
    return strata


def _priority(seed: int, population_id: str, member: PopulationMember) -> str:
    payload = f"{seed}\0{population_id}\0{member.identity}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_plan(
    population: PopulationView,
    recipes: tuple[RecipeSpec, ...] | list[RecipeSpec],
    budget: EstimationBudget,
    *,
    seed: int,
    accuracy_pp: float | None = None,
    allow_larger: bool = False,
) -> EstimationPlan:
    """Build a deterministic, bounded design whose selected prefixes survive cap growth."""
    recipes = tuple(recipes)
    if not recipes:
        raise ValueError("At least one recipe is required to build an estimation plan")
    if len({recipe.identity for recipe in recipes}) != len(recipes):
        raise ValueError("Plan recipes must be unique")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("Plan seed must be an integer")
    if accuracy_pp is not None and (not math.isfinite(accuracy_pp) or not 0 < accuracy_pp <= 100):
        raise ValueError("Accuracy target must be positive and finite")
    if accuracy_pp is not None and allow_larger:
        raise ValueError("Accuracy stopping cannot be combined with allow-larger estimates")

    grouped = _size_strata(population.members)
    rankings = {
        key: sorted(rows, key=lambda member: (_priority(seed, population.population_id, member), member.identity))
        for key, rows in sorted(grouped.items())
    }
    selected: list[tuple[str, PopulationMember]] = []
    cursor = 0
    while len(selected) < budget.max_images:
        added = False
        for key, rows in rankings.items():
            if cursor < len(rows):
                selected.append((key, rows[cursor]))
                added = True
                if len(selected) >= budget.max_images:
                    break
        if not added:
            break
        cursor += 1

    per_recipe_pilot = min(
        budget.pilot_images,
        len(selected),
        max(1, budget.max_new_encodes // len(recipes)),
    )
    quota_rows = []
    pilot_by_stratum: dict[str, int] = defaultdict(int)
    for key, _ in selected[:per_recipe_pilot]:
        pilot_by_stratum[key] += 1
    for recipe in recipes:
        quota_rows.append(
            RecipeQuota(recipe.identity, tuple((key, count) for key, count in sorted(pilot_by_stratum.items())))
        )

    selected_by_stratum: dict[str, list[str]] = defaultdict(list)
    for key, member in selected:
        selected_by_stratum[key].append(member.identity)
    strata = tuple(
        StratumPlan(
            key=key,
            member_count=len(grouped[key]),
            total_bytes=(sum(row.size_bytes for row in grouped[key]) if all(row.size_bytes is not None for row in grouped[key]) else None),
            selected_prefix=tuple(selected_by_stratum.get(key, ())),
        )
        for key in sorted(grouped)
    )
    coverage_gaps = tuple(row.key for row in strata if not row.selected_prefix)
    immutable = {
        "population_id": population.population_id,
        "root": str(population.root),
        "owner": population.owner,
        "depth": population.depth,
        "filters": population.filters,
        "seed": seed,
        "accuracy_pp": accuracy_pp,
        "allow_larger": allow_larger,
        "recipes": [recipe.identity for recipe in recipes],
        "budget": {
            "max_images": budget.max_images,
            "max_new_encodes": budget.max_new_encodes,
            "max_runtime_seconds": budget.max_runtime_seconds,
            "pilot_images": budget.pilot_images,
        },
        "strata": [
            {"key": row.key, "member_count": row.member_count, "total_bytes": row.total_bytes,
             "selected_prefix": row.selected_prefix}
            for row in strata
        ],
        "recipe_quotas": [
            {"recipe_id": row.recipe_id, "per_stratum": row.per_stratum}
            for row in quota_rows
        ],
        "ordering_revision": 1,
        "ordering": "sha256(seed, population_id, member_identity), round-robin by stratum",
    }
    immutable = json.loads(json.dumps(immutable, sort_keys=True, allow_nan=False))
    identity = design_digest(immutable)
    return EstimationPlan(
        plan_id=f"plan-{identity[:20]}",
        design_identity=identity,
        population_id=population.population_id,
        root=population.root,
        owner=population.owner,
        depth=population.depth,
        filters=population.filters,
        inventory_completed=population.completed,
        seed=seed,
        accuracy_pp=accuracy_pp,
        allow_larger=allow_larger,
        recipes=recipes,
        budget=budget,
        strata=strata,
        selected_member_ids=tuple(member.identity for _, member in selected),
        recipe_quotas=tuple(quota_rows),
        design_payload=immutable,
        coverage_gaps=coverage_gaps,
    )


def load_population(workspace, *, owner: str, filters: tuple[str, ...]) -> PopulationView:
    """Load only a completed inventory snapshot; never refresh or open trial storage."""
    import sqlite3

    from .inventory import InventoryStore
    from .snapshots import SelectionSnapshot

    expected_workspace_owner = "mangadl-pages" if owner == "mangadl" else "compresser"
    if expected_workspace_owner != workspace.owner:
        raise ValueError("Requested population owner does not match workspace")
    if filters and owner != "mangadl":
        raise ValueError("URL filters are only valid for MangaDL inventories")
    if workspace.inventory_file.is_file():
        store = InventoryStore(workspace.inventory_file)
        try:
            with store.connection(readonly=True) as db:
                file_row = db.execute(
                    "SELECT policy,report FROM inventory_file_snapshots WHERE root=? ORDER BY completed DESC LIMIT 1",
                    (str(workspace.target.resolve()),),
                ).fetchone()
        except sqlite3.OperationalError:
            file_row = None
        if file_row is not None and not filters:
            policy, raw_report = file_row
            report = json.loads(raw_report)
            if report.get("status") != "complete_enumeration" or report.get("depth") != "files":
                raise ValueError("Saved file inventory is incomplete; run inventory again")
            members = tuple(
                PopulationMember(
                    identity=row["relative_path"],
                    relative_path=row["relative_path"],
                    size_bytes=row.get("bytes"),
                    group=row["extension"].casefold(),
                    fingerprint=tuple(
                        value for value in (row.get("bytes"), row.get("mtime_ns"), row.get("ctime_ns"))
                        if value is not None
                    ),
                )
                for row in report["files"]
            )
            population_id = design_digest(
                [report["root"], policy, [(row.identity, row.fingerprint) for row in members]]
            )
            return PopulationView(
                population_id=population_id,
                root=workspace.target.resolve(),
                owner=owner,
                depth="files",
                filters=(),
                completed=report["completed"],
                members=members,
            )
        snapshot = SelectionSnapshot(store, workspace.target, owner=owner, filters=filters)
        try:
            images, gallery_keys = snapshot.load()
            records = []
            for image in images:
                relative = (
                    str(image.path.relative_to(snapshot.root))
                    if snapshot.root.is_dir()
                    else image.path.name
                )
                records.append(
                    PopulationMember(
                        identity=relative,
                        relative_path=relative,
                        size_bytes=image.size_bytes,
                        group=image.format.upper(),
                        fingerprint=tuple(snapshot.fingerprints[image.path]),
                    )
                )
            policy = json.loads(snapshot.policy)
            with store.connection(readonly=True) as db:
                row = db.execute(
                    "SELECT report FROM inventory_selections WHERE root=? AND policy=?",
                    (str(snapshot.root), snapshot.policy),
                ).fetchone()
            if row is None:
                raise ValueError("No completed inventory exists; run inventory first")
            report = json.loads(row[0])
            population_id = design_digest(
                [
                    report["root"],
                    report["policy"],
                    report.get("profile_identity"),
                    [(member.identity, member.fingerprint) for member in records],
                ]
            )
            return PopulationView(
                population_id=population_id,
                root=snapshot.root,
                owner=owner,
                depth="headers",
                filters=tuple(filters),
                completed=report["completed"],
                members=tuple(records),
            )
        except ValueError as exc:
            if "No completed snapshot" in str(exc) or "Cannot trust inventory snapshot" in str(exc):
                raise ValueError("No matching completed header inventory; run inventory first") from exc
            raise

    raise ValueError("No matching completed inventory; run inventory first")


def execute_plan_operation(args, options, *, owner: str) -> dict:
    """Create or inspect a persistent plan and publish the shared report artifact."""
    from dataclasses import replace
    import json

    from .estimation_models import EstimationBudget
    from .plan_store import load_plan, save_plan
    from .report_session import current_session

    workspace = args._workspace
    population = load_population(workspace, owner=owner, filters=options.filters)
    runtime = current_runtime_identity()
    if options.plan_id:
        plan = load_plan(workspace, options.plan_id)
        if plan.population_id != population.population_id:
            raise ValueError("The saved plan belongs to a changed inventory/filter scope; rebuild it")
        if any(recipe.runtime_identity != runtime for recipe in plan.recipes):
            raise ValueError("The saved plan uses a different runtime identity; rebuild it")
        if options.plan_recipes_explicit:
            requested = tuple(recipe for recipe in options.recipes)
            saved = tuple(replace(recipe, runtime_identity="") for recipe in plan.recipes)
            if requested != saved:
                raise ValueError("The requested recipe differs from the saved plan; rebuild it")
        if options.plan_seed_explicit and options.seed != plan.seed:
            raise ValueError("The requested seed differs from the saved plan; rebuild it")
        for requested, saved, label in (
            (options.max_images, plan.budget.max_images, "image cap"),
            (options.max_trials, plan.budget.max_new_encodes, "encode budget"),
            (options.max_time_seconds, plan.budget.max_runtime_seconds, "runtime budget"),
            (options.accuracy_pp, plan.accuracy_pp, "accuracy target"),
        ):
            if requested is not None and requested != saved:
                raise ValueError(f"The requested {label} differs from the saved plan; rebuild it")
        if options.allow_larger and not plan.allow_larger:
            raise ValueError("The requested allow-larger policy differs from the saved plan; rebuild it")
    else:
        recipes = tuple(replace(recipe, runtime_identity=runtime) for recipe in options.recipes)
        budget = EstimationBudget(
            max_images=options.max_images or 512,
            max_new_encodes=options.max_trials or 2000,
            max_runtime_seconds=options.max_time_seconds or 300.0,
            pilot_images=64,
        )
        plan = build_plan(
            population,
            recipes,
            budget,
            seed=options.seed,
            accuracy_pp=options.accuracy_pp,
            allow_larger=options.allow_larger,
        )
        save_plan(workspace, plan)

    session = current_session()
    if session is None:
        raise RuntimeError("Plan report session was not initialized")
    report, artifacts = session.plan(plan, population_count=len(population.members))
    if args.json:
        payload = {
            "operation": "plan",
            "plan": plan.to_dict(),
            "report_artifacts": artifacts,
            "report": {"title": report.title, "operation": report.operation, "status": report.status},
        }
        print(json.dumps(payload, indent=2, allow_nan=False))
    return 0
