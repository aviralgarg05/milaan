"""End-to-end tests that actually invoke the CLI, not just the functions behind it.

Every other test file calls Python functions in-process: `run_batch(batch,
proposer=SomeHandAssembledStandIn())`. That is fast and precise, and it is
exactly the kind of test that CANNOT catch a wiring bug between `main()` and
`run_batch()` — because the test builds the call `main()` would have made,
by hand, correctly, and never exercises whether `main()` actually builds it
that way.

INCIDENTS.md #26 is a wiring bug of precisely that shape: `milaan run` never
passed a `proposer` to `run_batch()` at all, and no test noticed, because every
test that exercised hints supplied one directly. This file runs the real,
installed `milaan.cli` module as a subprocess — the same code path a judge
running `python -m milaan.cli run` from a fresh clone actually executes — so a
gap between "the pieces work" and "the assembled thing works" fails here first.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

CLI = [sys.executable, "-m", "milaan.cli"]


def run_cli(*args: str, env: dict | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    import os

    full_env = os.environ.copy()
    if env is not None:
        full_env.update(env)
    return subprocess.run(
        [*CLI, *args], capture_output=True, text=True, timeout=timeout, env=full_env,
    )


# --------------------------------------------------------------------- basic run


def test_run_exits_zero_and_prints_the_scorecard():
    r = run_cli("run", "--quiet")
    assert r.returncode == 0, r.stderr
    assert "MATCH RATE" in r.stdout
    assert "FALSE MATCHES    0" in r.stdout


def test_run_verbose_prints_a_verdict_line_per_credit():
    r = run_cli("run")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("MATCHED") + r.stdout.count("AMBIGUOUS") + \
           r.stdout.count("NO_COVER") >= 18


def test_run_trace_prints_the_agents_decision_sequence():
    r = run_cli("run", "--quiet", "--trace")
    assert r.returncode == 0, r.stderr
    assert "AGENT TRACE" in r.stdout
    assert "TRY_INTERVAL" in r.stdout


def test_run_is_deterministic_across_two_subprocess_invocations(tmp_path):
    """Same batch, same verdicts, same hash -- NOT the same throughput line.

    `credits_per_second` is wall-clock derived and genuinely varies run to run
    on a shared machine (documented in LIMITS.md); asserting raw stdout
    equality would make this test flaky for a reason that has nothing to do
    with correctness. Compare the `--json` output instead, which is where the
    deterministic figures actually live, and drop the two wall-clock fields
    explicitly rather than by accident.
    """
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    ra = run_cli("run", "--quiet", "--json", str(out_a))
    rb = run_cli("run", "--quiet", "--json", str(out_b))
    assert ra.returncode == rb.returncode == 0

    a = json.loads(out_a.read_text())
    b = json.loads(out_b.read_text())
    for d in (a, b):
        d.pop("wall_seconds", None)
        d.pop("credits_per_second", None)
        for row in d.get("rows", ()):
            row.pop("ms", None)  # per-credit wall-clock timing, also not deterministic
    assert a == b


# -------------------------------------------------------------------------- json


def test_run_json_writes_valid_parseable_output(tmp_path):
    out = tmp_path / "score.json"
    r = run_cli("run", "--quiet", "--json", str(out))
    assert r.returncode == 0, r.stderr
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["matched"] == 12
    assert data["false_matches"] == 0
    assert data["decidable_credits"] == 15
    assert abs(data["match_rate_decidable"] - 0.80) < 1e-9
    # accepted_covers is a frozenset of tuples internally and must not leak
    # into the JSON dump -- this was a real crash (see cli.py's dumpable dict).
    assert "accepted_covers" not in data


# ------------------------------------------------------------------- generate


def test_generate_writes_a_batch_with_the_answer_key_withheld(tmp_path):
    out = tmp_path / "batch.json"
    r = run_cli("generate", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert "sha256" in r.stdout
    data = json.loads(out.read_text())
    for credit in data["credits"]:
        assert "settlement_id" not in credit
        assert "planted_class" not in credit
    for row in data["ledger"]:
        assert "settlement_id" not in row


# ----------------------------------------------------------------------- hints


def test_hints_ab_exits_zero_and_reports_the_ceiling():
    r = run_cli("hints")
    assert r.returncode == 0, r.stderr
    assert "CEILING ON ANY MODEL" in r.stdout
    assert "+0 credits" in r.stdout
    assert "malign false-matches         0" in r.stdout


# -------------------------------------------------------- --live-hints wiring
#
# These are the tests that would have caught INCIDENTS.md #26. They run the
# real CLI with the real flag, against the real (missing, or fake) credential
# state -- never a hand-assembled proposer standing in for the wiring.


def test_live_hints_with_no_credential_falls_back_and_completes():
    env = {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "",
           "ANTHROPIC_CONFIG_DIR": "/nonexistent/for/this/test"}
    r = run_cli("run", "--quiet", "--live-hints", env=env)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "no Anthropic credential was found" in r.stderr
    assert "FALSE MATCHES    0" in r.stdout
    assert "Traceback" not in r.stderr


def test_live_hints_require_model_hard_errors_with_no_credential():
    env = {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "",
           "ANTHROPIC_CONFIG_DIR": "/nonexistent/for/this/test",
           "MILAAN_REQUIRE_MODEL": "1"}
    r = run_cli("run", "--quiet", "--live-hints", env=env)
    assert r.returncode != 0
    assert "no Anthropic credential" in (r.stdout + r.stderr)


@pytest.mark.skipif(
    subprocess.run([sys.executable, "-c", "import anthropic"],
                   capture_output=True).returncode != 0,
    reason="requires the [hints] extra",
)
def test_live_hints_with_a_syntactically_valid_key_attempts_a_real_call_and_degrades():
    """The test that catches an interface mismatch a fake key alone would not.

    A key that merely fails auth still exercises the FULL real path: client
    construction, an actual HTTPS request, a real `AuthenticationError`, and
    `propose()`'s own error handling turning that into an abstention. If
    `hint_for()` did not exist, or `agent.run()` still took a pre-computed
    `hint=` rather than `hint_provider=`, this crashes with an AttributeError
    or TypeError before any network call happens -- exactly what shipped.
    """
    env = {"ANTHROPIC_API_KEY": "sk-ant-deliberately-invalid-for-integration-test"}
    r = run_cli("run", "--quiet", "--live-hints", env=env, timeout=30)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "LIVE MODEL CALLS" in r.stderr
    assert "1 calls, 1 errors" in r.stderr, (
        "exactly one call is expected: only cr_0014 is both opaque and reaches "
        "TRY_BLIND. A different count means the laziness fix (INCIDENTS.md #26) "
        "regressed and the layer is calling out for credits that can't use it."
    )
    assert "Traceback" not in r.stderr
    assert "FALSE MATCHES    0" in r.stdout


# --------------------------------------------------------------------- --help


def test_help_works_at_every_level():
    for args in (["--help"], ["run", "--help"], ["hints", "--help"], ["generate", "--help"]):
        r = run_cli(*args)
        assert r.returncode == 0, f"{args}: {r.stderr}"
        assert "usage" in r.stdout.lower()


def test_no_command_is_a_clean_argparse_error_not_a_crash():
    r = run_cli()
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
