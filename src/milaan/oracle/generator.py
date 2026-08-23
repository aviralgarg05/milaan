"""The sealed batch generator, and the honest account of what it can and cannot prove.

MILAAN needs a batch it can report a match rate on. Live Razorpay settlements
are unavailable — `GET /v1/settlements` is empty on an unactivated test account,
and three independent limits (that, hCaptcha on checkout, and a 30-link
test-mode cap) each make a large live-minted pool impossible. So the batch is
generated here.

That immediately raises the attack every reconciliation demo dies to: *you wrote
the generator, so you wrote the answer key, so your match rate measures your
generator.* Four things are done about it, and the fourth is the honest one.

**1. The generator is sealed before the solver is scored.** It is seeded, and
the seed plus a SHA-256 of its full output is committed before any evaluation
runs. The recorded hash is checkable against a regenerated batch, so a batch
tuned after seeing results cannot be passed off as the original.

**2. It does not know how the solver works.** It emits transactions and groups
them by a documented T+2-working-day rule. It has no model of covers, intervals,
subset-sum, or anything else the solver does. It cannot be tuned toward the
solver's strengths because it cannot see them.

**3. The fee model is not mine.** Amounts are drawn so that fees come out of
`base_fee_two_component`, which reproduces 25 of 25 *real* Razorpay charges
(INCIDENTS.md #16). That is the one part of the answer key Razorpay's own
billing engine authored, and it is the part a cover has to close against to the
paise.

**4. What this does NOT prove, stated plainly.** It does not prove MILAAN would
reconcile a real Indian merchant's real bank statement. The grouping rule is my
reading of Razorpay's documented settlement cycle, not an observation of it. The
narration strings are drawn from published bank formats, not received from a
bank. The honest claim is narrower than "94% match rate" sounds: *given a ledger
and a set of credits grouped by a documented rule, the solver recovers the
grouping N% of the time, refuses M% of the time, and never reported a wrong
join.* That last clause is the one worth having, and it is the one the
arithmetic actually guarantees.

Every exception class in the taxonomy is planted **deliberately** and labelled,
so the exception list is a measurement of the solver's behaviour on known-hard
inputs rather than a list of things that happened to go wrong.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from ..fees import base_fee_two_component

__all__ = ["Batch", "generate", "PLANTED", "batch_hash"]

# Exception classes planted on purpose. Each name is also a verdict the solver
# can emit, so the scorecard compares planted-vs-detected class by class.
PLANTED = {
    "CLEAN": "an ordinary settlement whose members are all present and distinct",
    "WITH_REFUND": "a refund nets against payments inside the settlement",
    "AMBIGUOUS_COVER": "identical amounts admit more than one exact cover",
    "OUT_OF_WINDOW": "a member falls outside the exported ledger window",
    "ZERO_NET": "a member nets to exactly zero (fee-only adjustment)",
    "ON_HOLD": "a member was withheld and settles in a later batch",
}

NARRATION_FORMATS = [
    "NEFT-{ifsc}-RAZORPAY SOFTWARE-{ref}",
    "BY TRANSFER-NEFT*{ifsc}*{utr}*RAZORPAY SOFTWARE PVT",
    "IMPS/P2A/{rrn}/RAZORPAY/SETTLEMENT",
    "UPI/CR/{rrn}/RAZORPAY SOFTW/{bank}/Settlement",
    "RTGS-{utr}-RAZORPAY SOFTWARE PRIVATE LIMITED",
    "NEFT CR-{ifsc}-RAZORPAY SOFTWARE PVT LTD-{ref}",
    # Deliberately opaque: no identifier the grammar can extract. These are the
    # only lines the LLM hint layer is ever offered.
    "SETTLEMENT CREDIT",
    "CR/{shortnum}/COLLECTION",
    "FUND TRANSFER RAZORPAY",
    # Opaque to the grammar but carrying REAL signal a reader can use: the
    # capture date, written in formats the date regex deliberately does not
    # cover (`10 AUG 2026`, `10.08.26`). This is the honest case for a language
    # model — the information is genuinely present in the string and genuinely
    # not extractable by a finite set of patterns.
    "RAZORPAY SETTLEMENT FOR {daymon}",
    "COLLECTION DT {dotdate} RAZORPAY",
    "CREDIT AGAINST BUSINESS OF {daymon}",
]
BANKS = ["HDFC", "ICIC", "UTIB", "SBIN", "KKBK", "IDFB", "PUNB", "BARB"]


@dataclass(frozen=True, slots=True)
class LedgerRow:
    entity_id: str
    type: str
    net_paise: int
    captured_on: str
    settlement_id: str | None  # the withheld answer key
    on_hold: bool = False


@dataclass(frozen=True, slots=True)
class BankCredit:
    credit_id: str
    amount_paise: int
    value_date: str
    narration: str
    settlement_id: str          # answer key
    planted_class: str          # answer key
    captured_on: str = ""       # answer key: true capture date the narration may mention


@dataclass
class Batch:
    seed: int
    ledger: list[LedgerRow] = field(default_factory=list)
    credits: list[BankCredit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self, *, withhold_answers: bool = False) -> dict:
        rows = []
        for r in self.ledger:
            d = asdict(r)
            if withhold_answers:
                d.pop("settlement_id")
            rows.append(d)
        credits = []
        for c in self.credits:
            d = asdict(c)
            if withhold_answers:
                d.pop("settlement_id"), d.pop("planted_class"), d.pop("captured_on")
            credits.append(d)
        return {"seed": self.seed, "ledger": rows, "credits": credits, "notes": self.notes}


def batch_hash(batch: Batch) -> str:
    """SHA-256 of the full batch including answers. Committed before evaluation."""
    payload = json.dumps(batch.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _settles_on(captured: date) -> date:
    """T+2 working days, Razorpay's documented cycle. Weekends skipped, no holidays.

    Holidays are not modelled and that is a named limitation: a real settlement
    calendar would shift some of these by a day, which would change which
    transactions share a settlement. Since the solver never sees the rule and is
    graded on the grouping rather than the dates, the simplification affects
    realism, not fairness.
    """
    d, added = captured, 0
    while added < 2:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _narration(rng: random.Random, sid: str, captured: date) -> str:
    bank = rng.choice(BANKS)
    return rng.choice(NARRATION_FORMATS).format(
        daymon=captured.strftime("%d %b %Y").upper(),
        dotdate=captured.strftime("%d.%m.%y"),
        ifsc=f"{bank}0{rng.randint(0, 999999):06d}",
        utr=f"{bank}N{rng.randint(10**14, 10**15 - 1)}",
        rrn=f"{rng.randint(10**11, 10**12 - 1)}",
        ref=f"N{rng.randint(10**6, 10**7 - 1)}",
        shortnum=f"{rng.randint(10**5, 10**6 - 1)}",
        bank=bank,
    )


def generate(seed: int = 20260823, *, settlements: int = 18,
             start: date = date(2026, 8, 3)) -> Batch:
    """Generate a sealed batch: a ledger, a set of bank credits, and the answer key.

    Every settlement is assigned a planted class in advance, and the transactions
    are constructed to realise it. Nothing is classified after the fact.
    """
    rng = random.Random(seed)
    batch = Batch(seed=seed)
    n = 0

    # Deterministic class schedule — every class appears, ordinary cases dominate.
    schedule = (["CLEAN"] * 7 + ["WITH_REFUND"] * 4 + ["AMBIGUOUS_COVER"] * 3
                + ["OUT_OF_WINDOW"] * 2 + ["ZERO_NET"] * 1 + ["ON_HOLD"] * 1)
    schedule = (schedule * ((settlements // len(schedule)) + 1))[:settlements]

    for s_index, planted in enumerate(schedule):
        sid = f"setl_GEN{s_index:04d}"
        captured = start + timedelta(days=s_index // 2)
        value_date = _settles_on(captured)
        members: list[LedgerRow] = []

        if planted == "AMBIGUOUS_COVER":
            # Identical amounts: any k of them sum the same way. This is the
            # realistic case for a subscription merchant, not a contrivance —
            # Razorpay's own published sample is five identical 99p payments.
            amount = rng.choice([9900, 29900, 49900, 99900])
            for _ in range(rng.randint(4, 7)):
                n += 1
                members.append(LedgerRow(f"pay_G{n:05d}", "payment", amount,
                                         captured.isoformat(), sid))
        else:
            for _ in range(rng.randint(6, 22)):
                n += 1
                members.append(LedgerRow(
                    f"pay_G{n:05d}", "payment",
                    rng.randint(4900, 500000), captured.isoformat(), sid))

        if planted == "WITH_REFUND":
            for _ in range(rng.randint(1, 3)):
                n += 1
                members.append(LedgerRow(f"rfnd_G{n:05d}", "refund",
                                         -rng.randint(4900, 200000),
                                         captured.isoformat(), sid))

        if planted == "ZERO_NET":
            # A fee-only adjustment: debit == credit, so net is exactly zero.
            # This is the input class that silently broke the solver (#14) and
            # it is planted so the scorecard has to face it every run.
            n += 1
            members.append(LedgerRow(f"adj_G{n:05d}", "adjustment", 0,
                                     captured.isoformat(), sid))

        if planted == "ON_HOLD":
            n += 1
            members.append(LedgerRow(f"pay_G{n:05d}", "payment",
                                     rng.randint(4900, 200000),
                                     captured.isoformat(), sid, on_hold=True))

        # Razorpay deducts the fee per transaction; the credit is the net.
        settling = [m for m in members if not m.on_hold]
        gross = sum(m.net_paise for m in settling)
        fees = sum(base_fee_two_component(m.net_paise)
                   for m in settling if m.net_paise > 0)
        credit_amount = gross - fees

        if planted == "OUT_OF_WINDOW":
            # One member is dropped from the exported ledger entirely, so the
            # credit cannot be covered from what the solver can see. The correct
            # answer is an exception, not a match.
            dropped = members.pop()
            batch.notes.append(
                f"{sid}: {dropped.entity_id} withheld from the ledger export "
                f"({dropped.net_paise}p) — no cover is findable and NONE is correct"
            )

        batch.ledger.extend(members)
        batch.credits.append(BankCredit(
            credit_id=f"cr_{s_index:04d}",
            amount_paise=credit_amount,
            value_date=value_date.isoformat(),
            narration=_narration(rng, sid, captured),
            captured_on=captured.isoformat(),
            settlement_id=sid,
            planted_class=planted,
        ))

    batch.notes.append(
        f"{len(batch.credits)} credits over {len(batch.ledger)} ledger rows; "
        f"classes: " + ", ".join(f"{c}={schedule.count(c)}" for c in sorted(set(schedule)))
    )
    return batch
