# Incidents

What broke, and how I got out. Written as it happened, not reconstructed.

Every entry carries the symptom, the cause, the commit that fixed it, and the
regression test that now pins it. Entries stay even when the finding was that I
was wrong — especially then.

---

### #1 — `groupby('settlement_id')` loses every settlement total

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlement_rows_do_not_carry_their_own_settlement_id`

**Symptom.** My first pass at the closure identity reported `NO-SETTLEMENT-ROW`
for all four settlements, and one spurious bucket keyed `None` holding a total
of 198p with zero members. Every group looked like it was missing its total.

**Cause.** In a Razorpay combined report a settlement row's own identifier lives
in `entity_id`, and its `settlement_id` column is null. Member rows point *up* to
the settlement via `settlement_id`. So grouping the whole file by
`settlement_id` collects every settlement row into a single `None` bucket and
leaves each real group headless. The obvious one-liner produces a confidently
wrong answer rather than an error.

**Fix.** Two separate accessors that cannot be confused: `group_by_settlement()`
keys members by `settlement_id` and explicitly excludes settlement rows;
`settlement_rows()` keys totals by `entity_id`. The test asserts `None` is never
a key and no member is itself a settlement.

---

### #2 — a blank column A silently shifts every field

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlements_report_has_a_blank_column_a`

**Symptom.** `sample-settlements-report.xlsx` parsed without error and produced
nonsense — the settlement id landed in the amount field.

**Cause.** The file's headers start at **B1**, not A1, and it carries 19 trailing
all-`None` columns. Anything that reads by ordinal position — `read_excel` with
default arguments included — shifts every column by one. This does not raise. It
succeeds, with all the data in the wrong fields, which is worse.

**Fix.** The loader locates the header row as the first row with more than two
populated cells, then indexes strictly by *header position*, discarding columns
with no header. Ordinals are never used.

---

### #3 — one column, two Python types, three date formats

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_date_columns_mix_datetime_and_str_in_the_same_column`

**Symptom.** `AttributeError: 'datetime.datetime' object has no attribute 'strip'`
partway through the batch — after several rows had already parsed fine.

**Cause.** `created_at` in Razorpay's sample holds native `datetime` objects
*and* strings, in the same column. Measured across the file's two date columns
there are 18 distinct (column, type, value) shapes, with strings in three
formats: `2022-04-07 10:43:32`, `14/07/2022 10:01:14`, and `14-07-2022`.

**Fix.** `reports/dates.py` dispatches on type first, then tries an ordered list
of day-first formats. It never raises — an unparseable cell yields
`ParsedDate(value=None)` with the original preserved, so one bad timestamp
becomes a named exception downstream instead of killing a 340-row batch.

**The part that isn't fixed, by choice.** `07/04/2022` is genuinely ambiguous.
MILAAN reads day-first (Indian convention) and *counts* every value that could
have been read either way. The count is reported per run. A settlement window
that is off by a month changes which payments are candidates for a cover, so
this is surfaced rather than resolved by guessing.

---

### #4 — the UTR column exists but the data doesn't

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlement_utr_is_null_in_every_row_of_the_combined_report`

**Symptom.** The anchor pass — match a bank credit to a settlement by UTR, skip
the solver entirely — had nothing to match on. 0 of 14 rows carried a UTR.

**Cause.** `settlement_utr` is a real column in the combined report and is null
in every row of Razorpay's published sample. The UTR lives only in the
*settlements* report, under the plain name `utr`. The two files are not
interchangeable, though they look it.

**Fix.** The anchor pass joins combined → settlements to recover a UTR. Noted
for later: the API's `/v1/settlements/recon/combined` *does* return
`settlement_utr`, so the API path and the XLSX path need different join
strategies. Both mappers ship; neither is assumed.

---

