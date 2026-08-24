"""`money.py`, including the parts nothing else in the suite exercised.

`from_rupee_str` and the comparison operators had zero coverage before this
file — an audit finding, not something caught by writing more of the pipeline.
`test_sample_reports.py` and `test_fee_model.py` exercise `from_report_rupees`
and `Paisa` arithmetic heavily; neither ever calls `from_rupee_str`, and neither
ever compares a `Paisa` to anything. Both gaps are real: the first hid a sign
bug (INCIDENTS.md #26), the second would have hidden a float comparison
succeeding silently if `_check` were ever accidentally skipped on one operator.
"""

from __future__ import annotations

import pytest

from milaan.money import Paisa, format_inr, from_report_rupees, from_rupee_str


# --------------------------------------------------- comparisons never touch a float


def test_every_comparison_operator_refuses_a_float():
    p = Paisa(100)
    for op in (lambda: p < 1.5, lambda: p <= 1.5, lambda: p > 0.5,
               lambda: p >= 0.5, lambda: p == 1.0):
        with pytest.raises(TypeError):
            op()


def test_comparisons_against_int_and_paisa_work_normally():
    assert Paisa(100) < Paisa(200)
    assert Paisa(100) == 100
    assert Paisa(100) <= 100
    assert not (Paisa(100) > 100)
    assert sorted([Paisa(300), Paisa(100), Paisa(200)]) == [100, 200, 300]


def test_paisa_hashes_like_the_underlying_int():
    assert hash(Paisa(100)) == hash(100)
    assert len({Paisa(100), Paisa(100), 100}) == 1


# --------------------------------------------------------- sign-marker composition


def test_dr_marker_alone_is_negative():
    assert from_rupee_str("100 Dr") == Paisa(-10_000)
    assert from_rupee_str("100 Cr") == Paisa(10_000)
    assert from_rupee_str("100") == Paisa(10_000)


def test_multiple_negative_markers_reinforce_rather_than_cancel():
    """INCIDENTS.md #26. Two negative signals must still mean negative.

    A naive XOR of sign markers reads "-100 Dr" as positive, because the
    leading minus and the Dr suffix flip the sign twice. Nobody writing that
    string means +100 — they are emphasising a debit. This is the exact bug an
    audit found and it shipped with zero test coverage on the function.
    """
    assert from_rupee_str("-100 Dr") == Paisa(-10_000)
    assert from_rupee_str("(100) Dr") == Paisa(-10_000)
    assert from_rupee_str("-100") == Paisa(-10_000)
    assert from_rupee_str("(100)") == Paisa(-10_000)


def test_a_credit_marker_does_not_cancel_a_leading_minus():
    """The one case where markers genuinely disagree — Cr does not flip a minus."""
    assert from_rupee_str("-100 Cr") == Paisa(-10_000)


# --------------------------------------------------------------- presentation noise


def test_tolerates_rupee_sign_commas_and_whitespace():
    assert from_rupee_str("₹1,23,456.78") == Paisa(12_345_678)
    assert from_rupee_str("  INR 500.00  ") == Paisa(50_000)
    assert from_rupee_str("1,000") == Paisa(100_000)


def test_rejects_sub_paise_precision_rather_than_rounding():
    with pytest.raises(ValueError):
        from_rupee_str("100.005")


def test_rejects_empty_or_garbage_input():
    with pytest.raises(ValueError):
        from_rupee_str("Dr")
    with pytest.raises(ValueError):
        from_rupee_str("not a number")
    with pytest.raises(TypeError):
        from_rupee_str(12345)  # type: ignore[arg-type]


# ------------------------------------------------------------------- format_inr


def test_format_inr_uses_indian_digit_grouping():
    assert format_inr(Paisa(1_23_45_678)) == "₹1,23,456.78"
    assert format_inr(Paisa(-10_000)) == "-₹100.00"
    assert format_inr(Paisa(0)) == "₹0.00"


# ------------------------------------------------------- round-trips from_report_rupees


def test_from_rupee_str_and_from_report_rupees_agree_on_plain_amounts():
    for text, rupees in [("0.99", 0.99), ("713.00", 713.0), ("1.00", 1.0)]:
        assert from_rupee_str(text) == from_report_rupees(rupees)
