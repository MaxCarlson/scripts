"""Slow test-only mathematical oracles. Never import production estimation here.

Fractions avoid cancellation in finite-population enumeration; Decimal supplies
an independent high-precision path for logarithmic bounds. These helpers do not
select samples, validate source files, or establish sequential-design validity.
"""

from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Sequence


def fixed_group(
    pilot_savings: Sequence[int],
    remaining_bytes: Sequence[int],
    remaining_savings: Sequence[int],
    chosen: Sequence[int],
    predictor: tuple[int, int] = (0, 0),
) -> tuple[Fraction | None, Fraction | None]:
    """Return a fixed group's total and estimated variance from a complete toy population."""
    size = len(remaining_bytes)
    if len(remaining_savings) != size:
        raise ValueError("Toy population lengths must agree")
    if len(set(chosen)) != len(chosen) or any(
        index < 0 or index >= size for index in chosen
    ):
        raise ValueError("Sample indices must be distinct population members")
    known = sum(map(Fraction, pilot_savings))
    if not size:
        return Fraction(known), Fraction(0)
    count = len(chosen)
    if not count:
        return None, None
    if count == size:
        return Fraction(known + sum(remaining_savings)), Fraction(0)
    intercept, slope = map(Fraction, predictor)
    predictions = [intercept + slope * value for value in remaining_bytes]
    residuals = [
        Fraction(remaining_savings[index]) - predictions[index] for index in chosen
    ]
    mean = sum(residuals) / count
    total = known + sum(predictions) + size * mean
    if count == 1:
        return total, None
    sample_variance = sum((value - mean) ** 2 for value in residuals) / (count - 1)
    variance = size**2 * Fraction(size - count, size) * sample_variance / count
    return total, variance


def round_half_width(
    remaining_bytes: Sequence[int],
    predictions: Sequence[int],
    count: int,
    *,
    recipe: int,
    round_index: int,
    groups: int,
) -> tuple[Fraction, Decimal | None]:
    """Return the declared alpha share and conservative two-tailed group bound.

    Inputs are the WHOLE frozen remainder, not just the observed sample. The caller
    must independently prove uniform sampling and bounded retained-original savings.
    """
    size = len(remaining_bytes)
    if len(predictions) != size or any(value < 0 for value in remaining_bytes):
        raise ValueError(
            "Known nonnegative byte sizes and matching predictions required"
        )
    if not 0 <= count <= size or min(recipe, round_index, groups) < 1:
        raise ValueError("Invalid draw size or one-based alpha-spending indices")
    delta = Fraction(1, 20 * 2 ** (recipe + round_index) * groups)
    if count == size:
        return delta, Decimal(0)
    if not count:
        return delta, None
    lower = min(-Fraction(value) for value in predictions)
    upper = max(
        Fraction(value) - prediction
        for value, prediction in zip(remaining_bytes, predictions)
    )
    width = upper - lower
    with localcontext() as context:
        context.prec = 60
        exact_width = Decimal(width.numerator) / Decimal(width.denominator)
        two_over_delta = Decimal(2 * delta.denominator) / Decimal(delta.numerator)
        radius = (
            Decimal(size)
            * exact_width
            * (two_over_delta.ln() / Decimal(2 * count)).sqrt()
        )
    return delta, radius