### #5 — 18% GST on a one-paisa fee is zero

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_eighteen_percent_gst_on_a_one_paisa_fee_rounds_to_zero`

**Symptom.** A fee model applying the published 18% GST rate produced totals a
paise off from the sample data.

**Cause.** Every payment in Razorpay's sample carries `fee = 1p, tax = 0p`.
Eighteen percent of one paisa is 0.18p, which rounds to zero. Razorpay rounds
tax **per transaction**, not per settlement, so a model that applies the rate to
an aggregate diverges.

**Why it matters more than a paise.** A cover either closes exactly or it does
not. A one-paisa modelling error does not produce a slightly-wrong answer; it
produces an unexplained exception on an otherwise correct match.

**Fix.** The fee model's residual against Razorpay's actual returned `fee`/`tax`
is reported as a number rather than absorbed, and any remainder becomes a named
exception class.

---

### #6 — I asserted a float hazard that does not exist

**Date** 21 Aug · **Fixed in** *(pending)* · **Pinned by** `test_the_float_hazard_is_conversion_not_accumulation`

**Symptom.** My own test failed: I wrote `assert 0.99*5 - 1.00 != 3.95` to
demonstrate why money must be integer paise. It *is* exactly 3.95. So is the
repeated-addition form.

**Cause.** I had the right conclusion and the wrong reason. I measured it
properly: across 2,000 randomised settlements of 340 rows, float summation
agreed with `Decimal` to the paise **every time**. A double carries ~15
significant digits and a settlement total is ~8, so accumulation error stays far
below a paise. **The accumulation hazard is not real at this scale, and MILAAN
does not claim it is.**

The hazard that *is* real is the conversion at the boundary. `int(r * 100)`
truncates, and binary floating point puts **4,586 of the first 99,999** paise
values just below their integer: ₹0.29 → 28p, ₹8.20 → 819p. A 4.6% corruption
rate on the most natural one-liner anyone would write, every failure short by
exactly one paise — precisely the error that turns a valid cover into an
unexplained exception.

**Fix.** The test now asserts what is true and documents what is not. Integer
paise are justified by the boundary conversion, not by the arithmetic, and
`from_report_rupees` routes through `Decimal(str(x))` for that reason.

**Why this entry stays.** The whole project claims to prefer an honest exception
over a confident guess. A test that asserts a hazard I had not measured is that
failure in miniature, in my own code, on day one.

---

### #7 — my test was wrong and the solver was right

**Date** 21 Aug · **Pinned by** `test_finds_a_simple_unique_cover`

**Symptom.** First run of the solver suite failed immediately. I had written
`solve([99, 99, 250, 700], 349)` and asserted `UNIQUE`. The solver returned
`AMBIGUOUS` with witnesses `(0, 2)` and `(1, 2)`.

**Cause.** The solver was correct and I was not. Two 99p items are
interchangeable, so 99+250 and 99′+250 are two genuinely distinct covers of 349p.
I had reached for a "simple" fixture without checking whether my own example was
decidable.

**Why it is worth a numbered entry.** This is the project's central claim
demonstrating itself against its author. Ambiguity is not an edge case bolted on
for completeness — it is the *default* in Indian subscription and D2C merchants,
where many transactions share one price. Razorpay's own published sample is five
identical 99p payments, and every proper subset of those is ambiguous by
construction. A matcher tuned to always return an answer would have silently
returned `(0, 2)` here, produced a clean-looking report, and mis-stated which
payment settled — the exact failure no downstream audit catches.

Two of the first seven incidents in this log are my tests being wrong rather
than my code. That is what it looks like to write the oracle before the
implementation and then actually believe it.

**Fix.** The test uses distinct amounts and asserts `second_solution == ()`. The
ambiguous case moved to its own test, where it is the point rather than an
accident.

---

### #8 — `GET /orders` is eventually consistent, and a minting harness will believe it

**Date** 23 Aug · **Found by** `scripts/check_keys.py` write probe

**Symptom.** Created `order_TTGXsvW1pVeluE`, got a `200` with the order body
back, then immediately listed `GET /v1/orders?count=3` — **0 items**. The order
appeared to have vanished the instant after it was created.

**Cause.** Not vanished, not indexed. Fetching the same order by id returned it
immediately and correctly; only the *list* endpoint lagged, by roughly a second.
Razorpay's collection endpoints are eventually consistent with respect to writes,
while point reads are not.

**Why this is dangerous specifically for MILAAN.** The minting harness creates a
few hundred transactions and then reads the ledger back to build the candidate
pool. A read-after-write against a list endpoint will silently return a *short*
pool. The solver would then be handed a candidate set missing the very
transactions that compose the target credit, and would report `NO_COVER` —
a fabricated exception, attributed to the solver, caused by the harness. That is
the worst class of bug this project can have: it degrades the headline metric
while looking like a genuine finding.

**Fix (planned).** The minting harness records every entity id it creates at
creation time and reconciles that registry against the list endpoint, polling
until the two agree, with a timeout that raises rather than proceeding on a
short pool. Point reads by id are the source of truth; list endpoints are
treated as an index that may lag. No batch is allowed into an eval run until its
registry reconciles exactly.

**Wider note.** This is why `check_keys.py` exists as a probe rather than an
assumption. Nothing in Razorpay's documentation states the consistency model of
the collection endpoints; it took a write and an immediate read to find it, on
the first day the keys existed.

---

### #9 — the industry-standard test card is not a Razorpay test card

**Date** 23 Aug · **Fixed in** `data/test-cards.md`

**Symptom.** First attempt to capture a test payment failed with
*"International cards are not supported. Please contact our support team for
help."* Nothing was misconfigured on the account.

**Cause.** I used `4111 1111 1111 1111` — the generic Visa test number that
works on most gateways — from memory, without checking. It is not in Razorpay's
documented domestic set, so their BIN lookup classifies it as international, and
new accounts have international payments disabled by default. Razorpay's actual
domestic test cards are `4100 2800 0000 1007` (Visa), `5500 6700 0000 1002`
(Mastercard) and `6527 6589 0000 1005` (RuPay), per
[razorpay/markdown-docs](https://github.com/razorpay/markdown-docs/blob/master/payments/payments/test-card-details.md).

**Why the error message made it worse.** "International cards are not supported"
is a plausible, actionable, *wrong* diagnosis. It points at an account setting
rather than at the card number, and the obvious next step — enabling
international payments — would not have fixed it. Ten minutes could easily have
gone into the wrong drawer.

**The useful thing this turned up.** Razorpay publishes **twenty error-scenario
cards** — ten Visa `4100 2800 000X 000Y` and ten Mastercard
`5305 6200 000X 000Y` — each producing a specific documented failure, plus the
rule that an OTP under four digits fails the payment deliberately.

That matters for MILAAN beyond unblocking the mint. Failed payments never
settle, so they must *not* appear in a candidate pool — and a candidate pool
polluted with failed payments is a realistic exception class rather than an
invented one. I can now generate that class from **Razorpay's own documented
failure modes** instead of authoring it myself, which is one more label I do not
have to be trusted about.

---

### #10 — headless minting is RED: checkout runs hCaptcha, and I will not beat it

**Date** 23 Aug · **Verdict** RED, fallback taken · **Probe** `/tmp/mint4.py`

**Symptom.** Razorpay's hosted checkout drives fine headlessly right up to
submission: the page renders, contact details fill, the Cards method opens, and
the card fields populate correctly. Clicking **Continue** then does nothing
visible. Enumerating every frame on the page found the reason:

```
[newassets.hcaptcha.com/captcha/v1/…]  "Please try again. ⚠️ | Verify | EN"
```

**Cause.** Checkout loads bot detection — invisible hCaptcha via Stripe's
`human-security` bundle, alongside a `sardine.ai` device collector. Headless
Chromium trips it. An earlier attempt using `fill()` failed for a *different*
and more mundane reason (React never sees a synthetic value assignment), so
switching to `press_sequentially` was necessary to get far enough to discover
the real blocker underneath.

**Decision: stop.** Defeating a payment provider's fraud controls to generate
demo data is out of bounds on its own terms, and it is also self-defeating here
— a submission whose data pipeline depends on evading Razorpay's bot detection
is not one you want to explain to Razorpay's panel. The 300-payment automated
pool is cut. This was pre-planned as cut-list item 5, decided on day one rather
than discovered on day eleven.

**What it actually costs, which is less than it looks.** The sealed,
hash-committed generator was already PRIMARY ground truth (`DATA.md`), chosen
before this probe rather than retreated to after it. Live minting was only ever
going to strengthen two specific things:

1. **The fee model** — and this survives intact, because it needs a *handful* of
   real captured payments, not hundreds. One already exists
   (`pay_TTGbjjcwSCSQaC`: 49900p → fee 1098p, exactly 2.200%) and a few more
   done by hand pin the rounding rule.
2. **A live Razorpay-authored settlement grouping** — which was never available
   anyway: `GET /v1/settlements` returns empty on an unactivated test account,
   settlement is T+2 working days, and no documentation says test mode produces
   settlements at all.

So the load-bearing claim is unchanged: the closure identity is validated
against **Razorpay's own published sample reports**, which are externally
authored and need no API at all.

**The honest sentence this forces, said on camera.** "The settlement groupings
in my evaluation corpus were produced by a seeded script that was sealed and
hash-committed before the solver existed — not by Razorpay's engine. The
identity that script implements is the one I verified against Razorpay's own
published sample data, and the fee model is calibrated against real captured
test payments." That is weaker than "Razorpay computed my answer key," and it is
what is true.

---

### #11 — the rate limiter does not say 429, and a naive batch loses 13 of 18

**Date** 23 Aug · **Fixed in** `scripts/mint_links.py` · **Pinned by** the registry's resume path

**Symptom.** Minting 18 payment links in a tight loop: the first five succeeded,
the remaining thirteen all failed at once.

**Cause.** `POST /v1/payment_links` is rate limited, but it does not answer the
way rate limiting is normally signalled. There is **no HTTP 429** and **no
`Retry-After` header** — it returns a plain `400 BAD_REQUEST_ERROR` whose
`description` is the string `"Too many requests"`. Code that branches on status
code sees an ordinary bad request, concludes the payload is malformed, and gives
up on an entity that would have succeeded a second later.

**Why it mattered here specifically.** Each of those eighteen amounts was chosen
to probe a particular fee-rounding boundary, and captured payments are now
hand-made and therefore expensive (INCIDENTS.md #10). Silently dropping thirteen
of them would not have produced an obviously broken batch — it would have
produced a *smaller* one, still plausible, missing exactly the calibration points
that distinguish half-up from banker's rounding.

**Fix.** Three parts, and the third is the one that matters.

1. Recognise the limiter by message rather than status code, since the status
   code carries no information.
2. Exponential backoff, 2s doubling to a 30s ceiling. Two amounts needed the
   full ladder before succeeding.
3. **The registry is a checkpoint.** Every minted link is written to
   `results/mint_batch.json` immediately, and a re-run skips any amount already
   present. A partial batch is resumable rather than restarted, which is what
   made recovering the missing thirteen free instead of a re-mint of all
   eighteen.

**The general lesson, and it applies well beyond this script.** Two of the
Razorpay behaviours found on day one — eventually-consistent list endpoints
(#8) and a rate limiter disguised as a 400 (#11) — fail in the same direction:
**they produce a short result set rather than an error.** A harness that trusts
either one builds a candidate pool with holes in it, and the solver then reports
exceptions that are artefacts of the harness while looking like genuine
findings. Both are now handled by reconciling against ids recorded at creation
time and never trusting a collection response to be complete.

---

### #12 — Razorpay's fee is not a percentage, and I can prove it

**Date** 23 Aug · **Landed in** `src/milaan/fees.py` · **Pinned by** `tests/test_fee_model.py`

**What I was testing.** A settlement credit is `Σ(payment − fee) − Σ(refunds)`,
so a cover only closes to the paise if every member's fee is exactly right.
Razorpay publishes a *rate* but no *rounding rule*, and the rounding rule is
what a paise-exact identity turns on. So I minted eighteen payment links at
amounts chosen to probe the boundary — `fee = amount × 11/500`, which lands on
exactly half a paise when `amount ≡ 250 (mod 500)` — and had them paid by hand.

**What came back.**

1. Base rate confirmed: **2.200% of gross**, exact at the four largest amounts.
2. Rounding is **not banker's**. Both half-paise probes rounded *up*:
   ₹7.50 → 17p (banker's predicts 16p), ₹507.50 → 1117p (banker's predicts 1116p).
   That was the question the batch was built to answer, and it is answered.
3. **Ceiling fits 16/18. Half-up fits 13/18.** Ceiling is the model.

**The two that nothing explains.**

```
    251p   exact   5.522   ceil   6   Razorpay charged   7
  10251p   exact 225.522   ceil 226   Razorpay charged 227
