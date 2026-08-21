"""Date parsing for Razorpay exports, where one column holds more than one type.

This is not defensive programming for its own sake. Razorpay's own published
``sample-combined-report.xlsx`` mixes native ``datetime`` objects and ``str``
values *inside the same column*, in at least three string formats:

    created_at:  datetime(2022, 4, 7, 10, 43, 32)
    created_at:  "14/07/2022 10:01:14"
    settled_at:  "14-07-2022"

A parser that assumes ``str`` raises ``AttributeError`` on the datetimes; one
that assumes ``datetime`` raises on the strings. Both fail loudly, which is the
good case — the bad case is ``pd.to_datetime`` quietly reading ``07/04/2022`` as
7 April under one inference and 4 July under another.

So: dates are parsed explicitly, day-first (Indian convention), and any value
that *could* be read either way — both components ≤ 12 — is recorded as
ambiguous. Ambiguity is surfaced, never resolved by guessing, because a
settlement window that is off by a month silently changes which payments are
candidates for a cover.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

__all__ = ["ParsedDate", "parse_datetime", "DATE_FORMATS"]

# Ordered most-specific first. Day-first throughout: these are Indian exports.
DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%d %b %Y %H:%M:%S",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d/%b/%Y",
)

# Formats whose leading two components are day and month in that order. A value
# matching one of these is ambiguous when both components are <= 12.
_DAY_FIRST = {f for f in DATE_FORMATS if f.startswith(("%d/%m", "%d-%m"))}


@dataclass(frozen=True, slots=True)
class ParsedDate:
    """A parsed timestamp plus how confident we are about it."""

    value: _dt.datetime | None
    raw: object
    fmt: str | None = None
    ambiguous: bool = False
    """True when the source string could be read as either DD/MM or MM/DD.

    MILAAN reads it day-first, but counts it, and the count is reported. If a
    run's ambiguous-date count is non-zero the settlement windows in that run
    rest on a convention rather than on the data, and the report says so.
    """

    def __bool__(self) -> bool:
        return self.value is not None


def _is_ambiguous(text: str, fmt: str) -> bool:
    if fmt not in _DAY_FIRST:
        return False
    sep = "/" if "/" in fmt else "-"
    head = text.strip().split(" ")[0].split(sep)
    if len(head) < 2:
        return False
    try:
        a, b = int(head[0]), int(head[1])
    except ValueError:
        return False
    return a <= 12 and b <= 12 and a != b


def parse_datetime(value: object) -> ParsedDate:
    """Parse a cell that may be a datetime, a date, an epoch int, a string, or blank.

    Never raises on unparseable input — returns ``ParsedDate(value=None)`` with
    the original preserved in ``raw``, so a bad timestamp becomes a named
    exception downstream rather than a crash halfway through a batch.
    """
    if value is None or value == "":
        return ParsedDate(None, value)

    if isinstance(value, _dt.datetime):
        return ParsedDate(value, value, fmt="native")
    if isinstance(value, _dt.date):
        return ParsedDate(_dt.datetime(value.year, value.month, value.day), value, fmt="native")

    # Razorpay's API speaks Unix seconds. Bound the range so a stray amount in a
    # date column cannot be silently reinterpreted as 1970.
    if isinstance(value, int) and not isinstance(value, bool):
        if 946_684_800 <= value <= 4_102_444_800:  # 2000-01-01 .. 2100-01-01
            return ParsedDate(_dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc).replace(tzinfo=None), value, fmt="epoch")
        return ParsedDate(None, value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ParsedDate(None, value)
        for fmt in DATE_FORMATS:
            try:
                parsed = _dt.datetime.strptime(text, fmt)
            except ValueError:
                continue
            return ParsedDate(parsed, value, fmt=fmt, ambiguous=_is_ambiguous(text, fmt))
        return ParsedDate(None, value)

    return ParsedDate(None, value)
