"""Solver correctness, including the properties that make refusal trustworthy.

The headline claim of MILAAN is that a reported match is arithmetically exact and
a reported ambiguity is genuinely ambiguous. Both are properties, not examples,
so both are tested against a brute-force oracle over randomised inputs: for small
n, every subset is enumerable, so ground truth here is a definition rather than
an opinion.
"""

from __future__ import annotations

import itertools
import random

import pytest

from milaan.solver.subsetsum import Budget, Outcome, solve


def brute(values: list[int], target: int) -> list[tuple[int, ...]]:
    """Every subset summing to target, by exhaustive enumeration. The oracle."""
    out = []
    for r in range(len(values) + 1):
        for combo in itertools.combinations(range(len(values)), r):
            if sum(values[i] for i in combo) == target:
                out.append(combo)
    return out


# ------------------------------------------------------------------ basics


def test_finds_a_simple_unique_cover():
    # Distinct amounts, so there is exactly one cover. (An earlier version of
    # this test used two identical 99p items and asserted UNIQUE — the solver
    # correctly reported AMBIGUOUS, because 99+250 and 99'+250 are two distinct
    # covers. See INCIDENTS.md #7.)
    r = solve([99, 130, 250, 700], 349)
    assert r.outcome is Outcome.UNIQUE
    assert r.solution == (0, 2)
    assert r.second_solution == ()


def test_razorpays_own_settlement_shape():
    """5 x 99p payments minus a 100p refund = 395p, from sample-combined-report."""
    values = [99, 99, 99, 99, 99, -100]
    r = solve(values, 395)
    assert r.outcome is Outcome.UNIQUE
    assert sum(values[i] for i in r.solution) == 395
    assert set(r.solution) == {0, 1, 2, 3, 4, 5}


def test_detects_ambiguity_and_supplies_both_witnesses():
    """Two 50p payments and one 100p payment: 100p has two distinct covers."""
    values = [50, 50, 100]
    r = solve(values, 100)
    assert r.outcome is Outcome.AMBIGUOUS
    assert r.solution != r.second_solution
    assert sum(values[i] for i in r.solution) == 100
    assert sum(values[i] for i in r.second_solution) == 100


def test_reports_no_cover_rather_than_a_near_miss():
    r = solve([100, 200, 400], 350)
    assert r.outcome is Outcome.NONE
    assert r.solution == ()


def test_identical_amounts_are_ambiguous_which_is_the_realistic_case():
    """A subscription merchant charging one price. Razorpay's sample is 5 x 99p.

    Any proper subset of k identical items has C(n,k) distinct covers, so a
    credit equal to k x 99p is genuinely undecidable from amounts alone. The
    solver must say so rather than pick one.
    """
    values = [99] * 6
    r = solve(values, 297)  # any 3 of the 6
    assert r.outcome is Outcome.AMBIGUOUS

    # ...but taking *all* of them is unique.
    assert solve(values, 594).outcome is Outcome.UNIQUE


# ------------------------------------------------------- budget is honest


def test_budget_exceeded_is_distinct_from_no_cover():
    """We must never report 'no cover' for a problem we declined to decide."""
    values = [10_000_000, 20_000_000, 30_000_000]
    r = solve(values, 50_000_000, budget=Budget(max_target_paise=1_000_000))
    assert r.outcome is Outcome.BUDGET_EXCEEDED
    assert r.outcome is not Outcome.NONE
    assert "max_target_paise" in r.reason


def test_too_many_items_is_declined_not_guessed():
    r = solve([7] * 900, 70, budget=Budget(max_items=512))
    assert r.outcome is Outcome.BUDGET_EXCEEDED


def test_out_of_range_target_is_a_clean_no_not_a_budget_failure():
    r = solve([100, 200], 5_000)
    assert r.outcome is Outcome.NONE
    assert "achievable range" in r.reason


# --------------------------------------------- properties vs brute force


@pytest.mark.parametrize("seed", range(40))
def test_agrees_with_brute_force_on_outcome_and_exactness(seed):
    """The core property: outcome matches exhaustive enumeration, and any
    reported solution actually sums to the target."""
    rng = random.Random(seed)
    n = rng.randint(1, 11)
    values = [rng.choice([1, 1]) * rng.randint(1, 400) * rng.choice([1, 1, 1, -1]) for _ in range(n)]
    target = rng.randint(-300, 900)

    result = solve(values, target)
    truth = brute(values, target)

    if result.outcome is Outcome.BUDGET_EXCEEDED:
        pytest.skip("declined by budget; correctness not claimed")

    if not truth:
        assert result.outcome is Outcome.NONE, (
            f"values={values} target={target}: solver said {result.outcome} "
            f"but no subset sums to target"
        )
    elif len(truth) == 1:
        assert result.outcome is Outcome.UNIQUE, (
            f"values={values} target={target}: unique cover {truth[0]} exists, "
            f"solver said {result.outcome}"
        )
        assert tuple(sorted(result.solution)) == truth[0]
    else:
        assert result.outcome is Outcome.AMBIGUOUS, (
            f"values={values} target={target}: {len(truth)} covers exist, "
            f"solver said {result.outcome}"
        )
        assert result.solution != result.second_solution

    if result.solution:
        assert sum(values[i] for i in result.solution) == target
    if result.second_solution:
        assert sum(values[i] for i in result.second_solution) == target


@pytest.mark.parametrize("seed", range(15))
def test_never_reports_a_solution_that_does_not_sum(seed):
    """The one thing that must never happen: a confident wrong join."""
    rng = random.Random(1000 + seed)
    values = [rng.randint(1, 5_000) * rng.choice([1, 1, 1, -1]) for _ in range(rng.randint(5, 30))]
    for _ in range(20):
        target = rng.randint(-5_000, 40_000)
        r = solve(values, target)
        if r.solution:
            assert sum(values[i] for i in r.solution) == target
        if r.second_solution:
            assert sum(values[i] for i in r.second_solution) == target


def test_uniqueness_claim_is_verified_not_assumed():
    """When the solver says UNIQUE, brute force must agree there is exactly one."""
    rng = random.Random(99)
    checked = 0
    for _ in range(300):
        n = rng.randint(1, 10)
        values = [rng.randint(1, 200) * rng.choice([1, 1, -1]) for _ in range(n)]
        target = rng.randint(-200, 600)
        r = solve(values, target)
        if r.outcome is Outcome.UNIQUE:
            assert len(brute(values, target)) == 1, (
                f"values={values} target={target}: claimed unique, "
                f"brute force found {len(brute(values, target))}"
            )
            checked += 1
    assert checked > 20, "expected a reasonable number of UNIQUE cases to verify"


def test_scales_to_a_realistic_settlement():
    """340 payments, one settlement-sized target, has to finish quickly."""
    rng = random.Random(4)
    values = [rng.randint(5_000, 500_000) for _ in range(340)]
    target = sum(values[:137])
    r = solve(values, target, budget=Budget(max_bit_operations=10**12, max_target_paise=10**9))
    assert r.outcome in {Outcome.UNIQUE, Outcome.AMBIGUOUS}
    if r.solution:
        assert sum(values[i] for i in r.solution) == target