```

Both `≡ 251 (mod 500)`, both odd, both one paise **above** ceiling. Their mirror
images just below the boundary — 249p and 10249p, also odd — match ceiling
exactly. All four odd amounts in the batch exceeded half-up; only one of
fourteen even amounts did.

**Why this is not a rounding question.** I tried to rescue it by fitting a
different rate, and it cannot be done. `ceil(r × 10251) = 227` requires
`r > 226/10251 ≈ 0.0220466`. `ceil(r × 500000) = 11000` requires
`r ≤ 11000/500000 = 0.022`. **The intervals are disjoint.** No single percentage,
under any rounding rule, reproduces both observations. There is a discrete
component to Razorpay's fee computation that nineteen samples do not resolve.
That proof ships as a test so a future refactor cannot quietly fit its way out
of it.

**What the system does about it.** `fee_for()` returns a fee *and* a confidence.
An observed fee always beats the model — the model is a fallback for entities
whose fee was never returned, never an override for one that was. An amount in a
residue class known to defeat the model comes back `confident=False` and is
routed to a `FEE_MODEL_RESIDUAL` exception rather than closing a cover.

**Why this is the most useful thing found so far.** Incident #5 said, before any
of this data existed, that the fee model's residual must be *reported as a
number and any remainder made a named exception class, not absorbed*. I wrote
that as a discipline. It turns out to be load-bearing: a model that absorbed
these two would produce a cover that is off by exactly one paise, and a
one-paisa error does not look wrong — it turns a correct match into an
unexplained exception, or worse, lets a wrong subset close. Two payments out of
nineteen, roughly 11%, would have been silently mis-modelled.

**Also found:** `tax` is 0 on sixteen of nineteen payments and 18% on the two
largest only. The threshold sits between ₹999 and ₹2,499 and is undocumented, so
the GST line is only partially exercised in test mode. `LIMITS.md` says so
rather than the results table implying otherwise.

**Open question, honestly open.** Whether the anomaly is parity, the residue
class, or something else entirely needs a targeted follow-up batch — odd/even
pairs bracketing the boundary at several magnitudes. Until then it is reported
as unexplained, because it is.

---

### #13 — test mode caps payment links at 30, and that retroactively justifies the whole data plan

**Date** 23 Aug · **Found by** `scripts/mint_followup.py` on its eighth link

**Symptom.** The follow-up probe batch minted seven links and then stopped:

```
RATE_LIMIT_EXCEEDED · "test mode limit of 30 reached for payment_link"
```

**Cause.** Razorpay test mode enforces a **hard ceiling of 30 payment links per
account**. Not a throttle — a cap. Twenty-nine had been created across the day's
probes and two calibration batches, and the thirtieth was refused.

**Note the contrast with #11.** That earlier limiter returned a plain
`400 BAD_REQUEST_ERROR` whose description was `"Too many requests"` — no code, no
`Retry-After`, indistinguishable from a malformed payload. This one returns a
proper `RATE_LIMIT_EXCEEDED` with a message that names the resource and the
number. Razorpay therefore has **two different rate-limiting behaviours on the
same endpoint**, and only one of them is machine-readable. A harness that handled
either one alone would misread the other: backing off forever against a hard cap,
or giving up immediately against a soft throttle.

**Why this is the most strategically useful finding of the day.** MILAAN's ground
truth was already the sealed, seeded, hash-committed generator, with live
Razorpay data positioned as a *second* results column if it ever materialised.
That call was made on 21 August, before any of this was known.

It now turns out that **three independent hard limits** would each, on their own,
have made a large live-minted pool impossible:

1. `GET /v1/settlements` is empty on an unactivated account, so Razorpay-authored
   groupings do not exist to be harvested (probe E4).
2. Checkout runs hCaptcha, so payments cannot be captured programmatically (#10).
3. Payment links are capped at 30 per test account — this entry.

A plan that had made "mint 300 real payments and let Razorpay's engine author the
answer key" the spine would have discovered limit 3 somewhere around day six,
with the solver already built against an assumption that could not hold. The
sealed generator was not a fallback taken under duress; it was the primary
choice, and each of these findings is a separate reason it was the right one.

**What it costs.** The 30-link budget is now spent, so the fee-model corpus is
frozen at 19 measured payments plus the 7 probes in flight — 26 total. That is
enough to answer the rounding question and to map the anomaly's fractional
neighbourhood, and it is not enough to characterise the discrete component fully.
`LIMITS.md` states the sample size and stops there.

---

### #12b — the anomaly, localised

**Date** 23 Aug · **Resolves the open question in #12** · **Pinned by** `tests/test_fee_model.py`

#12 left the question open and said so. A second batch of seven links answered
it: sweep the fractional part of the exact fee at constant magnitude, with
controls, and find where the +1 lives.

Writing `k = (amount × 11) mod 500`, so the exact fee is `q + k/500`, across all
25 measured payments:

```
 frac   .478  .500  .502 │ .510  .522  .540 │ .560  .600  .700  .900
 delta   +0    +0    +0  │  +1    +1    +1  │  +0    +0    +0    +0
 n       2     5     1   │  1     2     1   │  1     2     1     1
                         └──── the band ────┘
