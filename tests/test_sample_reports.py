"""Regression test #1 — the closure identity, on Razorpay's own published data.

This is the load-bearing test in MILAAN and it is deliberately the first thing
in the pitch video, because the data is not mine. These files are Razorpay's own
published sample reports, downloaded verbatim from razorpay.com/docs and vendored
under ``data/razorpay-samples/`` with their source URLs recorded in DATA.md.

The claim MILAAN rests on is:

    for every settlement:  sum(member credits) - sum(member debits) == settlement debit

evaluated in integer paise. If that identity does not hold, the entire idea of
reconstructing a settlement as an exact cover over ledger rows is wrong, and no
amount of solver quality rescues it.

It holds, exactly, on all three complete settlements in Razorpay's sample —
including the interesting one, which nets a refund against five payments:

    setl_Jq0XZksg0i2Fat   99p + 99p                          = 198p
    setl_JtAs2E7Uf55JMV   99p x 5 - 100p                     = 395p
    setl_JvXyfCc3YcAT6V   99p + 99p                          = 198p

The fourth settlement in the file does *not* close, and that is not a defect in
the data — it is a host-authored instance of MILAAN's OUT_OF_WINDOW exception
class, sitting in the sample for free. ``setl_K4eBPTyLTnLCGr`` is ₹1.91 in the
settlements report but only 99p of it appears in the combined report, because
the export window cut the settlement in half. MILAAN's exception taxonomy is
therefore validated against somebody else's data before a line of solver exists.

If any assertion here fails, suspect this repository's parser before suspecting
the data.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from pathlib import Path

import pytest

from milaan.money import Paisa, from_report_rupees
from milaan.reports import (
    group_by_settlement,
    load_combined_report,
    load_settlements_report,
    load_sheet,
    settlement_rows,
)

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "razorpay-samples"
COMBINED = SAMPLES / "sample-combined-report.xlsx"
SETTLEMENTS = SAMPLES / "sample-settlements-report.xlsx"

# The three settlements whose members are fully present in the combined report,
# with the exact paise total each must close to.
COMPLETE = {
    "setl_Jq0XZksg0i2Fat": 198,
    "setl_JtAs2E7Uf55JMV": 395,
    "setl_JvXyfCc3YcAT6V": 198,
}
# Present as a member reference, but its settlement row is outside the export window.
INCOMPLETE = "setl_K4eBPTyLTnLCGr"


@pytest.fixture(scope="module")
def entries():
    return load_combined_report(COMBINED)


# ---------------------------------------------------------------- the identity


def test_closure_identity_holds_on_every_complete_settlement(entries):
    """sum(credits) - sum(debits) over members == the settlement row's debit."""
    members = group_by_settlement(entries)
    totals = settlement_rows(entries)

    closed = 0
    for sid, expected in COMPLETE.items():
        assert sid in totals, f"{sid} has no settlement row in the combined report"
        net = sum(int(m.net) for m in members[sid])
        assert net == expected, f"{sid}: members net to {net}p, expected {expected}p"
        assert net == int(totals[sid].debit), (
            f"{sid}: members net to {net}p but the settlement row debits "
            f"{int(totals[sid].debit)}p"
        )
        closed += 1

    assert closed == 3, "expected exactly three complete settlements in the sample"


def test_the_interesting_settlement_nets_a_refund_against_five_payments(entries):
    """setl_JtAs2E7Uf55JMV is the one-to-many-with-negatives case the solver targets.

    Five 99p payments and one 100p refund. It matters that this shape exists in
    real Razorpay data, because a cover made only of positive terms is a much
    easier problem than one where a member can subtract.
    """
    members = group_by_settlement(entries)["setl_JtAs2E7Uf55JMV"]
    kinds = Counter(m.type for m in members)

    assert kinds["payment"] == 5
    assert kinds["refund"] == 1
    assert sum(int(m.net) for m in members if m.type == "payment") == 495
    assert sum(int(m.net) for m in members if m.type == "refund") == -100
    assert sum(int(m.net) for m in members) == 395


def test_incomplete_settlement_is_a_genuine_out_of_window_instance(entries):
    """The host's own data contains an exception, not just happy paths."""
    members = group_by_settlement(entries)
    totals = settlement_rows(entries)

    assert INCOMPLETE in members, "expected member rows referencing the cut settlement"
    assert INCOMPLETE not in totals, "its settlement row should be outside the export window"

    visible = sum(int(m.net) for m in members[INCOMPLETE])
    declared = {s.id: s.amount for s in load_settlements_report(SETTLEMENTS)}[INCOMPLETE]

    assert visible == 99
    assert int(declared) == 191
    assert visible < int(declared), (
        "the combined report should show strictly less than the settlements report "
        "declares — that shortfall is what OUT_OF_WINDOW means"
    )


# ------------------------------------------------------- the parser trap pins
# Each of these is an incident that cost real debugging time. They are pinned so
# the fix cannot regress, and they are cited in INCIDENTS.md.


def test_settlements_report_has_a_blank_column_a(entries):
    """INCIDENT #2. Headers start at B1, so ordinal indexing shifts every column.

    A naive read of this file does not fail — it succeeds, with every value in
    the wrong field. The loader indexes by header position, never by ordinal.
    """
    import openpyxl

    wb = openpyxl.load_workbook(SETTLEMENTS, data_only=True)
    grid = [[c.value for c in r] for r in wb.worksheets[0].iter_rows()]
    wb.close()

    assert all(row[0] is None for row in grid), "column A should be entirely blank"

    rows = load_settlements_report(SETTLEMENTS)
    assert len(rows) == 1
    assert rows[0].id == INCOMPLETE, "the id must not have been shifted out of position"
    assert rows[0].amount == Paisa(191)


