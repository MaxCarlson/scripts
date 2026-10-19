"""Fixed-design pilot/confirmation inference. No sequential coverage claims.

The predictor is frozen using the prescribed pilot before confirmation starts.
Every selected identity remains part of its draw even when measurement fails.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import math
from statistics import stdev
from typing import Sequence

from .estimation_models import (
    ConfirmationDesign,
    ConfirmationStratum,
    EstimationPlan,
    GroupEstimate,
    LinearPredictor,
    RecipeEstimate,
    RecipeObservation,
    design_digest,
)

_Z95 = 1.959963984540054


def fit_predictor(observations: Sequence[RecipeObservation]) -> LinearPredictor:
    """Centered pilot-only OLS, with a constant fallback below three distinct inputs."""
    rows = [row for row in observations if row.complete]
    if not rows:
        return LinearPredictor()
    origin = rows[0].input_bytes
    origin_y = rows[0].saved_bytes
    offsets = [row.input_bytes - origin for row in rows]
    mean_x = math.fsum(offsets) / len(rows)
    mean_y = math.fsum(row.saved_bytes - origin_y for row in rows) / len(rows)
    slope = 0.0
    if len(rows) >= 3 and len(set(offsets)) >= 3:
        denominator = math.fsum((x - mean_x) ** 2 for x in offsets)
        slope = (
            math.fsum((x - mean_x) * ((row.saved_bytes - origin_y) - mean_y) for x, row in zip(offsets, rows))
            / denominator
        )
    return LinearPredictor(origin, mean_x, mean_y, slope, origin_y)


def estimate_group(
    pilot_savings: Sequence[int],
    remaining_bytes: Sequence[int],
    confirmation: Sequence[tuple[int, int]],
    *,
    predictor: LinearPredictor = LinearPredictor(),
) -> GroupEstimate:
    """Evaluate one fixed SRS draw; selection validity is enforced by estimate_fixed."""
    size, count = len(remaining_bytes), len(confirmation)
    indices = [index for index, _ in confirmation]
    if len(set(indices)) != count or any(type(i) is not int or not 0 <= i < size for i in indices):
        raise ValueError("Confirmation indices must be distinct remainder members")
    if any(type(value) is not int or value < 0 for value in remaining_bytes):
        raise ValueError("Known nonnegative inventory byte sizes are required")
    known = sum(pilot_savings)
    if count == size:
        return GroupEstimate(known + sum(saved for _, saved in confirmation), 0.0, size, count)
    predicted_total = size * predictor.mean_savings + predictor.slope * (
        sum(remaining_bytes) - size * predictor.origin_x - size * predictor.mean_offset
    )
    if not count:
        total = math.fsum((known + size * predictor.origin_y, predicted_total))
        if not math.isfinite(total):
            raise ValueError("Nonfinite fixed estimate")
        return GroupEstimate(total, None, size, 0, ("unsampled remainder",))
    residuals = [predictor.residual(remaining_bytes[index], saved) for index, saved in confirmation]
    mean = math.fsum(residuals) / count
    total = math.fsum((known + size * predictor.origin_y, predicted_total, size * mean))
    if not math.isfinite(total):
        raise ValueError("Nonfinite fixed estimate")
    if count == 1:
        return GroupEstimate(total, None, size, count, ("singleton remainder has unknown variance",))
    spread = math.fsum((value - mean) ** 2 for value in residuals) / (count - 1)
    variance = size * (size - count) * spread / count
    if not math.isfinite(variance):
        raise ValueError("Nonfinite fixed variance")
    return GroupEstimate(total, variance, size, count)


def _index_observations(plan, observations, allowed, *, require_terminal_pilot=False):
    members = {row.identity: row for row in plan.members}
    recipes = {row.identity: row for row in plan.recipes}
    result = {}
    for row in observations:
        if not isinstance(row, RecipeObservation):
            raise ValueError("Typed recipe observations are required")
        key = (row.recipe_id, row.member_id)
        if key in result:
            raise ValueError("Duplicate prescribed observation")
        if key not in allowed:
            raise ValueError("Observation is not a prescribed member/recipe job")
        member, recipe = members[row.member_id], recipes[row.recipe_id]
        if (
            tuple(row.fingerprint) != tuple(member.fingerprint)
            or row.input_bytes != member.size_bytes
            or row.runtime_identity != recipe.runtime_identity
        ):
            raise ValueError("Observation source fingerprint, bytes or runtime identity is stale")
        if row.complete and not plan.allow_larger and row.saved_bytes < 0:
            raise ValueError("Observation violates retained-original policy")
        result[key] = row
    if require_terminal_pilot and (
        set(result) != allowed or any(row.state in ("not_started", "interrupted") for row in result.values())
    ):
        raise ValueError("The prescribed pilot must finish before freezing confirmation")
    return result


def _allocate_counts(capacities, weights, allowance, *, floor=2):
    """Coverage floors, then capped proportional largest remainder with stable ties."""
    result = [0] * len(capacities)
    left = min(allowance, sum(capacities))
    for i, capacity in enumerate(capacities):
        count = min(floor, capacity, left)
        result[i] += count
        left -= count
    while left:
        active = [i for i, capacity in enumerate(capacities) if result[i] < capacity]
        total_weight = math.fsum(weights[i] for i in active)
        shares = {i: left * weights[i] / total_weight for i in active}
        saturated = [i for i in active if shares[i] >= capacities[i] - result[i]]
        if saturated:
            for i in saturated:
                count = capacities[i] - result[i]
                result[i] += count
                left -= count
            continue
        for i in active:
            count = math.floor(shares[i])
            result[i] += count
            left -= count
        for i in sorted(active, key=lambda i: (-(shares[i] - math.floor(shares[i])), i))[:left]:
            result[i] += 1
        left = 0
    return result


def allocate_confirmation(plan: EstimationPlan, pilot_results: Sequence[RecipeObservation]) -> ConfirmationDesign:
    """Freeze per-recipe confirmation prefixes before any confirmation is observed."""
    plan.validate_design()
    allowed = {(recipe.identity, member) for recipe in plan.recipes for member in plan.pilot_member_ids}
    pilot = _index_observations(plan, pilot_results, allowed, require_terminal_pilot=True)
    members = {row.identity: row for row in plan.members}
    pilot_set = set(plan.pilot_member_ids)
    groups = []
    for recipe in plan.recipes:
        for stratum in plan.strata:
            pilots = tuple(i for i in stratum.ordered_member_ids if i in pilot_set)
            remainder = tuple(i for i in stratum.ordered_member_ids if i not in pilot_set)
            valid = [pilot[recipe.identity, i] for i in pilots if pilot[recipe.identity, i].complete]
            sizes = [members[i].size_bytes for i in stratum.ordered_member_ids]
            measured = len(valid) >= 2
            spread = stdev([row.saved_bytes for row in valid]) if measured else (stdev(sizes) if len(sizes) > 1 else 0)
            scale = max(spread, 0.05 * (sum(sizes) / len(sizes)), 1.0)
            cost = max(math.fsum(row.elapsed_seconds for row in valid) / len(valid), 0.001) if valid else 1.0
            weight = len(remainder) * scale / math.sqrt(cost)
            if not math.isfinite(weight):
                raise ValueError("Nonfinite confirmation allocation weight")
            groups.append(
                ConfirmationStratum(
                    recipe.identity,
                    stratum.key,
                    pilots,
                    remainder,
                    (),
                    fit_predictor(valid),
                    "measured_pilot" if measured else "metadata_proxy",
                    weight,
                )
            )
    count_groups = len(plan.strata)
    capacities = [
        sum(len(row.remaining_ids) for row in groups[i * count_groups : (i + 1) * count_groups])
        for i in range(len(plan.recipes))
    ]
    allowances = _allocate_counts(capacities, [1.0] * len(capacities), plan.budget.max_images - len(pilot_set), floor=0)
    for i, allowance in enumerate(allowances):
        start = i * count_groups
        subset = groups[start : start + count_groups]
        counts = _allocate_counts(
            [len(row.remaining_ids) for row in subset], [row.allocation_weight for row in subset], allowance
        )
        for j, count in enumerate(counts):
            groups[start + j] = replace(groups[start + j], selected_ids=groups[start + j].remaining_ids[:count])
    digest = design_digest([asdict(pilot[key]) for key in sorted(pilot)])
    return ConfirmationDesign(plan.design_identity, digest, tuple(groups))


def estimate_fixed(
    plan: EstimationPlan,
    design: ConfirmationDesign,
    pilot_results: Sequence[RecipeObservation],
    confirmation_results: Sequence[RecipeObservation],
) -> tuple[RecipeEstimate, ...]:
    """Return one marginal approximate fixed-design estimate per registered recipe."""
    expected = allocate_confirmation(plan, pilot_results)
    if design != expected:
        raise ValueError("Confirmation design or frozen pilot changed")
    allowed_pilot = {(recipe.identity, member) for recipe in plan.recipes for member in plan.pilot_member_ids}
    pilot = _index_observations(plan, pilot_results, allowed_pilot)
    allowed_confirmation = {(row.recipe_id, i) for row in design.groups for i in row.selected_ids}
    observed = _index_observations(plan, confirmation_results, allowed_confirmation)
    members = {row.identity: row for row in plan.members}
    total_bytes = sum(member.size_bytes for member in plan.members)
    results = []
    for recipe in plan.recipes:
        estimates, gaps = [], []
        for group in (row for row in design.groups if row.recipe_id == recipe.identity):
            known = [pilot[recipe.identity, i] for i in group.pilot_ids]
            draws = [observed.get((recipe.identity, i)) for i in group.selected_ids]
            if any(not row.complete for row in known) or any(row is None or not row.complete for row in draws):
                estimate = GroupEstimate(
                    None,
                    None,
                    len(group.remaining_ids),
                    len(draws),
                    ("prescribed pilot or confirmation observations unresolved",),
                )
            else:
                positions = {member_id: i for i, member_id in enumerate(group.remaining_ids)}
                estimate = estimate_group(
                    tuple(row.saved_bytes for row in known),
                    tuple(members[i].size_bytes for i in group.remaining_ids),
                    tuple((positions[row.member_id], row.saved_bytes) for row in draws),
                    predictor=group.predictor,
                )
            estimates.append(estimate)
            gaps.extend(f"{group.stratum_key}: {gap}" for gap in estimate.gaps)
        point = (
            sum(row.estimated_saved_bytes for row in estimates)
            if all(row.estimated_saved_bytes is not None for row in estimates)
            else None
        )
        variance = (
            math.fsum(row.variance for row in estimates) if all(row.variance is not None for row in estimates) else None
        )
        interval = (
            None
            if point is None or variance is None or gaps
            else (point - _Z95 * math.sqrt(variance), point + _Z95 * math.sqrt(variance))
        )
        results.append(
            RecipeEstimate(
                recipe.identity,
                plan.design_identity,
                design.identity,
                point,
                variance,
                total_bytes,
                100 * point / total_bytes if point is not None and total_bytes else None,
                interval,
                tuple(estimates),
                tuple(gaps),
            )
        )
    return tuple(results)