```

The band is `(0.502, 0.560)`, bracketed to within 0.008 on the left and 0.020 on
the right. Every amount inside came back at ceiling + 1; every amount outside
matched ceiling exactly.

**The controls did their job.** Three probes at .600, .700 and .900 were minted
expecting +0 precisely so that a backend change affecting everything would be
distinguishable from a real effect. They came back +0. The effect is real.

**And the stronger claim now holds over the full dataset.** Intersecting the
feasible rate interval implied by each of the 25 observations gives the **empty
set** — under ceiling and under half-up alike — and allowing an additive constant
does not rescue it either. Razorpay's test-mode card fee is **not expressible as
any single percentage of gross**. Both proofs ship as tests rather than as prose,
so a later refactor cannot fit its way out of them.

**What ships.** Two models, both reported. `base_fee_ceiling` is conservative and
fits 21/25. `base_fee_banded` adds the measured +1 inside the band and fits
25/25 — *by construction*, which is exactly why the evaluation publishes the
match rate under both. A curve fitted to four points is a hypothesis, not a
result, and presenting the 25/25 alone would be the kind of flattering number
this project exists to avoid.

Amounts inside the band still come back `confident=False` and route to
`FEE_MODEL_RESIDUAL`.

**What is still unknown, and stays unknown.** *Why* the band exists. The 30-link
test-mode cap (#13) is now spent, so the corpus is frozen at 25. Narrowing
`(0.502, 0.560)` further, or explaining the discrete component behind it, needs
an account this project does not have. `LIMITS.md` states the sample size and
stops there.

---

### #14 — the solver called a provably ambiguous problem UNIQUE

**Date** 23 Aug · **Found by** an external audit of this repo · **Pinned by** `test_a_zero_valued_candidate_makes_every_cover_ambiguous`

**Symptom.** `solve([100, 0], 100)` returned `UNIQUE` with cover `(0,)`. Brute
force finds **two** covers: `{0}` and `{0, 1}`. Same for `solve([0], 0)` (two
covers) and `solve([100, 0, 0], 100)` (four).

**Cause.** A zero-valued entry can join or leave any cover without changing its
sum, so `k` zeros give every solution `2^k` equivalent variants. The bitset DP
cannot see this: shifting by zero is the identity, so `reachable | (reachable << 0)`
is a no-op, a zero-weight item is never selected during reconstruction, and
`_find_second` only ever pins out members of the first solution — so an item
that is absent from that solution is never tried. The solver returned the single
cover that omits every zero and called it unique.

**Why this is the worst bug in the project so far.** It falsifies the headline
guarantee. MILAAN's entire claim is that `UNIQUE` means *no second cover exists*
— that is the difference between a reconciliation engine and a suggestion
engine, and it is the sentence the pitch is built on. For a whole class of
inputs it was simply false.

And it was reachable from real data, not a contrived fixture: `LedgerEntry.net`
returns exactly `Paisa(0)` for any row where `debit == credit`, which a fee-only
adjustment or a fully-refunded payment produces.

**Why 100+ passing property tests missed it.** Every random generator I wrote
starts at `rng.randint(1, ...)`. **A zero was never sampled — not once, in any
test, in the entire suite.** The brute-force oracle was correct and would have
caught this immediately; it was never handed an input that could expose it. The
oracle was right and the corpus was blind, which is a more uncomfortable failure
than a wrong oracle: every green run was evidence about a region of the input
space I had silently excluded.

**Fix.** Zero-valued candidates are partitioned out before the DP. If any exist
and a cover exists, the verdict is `AMBIGUOUS` with both witnesses — the cover
with and without a zero. `test_property_tests_now_generate_zeros` asserts the
generator actually produces zeros, so the corpus itself is now under test rather
than only the solver.

**What I take from it.** A property test is only as good as its generator, and
"all tests pass" is a statement about the corpus as much as the code. The
generator is now an artifact I review, not scaffolding I write once.

---

### #15 — `fee` meant two different things and the difference was exactly the GST

**Date** 23 Aug · **Found by** an external audit of this repo · **Pinned by** `test_observed_and_modelled_fees_agree_on_what_net_means`

**Symptom.** `FeeEstimate.fee_paise` was **tax-inclusive** when it came from
Razorpay's API and **tax-exclusive** when it came from the model. One ₹2,499
payment produced three different answers for its net:

```
observed  fee_paise=6488 tax_paise=990  ->  amount-fee-tax = 242422   (wrong, double-counts GST)
modelled  fee_paise=5498 tax_paise=0    ->  amount-fee-tax = 244402   (wrong, no GST at all)
truth     Razorpay charged 6488 all-in  ->  net             243412
```

**Cause.** Razorpay reports `fee` **inclusive** of `tax`, while the 2.200% rate
applies to the base. I knew this — `tests/test_fee_model.py` defines
`_base(fee, tax) = fee - tax` with that exact comment, and
`scripts/mint_followup.py` does the same subtraction. The knowledge simply never
made it into `fees.py`, so the two paths disagreed about what a single field
name meant.

**Why 990 paise matters here more than it sounds.** A cover either closes
exactly or it does not. An off-by-990p member does not produce a slightly wrong
total — it turns a correct match into an unexplained exception, or lets a wrong
subset close. This is precisely the silent financial misstatement the README's
second paragraph is about, sitting in the module that computes money.

**Fix.** The ambiguity is now unrepresentable. There is no field called `fee`:
`base_fee_paise` is tax-exclusive on every path, `tax_paise` is the GST on it,
`gross_fee_paise` is the all-in figure Razorpay reports, and
`net_settled_paise` is the only number a cover is ever built from. A test asserts
all four agree across every one of the 25 measured payments.

**The pattern across #14 and #15.** Both were found by someone else reading the
code, not by me writing more of it — and both were in modules I had already
covered with tests I trusted. #14 was a blind spot in my generator; #15 was
knowledge that lived in a test helper and a script but never reached the module
that needed it. Neither was a hard bug. Both were invisible from the inside.

---

### #16 — the anomaly was not exotic. The fee is two rates, not one.

**Date** 23 Aug · **Found by** an external audit of this repo · **Pinned by** `test_the_two_component_model_reproduces_every_observation`

**What I had published.** Incidents #12 and #12b reported four payments whose
fee sat one paise above `ceil(amount × 2.2%)`, localised the effect to a
fractional-part band of `(0.502, 0.560)`, and proved rigorously that **no single
percentage of gross, under any rounding rule, reproduces all 25 observations** —
the feasible rate interval intersects to the empty set. I concluded there was
"a discrete component that 25 samples localise but do not explain," shipped two
models side by side, and flagged amounts in the band as low-confidence.

**What it actually is.**

```
fee = ceil(amount / 50) + ceil(amount / 500)
```

Two percent and nought-point-two percent — Razorpay's own published MDR and
platform-fee components — **each rounded up to the paise separately**, the way a
billing system rounds a line item rather than a total. It reproduces **25 of 25**
measured payments, including all four I had published as unexplained. Single-rate
ceiling fits 21/25; half-up fits 18/25.

**Why the band is exactly where it is.** `ceil(a·2%) + ceil(a·0.2%)` exceeds
`ceil(a·2.2%)` by one paise precisely when both components have a fractional
part but their sum does not carry into the next paise. That condition, worked
out, *is* the `(0.502, 0.560)` interval I measured empirically and could not
account for. The band was never mysterious — it was the carry boundary of a
tariff I had assumed was a single rate. A test now asserts the band and the
model-disagreement set are the same set, so the old measurement and the new
explanation are pinned to each other.

**The proof was right; the conclusion was too weak.** "No single rate fits" was
correct and remains correct — it is exactly what a two-component tariff looks
like from the outside. I proved the negative rigorously and then stopped, because
I had framed the question as *which rate is it?* The question I never asked was
*is it one rate?* The disjointness result was pointing straight at the answer and
I read it as a dead end.

**Why I am not deleting incidents #12 and #12b.** The measurement in them is
sound, the controls did their job, and the impossibility proof still ships as a
test. What was wrong was the inference. Rewriting them to look like I found this
would be the exact dishonesty the log exists to prevent, and the sequence —
measure carefully, prove a negative, draw too small a conclusion, get corrected —
is more useful to a reader than a clean single entry would be.

**What changes in the code.** The two-component model is primary.
`base_fee_ceiling` stays as the ablation so the 21/25 → 25/25 improvement is a
reported number rather than a claim. The `FEE_MODEL_RESIDUAL` flagging is
removed: it was the right behaviour under uncertainty, and continuing it now
that the uncertainty is gone would be theatre.

**Fourth time now.** #6 (a float hazard I asserted without measuring), #7 (my
test wrong, solver right), #14 and #15 (found by audit), and now this. Every one
of them is a case where the thing that broke was my own conclusion rather than
my code — and the two most valuable findings in this project both came from
someone else reading it. That is worth more than a clean log.

---

### #17 — exact-cover search alone is not a reconciliation strategy

**Date** 23 Aug · **Fixed by** `src/milaan/solver/interval.py` · **Pinned by** `test_blind_search_alone_would_report_nothing_but_ambiguity`

**Symptom.** First end-to-end run of the batch loop. Match rate **0.0%**.
`AMBIGUOUS_COVER` on **18 of 18** credits. Not one line resolved.

**Cause, and it was not a bug.** The solver was right every single time. The
candidate pool for a credit was every transaction captured within ±6 days —
around 200 of them. That gives 2²⁰⁰ subsets against roughly 10⁷ achievable paise
sums in range, so by pigeonhole nearly every target has many exact covers.
**Ambiguity was not an edge case at that pool size; it was the guaranteed
outcome.** An engine that reported a single cover anyway would have been
guessing, and would have looked far better on the scorecard while being wrong.

**Why this is the most useful thing the first run could have told me.** I had
built the blind subset-sum solver first because it was the interesting
algorithm — signed values, uniqueness proof, bitset DP, a budget. It is the
thing a staff engineer reads and respects. It is also, on its own, useless here.
The cheap layers I had listed in the README as "optimisations" and not yet
written are not optimisations at all: **they are what makes the problem
decidable.** Search is the fallback for the residue after structure has done the
work, and I had built the fallback first and called it the product.

**Fix.** The interval layer. Razorpay batches by capture time, so a cover is
almost always a contiguous run in capture order. Contiguity collapses the search
space from 2ⁿ subsets to n(n+1)/2 intervals — about 20,000 for n=200 rather than
10⁶⁰ — which is few enough that a collision is informative rather than
inevitable. Linear via prefix sums.

**Result on the same batch, same seed:**

```
                        blind only      interval → blind
