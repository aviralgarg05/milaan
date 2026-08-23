"""The typed hint an LLM is allowed to propose, and nothing else.

A hint is deliberately not an answer. The model is never asked "which payments
make up this credit" — that question has an arithmetic answer and a language
model has no business producing it. It is asked only to read a bank narration
string that the deterministic grammar could not parse, and to say what
*identifiers* it can see in it.

That framing is what makes the safety property achievable. Every field below is
either:

  * a **verbatim substring of the narration** (`reference`, `counterparty`), which
    can be checked by string containment — an ungrounded claim is rejected
    before it reaches the solver; or
  * a **narrowing filter** (`date_window_days`, `channel`), which can only ever
    remove candidates from consideration, never add one.

There is no field through which a model can assert that a particular payment
belongs to a particular settlement. The shape of the type is the first line of
defence, ahead of any validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Hint", "HINT_JSON_SCHEMA"]


@dataclass(frozen=True, slots=True)
class Hint:
    """What a model may propose after reading an opaque narration."""

    reference: str | None = None
    """A transaction reference the model believes it can see (UTR, RRN, ref no).

    MUST appear verbatim in the narration. Checked, not trusted.
    """

    counterparty: str | None = None
    """A payer/payee name fragment. MUST appear verbatim in the narration."""

    channel: str | None = None
    """NEFT / RTGS / IMPS / UPI / ACH, if the narration indicates one.

    Constrained to an enum, so an unparseable value is a schema violation
    rather than a filter on a channel that does not exist.
    """

    date_window_days: int | None = None
    """How many days around the credit date to consider. 0-30.

    A pure narrowing parameter — it cannot introduce a candidate that was not
    already in the pool.
    """

    confidence: float = 0.0
    """The model's own confidence, 0-1. Recorded and reported, never acted on.

    It is kept because a calibration curve of stated-vs-actual confidence is a
    genuinely interesting number to publish, not because anything downstream
    branches on it.
    """

    reasoning: str = ""
    """Free text. Logged for the audit trail. Read by humans, never by code.

    Nothing in MILAAN parses this field. A test asserts that mutating it cannot
    change any verdict.
    """

    unparseable: bool = False
    """The model's explicit abstention. Preferred over a low-confidence guess."""

    rejected_claims: tuple[str, ...] = field(default=())
    """Populated by grounding, not by the model: claims that failed verification.

    Published in the results file. If this is routinely non-empty, the model is
    hallucinating references and the number says so out loud.
    """


# Sent to the API as output_config.format. Constrained tightly on purpose:
# every string field is length-bounded, the channel is an enum, and the window
# is an integer with an explicit range. A schema violation is caught by the API
# rather than by MILAAN.
HINT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "reference": {
            "type": ["string", "null"],
            "description": (
                "A transaction reference visible in the narration (UTR, RRN, or "
                "reference number), copied EXACTLY as it appears. If you cannot see "
                "one, use null. Do not reconstruct, correct, complete or infer a "
                "reference — a value that does not appear character-for-character in "
                "the narration will be rejected."
            ),
        },
        "counterparty": {
            "type": ["string", "null"],
            "description": (
                "A payer or payee name fragment copied EXACTLY as it appears in the "
                "narration. Null if none is visible. Same rule: it must be a literal "
                "substring of the narration."
            ),
        },
        "channel": {
            "type": ["string", "null"],
            "enum": ["NEFT", "RTGS", "IMPS", "UPI", "ACH", None],
            "description": "The payment channel, if the narration indicates one.",
        },
        "date_window_days": {
            "type": ["integer", "null"],
            "description": (
                "How many days around the credit date the constituent transactions "
                "likely fall within, 0-30. Null if the narration gives no signal."
            ),
        },
        "confidence": {
            "type": "number",
            "description": "Your confidence in this reading, 0.0 to 1.0.",
        },
        "reasoning": {
            "type": "string",
            "description": "One sentence on what you read and why. For the audit log.",
        },
        "unparseable": {
            "type": "boolean",
            "description": (
                "True if the narration carries no usable identifier. Prefer this over "
                "a low-confidence guess — an abstention costs an exception, a wrong "
                "reference costs a wrong join."
            ),
        },
    },
    "required": [
        "reference", "counterparty", "channel", "date_window_days",
        "confidence", "reasoning", "unparseable",
    ],
    "additionalProperties": False,
}
