"""The fee model, pinned against 25 real captured Razorpay test payments.

These are not fixtures I invented. Each row is a live test-mode payment with a
Razorpay-issued id (see `results/mint_batch.json`), whose `fee` and `tax` were
computed by Razorpay's own engine. The amounts were chosen to probe the rounding
boundary — `fee = amount × 11/500`, so amounts congruent to 250 mod 500 land the
fee on exactly half a paise — and then, in a second batch, to sweep the
fractional part across the region where the first batch misbehaved.

The point of this file is not that the model is right. It is that the model's
error is **measured, bounded and named**, and that no single percentage of gross
reproduces all 25 observations under any rounding rule.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest

from milaan.fees import (
    OBSERVATIONS,
    base_fee_banded,
    in_suspect_band,
    RATE_DEN,
    RATE_NUM,
    UNEXPLAINED,
    base_fee_ceiling,
    fee_for,
)


def _exact(amount: int) -> Decimal:
    return Decimal(amount) * RATE_NUM / RATE_DEN


def _q(amount: int, rounding) -> int:
    return int(_exact(amount).quantize(Decimal("1"), rounding=rounding))


def _base(fee: int, tax: int) -> int:
    """Razorpay reports `fee` inclusive of `tax`; the rate applies to the base."""
    return fee - tax


# --------------------------------------------------------------- the rate


def test_base_rate_is_exactly_2_2_percent_at_large_amounts():
    """Where rounding cannot hide it, the rate is exactly 11/500."""
    for amount, fee, tax in OBSERVATIONS:
        if amount >= 49_900:
            assert _base(fee, tax) == _q(amount, ROUND_HALF_UP), (
                f"{amount}p: base fee {_base(fee, tax)}p is not 2.200%"
            )


def test_gst_is_18_percent_of_the_base_fee_where_it_appears():
    charged = [(a, f, t) for a, f, t in OBSERVATIONS if t]
    assert charged, "expected at least one payment carrying GST"
    for amount, fee, tax in charged:
        base = _base(fee, tax)
        expected = int((Decimal(base) * 18 / 100).quantize(Decimal("1"), ROUND_HALF_UP))
        assert tax == expected, f"{amount}p: tax {tax}p is not 18% of base {base}p"


def test_gst_is_absent_below_a_threshold_that_razorpay_does_not_document():
    """Twenty-two of 25 payments carry tax=0. The threshold is unpublished.

    This is why `LIMITS.md` says the GST line is only partially exercised: below
    roughly ₹1,000 test mode returns an all-in fee and never breaks out tax, so
    MILAAN cannot claim to have reconciled a GST-bearing settlement at small
    ticket sizes.
    """
    taxed = [a for a, _, t in OBSERVATIONS if t]
    untaxed = [a for a, _, t in OBSERVATIONS if not t]
    assert min(taxed) > max(untaxed), (
        "expected a clean threshold: every taxed amount above every untaxed one"
    )
    assert max(untaxed) == 99_900 and min(taxed) == 249_900, (
        "threshold moved; re-measure and update LIMITS.md"
    )


# ----------------------------------------------------------- the rounding


def test_rounding_is_not_bankers():
    """The question the calibration batch was built to answer.

    Two amounts put the fee on exactly half a paise. Banker's rounding would
    round both to even, i.e. *down*. Razorpay rounded both up.
    """
    probes = [a for a, _, _ in OBSERVATIONS if (a * RATE_NUM) % RATE_DEN * 2 == RATE_DEN]
    assert probes, "the calibration batch must contain exact-half-paise amounts"

    distinguishing = [a for a in probes if _q(a, ROUND_HALF_UP) != _q(a, ROUND_HALF_EVEN)]
    assert len(distinguishing) >= 2, f"need >=2 distinguishing probes, got {distinguishing}"

    observed = dict((a, _base(f, t)) for a, f, t in OBSERVATIONS)
    for amount in distinguishing:
        assert observed[amount] == _q(amount, ROUND_HALF_UP), (
            f"{amount}p: expected half-up {_q(amount, ROUND_HALF_UP)}p, "
            f"got {observed[amount]}p"
        )
        assert observed[amount] != _q(amount, ROUND_HALF_EVEN)


def test_ceiling_beats_half_up_and_is_the_model():
    ceil_fits = sum(_base(f, t) == _q(a, ROUND_CEILING) for a, f, t in OBSERVATIONS)
    half_up_fits = sum(_base(f, t) == _q(a, ROUND_HALF_UP) for a, f, t in OBSERVATIONS)

    assert ceil_fits == 21, f"ceiling fit changed: {ceil_fits}/25"
    assert half_up_fits == 18, f"half-up fit changed: {half_up_fits}/25"
    assert ceil_fits > half_up_fits


def test_the_model_matches_every_observation_it_claims_to():
    for amount, fee, tax in OBSERVATIONS:
        if amount in UNEXPLAINED:
            continue
        assert base_fee_ceiling(amount) == _base(fee, tax), (
            f"{amount}p: model says {base_fee_ceiling(amount)}p, "
            f"Razorpay charged {_base(fee, tax)}p"
        )


# ------------------------------------------------- the part that is unknown


@pytest.mark.parametrize("amount", UNEXPLAINED)
def test_the_unexplained_residuals_are_still_unexplained(amount):
    """A guard against quietly 'fixing' these by fitting a model to them.

    Four amounts came back one paise ABOVE plain ceiling. If a future change
    makes the *ceiling* model reproduce them, that change must be deliberate and
    documented — not a coincidence of refactoring. (`base_fee_banded` is expected
    to reproduce them; that is what it is for.)
    """
    observed = dict((a, _base(f, t)) for a, f, t in OBSERVATIONS)
    assert observed[amount] == base_fee_ceiling(amount) + 1, (
        f"{amount}p no longer sits 1p above ceiling — if this is a real fix, "
        "update fees.py UNEXPLAINED and the docstring rather than deleting this test"
    )


def test_no_single_rate_can_explain_both_extremes():
    """The proof that this is not a rounding question.

    `ceil(r × 10251) = 227` requires r > 226/10251. `ceil(r × 500000) = 11000`
    requires r ≤ 11000/500000. Those intervals do not overlap, so there is a
    discrete component to Razorpay's fee that a percentage cannot express.
    """
    lower_bound_from_10251 = Decimal(226) / 10251
    upper_bound_from_500000 = Decimal(11000) / 500000

    assert lower_bound_from_10251 > upper_bound_from_500000, (
        "the intervals now overlap — a single rate may exist after all; re-derive"
    )


def test_suspect_residues_are_flagged_rather_than_silently_estimated():
    """An unobserved fee in a known-bad residue class must not close a cover."""
    estimate = fee_for(500_251)  # ≡ 251 (mod 500), never observed
    assert estimate.source == "modelled"
    assert estimate.confident is False
    assert "FEE_MODEL_RESIDUAL" in estimate.note

    ordinary = fee_for(4_900)
    assert ordinary.confident is True and ordinary.note == ""


def test_an_observed_fee_always_wins_over_the_model():
    """The model is a fallback, never an override. Ground truth is what Razorpay charged."""
    estimate = fee_for(251, observed_fee=7)
    assert estimate.fee_paise == 7
    assert estimate.source == "observed"
    assert estimate.confident is True
    assert base_fee_ceiling(251) == 6, "the model would have said 6, and would be wrong"


# ------------------------------------------------- the measured band


def test_the_suspect_band_is_bracketed_by_controls_on_both_sides():
    """The +1 region is not asserted, it is bounded by observations either side.

    Four payments inside the band came back at ceiling+1 (.510, .522 twice, .540).
    Twenty-one outside it matched ceiling exactly — including .502 and .560, which
    bracket the band to within 0.008 on the left and 0.020 on the right, and three
    amounts minted specifically as controls (.600, .700, .900). A backend change
    affecting everything would have shown up as the controls drifting too. They
    did not.
    """
    inside, outside = [], []
    for amount, fee, tax in OBSERVATIONS:
        delta = _base(fee, tax) - _q(amount, ROUND_CEILING)
        (inside if in_suspect_band(amount) else outside).append((amount, delta))

    assert all(d == 1 for _, d in inside), f"band should be uniformly +1: {inside}"
    assert all(d == 0 for _, d in outside), f"outside band should be uniformly +0: {outside}"
    assert len(inside) == 4 and len(outside) == 21


def test_the_banded_model_reproduces_every_observation():
    """...and is reported alongside plain ceiling, never instead of it.

    This model fits its own training data by construction. That is exactly why
    the evaluation publishes the match rate under BOTH models — a curve fitted to
    four points is a hypothesis, not a result.
    """
    for amount, fee, tax in OBSERVATIONS:
        assert base_fee_banded(amount) == _base(fee, tax), f"{amount}p"


def test_no_single_rate_fits_all_observations_under_any_rounding():
    """The strongest form of the claim, over all 25 measurements.

    Intersecting the feasible rate interval implied by each observation yields the
    EMPTY set, for ceiling and for half-up alike. Razorpay's test-mode card fee is
    therefore not expressible as any single percentage of gross.
    """
    from fractions import Fraction

    for rule in ("ceil", "round"):
        lo, hi = Fraction(0), Fraction(1)
        for amount, fee, tax in OBSERVATIONS:
            base = _base(fee, tax)
            if rule == "ceil":
                l, h = Fraction(base - 1, amount), Fraction(base, amount)
            else:
                l, h = Fraction(2 * base - 1, 2 * amount), Fraction(2 * base + 1, 2 * amount)
            lo, hi = max(lo, l), min(hi, h)
        assert lo >= hi, f"a single rate now fits under {rule}: ({float(lo)}, {float(hi)}]"


def test_no_additive_constant_rescues_the_rate_either():
    from fractions import Fraction

    lo, hi = Fraction(-1000), Fraction(1000)
    for amount, fee, tax in OBSERVATIONS:
        exact = Fraction(amount * RATE_NUM, RATE_DEN)
        lo, hi = max(lo, Fraction(_base(fee, tax) - 1) - exact), min(hi, Fraction(_base(fee, tax)) - exact)
    assert lo >= hi, f"fee = ceil(0.022*a + c) now fits with c in ({float(lo)}, {float(hi)}]"
