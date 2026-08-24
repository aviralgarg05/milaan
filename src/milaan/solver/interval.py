"""The interval layer — and the reason the blind solver alone is not enough.

A settlement is not an arbitrary subset of the ledger. Razorpay batches by
capture time: everything eligible in a window settles together on T+2 working
days. So a cover is almost always a **contiguous run in capture order**, and
searching contiguous runs instead of arbitrary subsets changes the problem from
intractable-and-ambiguous to linear-and-usually-unique.

**Why this layer is not an optimisation.** The first end-to-end run of MILAAN
used the blind subset-sum solver alone on a ±6-day candidate pool. It reported
`AMBIGUOUS_COVER` on **18 of 18** credits and a match rate of **zero** — and it
was right to. With ~200 candidates there are 2²⁰⁰ subsets and only ~10⁷
achievable paise sums in range, so by pigeonhole almost every target has many
exact covers. Ambiguity is not an edge case at that pool size; it is the
overwhelmingly likely outcome, and an engine that reported a single cover anyway
would be guessing.

That is the empirical case for structure over search, and it is worth stating in
the negative: **exact-cover search alone is not a reconciliation strategy.** It
is a fallback for the residue after structure has done its work. See
INCIDENTS.md #17.

Contiguity collapses the search space from 2ⁿ subsets to n(n+1)/2 intervals —
about 20,000 for n=200 rather than 10⁶⁰ — which is few enough that an exact
collision is informative rather than inevitable. When two intervals do sum
alike, that is a real ambiguity worth refusing, not a counting artefact.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["IntervalResult", "find_intervals"]


@dataclass(frozen=True, slots=True)
class IntervalResult:
    covers: tuple[tuple[int, ...], ...]
    """Every contiguous run summing to the target, as index tuples into the sorted order."""

    scanned: int = 0

    @property
    def unique(self) -> bool:
        return len(self.covers) == 1

    @property
    def ambiguous(self) -> bool:
        return len(self.covers) > 1


def find_intervals(values: list[int], target: int, *, max_covers: int = 8) -> IntervalResult:
    """Find every contiguous run of ``values`` summing exactly to ``target``.

    ``values`` must already be in capture order — the caller owns the sort,
    because the ordering is a domain fact (when Razorpay captured the payment)
    and not something this function can infer.

    Linear in n via prefix sums and a hash map: for each endpoint ``j`` we look
    up how many earlier prefixes equal ``prefix[j] - target``. Saturates at
    ``max_covers`` because the caller only needs to distinguish none / one /
    more-than-one, and enumerating every collision on a pathological input is
    wasted work.
    """
    if not all(isinstance(v, int) for v in values):
        raise TypeError("interval search operates on integer paise only")
    if max_covers < 2:
        # At max_covers=1 the search returns after the first hit, so `unique`
        # would be True on a provably ambiguous input — the caller could not tell
        # one cover from many, which is the distinction this whole module exists
        # to preserve.
        raise ValueError("max_covers must be >= 2 to distinguish unique from ambiguous")

    # prefix[i] is the sum of the first i values, so the run [i, j) sums to
    # prefix[j] - prefix[i]. Sums are exact because everything is an int.
    prefix = [0]
    for v in values:
        prefix.append(prefix[-1] + v)

    seen: dict[int, list[int]] = {}
    covers: list[tuple[int, ...]] = []

    for j in range(len(prefix)):
        seen.setdefault(prefix[j], []).append(j)

    for j in range(1, len(prefix)):
        wanted = prefix[j] - target
        for i in seen.get(wanted, ()):
            if i >= j:
                break  # `seen` lists are ascending; nothing later can start before j
            covers.append(tuple(range(i, j)))
            if len(covers) >= max_covers:
                return IntervalResult(tuple(covers), scanned=len(values))

    # The empty run sums to zero; it is a cover of a zero target but never of a
    # non-zero one, and it is never a useful answer for a bank credit.
    covers = [c for c in covers if c]
    return IntervalResult(tuple(covers), scanned=len(values))