match rate (decidable)      0.0%              75.0%
correctly refused            0/6                6/6
false matches                  0                  0
resolved by interval           —              13/18
throughput             6.6 cr/s           25.5 cr/s
```

**What did not change is the point.** False matches were zero before and zero
after. The blind solver at 0% was not broken — it was refusing, correctly, on
problems that genuinely had many answers. Adding structure did not make the
engine more willing to guess; it made the questions decidable. That distinction
is the whole design, and it took a 0% run to see it clearly.

**The measurement stays as a test.** `test_blind_search_alone_would_report_nothing_but_ambiguity`
re-runs the blind path on the same pools and asserts 6 of 6 ambiguous, so the
claim behind this entry remains checkable rather than becoming a story I tell.

---

### #18 — I measured my own LLM layer's ceiling and it is zero

**Date** 24 Aug · **Measured by** `milaan hints` · **Pinned by** `tests/test_hints_ab.py`

**What I set out to measure.** The containment property proves the hint layer
cannot cause a wrong join. That is a *safety* claim and says nothing about
whether the layer is *useful*. Those are two claims and only one had a number,
so I built the A/B: the same sealed batch under three configurations — no hints,
a **perfect** extractor, and a **deliberately hostile** one.

The oracle matters more than testing one model would. It reads the capture date
out of the narration with 100% accuracy and abstains otherwise, so **no real
model can beat it**. Its score is the ceiling on what any language model could
contribute — measurable with no API key, and a far more useful number than one
model's score, because if the ceiling is low the layer is not worth its cost
regardless of which model you pick.

**The result, at three batch sizes:**

```
                        18 credits    30 credits    60 credits
