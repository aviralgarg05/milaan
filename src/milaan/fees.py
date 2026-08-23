"""The fee model, and the honest account of where it does not hold.

A settlement credit is `Σ(payment − fee) − Σ(refunds)`. So a cover only closes to
the paise if the fee for every member is exactly right. A one-paisa fee error
does not produce a slightly-wrong answer — it produces an *unexplained exception*
on a match that is otherwise correct.

That makes the fee model load-bearing, and it is the one part of MILAAN that
cannot be derived from first principles: Razorpay's published pricing gives a
rate, not a rounding rule, and the rounding rule is what a paise-exact identity
turns on.

So it was measured. Nineteen real captured test-mode payments, amounts chosen to
probe the rounding boundary rather than sampled — see `scripts/mint_links.py`.
The observations are pinned in `tests/test_fee_model.py` and reproduced below.

WHAT THE MEASUREMENT ESTABLISHED
--------------------------------
1. The base rate is **2.200%** of gross (`fee = amount × 11/500`), confirmed
   exactly at the four largest amounts.
2. Rounding is **not banker's**. Both amounts engineered to land the fee on
   exactly half a paise came back rounded *up*: ₹7.50 → 17p (banker's predicts
   16p) and ₹507.50 → 1117p (banker's predicts 1116p).
3. **Ceiling fits 16 of 18.** Plain half-up fits only 13. Ceiling is therefore
   the model, and `CEILING_FITS`/`OBSERVATIONS` below record the evidence.

WHAT IT DID NOT EXPLAIN, AND THIS IS NOT A ROUNDING QUESTION
------------------------------------------------------------
Two amounts sit one paise **above ceiling**:

    251p    exact 5.522    ceil 6    actual 7
    10251p  exact 225.522  ceil 226  actual 227

Both are `≡ 251 (mod 500)`; both are odd; both sit just above a half-paise
boundary. Their mirror images just *below* the boundary — 249p and 10249p, also
odd — match ceiling exactly.

This cannot be repaired by choosing a different rate. Requiring
`ceil(r × 10251) = 227` forces `r > 0.0220466`, while `ceil(r × 500000) = 11000`
forces `r ≤ 0.022`. Those intervals are disjoint, so **no single percentage with
any rounding rule reproduces both observations.** There is a discrete component
to Razorpay's fee computation that 19 samples do not resolve, and MILAAN does not
pretend otherwise.

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
`tax` is 0 on sixteen of the nineteen payments and non-zero only on the two
largest (₹2,499 → 990p and ₹5,000 → 1,980p, both exactly 18% of the base fee).
The threshold sits somewhere between ₹999 and ₹2,499 and is not documented. So
the GST line is only partially exercised in test mode, and `LIMITS.md` says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

__all__ = ["FeeEstimate", "fee_for", "RATE_NUM", "RATE_DEN", "OBSERVATIONS", "UNEXPLAINED"]

RATE_NUM, RATE_DEN = 11, 500  # 2.200% of gross
GST_NUM, GST_DEN = 18, 100

# (amount_paise, observed_fee_paise, observed_tax_paise) — 19 real captured
# test-mode payments, 23 Aug 2026. Ids in results/mint_batch.json.
OBSERVATIONS: tuple[tuple[int, int, int], ...] = (
    (100, 3, 0), (249, 6, 0), (250, 6, 0), (251, 7, 0), (750, 17, 0),
    (1250, 28, 0), (4900, 108, 0), (9900, 218, 0), (10249, 226, 0),
    (10250, 226, 0), (10251, 227, 0), (29900, 658, 0), (49900, 1098, 0),
    (50750, 1117, 0), (71300, 1569, 0), (99900, 2198, 0),
    (249900, 6488, 990), (500000, 12980, 1980),
)

# Amounts the ceiling model does not reproduce. Kept as data, not prose, so the
# test suite fails loudly if a future change silently "fixes" them by fitting.
UNEXPLAINED: tuple[int, ...] = (251, 10251)


def base_fee_ceiling(amount_paise: int) -> int:
    """2.200% of gross, rounded up to the paise. The working model."""
    if amount_paise < 0:
        raise ValueError("amount must be non-negative")
    exact = Decimal(amount_paise) * RATE_NUM / RATE_DEN
    return int(exact.quantize(Decimal("1"), rounding=ROUND_CEILING))


@dataclass(frozen=True, slots=True)
class FeeEstimate:
    amount_paise: int
    fee_paise: int
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


def fee_for(amount_paise: int, *, observed_fee: int | None = None,
            observed_tax: int | None = None) -> FeeEstimate:
    """Fee for one payment. Prefers Razorpay's returned value over the model.

    The model exists for entities whose fee was never observed. It never
    overrides an observed fee, because the observed value *is* the ground truth
    the cover has to close against.
    """
    if observed_fee is not None:
        return FeeEstimate(amount_paise, observed_fee, observed_tax or 0,
                           source="observed", confident=True)

    modelled = base_fee_ceiling(amount_paise)
    residue = amount_paise % RATE_DEN
    suspect = residue in {a % RATE_DEN for a in UNEXPLAINED}
    return FeeEstimate(
        amount_paise, modelled, 0, source="modelled", confident=not suspect,
        note=(
            f"amount ≡ {residue} (mod {RATE_DEN}); this residue class is one where "
            "measured fees exceeded the ceiling model by 1p (see UNEXPLAINED). "
            "Route to FEE_MODEL_RESIDUAL rather than closing a cover on it."
        ) if suspect else "",
    )
