"""`hints/llm.py` — the actual "ai thing". Zero test coverage before INCIDENTS.md #26.

That incident is the reason every test here exists: the module's own logic
(`CallStats`, `OfflineProposer`, the credential check) was never wrong, but
nothing verified the SEAM between this module and its only caller, and the seam
is where the real bugs were — an interface mismatch that crashed on first use,
and an eager call pattern that would have overspent 4.5x on a real API key.
These tests target exactly that seam: does `hint_for()` present what `cli.py`
actually calls, does the credential check behave the way its own docstring
claims, and — via `test_cli_integration.py` — does the wiring survive a run of
the real, installed CLI rather than only a hand-assembled call in a unit test.

No network calls. `AnthropicProposer.propose()` is exercised only through a
fake client substituted after construction, so the HTTP-calling code path is
tested without spending money or requiring a key.
"""

from __future__ import annotations

import os

import pytest

from milaan.hints.llm import (
    AnthropicProposer,
    CallStats,
    OfflineProposer,
    _looks_like_credentials_exist,
    default_proposer,
)
from milaan.hints.schema import Hint
from milaan.narration.grammar import extract


# --------------------------------------------------------------------- CallStats


def test_call_stats_cost_is_zero_with_no_calls():
    st = CallStats()
    assert st.cost_inr == 0.0
    assert st.inr_per_call == 0.0
    assert st.percentile(50) == 0.0


def test_call_stats_computes_cost_from_the_pricing_table():
    st = CallStats(model="claude-opus-5")
    st.calls = 2
    st.input_tokens = 1_000_000
    st.output_tokens = 100_000
    # $5.00 in + $25.00*0.1 out = $7.50, at 83 INR/USD
    assert st.cost_inr == pytest.approx(7.50 * 83.0)
    assert st.inr_per_call == pytest.approx(st.cost_inr / 2)


def test_call_stats_falls_back_to_default_pricing_for_an_unknown_model():
    st = CallStats(model="some-future-model-not-in-the-table")
    st.input_tokens = 1_000_000
    st.calls = 1
    from milaan.hints.llm import DEFAULT_MODEL, MODEL_PRICING

    expected = MODEL_PRICING[DEFAULT_MODEL][0] * 83.0
    assert st.cost_inr == pytest.approx(expected)


def test_call_stats_percentiles_are_order_correct():
    st = CallStats()
    st.latencies_ms = [100, 200, 300, 400, 500]
    assert st.percentile(50) == 300
    assert st.percentile(0) == 100
    assert st.percentile(100) == 500


# ---------------------------------------------------------------- OfflineProposer


def test_offline_proposer_abstains_on_everything():
    p = OfflineProposer()
    hint = p.propose(extract("SETTLEMENT CREDIT"))
    assert hint.unparseable is True
    assert p.stats.calls == 0
    assert p.stats.model == "offline"


def test_offline_proposer_hint_for_returns_none():
    """The wrapper must turn an abstention into None, not an empty GroundedHint.

    `cli.py` counts a credit as "offered a hint" iff `hint_for()` returns
    something other than None. An `OfflineProposer` never offers one.
    """
    p = OfflineProposer()
    assert p.hint_for(extract("SETTLEMENT CREDIT"), value_date=None) is None


# --------------------------------------------------- HintProposer.hint_for() wrapping


class _FixedProposer(AnthropicProposer.__base__ if False else object):
    pass


def _make_stub(raw_hint: Hint):
    """A proposer whose `propose()` returns a fixed `Hint`, to test the wrapper alone."""
    from milaan.hints.llm import CallStats, HintProposer

    class Stub(HintProposer):
        def __init__(self):
            self.stats = CallStats(model="stub")

        def propose(self, fields):
            return raw_hint

    return Stub()


def test_hint_for_grounds_a_grounded_raw_hint():
    narration = "NEFT-HDFC0000123-RAZORPAY SOFTWARE-N2938471"
    stub = _make_stub(Hint(reference="N2938471", confidence=0.9))
    grounded = stub.hint_for(extract(narration), value_date=None)
    assert grounded is not None
    assert grounded.reference == "N2938471"


