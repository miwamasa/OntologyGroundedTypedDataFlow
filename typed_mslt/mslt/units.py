"""Dimensional algebra for semantic units.

Units are not decorative strings: an occurrence-exposure rate *is* a count
divided by a person-year exposure, and the ``1/year`` that comes out should be
derived by the algebra rather than asserted by the author. That derivation is
what catches a denominator that carries the wrong dimension -- the classic
``person`` vs ``person-year`` confusion -- which a check on the semantic
``kind`` alone cannot see.

Base dimensions are ``person`` and ``year``. Everything else is either a
product/quotient of those, a dimensionless quantity (a proportion, a
probability), or an opaque unit for genuinely heterogeneous frames.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

BASE_DIMENSIONS = ("person", "year")

# An occurrence-exposure rate counts the persons who experienced the event, so
# an event count is dimensionally a person count. Keeping the alias means older
# manifests written with "event" still parse.
_ALIASES = {
    "person": "person", "persons": "person",
    "event": "person", "events": "person",
    "year": "year", "years": "year",
}

# Dimensionless quantities that carry a meaningful name for display.
_DIMENSIONLESS = {"proportion", "probability", "ratio", "share", "1", ""}

# Units whose rows are heterogeneous, so no dimensional analysis applies.
_OPAQUE = {"mixed"}

_ATOM = re.compile(r"^([A-Za-z_]+)(?:\^(-?\d+))?$")


class UnitError(TypeError):
    """Raised when units cannot be parsed or do not combine lawfully."""


def _normalize(exponents: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((d, e) for d, e in exponents.items() if e != 0))


@dataclass(frozen=True)
class Unit:
    """A product of base dimensions with integer exponents.

    ``label`` is display-only and excluded from equality, so ``proportion`` and
    ``probability`` compare equal (both are dimensionless) while still printing
    under the name the domain uses for them.
    """

    exponents: tuple[tuple[str, int], ...] = ()
    opaque: str = ""
    label: str = field(default="", compare=False)

    # -- construction ----------------------------------------------------
    @classmethod
    def parse(cls, text: "str | Unit") -> "Unit":
        if isinstance(text, Unit):
            return text
        s = str(text).strip()
        if s in _OPAQUE:
            return cls(opaque=s, label=s)
        if s in _DIMENSIONLESS:
            return cls(label=s if s not in {"1", ""} else "")

        num, sep, den = s.partition("/")
        if sep and "/" in den:
            raise UnitError(f"cannot parse unit {s!r}: more than one '/'")
        exps: dict[str, int] = {}
        for side, sign in ((num, 1), (den, -1)):
            for atom in re.split(r"[-*·]", side.strip()):
                atom = atom.strip()
                if not atom or atom in _DIMENSIONLESS:
                    continue
                m = _ATOM.match(atom)
                if not m:
                    raise UnitError(f"cannot parse unit {s!r}: bad atom {atom!r}")
                name, exp = m.group(1).lower(), int(m.group(2) or 1)
                base = _ALIASES.get(name)
                if base is None:
                    raise UnitError(
                        f"cannot parse unit {s!r}: unknown dimension {name!r}; "
                        f"expected one of {sorted(set(_ALIASES))}"
                    )
                exps[base] = exps.get(base, 0) + sign * exp
        return cls(_normalize(exps))

    @classmethod
    def dimensionless(cls, label: str = "") -> "Unit":
        return cls(label=label)

    def labeled(self, name: str) -> "Unit":
        """Attach a display name to a dimensionless unit.

        Raises if the unit is not dimensionless, so the name stays a label on a
        derived fact rather than a claim that replaces the derivation.
        """
        if not self.is_dimensionless():
            raise UnitError(f"cannot label {self} as {name!r}: not dimensionless")
        return Unit(label=name)

    # -- algebra ---------------------------------------------------------
    def _require_analysable(self, other: "Unit", op: str) -> None:
        for u in (self, other):
            if u.opaque:
                raise UnitError(f"cannot {op} opaque unit {u.opaque!r}")

    def __mul__(self, other: "Unit") -> "Unit":
        self._require_analysable(other, "multiply")
        exps = dict(self.exponents)
        for d, e in other.exponents:
            exps[d] = exps.get(d, 0) + e
        return Unit(_normalize(exps))

    def __truediv__(self, other: "Unit") -> "Unit":
        self._require_analysable(other, "divide")
        exps = dict(self.exponents)
        for d, e in other.exponents:
            exps[d] = exps.get(d, 0) - e
        return Unit(_normalize(exps))

    def is_dimensionless(self) -> bool:
        return not self.opaque and not self.exponents

    # -- display ---------------------------------------------------------
    def __str__(self) -> str:
        if self.opaque:
            return self.opaque
        if not self.exponents:
            return self.label or "1"

        def render(parts: list[tuple[str, int]]) -> str:
            return "-".join(d if e == 1 else f"{d}^{e}" for d, e in parts)

        num = [(d, e) for d, e in self.exponents if e > 0]
        den = [(d, -e) for d, e in self.exponents if e < 0]
        head = render(num) if num else "1"
        return f"{head}/{render(den)}" if den else head

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Unit({str(self)!r})"


PERSON = Unit.parse("person")
YEAR = Unit.parse("year")
PERSON_YEAR = Unit.parse("person-year")
PER_YEAR = Unit.parse("1/year")
PROPORTION = Unit.dimensionless("proportion")
PROBABILITY = Unit.dimensionless("probability")
MIXED = Unit.parse("mixed")