def test_date_columns_mix_datetime_and_str_in_the_same_column():
    """INCIDENT #3. One column, two Python types, three string formats.

    ``created_at`` holds native ``datetime`` objects *and* strings like
    ``"14/07/2022 10:01:14"``; ``settled_at`` adds ``"14-07-2022"``. Any parser
    that assumes a single type raises partway through the batch.
    """
    sheet = load_sheet(COMBINED)
    raw_types = Counter()
    for row in sheet:
        for col in ("created_at", "settled_at"):
            raw = row.get(f"_{col}_raw")
            if raw is not None and raw != "":
                raw_types[type(raw).__name__] += 1

    assert raw_types["datetime"] > 0, "expected native datetimes"
    assert raw_types["str"] > 0, "expected string dates in the same columns"

    # and every one of them still parsed
    for row in sheet:
        for col in ("created_at", "settled_at"):
            if row.get(f"_{col}_raw"):
                assert isinstance(row[col], _dt.datetime), (
                    f"{col} raw={row[f'_{col}_raw']!r} failed to parse"
                )


def test_settlement_utr_is_null_in_every_row_of_the_combined_report(entries):
    """INCIDENT #4. The column exists; the data does not.

    This is why the anchor pass needs two files. The UTR — the only field that
    ties a bank credit line to a settlement without solving anything — lives in
    the settlements report, not the combined report, even though the combined
    report has a column for it.
    """
    assert len(entries) == 14
    assert all(e.settlement_utr is None for e in entries)

    declared = load_settlements_report(SETTLEMENTS)
    assert declared[0].utr is not None, "the settlements report does carry a UTR"


def test_eighteen_percent_gst_on_a_one_paisa_fee_rounds_to_zero(entries):
    """INCIDENT #5. The fee model must reproduce Razorpay's rounding, not the rate.

    Every payment in the sample carries fee=1p and tax=0p. 18% of one paisa is
    0.18p, which rounds to zero. A fee model that applies 18% and rounds
    half-up per-settlement rather than per-transaction will be off by a paise,
    and a paise is the difference between a cover and an exception.
    """
    payments = [e for e in entries if e.type == "payment"]
    assert payments, "expected payment rows"
    assert {(int(p.fee), int(p.tax)) for p in payments} == {(1, 0)}


def test_settlement_rows_do_not_carry_their_own_settlement_id(entries):
    """INCIDENT #1. The join everyone gets wrong on the first try.

    A settlement row's own identifier is in ``entity_id``; its ``settlement_id``
    is null. ``groupby('settlement_id')`` therefore drops every settlement total
    into a single spurious ``None`` bucket, and each real group looks like it is
    missing its total. Members are grouped by ``settlement_id``; totals are
    keyed by ``entity_id``.
    """
    totals = settlement_rows(entries)
    assert set(totals) == set(COMPLETE)
    assert all(s.settlement_id is None for s in totals.values())
    assert all(s.entity_id.startswith("setl_") for s in totals.values())

    members = group_by_settlement(entries)
    assert None not in members
    assert not any(m.is_settlement for group in members.values() for m in group)


def test_the_float_hazard_is_conversion_not_accumulation():
    """INCIDENT #6, and a correction to my own first version of this test.

    I originally asserted that summing rupee floats drifts, and wrote
    ``assert 0.99*5 - 1.00 != 3.95``. It fails: that expression is exact. So is
    the repeated-addition form, and so is a 340-row settlement — measured over
    2000 randomised settlements of 340 rows each, float summation agreed with
    Decimal to the paise every single time. A double carries ~15 significant
    digits and a settlement total is ~8, so accumulation error stays well below
    a paise. **The accumulation hazard is not real at this scale and MILAAN does
    not claim it is.**

    The hazard that *is* real is the conversion at the boundary. ``int(r * 100)``
    truncates rather than rounds, and binary floating point puts 4,586 of the
    first 99,999 paise values just below their integer — ₹0.29 becomes 28p and
    ₹8.20 becomes 819p. That is a 4.6% corruption rate on the most natural
    one-liner anyone would write, and every corrupted value is short by exactly
    one paise, which is precisely the error that turns a valid cover into an
    unexplained exception.

    So integer paise are justified by the boundary, not by the arithmetic, and
    ``from_report_rupees`` goes through ``Decimal(str(x))`` for that reason.
    """
    assert int(0.29 * 100) == 28, "the truncation hazard should still be present"
    assert int(8.20 * 100) == 819

    corrupted = [p for p in range(1, 100_000) if int((p / 100) * 100) != p]
    assert len(corrupted) > 4_000, f"expected thousands of truncation failures, got {len(corrupted)}"

    # The boundary adapter is correct on every one of them.
    for paise in corrupted[:500]:
        assert int(from_report_rupees(paise / 100)) == paise


def test_money_cannot_silently_mix_with_floats(entries):
    """The type refuses the operation rather than producing a plausible wrong number."""
    members = group_by_settlement(entries)["setl_JtAs2E7Uf55JMV"]
    assert sum(int(m.net) for m in members) == 395

    assert isinstance(from_report_rupees(0.99), Paisa)
    with pytest.raises(TypeError):
        from_report_rupees(0.99) + 1.0
    with pytest.raises(TypeError):
        Paisa(100) * 1.18  # an 18% GST rate is not a money operation
    with pytest.raises(TypeError):
        Paisa(395) / 5
