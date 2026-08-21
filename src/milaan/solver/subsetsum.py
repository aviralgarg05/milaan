"""Exact subset-sum over signed paise, with uniqueness detection and a hard budget.

This is the fallback layer. Most bank credits are resolved by the anchor pass (a
UTR in the narration) or the interval pass (settlements batch by capture time, so
a cover is usually contiguous). What reaches here is the genuinely underdetermined
residual: a lump-sum credit, no usable reference, and a pool of candidate
transactions in which some subset sums to the credit.

Three things make this different from the textbook problem.

**Negatives.** A refund subtracts. The standard trick applies: let ``NEG`` be the
total magnitude of the negative items, and solve for ``target + NEG`` over
magnitudes, reading a *selected* negative as "this refund was **not** in the
settlement". The identity is

    T + Σ|neg|  =  Σ(chosen positives) + Σ(unchosen negatives)

so a pure-positive solver answers the signed question exactly, with the negative
half of the answer read off by complement.

**Uniqueness matters more than existence.** A reconciliation engine that returns
*a* cover is not useful; a wrong join is a silent financial misstatement that
produces a clean-looking report no downstream audit will catch. So the solver
looks for a *second* distinct solution and reports ``AMBIGUOUS`` when it finds
one. Ambiguity is common in exactly the businesses this matters for — a
subscription merchant charging one price has many identical amounts, and
Razorpay's own sample file is five identical 99p payments.

**Refusing is a valid answer.** Subset-sum is NP-complete and the bitset DP is
pseudo-polynomial in the target, so a large enough problem must be declined
rather than hung on. ``BUDGET_EXCEEDED`` is a first-class outcome, reported and
counted, never silently downgraded to "no cover found".

The DP itself is a Python big-int used as a bitset — ``reachable |= reachable << w``
sets every sum reachable by adding item ``w``, in one CPython-native shift.
Reconstruction checkpoints every ``√n`` items so peak memory stays at
``O(√n · target/8)`` bytes instead of ``O(n · target/8)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isqrt

__all__ = ["Outcome", "SubsetSumResult", "solve", "Budget"]


class Outcome(str, Enum):
    UNIQUE = "UNIQUE"
    """Exactly one subset sums to the target."""

    AMBIGUOUS = "AMBIGUOUS"
    """Two or more distinct subsets sum to the target. MILAAN refuses these."""

    NONE = "NONE"
    """No subset sums to the target."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    """The problem was too large to decide within the configured budget.

    Distinct from NONE: we do not know whether a cover exists. Reporting these
    as "no cover" would understate the exception list and overstate the match
    rate, so they are counted separately.
    """


@dataclass(frozen=True, slots=True)
class Budget:
    """Hard limits. Exceeding one yields BUDGET_EXCEEDED, never a wrong answer."""

    max_items: int = 512
    max_target_paise: int = 50_000_000  # ₹5,00,000 — a 6 MB bitset
    max_bit_operations: int = 400_000_000
    """Rough proxy for work: items × target bits. Keeps a single line bounded."""


@dataclass(frozen=True, slots=True)
class SubsetSumResult:
    outcome: Outcome
    solution: tuple[int, ...] = ()
    """Indices into the original ``values`` list, ascending. Empty unless UNIQUE."""

    second_solution: tuple[int, ...] = ()
    """A witness for AMBIGUOUS — the other cover, so the refusal is explainable."""

    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.outcome is Outcome.UNIQUE


def solve(
    values: list[int],
    target: int,
    *,
    budget: Budget | None = None,
    detect_ambiguity: bool = True,
) -> SubsetSumResult:
    """Find the subset of ``values`` (signed paise) summing exactly to ``target``.

    Returns UNIQUE with the solution, AMBIGUOUS with two witnesses, NONE, or
    BUDGET_EXCEEDED. Never returns an approximate or partial cover.
    """
    budget = budget or Budget()

    if not all(isinstance(v, int) for v in values):
        raise TypeError("subset-sum operates on integer paise only")
    if not isinstance(target, int):
        raise TypeError("target must be integer paise")

    n = len(values)
    if n > budget.max_items:
        return SubsetSumResult(
            Outcome.BUDGET_EXCEEDED,
            reason=f"{n} candidates exceeds max_items={budget.max_items}",
        )

    # Empty target is satisfied by the empty set, and only by it if no non-empty
    # subset also sums to zero. Zero-valued items make that non-trivial, so fall
    # through to the general path rather than special-casing.
    if n == 0:
        return (
            SubsetSumResult(Outcome.UNIQUE, ())
            if target == 0
            else SubsetSumResult(Outcome.NONE, reason="no candidates")
        )

    # --- shift signed problem to a non-negative one ------------------------
    # weight[i] is the magnitude; flipped[i] means "selecting this weight in the
    # shifted problem corresponds to EXCLUDING the original (negative) item".
    weights: list[int] = []
    flipped: list[bool] = []
    neg_total = 0
    for v in values:
        if v < 0:
            weights.append(-v)
            flipped.append(True)
            neg_total += -v
        else:
            weights.append(v)
            flipped.append(False)

    shifted = target + neg_total
    total = sum(weights)

    if shifted < 0 or shifted > total:
        return SubsetSumResult(
            Outcome.NONE,
            reason=(
                f"target {target}p is outside the achievable range "
                f"[{-neg_total}p, {total - neg_total}p]"
            ),
        )
    if shifted > budget.max_target_paise:
        return SubsetSumResult(
            Outcome.BUDGET_EXCEEDED,
            reason=f"shifted target {shifted}p exceeds max_target_paise={budget.max_target_paise}",
        )
    if n * shifted > budget.max_bit_operations:
        return SubsetSumResult(
            Outcome.BUDGET_EXCEEDED,
            reason=f"{n} items × {shifted}p exceeds max_bit_operations",
        )

    first = _find_one(weights, shifted)
    if first is None:
        return SubsetSumResult(Outcome.NONE, reason="no subset sums to the target")

    solution = _unshift(first, flipped, n)

    if not detect_ambiguity:
        return SubsetSumResult(Outcome.UNIQUE, solution)

    second_shifted = _find_second(weights, shifted, first)
    if second_shifted is not None:
        return SubsetSumResult(
            Outcome.AMBIGUOUS,
            solution=solution,
            second_solution=_unshift(second_shifted, flipped, n),
            reason="at least two distinct subsets sum exactly to the target",
        )

    return SubsetSumResult(Outcome.UNIQUE, solution)


def _unshift(selected: set[int], flipped: list[bool], n: int) -> tuple[int, ...]:
    """Map a shifted-problem selection back to original-item indices.

    A positive item is in the cover iff it was selected. A negative item is in
    the cover iff it was **not** selected — see the identity in the module
    docstring.
    """
    return tuple(
        i
        for i in range(n)
        if (i in selected) != flipped[i]  # selected-and-positive, or unselected-and-negative
    )


def _reach(weights: list[int], target: int, skip: int | None = None) -> list[int]:
    """Checkpointed reachability masks.

    Returns ``√n``-spaced snapshots of the reachable-sum bitset, enough to
    reconstruct a solution without holding one mask per item.
    """
    n = len(weights)
    step = max(1, isqrt(n))
    limit_mask = (1 << (target + 1)) - 1

    reachable = 1
    checkpoints = [(0, reachable)]
    for i, w in enumerate(weights):
        if i == skip:
            continue
        if w <= target:
            reachable = (reachable | (reachable << w)) & limit_mask
        if (i + 1) % step == 0:
            checkpoints.append((i + 1, reachable))
    checkpoints.append((n, reachable))
    return checkpoints


def _find_one(weights: list[int], target: int, forbid: set[int] | None = None) -> set[int] | None:
    """One subset of ``weights`` summing to ``target``, or None.

    ``forbid`` pins specific items *out* of the solution, which is how the
    second-solution search is driven.
    """
    n = len(weights)
    forbid = forbid or set()
    limit_mask = (1 << (target + 1)) - 1

    active = [i for i in range(n) if i not in forbid and weights[i] <= target]
    if not active:
        return set() if target == 0 else None

    step = max(1, isqrt(len(active)))
    reachable = 1
    checkpoints = [(0, reachable)]
    for pos, i in enumerate(active):
        reachable = (reachable | (reachable << weights[i])) & limit_mask
        if (pos + 1) % step == 0:
            checkpoints.append((pos + 1, reachable))
    if checkpoints[-1][0] != len(active):
        checkpoints.append((len(active), reachable))

    if not (reachable >> target) & 1:
        return None

    # Walk back through checkpoints, recomputing each block to decide membership.
    selected: set[int] = set()
    remaining = target
    for ci in range(len(checkpoints) - 1, 0, -1):
        block_start, _ = checkpoints[ci - 1]
        block_end, _ = checkpoints[ci]
        base = checkpoints[ci - 1][1]

        # Recompute this block's intermediate masks (small: √n of them).
        masks = [base]
        cur = base
        for pos in range(block_start, block_end):
            cur = (cur | (cur << weights[active[pos]])) & limit_mask
            masks.append(cur)

        for offset in range(block_end - block_start, 0, -1):
            i = active[block_start + offset - 1]
            w = weights[i]
            if (masks[offset - 1] >> remaining) & 1:
                continue  # reachable without this item; leave it out
            if remaining >= w and (masks[offset - 1] >> (remaining - w)) & 1:
                selected.add(i)
                remaining -= w
            else:  # pragma: no cover - implies an inconsistent mask
                raise AssertionError("reconstruction failed: inconsistent DP state")
        if remaining == 0:
            break

    return selected if remaining == 0 else None


def _find_second(weights: list[int], target: int, first: set[int]) -> set[int] | None:
    """Search for a solution distinct from ``first``.

    Any distinct solution must exclude at least one item that ``first``
    includes, so forbidding each member of ``first`` in turn is exhaustive: if
    every such restricted problem is infeasible, ``first`` is the unique cover.

    Cost is ``|first|`` DP passes. That is the price of being able to say
    "unique" rather than "found one", and being able to say it is the difference
    between a reconciliation engine and a suggestion engine.
    """
    for pinned_out in sorted(first):
        candidate = _find_one(weights, target, forbid={pinned_out})
        if candidate is not None and candidate != first:
            return candidate
    return None
