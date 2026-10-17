"""Independent exact-arithmetic design checks, prepared before production estimation."""

from fractions import Fraction
from itertools import combinations

import pytest


def test_fixed_wrong_predictor_has_exact_expectation_and_variance():
    from estimation_reference import fixed_group

    # Pilot savings=6; remaining savings=9,-4,20. True total=31.
    # Deliberately poor prediction=2*x+7. Enumerate every possible n=2 draw.
    expected = [
        (Fraction(87, 2), Fraction(3267, 4)),
        (Fraction(99, 2), Fraction(2523, 4)),
        (0, 12),
    ]
    actual = [
        fixed_group([1, 5], [30, 40, 50], [9, -4, 20], draw, (7, 2))
        for draw in combinations(range(3), 2)
    ]
    assert actual == expected
    assert sum(total for total, _ in actual) / 3 == 31
    assert sum(var for _, var in actual) / 3 == Fraction(973, 2)
    assert sum((total - 31) ** 2 for total, _ in actual) / 3 == Fraction(973, 2)


def test_unpredicted_estimator_census_and_signed_growth():
    from estimation_reference import fixed_group

    draws = [
        fixed_group([1, 5], [30, 40, 50], [9, -4, 20], draw)
        for draw in combinations(range(3), 2)
    ]
    assert [value for value, _ in draws] == [Fraction(27, 2), Fraction(99, 2), 30]
    assert sum(var for _, var in draws) / 3 == Fraction(433, 2)
    assert fixed_group([1, 5], [30, 40, 50], [9, -4, 20], (0, 1, 2), (7, 2)) == (31, 0)
    assert fixed_group([], [10, 20], [-20, -10], (0, 1)) == (-30, 0)


def test_exact_prediction_and_unknown_uncertainty():
    from estimation_reference import fixed_group

    assert fixed_group([27, 47], [30, 40, 50], [67, 87, 107], (0, 1), (7, 2)) == (
        335,
        0,
    )
    assert fixed_group([1, 5], [30, 40, 50], [9, -4, 20], ()) == (None, None)
    assert fixed_group([1, 5], [30, 40, 50], [9, -4, 20], (0,)) == (33, None)
    assert fixed_group([1, 5], [], [], ()) == (6, 0)
    with pytest.raises(ValueError, match="distinct"):
        fixed_group([], [10, 20], [1, 2], (0, 0))


def test_sequential_range_uses_whole_remaining_population_and_two_tails():
    from estimation_reference import round_half_width

    delta, half_width = round_half_width(
        [10, 20, 40], [5, 10, 20], 2, recipe=1, round_index=1, groups=1
    )
    assert delta == Fraction(1, 80)
    # L=-20, U=20, W=40; 3*40*sqrt(log(160)/(2*2)).
    assert float(half_width) == pytest.approx(135.16887857358947, rel=1e-12)
    assert (
        round_half_width(
            [10, 20, 40], [5, 10, 20], 3, recipe=1, round_index=1, groups=1
        )[1]
        == 0
    )
    assert (
        round_half_width(
            [10, 20, 40], [5, 10, 20], 0, recipe=1, round_index=1, groups=1
        )[1]
        is None
    )


def test_alpha_spending_does_not_reset_between_recipes_and_rounds():
    from estimation_reference import round_half_width

    spent = sum(
        round_half_width([1, 2], [0, 0], 1, recipe=k, round_index=r, groups=3)[0] * 3
        for k in range(1, 9)
        for r in range(1, 9)
    )
    assert spent == Fraction(65025, 1310720)
    assert spent < Fraction(1, 20)
