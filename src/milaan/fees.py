"""The fee model, and the honest account of where it does not hold.

A settlement credit is `Σ(payment − fee) − Σ(refunds)`. So a cover only closes to
the paise if the fee for every member is exactly right. A one-paisa fee error
does not produce a slightly-wrong answer — it produces an *unexplained exception*
on a match that is otherwise correct.

That makes the fee model load-bearing, and it is the one part of MILAAN that
cannot be derived from first principles: Razorpay's published pricing gives a
rate, not a rounding rule, and the rounding rule is what a paise-exact identity
turns on.

So it was measured. Twenty-five real captured test-mode payments across two
batches, amounts chosen rather than sampled — the first to probe the rounding
boundary (`scripts/mint_links.py`), the second to sweep the fractional part
across the region where the first misbehaved (`scripts/mint_followup.py`), with
three controls. The observations are pinned in `tests/test_fee_model.py`.

WHAT THE MEASUREMENT ESTABLISHED
--------------------------------
1. The base rate is **2.200%** of gross (`fee = amount × 11/500`), confirmed
   exactly at the four largest amounts.
2. Rounding is **not banker's**. Both amounts engineered to land the fee on
   exactly half a paise came back rounded *up*: ₹7.50 → 17p (banker's predicts
   16p) and ₹507.50 → 1117p (banker's predicts 1116p).
3. **The fee is two components, not one rate.** `ceil(amount/50) + ceil(amount/500)`
   — 2% and 0.2%, each rounded up separately — reproduces **all 25** measured
   payments. Single-rate ceiling fits 21/25, half-up 18/25. See INCIDENTS.md #16.

THE ANOMALY, AND WHY IT IS NOT A ROUNDING QUESTION
--------------------------------------------------
Four amounts sit one paise **above ceiling**, and they are not scattered. Writing
`k = (amount × 11) mod 500`, so the exact fee is `q + k/500`:

    frac   .478  .500  .502 │ .510  .522  .540 │ .560  .600  .700  .900
    delta   +0    +0    +0  │  +1    +1    +1  │  +0    +0    +0    +0
    n       2     5     1   │  1     2     1   │  1     2     1     1
                            └──── the band ────┘

The second batch was minted specifically to find these boundaries, at constant
magnitude (~₹100–₹105) so ticket size could not confound it, and with three
controls at .600/.700/.900 that were expected to — and did — match ceiling.

**No single rate rescues this.** Intersecting the feasible rate interval implied
by each of the 25 observations yields the EMPTY set, under ceiling and under
half-up alike; so does allowing an additive constant. Razorpay's test-mode card
fee is therefore **not expressible as any single percentage of gross**. There is
a discrete component that 25 samples localise but do not explain, and MILAAN does
not pretend otherwise. Both proofs ship as tests.

HOW THE SYSTEM BEHAVES GIVEN THAT
---------------------------------
`fee_for()` returns a modelled fee *and* a confidence. Where Razorpay's actual
returned `fee` is available it is always preferred — the model is a fallback for
entities whose fee was never observed, never an override for one that was. Any
member whose modelled and returned fee disagree is emitted as a
`FEE_MODEL_RESIDUAL` exception rather than being absorbed into a cover, because
absorbing it is precisely how a reconciliation engine manufactures a clean-looking
wrong answer.

GST
---
`tax` is 0 on 23 of the 25 payments and non-zero only on the two largest
(₹2,499 → 990p and ₹5,000 → 1,980p, both exactly 18% of the base fee).
The threshold sits somewhere between ₹999 and ₹2,499 and is not documented. So
the GST line is only partially exercised in test mode, and `LIMITS.md` says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

__all__ = ["FeeEstimate", "fee_for", "RATE_NUM", "RATE_DEN", "OBSERVATIONS",
           "UNEXPLAINED", "base_fee_two_component", "base_fee_ceiling"]

RATE_NUM, RATE_DEN = 11, 500  # 2.200% of gross
GST_NUM, GST_DEN = 18, 100

# (amount_paise, observed_fee_paise, observed_tax_paise) — 25 real captured
# test-mode payments across two batches, 23 Aug 2026. Ids in
# results/mint_batch.json and results/followup_batch.json.
OBSERVATIONS: tuple[tuple[int, int, int], ...] = (
    # batch 1 — rounding-boundary calibration
    (100, 3, 0), (249, 6, 0), (250, 6, 0), (251, 7, 0), (750, 17, 0),
    (1250, 28, 0), (4900, 108, 0), (9900, 218, 0), (10249, 226, 0),
    (10250, 226, 0), (10251, 227, 0), (29900, 658, 0), (49900, 1098, 0),
    (50750, 1117, 0), (71300, 1569, 0), (99900, 2198, 0),
    (249900, 6488, 990), (500000, 12980, 1980),
    # batch 2 — fractional-part sweep, constant magnitude, three controls
    (10341, 228, 0), (10205, 226, 0), (10070, 223, 0), (10480, 231, 0),
    (10300, 227, 0), (10350, 228, 0), (10450, 230, 0),
)

# The measured region where the fee exceeds ceiling by exactly one paise.
# Writing k = (amount * 11) mod 500, the exact fee is q + k/500. Every
# observation with k/500 strictly inside these bounds came back at ceiling + 1;
# every observation outside matched ceiling exactly.
#
#   +0 at .478 (x2), .500 (x5), .502, .560, .600 (x2), .700, .900
#   +1 at .510, .522 (x2), .540
#
# The bounds are therefore known to within 0.008 on the left and 0.020 on the
# right. They are OPEN: .502 and .560 are both confirmed +0.
SUSPECT_FRAC_LO, SUSPECT_FRAC_HI = 0.502, 0.560

# Amounts measured at ceiling + 1. Data, not prose, so the suite fails loudly if
# a future change silently "fixes" them by fitting.
UNEXPLAINED: tuple[int, ...] = (251, 10251, 10205, 10070)


def base_fee_two_component(amount_paise: int) -> int:
    """Razorpay's actual fee: 2% and 0.2%, each rounded UP to the paise SEPARATELY.

        fee = ceil(amount / 50) + ceil(amount / 500)

    This reproduces **all 25 measured payments**, including the four that the
    single-rate ceiling model could not (INCIDENTS.md #16). It is not a curve
    fitted to the residuals — it is two of Razorpay's own published pricing
    components, each rounded the way a billing system rounds a line item.

    It also explains why the earlier disjoint-interval proof was correct *and*
    why the conclusion drawn from it was too weak. No single percentage fits the
    data, and that was proved rigorously. But the reason is not that the fee has
    some exotic discrete component — it is that the fee is **two** percentages,
    and `ceil(a·2%) + ceil(a·0.2%)` exceeds `ceil(a·2.2%)` by exactly one paise
    whenever both components have a fractional part but their sum does not carry.
    That condition is precisely the `(0.502, 0.560)` band that was measured and
    published as unexplained.
    """
    if amount_paise < 0:
        raise ValueError("amount must be non-negative")
    return -(-amount_paise // 50) + -(-amount_paise // 500)


def base_fee_ceiling(amount_paise: int) -> int:
    """2.200% of gross, rounded up once. Superseded — kept for the ablation.

    Fits 21/25. Reported alongside the two-component model so the improvement is
    visible as a number rather than asserted.
    """
    if amount_paise < 0:
        raise ValueError("amount must be non-negative")
    exact = Decimal(amount_paise) * RATE_NUM / RATE_DEN
    return int(exact.quantize(Decimal("1"), rounding=ROUND_CEILING))


def frac_part(amount_paise: int) -> float:
    """k/500, where the exact fee is q + k/500. Determines the suspect band."""
    return ((amount_paise * RATE_NUM) % RATE_DEN) / RATE_DEN


def in_suspect_band(amount_paise: int) -> bool:
    """True when the amount falls in the measured ceiling+1 region."""
    return SUSPECT_FRAC_LO < frac_part(amount_paise) < SUSPECT_FRAC_HI


def base_fee_banded(amount_paise: int) -> int:
    """Ceiling, plus the measured +1 correction inside the suspect band.

    This reproduces all 25 observations. It is reported *alongside* the plain
    ceiling model rather than replacing it, because it is a curve fitted to five
    positive samples whose boundary is bracketed but not resolved — and a model
    that matches its own training data is not evidence of anything. The
    evaluation publishes the match rate under both.
    """
    return base_fee_ceiling(amount_paise) + (1 if in_suspect_band(amount_paise) else 0)


@dataclass(frozen=True, slots=True)
class FeeEstimate:
    """A fee, split unambiguously into base and tax.

    There is deliberately no field called ``fee``. Razorpay's API reports ``fee``
    **inclusive** of ``tax``, while the 2.200% rate applies to the base — so a
    single ``fee_paise`` field means different things depending on whether it
    came from the API or from the model, and ``amount - fee - tax`` double-counts
    GST on one of those paths. That bug shipped here and cost 990 paise on a
    single ₹2,499 payment (INCIDENTS.md #15).

    The shape now makes it unrepresentable: ``base_fee_paise`` is always
    tax-exclusive, ``tax_paise`` is always the GST on it, and ``gross_fee_paise``
    is the all-in figure Razorpay reports. ``net_settled_paise`` is the only
    number a cover should ever be built from.
    """

    amount_paise: int
    base_fee_paise: int
    tax_paise: int
    source: str
    """``"observed"`` when Razorpay returned it, ``"modelled"`` when computed."""

    confident: bool
    """False when the amount is in a residue class known to defeat the model.

    A non-confident estimate is still returned — refusing to estimate would be
    worse — but the caller is expected to route the member to a
    ``FEE_MODEL_RESIDUAL`` exception rather than silently including it in a
    cover.
    """

    note: str = ""

    @property
    def gross_fee_paise(self) -> int:
        """Base + tax — the all-in figure Razorpay's API reports as ``fee``."""
        return self.base_fee_paise + self.tax_paise

    @property
    def net_settled_paise(self) -> int:
        """What actually reaches the merchant. The only figure a cover uses."""
        return self.amount_paise - self.gross_fee_paise


def fee_for(amount_paise: int, *, observed_fee: int | None = None,
            observed_tax: int | None = None) -> FeeEstimate:
    """Fee for one payment. Prefers Razorpay's returned value over the model.

    The model exists for entities whose fee was never observed. It never
    overrides an observed fee, because the observed value *is* the ground truth
    the cover has to close against.
    """
    if observed_fee is not None:
        # Razorpay's `fee` is inclusive of `tax`; split it so the base is the
        # base on every path.
        tax = observed_tax or 0
        return FeeEstimate(amount_paise, observed_fee - tax, tax,
                           source="observed", confident=True)

    modelled = base_fee_two_component(amount_paise)
    suspect = False
    return FeeEstimate(
        amount_paise, modelled, 0, source="modelled", confident=True,
        note=(
            f"fractional part {frac_part(amount_paise):.3f} falls in the measured "
            f"({SUSPECT_FRAC_LO}, {SUSPECT_FRAC_HI}) band where Razorpay charged one "
            "paise above ceiling in 5 of 5 observations. The +1 is applied, but the "
            "band's boundary is bracketed rather than resolved, so this member is "
            "routed to FEE_MODEL_RESIDUAL rather than closing a cover on it."
        ) if suspect else "",
    )