def test_hint_for_drops_a_hallucinated_claim_but_still_returns_a_result():
    narration = "SETTLEMENT CREDIT"
    stub = _make_stub(Hint(reference="NOT-IN-THE-NARRATION", confidence=0.9))
    grounded = stub.hint_for(extract(narration), value_date=None)
    assert grounded is not None
    assert grounded.reference is None
    assert grounded.rejected_claims


def test_hint_for_returns_none_for_an_unparseable_raw_hint():
    """An explicit model abstention must not be counted as an offered hint."""
    stub = _make_stub(Hint(unparseable=True, reasoning="nothing here"))
    assert stub.hint_for(extract("SETTLEMENT CREDIT"), value_date=None) is None


def test_hint_for_returns_none_after_a_failed_call():
    """propose() converts a failed API call into unparseable=True; hint_for must too."""
    stub = _make_stub(Hint(unparseable=True, reasoning="model call failed: AuthenticationError"))
    assert stub.hint_for(extract("SETTLEMENT CREDIT"), value_date=None) is None


# ----------------------------------------------------- AnthropicProposer, no network


def test_anthropic_proposer_refuses_a_narration_the_grammar_already_read():
    """The guard against spending a call where the grammar already succeeded."""
    pytest.importorskip("anthropic", reason="requires the [hints] extra")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-construction-only"
    try:
        p = AnthropicProposer()
    finally:
        del os.environ["ANTHROPIC_API_KEY"]

    readable = extract("NEFT-HDFC0000123-RAZORPAY SOFTWARE-N2938471")
    assert not readable.is_opaque
    with pytest.raises(ValueError, match="already parsed"):
        p.propose(readable)


def test_anthropic_proposer_call_failure_becomes_an_abstention_not_a_crash():
    """A real network/auth failure must degrade to Hint(unparseable=True), not raise."""
    pytest.importorskip("anthropic", reason="requires the [hints] extra")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-deliberately-invalid-for-this-test"
    try:
        p = AnthropicProposer()
    finally:
        del os.environ["ANTHROPIC_API_KEY"]

    class _BrokenClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("simulated network failure")

    p._client = _BrokenClient()
    hint = p.propose(extract("SETTLEMENT CREDIT"))
    assert hint.unparseable is True
    assert "model call failed" in hint.reasoning
    assert p.stats.calls == 1
    assert p.stats.errors == 1


# --------------------------------------------------------------- default_proposer


def test_default_proposer_is_offline_with_no_credential_present():
    env_backup = {
        k: os.environ.pop(k, None)
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CONFIG_DIR")
    }
    os.environ["ANTHROPIC_CONFIG_DIR"] = "/nonexistent/path/for/this/test"
    try:
        assert _looks_like_credentials_exist() is False
        p = default_proposer()
        assert isinstance(p, OfflineProposer)
    finally:
        os.environ.pop("ANTHROPIC_CONFIG_DIR", None)
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v


def test_default_proposer_attempts_anthropic_when_a_key_env_var_is_present():
    """Presence, not validity, is what this check can see -- and it should try.

    Requires the [hints] extra: without `anthropic` installed, `default_proposer()`
    correctly falls back to `OfflineProposer` even with a key present, since
    `AnthropicProposer.__init__` raises `ModuleNotFoundError` on construction --
    itself a real, if different, reason to fall back gracefully.
    """
    pytest.importorskip("anthropic", reason="requires the [hints] extra")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-presence-only"
    try:
        assert _looks_like_credentials_exist() is True
        p = default_proposer()
        assert isinstance(p, AnthropicProposer)
    finally:
        del os.environ["ANTHROPIC_API_KEY"]


def test_milaan_require_model_hard_errors_with_no_credential():
    env_backup = {
        k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    os.environ["ANTHROPIC_CONFIG_DIR"] = "/nonexistent/path/for/this/test"
    os.environ["MILAAN_REQUIRE_MODEL"] = "1"
    try:
        with pytest.raises(RuntimeError, match="no Anthropic credential"):
            default_proposer()
    finally:
        os.environ.pop("ANTHROPIC_CONFIG_DIR", None)
        os.environ.pop("MILAAN_REQUIRE_MODEL", None)
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v
