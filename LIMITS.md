# Limits

What MILAAN does not do, does not know, and does not claim. Referenced from the
README, `DATA.md`, `INCIDENTS.md` and two test docstrings — this file is where
every hedge in the project resolves to a plain sentence.

## The claim, stated exactly

> Given a ledger and a set of bank credits grouped by a documented T+2
> working-day rule, MILAAN recovers the grouping on **75% of decidable credits**
> (9/12), correctly refuses **6 of 6** planted-undecidable credits, and reported
> **zero wrong joins** across the batch.

The last clause is guaranteed by arithmetic — a cover sums to the paise or it is
not accepted. The first two are measurements on a generated batch, and the
paragraphs below are why that distinction matters.

## What the match rate does not prove

It does **not** show that MILAAN would reconcile a real Indian merchant's real
bank statement.

- The **grouping rule is mine.** T+2 working days is Razorpay's documented
  settlement cycle, but the batch applies my reading of it, not an observation of
  their engine. Holidays are not modelled, so a real calendar would shift some
  settlements by a day and change which transactions share one.
- The **narration strings are synthetic**, drawn from published bank statement
  formats. No real Indian bank emitted a line against my account. Held out by
  *format*, not by bank, because there were no external contributors.
- The **transaction mix is mine.** Amounts, refund frequency and batch sizes are
  chosen, not sampled from a real merchant.

What is *not* mine: the fee. Amounts settle net of
`ceil(a/50) + ceil(a/500)`, a model that reproduces 25 of 25 **real** Razorpay
charges (INCIDENTS.md #16). That is the part of the answer key Razorpay's own
billing engine authored, and a cover has to close against it to the paise.

## Why the batch is generated at all

Three independent limits each make a live-minted pool impossible, and all three
were found empirically, not assumed:

1. `GET /v1/settlements` returns empty on an unactivated test account, so
   Razorpay-authored groupings do not exist to harvest (probe E4).
2. Checkout runs hCaptcha, so payments cannot be captured programmatically, and
   defeating a payment provider's fraud controls to generate demo data is out of
   bounds (INCIDENTS.md #10).
3. Payment links are capped at **30 per test account** (INCIDENTS.md #13).

The sealed generator was chosen as primary ground truth on 21 August, before any
of these were known.

## What is measured on small numbers

- **18 credits, 269 ledger rows, one seed.** The percentages carry the precision
  of an 18-item sample and no more. 75% is 9 of 12.
- **25 measured payments** for the fee model, frozen by the 30-link cap. Enough
  to identify a two-component tariff and confirm it on every observation; not
  enough to rule out a third component that never fires in that range.
- **The GST threshold is unmeasured.** Tax is 0 on 23 of 25 payments and 18% on
  the two largest. The cutoff is somewhere between ₹999 and ₹2,499 and Razorpay
  does not document it. Test mode *does* break out GST above that line — an
  earlier version of `DATA.md` said it never does, which was wrong.

## What is not built

The anchor layer (UTR in a narration → settlement id) has a working grammar but
no join, because the generator does not link a narration's UTR to its
settlement — doing so would hand the solver the answer through the front door.
On real data this layer would resolve most credits before any search runs, and
its absence is why the interval layer carries 13 of 18 here.

Perturbed-interval matching (a contiguous run minus held items plus carry-ins)
is not built. It is the most likely fix for the `WITH_REFUND` residue, where 3
of 4 credits are currently refused.

## Where the LLM is, and what it is worth

The hint layer ships with its containment property proved and tested, but the
batch does not yet report how often it converts an exception into a match. Until
it does, the honest statement is that the **safety** property is demonstrated
and the **usefulness** is not yet measured. The two are separate claims and only
one of them is currently backed by a number.