baseline (no hints)       9 matched    17 matched    32 matched
oracle (perfect)          9 matched    17 matched    32 matched
CEILING ON ANY MODEL           +0            +0            +0

malign false-matches            0             0             0
malign accepted ⊆ baseline   True          True          True
hallucinated claims rejected    6            10            18
credits lost to hostility       0             0             0
```

**A perfect extractor adds nothing. A fully compromised one costs nothing.**

**Why, and this is the interesting part: the safety property is the cause.**
Uniqueness is adjudicated on the *full* candidate pool, never the hint-narrowed
one — that is step 3 of containment, and it exists precisely so a hint cannot
manufacture uniqueness by filtering a competing cover away. The direct
consequence is that **a hint can never break a genuine tie.** Its only remaining
lever is rescuing a line the solver declined on budget, and once the interval
layer (#17) is in place there are no such lines. The mechanism that makes the
layer trustworthy is exactly the mechanism that makes it useless here. I did not
anticipate that when I designed it.

**What I am not doing about it.** Not deleting the layer, not quietly dropping
the measurement, and not weakening containment to manufacture a win. Weakening
it is the only way to get a positive number, and the number would be worth less
than nothing: it would be bought by allowing exactly the wrong joins the project
exists to prevent.

**What the layer is still worth.** The containment mechanism — grounding, filter-only
narrowing, full-pool adjudication — is the reusable artifact, and it holds under
an adversary at every scale tested. The layer earns its cost only where
`BUDGET_EXCEEDED` actually occurs: pools too large to decide and without the
time-ordering that makes the interval layer work. Real bank data may well look
like that. This batch does not, and the honest statement is that on this
workload the layer contributes nothing.

**Why this is the entry I would show first.** The rubric asks for *the right
tool in the right place, and where you chose not to use one*. The strongest form
of that is not an argument about where an LLM does not belong — it is having
built the thing, measured its ceiling honestly, found it to be zero, and
published the zero. The negative result is the finding.

---

### #19 — sorting by id, not by time, silently broke the interval layer

**Date** 24 Aug · **Fixed by** a capture timestamp on every ledger row · **Pinned by** `test_headline_figures_are_what_the_submission_reports`

**Symptom.** Three of four `WITH_REFUND` credits were refused. Not wrong —
refused — but they should have been findable.

**Diagnosis before building.** The obvious next move was a perturbed-interval
layer (a contiguous run minus a bounded set of exclusions). I checked first
whether the true member set was contiguous at all, and it was not:

```
cr_0007  members=20  true-set contiguous=True   intervals found=1  true cover among them=True
cr_0008  members=18  true-set contiguous=False  intervals found=0  true cover among them=False
cr_0009  members=23  true-set contiguous=False  intervals found=0  true cover among them=False
cr_0010  members=20  true-set contiguous=False  intervals found=0  true cover among them=False
```

Building perturbation would have been wrong: it *adds* candidate covers, so it
would have made ambiguity worse while leaving the real cause untouched.

**Cause.** I sorted the candidate pool by `(day_offset, entity_id)`. Two
settlements share each capture date, and ids are typed: `pay_G…` sorts before
`rfnd_G…`. So the first settlement's **refunds** sorted after the second
settlement's **payments**, interleaving two settlements and destroying
contiguity for any settlement containing a refund.

**Fix, and it is a domain fact rather than a trick.** Real ledger rows carry a
capture *timestamp*, not just a date, and settlement grouping follows it. Rows
now carry `captured_at` and the pool is ordered by it. A date alone cannot order
rows within a day, and two settlements can share a day.

**Result:** decidable match rate 75% → **80%**, `WITH_REFUND` 1/4 → **4/4**,
interval layer 13 → 16 of 18, throughput 25 → 79 credits/sec. False matches
stayed at zero throughout.

**The lesson is the diagnosis, not the fix.** The plan said "build the
perturbed-interval layer" and the plan was wrong. Ten minutes of asking *why*
the layer failed replaced a day of building the wrong thing — and would have
produced a worse number.

---

### #20 — I named a test class after an outcome the construction cannot guarantee

**Date** 24 Aug · **Pinned by** `test_every_planted_undecidable_credit_is_refused_not_guessed`

**Symptom.** After the #19 fix, a credit planted as `AMBIGUOUS_COVER` came back
`MATCHED`, and the scorecard read `CORRECTLY REFUSED 5/6`. My first reading was
that the engine had got lucky on an undecidable input.

**Cause.** It had not. `cr_0012` is seven identical ₹999 payments and the credit
is the sum of **all seven** — and "all of them" is a unique set. Equal amounts
only create ambiguity when the target is a *proper* subset. The generator was
planting a **condition** (many equal amounts) and I had named the class after an
**outcome** (ambiguous), so the label asserted something the construction could
not deliver, and a correct answer was scored as a failure.

**Fix.** The class is now `IDENTICAL_AMOUNTS`, described as "ambiguity is likely
but not guaranteed". Separately, the scorecard's undecidable denominator is
restricted to classes where undecidability is **structural** — `OUT_OF_WINDOW`
(a member is missing, so no cover is findable) and `ZERO_NET` (a zero gives
every cover 2^k variants). `IDENTICAL_AMOUNTS` and `ON_HOLD` are
decidable-in-principle and are now held to the same standard as any other
credit, which *lowers* the reported rate from 91.7% to 80.0%.

**Why I took the lower number.** The 91.7% was flattering and wrong: it counted
three genuinely-refused credits as "correctly refused" when nothing guaranteed
they were unrefusable. A denominator that excuses whatever the engine failed at
is not a measurement. This is the same discipline as #12 — the risk in a
self-authored corpus is not usually fabricated data, it is a label that quietly
grades the engine on a curve.

**Addendum, 24 Aug (after #19).** Re-measured once capture-time ordering landed.
The interval layer now resolves 16 of 18 credits, so only two reach the blind
layer — and neither carries an opaque narration. **The hint layer is no longer
merely unhelpful on this batch; it is never invoked.** The ceiling was +0 when it
was offered 1–4 lines, and it is +0 now because it is offered none. Both facts
are asserted separately in `tests/test_hints_ab.py`, because "the ceiling is
zero" and "the layer is unreachable" are different claims and a future change
could move either. The adversarial half is still measured on a larger batch,
where the layer is reachable, and containment still holds there.

---

### #21 — an audit found my documents overstating my own code, in four places

**Date** 24 Aug · **Found by** an adversarial verification pass · **Pinned by** `test_the_sealed_digest_is_pinned_so_tuning_cannot_pass_silently`

Four false claims, all in the documents rather than the code, all mine. The code
was fine every time. Listed worst first.

**1. The README claimed Razorpay authored my answer key. It does not.**

> *"Razorpay independently assigns entity ids, `fee`, `tax`, capture timestamps
> and the settlement grouping … MILAAN never decides which payment belongs to
> which settlement."*

For the 18-credit batch that produces **every headline number**, my generator
assigns the ids, the timestamps and the grouping. Razorpay authors the fee
*formula* and nothing else. `grep -c 'razorpay-samples' src/milaan/cli.py` returns
**0** — the run path opens no Razorpay file at all, and DATA.md records the probe
showing `GET /v1/settlements` is empty, so Razorpay-authored groupings
demonstrably do not exist in this repo.

This was the single worst sentence in the project. It was the answer to the
central attack — *you wrote your own answer key* — and it answered it with a
falsehood. What is true and sufficient: on Razorpay's **published sample
reports** the grouping really is theirs, and on the generated batch the defence
is self-certification — a cover sums to the paise or it does not. The README now
separates the two legs and says which data each applies to.

**2. LIMITS.md, the honesty document, had stale numbers.** It still read 75%
(9/12), "6 of 6", 269 ledger rows — the figures from before #19 and #20. The
shipping tool prints 80% (12/15), 3/3, 237 rows. A reviewer who opens the file
the README points to for "full caveats" would have found it contradicting the
tool's own output.

**3. I overstated the rigour of my own negative result.** README and SUBMISSION
said a *perfect extractor adds nothing* **because** uniqueness is adjudicated on
the full pool. The oracle was offered **zero lines** — so full-pool adjudication
was never exercised and cannot be what caused the zero. The measured cause is
reachability: after #19 only two credits reach the blind layer and neither has an
opaque narration. Containment remains a sound *prediction* backed by the malign
config and 33 unit tests, but it did not produce this particular +0, and the two
are now stated separately. Ironic placement: the overstatement was inside the
paragraph arguing for honest measurement.

**4. A "hash commitment" with no committed hash.** DATA.md said the generator was
*"seeded, sealed and hash-committed before any solver exists"*. Two problems.
`git log --diff-filter=A` shows the generator was committed **23 Aug** and the
solver **21 Aug** — two days earlier, so the chronology was backwards. And
grepping the repo for the digest the tool prints returned nothing: the hash was
computed at runtime and the test only checked it against itself. Self-consistency
proves determinism, not sealing. A seal a third party cannot check is not a seal.
The digest is now pinned as a literal in the test suite, so any change to the
generator breaks the build.

**What I take from this.** Every previous entry in this log is a case of the code
or my reasoning being wrong. This one is different and worse: **the code was
correct and the documents describing it were not.** All four claims made the
project sound stronger than it was, which is the direction that should worry a
reader most — and three of them appeared in the same commits where I was
congratulating myself for honest measurement.

I did not find any of them. An adversarial pass over the repo did, in one run,
and it is the second time an outside reading has caught something I could not see
from inside (the first being #16, the fee model). The pattern is consistent
enough to be worth naming: I am reliable at measuring things and unreliable at
auditing my own claims about the measurements.

---

### #22 — my central safety property was false as stated, and I had a test celebrating the counterexample

**Date** 24 Aug · **Found by** an adversarial verification pass · **Pinned by** `test_the_one_case_where_a_hint_expands_the_accepted_set`

**The claim, as it stood in three files and the pitch:**

> For ANY output the model produces, the set of covers MILAAN accepts is a
> SUBSET of the covers it would accept with no model at all.

**It is false**, and here is the counterexample the audit produced in six lines:

```
accepted WITHOUT hint: 0   []
accepted WITH hint   : 1   [('p0','p1','p2','p3')]
subset property holds: False
```

**Cause.** `resolve()` has a `BUDGET_EXCEEDED` branch: when the full pool is too
large to decide, a hint may narrow it to something decidable, and MILAAN then
accepts a cover it would otherwise have left unresolved. That is by design and it
is the layer's only value — but it is precisely a case where accepted-with is
**not** a subset of accepted-without.

**The part that stings.** I wrote a test for this exact behaviour —
`test_a_hint_can_rescue_a_line_the_solver_declined_to_decide` — and its docstring
called it *"the upside case … the entire value the model adds"*. I had the
counterexample to my own headline property, in the same test file, celebrating
it, and did not connect the two. Thirty-three containment tests passed around it
because none of them ran under a budget tight enough to trigger the branch.

**Fix — split one over-broad claim into two accurate ones.**

- **Soundness, unconditional:** every accepted cover sums to the target exactly.
  A hint can never cause a wrong join. *This is the claim the product rests on
  and it was never in doubt.*
- **Subset, on decidable problems:** accepted-with ⊆ accepted-without, except
  under `BUDGET_EXCEEDED`. The transition there is always **undecided → decided**,
  never *one answer → a different answer*.

Both are now asserted separately, the exception has its own named test, and a new
test checks soundness specifically under the budget-rescue path where subset
fails.

**Why the weaker statement is still worth having.** "A hint can rescue a line the
solver gave up on, and can do nothing else" is a precise description of a bounded
blast radius. The over-broad version was not stronger — it was wrong, and a
reviewer who found the counterexample would have had cause to doubt every other
property claim in the repo.

**Same audit, same day, same shape as #21.** The code did what it should. The
sentence describing it claimed more than the code delivered. That is now six
entries in this log where my own words were the defect, against fifteen where the
code was — and the words fail in the flattering direction every time.

---

### #23 — it was not an agent, and relabelling it would have been the wrong fix

**Date** 24 Aug · **Fixed by** `src/milaan/agent.py` · **Pinned by** `tests/test_agent.py`

**The finding.** Track 04 asks for an *agent*. An auditor read the control flow
and said plainly that this was not one: `filter pool → try interval → else try
blind → emit verdict`. A straight line. No loop, no state, no policy, no
decision — the layered escalation was an `if/else`, not a strategy.

That was correct, and the tempting response was to write a paragraph arguing that
"agent" is a loose word and that Track 04's own examples ("tax-line matcher",
"multi-source reconciliation") are matching engines. That argument is even
*true*. It is still the wrong response, because it defends the label instead of
asking whether the design was right.

**It was not.** The fixed ±6-day candidate window was the weakest thing in the
system and I had never questioned it. A bank credit is composed of transactions
captured in some interval, and the engine does not know that interval:

```
window too WIDE   -> neighbouring settlements enter the pool -> ties -> AMBIGUOUS
window too NARROW -> a genuine member is excluded            -> nothing sums -> NO_COVER
```

Those two failure modes point in **opposite directions**. There is no single
window that is right for every credit, so a fixed one is indefensible — and the
correct design is precisely the thing an agent is: observe how the last attempt
failed, decide what to try next, try again.

    NO_COVER  -> the pool is too small. Widen.
    AMBIGUOUS -> the pool is too big.  Narrow, or refuse.
    UNIQUE    -> adjudicate, then stop.

**Deterministic on purpose.** No model is consulted in the policy. The signal —
*which way* the last attempt failed — is unambiguous, and a language model could
only add noise to a decision arithmetic already answers. That is the
"where you chose not to use one" boundary drawn at the level of the agent's own
reasoning, not merely its tools.

**Bounded and auditable.** The window ladder is finite and ascending, each rung
is tried at most once, there is a per-credit action budget, and every episode
returns its full `(observation, action, outcome)` sequence. `milaan run --trace`
prints it. An agent whose decisions cannot be replayed has no business near
money.

**What it changed.** Match rate is unchanged at 80% on decidable credits — the
agent did not buy a better number. What it bought is *correct exception classes*:
`ON_HOLD` and `ZERO_NET` now return `NO_COVER`, which is the true answer for a
credit whose member was withheld, where the fixed window reported the vaguer
`AMBIGUOUS_COVER`. Credits resolve across four different windows (±2 to ±6) at
6.7 actions each, so the loop is doing real work rather than decorating a
straight line.

**And it made the LLM layer reachable again.** Under the old flow hints were
consulted only in the blind branch, which almost never fired, so the +0 ceiling in
#18 was partly a measurement of unreachability. The agent consults the hint layer
on every credit with an opaque narration: the oracle is now offered **4 lines**
and still adds **+0**. Same conclusion, properly supported.

---

### #24 — the agent reported a wrong join within an hour of existing

**Date** 24 Aug · **Fixed by** find-narrow-adjudicate-wide · **Pinned by** `test_uniqueness_is_adjudicated_at_the_widest_window_not_the_narrowest`

**Symptom.** First run of the agent: decidable match rate up from 80% to **86.7%**,
and **one FALSE MATCH**. The number that must be zero was not zero.

```
FALSE MATCH cr_0011 planted=IDENTICAL_AMOUNTS window=±2d cover=6 truth=6
  actions: TRY_INTERVAL → WIDEN → TRY_INTERVAL → ACCEPT
