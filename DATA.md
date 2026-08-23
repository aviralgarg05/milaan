# Data provenance

The attack that kills most reconciliation demos is: *you generated the data, so
you generated the answer key, so your match rate measures your generator.*

This file exists so a reviewer can check that attack themselves, artifact by
artifact. Everything MILAAN touches falls into one of three buckets, and they are
never blended in a results table.

---

## 1. Real, and Razorpay's — they authored it, not me

### Published sample reports
`data/razorpay-samples/*.xlsx`, downloaded verbatim 21 Aug 2026 from Razorpay's
documentation CDN, unmodified. URLs in `SOURCES.md`.

This is where the closure identity is validated. Razorpay decided the settlement
groupings in that file years before this project existed, so when

> `Σ(member credits) − Σ(member debits) == settlement debit`

holds to the paise on all three complete settlements — including
`5 × 99p − 100p = 395p` — that is a property of *their* ledger, not of my
generator. The fourth settlement in the file does not close, and it is a
host-authored instance of the `OUT_OF_WINDOW` exception class. **My exception
taxonomy was validated against someone else's data before I wrote a solver.**

Pinned by `tests/test_sample_reports.py`, which runs with no key and no network.

### Live test-mode entities
Every order, payment link, payment and refund minted during a run is a real
Razorpay test-mode entity with a Razorpay-issued id, timestamp, status **and
fee**. A reviewer with their own test key can fetch any id in `results/*.json`.

Razorpay independently assigns what I cannot predict or control: the entity ids,
the `fee`, the capture timestamps, and — if settlements ever materialise — the
grouping. **The `settlement_id` column is stripped before the solver sees it**
and the solver's proposed cover is graded by set equality against the withheld
column. MILAAN never decides which payment belongs to which settlement.

### Documented failure modes
The twenty error-scenario cards in `data/test-cards.md` are Razorpay's, with
documented outcomes. The `failed payment` exception class is generated from them
rather than invented, so those labels are not mine to be trusted about.

---

## 2. Real, and published — a third party authored it

Bank narration formats, drawn from statement samples the banks themselves
publish. Provenance is tracked per format with a captured-real /
vendor-published-sample / reconstructed column, and **unverified formats are
excluded from the headline number.**

There are no external human contributors to this corpus. Held-out split is
therefore **by format, not by bank**, and `n` is stated out loud in the video
rather than left to be inferred. This is a weaker generalisation claim than
by-bank holdout and is reported as such.

---

## 3. Mine, and labelled as mine

The transaction mix, the amounts, the entropy regimes, and — until and unless
live settlements appear — the batching script that groups transactions into
settlements. That script is **seeded, sealed and hash-committed before any
solver exists**, so it cannot be tuned to the solver, but it is still mine and
the README, this file and the video all say so in the same words.

**The precise claim, narrower than it may sound:** MILAAN measures whether a
proposed cover is arithmetically exact and uniquely determined against a
withheld grouping. It does not claim to measure agreement with a real Indian
bank's settlement of a real merchant account.

---

## Ground-truth posture: sealed generator is PRIMARY

Probed 23 Aug 2026 on a fresh test account, recorded either way:

| Probe | Result |
|---|---|
| E1 REST auth | **GREEN** |
| write surface (`create_order`, `create_payment_link`) | **GREEN**, both 200 |
| E3 fee on a captured payment | **GREEN**, non-zero — see below |
| E4 `GET /v1/settlements` | **EMPTY** |
| E4b `GET /v1/settlements/recon/combined` | 200, **0 rows** |

Razorpay's settlement docs require an account that is "KYC approved" and "fully
activated", and settlement runs T+2 working days. No documentation states
whether test mode produces settlements at all. So the sealed generator is
primary ground truth from day one, and `scripts/check_keys.py` re-probes daily.
**If Razorpay-authored groupings ever appear they are promoted to a second
results column reported beside the sealed one — never silently substituted.**

This was decided *before* the probe, so an empty result is a recorded outcome
rather than a retreat.

### The fee model, and what test mode does and does not validate

First captured test payment, `pay_TTGbjjcwSCSQaC`, 23 Aug 2026:

```
amount 49900p    fee 1098p    tax 0p    →  net 48802p
1098 / 49900 = exactly 2.200%
```

**Validated:** the *total* fee is non-zero and computed by Razorpay's own
engine, so the fee model is checked against their arithmetic rather than against
a pricing page. The residual between modelled and returned `fee` is reported as
a number, not absorbed.

**Not validated:** the fee/tax split. `tax` is **0** here, and 0 in every row of
Razorpay's published sample too (fee=1p, tax=0p). Test mode returns an all-in
fee and does not break out GST. So the GST line — a genuine complication in
production reconciliation — **cannot be exercised in test mode**, and MILAAN
does not claim to have exercised it. Stated in `LIMITS.md` and on camera.

Rounding is derived empirically across the minted batch rather than from the
published rate, because 18% of a one-paisa fee rounds to zero and Razorpay
rounds per transaction, not per settlement (INCIDENTS.md #5).

*One data point so far. The rate's stability and its rounding rule get
re-measured across the full minted batch, and that measurement is published.*
