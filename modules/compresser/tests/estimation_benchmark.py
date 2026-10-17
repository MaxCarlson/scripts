"""Seeded known-population validation; coverage is descriptive, never a proof."""

from dataclasses import asdict
import json
import math
from pathlib import Path

from compresser.estimation_models import (
    EstimationBudget,
    PopulationMember,
    PopulationView,
    RecipeObservation,
    RecipeSpec,
)
from compresser.estimation_stats import allocate_confirmation, estimate_fixed
from compresser.sampling_plan import build_plan


def run(repetitions: int = 400) -> dict:
    sizes = [100 + (i * 53) % 1000 for i in range(96)]
    members = tuple(PopulationMember(str(i), str(i), size, "PNG", (2, size, i)) for i, size in enumerate(sizes))
    population = PopulationView(
        "known-synthetic-population", Path.cwd(), "compresser", "headers", (), "2026-10-17T00:00:00+00:00", members
    )
    recipes = tuple(
        RecipeSpec(
            fmt, "lossless", None, 0.99, "pillow", 6, "synthetic-runtime", retained_original_policy="allow-larger"
        )
        for fmt in ("webp", "png")
    )
    savings = {
        recipes[0].identity: [size // 3 + ((i * 37) % 81) - 40 for i, size in enumerate(sizes)],
        recipes[1].identity: [(-size // 4 if i % 11 == 0 else size // 2) for i, size in enumerate(sizes)],
    }
    errors, covered, incomplete = (
        {row.identity: [] for row in recipes},
        {row.identity: 0 for row in recipes},
        {row.identity: 0 for row in recipes},
    )
    for seed in range(repetitions):
        plan = build_plan(population, recipes, EstimationBudget(64, 2000, 300, 16), seed=seed, allow_larger=True)

        def observation(recipe, member_id):
            index = int(member_id)
            return RecipeObservation(
                member_id,
                recipe.identity,
                members[index].fingerprint,
                recipe.runtime_identity,
                sizes[index],
                sizes[index] - savings[recipe.identity][index],
                0.01 + sizes[index] / 100000,
            )

        pilot = tuple(observation(recipe, member_id) for recipe in recipes for member_id in plan.pilot_member_ids)
        design = allocate_confirmation(plan, pilot)
        by_id = {row.identity: row for row in recipes}
        confirmation = tuple(
            observation(by_id[group.recipe_id], member_id)
            for group in design.groups
            for member_id in group.selected_ids
        )
        for result in estimate_fixed(plan, design, pilot, confirmation):
            truth = sum(savings[result.recipe_id])
            if not result.complete:
                incomplete[result.recipe_id] += 1
                continue
            errors[result.recipe_id].append(result.estimated_saved_bytes - truth)
            covered[result.recipe_id] += result.interval[0] <= truth <= result.interval[1]
    records = []
    for recipe in recipes:
        values = errors[recipe.identity]
        truth = sum(savings[recipe.identity])
        records.append(
            {
                "recipe": asdict(recipe),
                "truth_saved_bytes": truth,
                "complete_runs": len(values),
                "incomplete_runs": incomplete[recipe.identity],
                "mean_bias_bytes": math.fsum(values) / len(values),
                "mean_bias_percent_of_input": 100 * math.fsum(values) / len(values) / sum(sizes),
                "rmse_bytes": math.sqrt(math.fsum(error * error for error in values) / len(values)),
                "maximum_absolute_error_bytes": max(abs(error) for error in values),
                "approximate_interval_coverage": covered[recipe.identity] / len(values),
            }
        )
    return {
        "repetitions": repetitions,
        "population_count": len(sizes),
        "population_input_bytes": sum(sizes),
        "budget": {"max_images": 64, "pilot_images": 16, "recipes": 2},
        "interpretation": "Descriptive simulation of approximate fixed intervals; no coverage acceptance threshold or certification.",
        "recipes": records,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, allow_nan=False))