```

**Cause, and it is the same mistake in a new costume.** The agent accepted the
first window that produced a *unique* cover. At ±2d the pool contained six
identical amounts belonging to a neighbouring settlement, and they formed the only
contiguous run summing to the credit — unique, exact, and wrong. Widening would
have revealed the true run and shown the credit was ambiguous.

Narrowing a pool until a competing cover disappears is **manufacturing
uniqueness**. It is the precise move `hints/grounding.py` forbids a hint from
making, with an entire module and 34 tests devoted to preventing it. I wrote that
guarantee, then built an agent whose policy did it structurally.

**Fix.** Find narrow, adjudicate wide. A cover discovered at a tight window is a
*candidate*; uniqueness is always decided at the widest window on the ladder, and
if a competitor appears there the credit is refused with both witnesses. Match
rate fell back from 86.7% to 80.0% and false matches returned to zero.

**The 6.7 points were not real.** They were bought by looking at less evidence,
which is the one way to raise a match rate that a false-match count is designed
to catch. It caught it — on the first run, before the change was committed.

**Third time this exact shape has appeared:** hints could have manufactured
uniqueness (prevented by design), the interval layer could have (prevented by
full-pool adjudication), and the agent's window policy actually did. It is the
central hazard of this problem domain, and apparently not one I recognise on
sight — I have to be shown it each time by a number going the wrong way.
