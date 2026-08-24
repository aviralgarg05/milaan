# Limits

What MILAAN does not do, does not know, and does not claim. Referenced from the
README, `DATA.md`, `INCIDENTS.md` and two test docstrings — this file is where
every hedge in the project resolves to a plain sentence.

## The claim, stated exactly

> Given a ledger and a set of bank credits grouped by a documented T+2
> working-day rule, MILAAN recovers the grouping on **80% of decidable credits**
> (12/15), correctly refuses **3 of 3** structurally-undecidable credits, and
> reported **zero wrong joins** across the batch.

The undecidable denominator dropped from 6 to 3 on purpose, and it *lowered* the
headline. See INCIDENTS.md #20: three of the six had been excused as "correctly
refused" when nothing in their construction guaranteed they were unrefusable. A
denominator that excuses whatever the engine failed at is not a measurement.

The last clause is guaranteed by arithmetic — a cover sums to the paise or it is
not accepted. The first two are measurements on a generated batch, and the
paragraphs below are why that distinction matters.

## What the match rate does not prove

It does **not** show that MILAAN would reconcile a real Indian merchant's real
bank statement.

- The **grouping is mine, not Razorpay's.** The generator assigns the entity ids,
  the capture timestamps and the settlement membership. An earlier version of the
  README claimed Razorpay authored these; it did not, and that claim is gone
  (INCIDENTS.md #21). What defends this batch is self-certification — a cover
  sums to the paise or it does not — plus the sealed generator, not external
  authorship.
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

- **18 credits, 237 ledger rows, one seed.** The percentages carry the precision
  of an 18-item sample and no more. 80% is 12 of 15.
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
its absence is why the interval layer carries 16 of 18 here.

Perturbed-interval matching is not built, and was diagnosed as the *wrong* fix
for the `WITH_REFUND` residue — that residue was an ordering bug, now fixed, and
those credits are 4/4 (INCIDENTS.md #19). Perturbation adds candidate covers and
would make ambiguity worse.

## Where the LLM is, and what it is worth

Both claims are now measured. **Usefulness: +0** — `milaan hints` runs the batch
against a perfect extractor and a hostile one; the perfect one adds nothing
because after the capture-time fix only two credits reach the layer at all and
neither has an opaque narration. **Safety: soundness holds unconditionally**
(every accepted cover is exact); the subset property holds except under
`BUDGET_EXCEEDED`, which is documented rather than glossed (INCIDENTS.md #22).

**The +0 is now properly supported.** An intermediate version measured +0 while
the layer was never invoked at all, which measures reachability rather than
usefulness. Under the agent it is consulted on 4 credits and still adds nothing.

**The layer is an optional extra and the core does not depend on it.** `anthropic`
is not a base dependency; `pip install -e ".[hints]"` is required to exercise it
against a model, and it has never been run against one — there is no API key in
this project. Its behaviour is characterised entirely by the oracle and malign
stand-ins.
