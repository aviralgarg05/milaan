"""Integer paise. The only place in MILAAN where a float is allowed to touch money.

The reconciliation claim is "closes to the paise". That claim is worth nothing if
the arithmetic that produces it runs on binary floating point, where 0.1 + 0.2 is
not 0.3 and a sum of 340 rupee-denominated payments drifts. So money is an int
everywhere inside the system, and the conversion happens exactly once, here, at
the boundary, under test.

Two boundaries exist and they behave differently:

  * The Razorpay **API** returns money already in integer paise (`amount: 99`).
    That path is lossless and must not go anywhere near a float.
  * The Razorpay **XLSX reports** return money in rupees, and openpyxl hands them
    over as Python floats (`0.99`). That path is lossy on arrival, so it is
    routed through Decimal(str(x)) — reading the shortest repr that round-trips
    the float rather than the float's true binary value, which is what a human
    reading the spreadsheet sees.

Anything else raises. In particular there is no float arithmetic on Paisa: the
type refuses to add, multiply by, or compare against a float at all.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["Paisa", "from_api", "from_report_rupees", "from_rupee_str", "format_inr"]


class Paisa(int):
    """A quantity of money in integer paise.

    Subclasses ``int`` so it is fast and usable directly as a dict key or list
    index in the solver's hot loop, but blocks every float pathway so a rupee
    value cannot silently enter through arithmetic.
    """

    __slots__ = ()

    def __new__(cls, value: int) -> "Paisa":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"Paisa takes an int number of paise, got {type(value).__name__}: {value!r}. "
                "Use from_report_rupees() or from_rupee_str() to convert from rupees."
            )
        return super().__new__(cls, value)

    # -- arithmetic: stays in Paisa, never accepts a float -------------------

    def _check(self, other: Any, op: str) -> None:
        if isinstance(other, float):
            raise TypeError(
                f"refusing to {op} a float ({other!r}) with Paisa. "
                "Convert at the boundary with from_report_rupees()."
            )

    def __add__(self, other: Any) -> "Paisa":
        self._check(other, "add")
        return Paisa(int(self) + int(other))

    def __radd__(self, other: Any) -> "Paisa":
        self._check(other, "add")
        return Paisa(int(other) + int(self))

    def __sub__(self, other: Any) -> "Paisa":
        self._check(other, "subtract")
        return Paisa(int(self) - int(other))

    def __rsub__(self, other: Any) -> "Paisa":
        self._check(other, "subtract")
        return Paisa(int(other) - int(self))

    def __neg__(self) -> "Paisa":
        return Paisa(-int(self))

    def __abs__(self) -> "Paisa":
        return Paisa(abs(int(self)))

    def __mul__(self, other: Any) -> "Paisa":
        self._check(other, "multiply")
        return Paisa(int(self) * int(other))

    __rmul__ = __mul__

    def __truediv__(self, other: Any):
        raise TypeError(
            "true division on Paisa is refused because it produces a float. "
            "Money is split with explicit integer rules, not by dividing."
        )

    __rtruediv__ = __truediv__

    # Comparison was not blocked in the first version: Paisa inherits int's rich
    # comparisons, which silently accept a float. `Paisa(100) == 1.0` answering
    # False is harmless; `Paisa(100) < 1.5` answering True is a money comparison
    # against a rupee value that reads as correct.
    def __eq__(self, other: Any) -> bool:
        self._check(other, "compare")
        return int(self) == other

    def __lt__(self, other: Any) -> bool:
        self._check(other, "compare")
        return int(self) < other

    def __le__(self, other: Any) -> bool:
        self._check(other, "compare")
        return int(self) <= other

    def __gt__(self, other: Any) -> bool:
        self._check(other, "compare")
        return int(self) > other

    def __ge__(self, other: Any) -> bool:
        self._check(other, "compare")
        return int(self) >= other

    def __hash__(self) -> int:
        return int.__hash__(self)

    def __repr__(self) -> str:
        return f"Paisa({int(self)})"

    def __str__(self) -> str:
        return format_inr(self)

    @property
    def rupees_str(self) -> str:
        """Human-readable rupees. Display only — never feed this back into arithmetic."""
        return format_inr(self)


ZERO = Paisa(0)


def from_api(value: int) -> Paisa:
    """Razorpay REST/MCP money field. Already integer paise; lossless."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"Razorpay API money fields are integer paise; got {type(value).__name__}: {value!r}"
        )
    return Paisa(value)


def from_report_rupees(value: Any) -> Paisa:
    """Razorpay XLSX/CSV money cell, denominated in rupees.

    ``None`` and blank map to zero: the combined report leaves the unused side of
    the debit/credit pair empty rather than writing 0, so a missing cell is a
    real zero and not missing data.

    Floats are read via ``Decimal(str(x))`` — the shortest decimal that
    round-trips, i.e. what the spreadsheet displays — then scaled by 100 and
    rounded half-up. A value carrying sub-paise precision is a data error and
    raises rather than being silently truncated.
    """
    if value is None:
        return ZERO
    if isinstance(value, bool):
        raise TypeError(f"bool is not a money value: {value!r}")
    if isinstance(value, str):
        return from_rupee_str(value)
    if isinstance(value, (int, float, Decimal)):
        try:
            d = Decimal(str(value))
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ValueError(f"not a rupee amount: {value!r}") from exc
        scaled = d * 100
        if scaled != scaled.to_integral_value():
            raise ValueError(
                f"rupee amount {value!r} carries sub-paise precision ({scaled} paise). "
                "MILAAN will not round money silently."
            )
        return Paisa(int(scaled))
    raise TypeError(f"not a rupee amount: {type(value).__name__}: {value!r}")


def from_rupee_str(text: str) -> Paisa:
    """Parse a rupee string as it appears in a statement or a dashboard export.

    Tolerates the presentation noise Indian financial exports carry — a rupee
    sign, Indian-grouping commas, whitespace, and a trailing ``Cr``/``Dr``
    marker — but not ambiguity. ``Dr`` yields a negative amount.
    """
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    s = text.strip().replace("₹", "").replace("INR", "").replace(",", "").strip()
    sign = 1
    for marker, mult in (("CR", 1), ("DR", -1)):
        if s.upper().endswith(marker):
            sign = mult
            s = s[: -len(marker)].strip()
            break
    if s.startswith("(") and s.endswith(")"):  # accounting negative
        sign = -sign
        s = s[1:-1].strip()
    if s.startswith("-"):
        sign = -sign
        s = s[1:].strip()
    if not s:
        raise ValueError(f"no amount in {text!r}")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not a rupee amount: {text!r}") from exc
    scaled = d * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"rupee amount {text!r} carries sub-paise precision")
    return Paisa(sign * int(scaled))


def format_inr(paise: int) -> str:
    """Render integer paise in Indian digit grouping (lakh/crore), display only."""
    neg = paise < 0
    whole, frac = divmod(abs(int(paise)), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'-' if neg else ''}₹{s}.{frac:02d}"
