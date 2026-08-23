"""Deterministic extraction from Indian bank narration strings.

This runs FIRST, on every line, and it is the thing the LLM hint layer is
measured against. Whatever the grammar can extract, the LLM is never asked
about — the model's budget is spent only on the residue.

The formats are not standardised. Every bank writes its own, and the same bank
writes several depending on channel and statement export. What they have in
common is that the *identifiers* inside them are structured even when the string
around them is not:

    NEFT-HDFC0000123-RAZORPAY SOFTWARE-N2938471
    IMPS/P2A/412345678901/RAZORPAY/SETTLEMENT
    UPI/CR/412345678901/RAZORPAY SOFTW/UTIB/Settlement
    BY TRANSFER-NEFT*ICIC0000001*ICICN52026081234567*RAZORPAY SOFTWARE PVT

So the grammar targets the identifiers, not the sentence:

  * **IFSC** — 4 letters, a literal ``0``, then 6 alphanumerics. Unambiguous
    and self-validating, which makes it the highest-confidence token in a
    narration even though it identifies a branch rather than a transaction.
  * **NEFT/RTGS UTR** — bank prefix, a channel letter, then digits. Length
    varies by channel (NEFT 16, RTGS 22) and banks pad differently, so the
    pattern is deliberately loose on length and tight on shape.
  * **RRN** — a bare 12-digit run, used by IMPS and UPI. This one is genuinely
    ambiguous: a 12-digit number in a narration might be an RRN, an account
    fragment, or a phone number. It is extracted with lower confidence and
    marked as such rather than being trusted.

Everything returns a confidence and the exact substring it came from. The
substring matters: it is what the grounding check in ``hints/grounding.py``
verifies an LLM-proposed hint against, so extraction and verification speak the
same language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

__all__ = ["Channel", "Token", "NarrationFields", "extract",
           "IFSC_RE", "UTR_RE", "RRN_RE", "REF_RE"]


class Channel(str, Enum):
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    UPI = "UPI"
    ACH = "ACH"
    UNKNOWN = "UNKNOWN"


# 4 letters, literal zero, 6 alphanumerics. Self-validating by shape.
IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")

# NEFT/RTGS style: bank prefix + channel letter + digits. Loose on length
# because banks pad inconsistently; tight on shape so it cannot match prose.
UTR_RE = re.compile(r"\b([A-Z]{2,6}[NRHC]\d{8,20})\b")

# Bare 12-digit run — IMPS/UPI RRN. Genuinely ambiguous; see module docstring.
RRN_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")

# Short reference: one letter then 6-19 digits, e.g. the `N2938471` tail some
# banks write instead of a full UTR. The word boundary keeps it from matching
# the interior of a real UTR like ICICN52026081234567. Lower confidence than a
# UTR because the shape is weak enough to catch unrelated identifiers.
REF_RE = re.compile(r"\b([A-Z]\d{6,19})\b")

_CHANNEL_RE = re.compile(r"\b(NEFT|RTGS|IMPS|UPI|ACH|NACH)\b", re.IGNORECASE)

_DATE_RES = (
    (re.compile(r"\b(\d{2})[-/](\d{2})[-/](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b"), "ymd"),
)

# Tokens that appear in nearly every settlement narration and therefore
# distinguish nothing. Excluded from counterparty extraction.
_STOPWORDS = frozenset({
    "BY", "TO", "FROM", "CR", "DR", "TRANSFER", "TRF", "PAYMENT", "PMT",
    "SETTLEMENT", "SETTLE", "NEFT", "RTGS", "IMPS", "UPI", "ACH", "NACH",
    "P2A", "P2P", "INB", "MMT", "REF", "REFNO", "TXN", "THE", "AND", "PVT",
    "LTD", "LIMITED", "INDIA", "BANK",
})


@dataclass(frozen=True, slots=True)
class Token:
    """One extracted identifier, and exactly where it came from.

    ``text`` is a verbatim substring of the narration. That is a hard invariant,
    asserted in tests, because the grounding check for LLM hints reuses it: a
    hint is accepted only if its claimed token appears in the narration the same
    way a grammar token does.
    """

    kind: str
    text: str
    start: int
    end: int
    confidence: float

    def verify_against(self, narration: str) -> bool:
        return narration[self.start:self.end] == self.text


@dataclass(frozen=True, slots=True)
class NarrationFields:
    raw: str
    channel: Channel = Channel.UNKNOWN
    utrs: tuple[Token, ...] = ()
    rrns: tuple[Token, ...] = ()
    ifscs: tuple[Token, ...] = ()
    refs: tuple[Token, ...] = ()
    dates: tuple[Token, ...] = ()
    counterparty_tokens: tuple[Token, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def has_strong_reference(self) -> bool:
        """True when a UTR was found — the anchor pass can skip the solver.

        Only UTRs count. An IFSC identifies a branch, not a transaction, and an
        RRN is ambiguous enough that treating it as an anchor would produce
        confident wrong joins.
        """
        return bool(self.utrs)

    @property
    def is_opaque(self) -> bool:
        """True when the grammar found nothing usable. This is the LLM's only entry point.

        A narration is opaque when it carries no UTR, no RRN and no IFSC.
        Everything else is handled deterministically and the model is never
        consulted — which is what keeps the measured ₹/decision low and the
        blast radius small.
        """
        return not (self.utrs or self.rrns or self.ifscs or self.refs)

    @property
    def best_reference(self) -> Token | None:
        candidates = [*self.utrs, *self.rrns, *self.refs]
        return max(candidates, key=lambda t: t.confidence) if candidates else None


def _tokens(pattern: re.Pattern[str], text: str, kind: str, confidence: float) -> tuple[Token, ...]:
    return tuple(
        Token(kind, m.group(1), m.start(1), m.end(1), confidence)
        for m in pattern.finditer(text)
    )


def extract(narration: str) -> NarrationFields:
    """Pull every structured identifier the grammar recognises out of a narration.

    Never raises and never guesses. An unrecognised narration comes back with
    ``is_opaque == True`` rather than with a low-confidence invention, because a
    wrong reference is worse than no reference — it produces a confident join to
    the wrong settlement.
    """
    if not isinstance(narration, str):
        raise TypeError(f"narration must be str, got {type(narration).__name__}")

    upper = narration.upper()
    notes: list[str] = []

    ifscs = _tokens(IFSC_RE, upper, "ifsc", 0.99)
    utrs = _tokens(UTR_RE, upper, "utr", 0.95)

    # An IFSC also matches the UTR shape's prefix in some banks' formats. Drop
    # any UTR whose span overlaps an IFSC — the IFSC reading is the safer one.
    ifsc_spans = [(t.start, t.end) for t in ifscs]
    utrs = tuple(
        t for t in utrs
        if not any(t.start < e and s < t.end for s, e in ifsc_spans)
    )

    refs = tuple(
        t for t in _tokens(REF_RE, upper, "ref", 0.5)
        if not any(t.start < e and s_ < t.end for s_, e in ifsc_spans)
        and not any(t.start < u.end and u.start < t.end for u in utrs)
    )

    rrns = _tokens(RRN_RE, upper, "rrn", 0.55)
    if rrns:
        notes.append(
            f"{len(rrns)} bare 12-digit run(s) read as RRN at confidence 0.55; "
            "a 12-digit number in a narration may also be an account fragment"
        )

    dates: list[Token] = []
    for pattern, order in _DATE_RES:
        for m in pattern.finditer(upper):
            dates.append(Token(f"date:{order}", m.group(0), m.start(), m.end(), 0.8))

    channel = Channel.UNKNOWN
    if (m := _CHANNEL_RE.search(upper)):
        raw = m.group(1).upper()
        channel = Channel.ACH if raw == "NACH" else Channel(raw)

    # Counterparty: alphabetic runs that are not stopwords and not part of an
    # identifier already extracted. Low confidence by design — this is a hint
    # for narrowing, never an assertion of identity.
    claimed = [(t.start, t.end) for t in (*ifscs, *utrs, *rrns, *refs, *dates)]
    counterparty: list[Token] = []
    for m in re.finditer(r"\b([A-Z]{3,})\b", upper):
        if m.group(1) in _STOPWORDS:
            continue
        if any(m.start() < e and s < m.end() for s, e in claimed):
            continue
        counterparty.append(Token("counterparty", m.group(1), m.start(), m.end(), 0.4))

    return NarrationFields(
        raw=narration,
        channel=channel,
        utrs=utrs,
        rrns=rrns,
        ifscs=ifscs,
        refs=refs,
        dates=tuple(dates),
        counterparty_tokens=tuple(counterparty),
        notes=tuple(notes),
    )
