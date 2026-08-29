from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional

from .units import Unit, UnitError

class Quality(str, Enum):
    OBSERVED = "Observed"
    ESTIMATED = "Estimated"

@dataclass(frozen=True)
class SemanticType:
    kind: str
    dims: FrozenSet[str] = field(default_factory=frozenset)
    unit: Unit = field(default_factory=Unit)
    age_scheme: str = ""
    universe: str = "JapanesePopulation"
    time_semantics: str = "Period"
    quality: Quality = Quality.OBSERVED
    source_state: Optional[str] = None
    target_state: Optional[str] = None
    note: str = ""
    # The named assumptions this value's number depends on. `quality` says
    # *that* a value is estimated; this says *what it is estimated on*, which
    # is what makes the estimate's sensitivity mechanically analysable: only
    # these knobs can move it, and nothing else can.
    depends_on: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Units may be written as strings at the construction site; normalize
        # them so every type carries a unit the algebra can operate on.
        if not isinstance(self.unit, Unit):
            object.__setattr__(self, "unit", Unit.parse(self.unit))
        if not isinstance(self.depends_on, frozenset):
            object.__setattr__(self, "depends_on", frozenset(self.depends_on))
        if self.depends_on and self.quality is not Quality.ESTIMATED:
            raise SemanticTypeError(
                f"{self.kind}: depends on assumptions {sorted(self.depends_on)} "
                "but is declared Observed"
            )

    def with_quality(self, q: Quality, note: str = "") -> "SemanticType":
        return SemanticType(
            self.kind, self.dims, self.unit, self.age_scheme, self.universe,
            self.time_semantics, q, self.source_state, self.target_state,
            note or self.note, self.depends_on,
        )

    def short(self) -> str:
        q = f"{self.quality.value}<" if self.quality == Quality.ESTIMATED else ""
        close = ">" if q else ""
        tr = ""
        if self.source_state or self.target_state:
            tr = f"<{self.source_state or '?'}->{self.target_state or '?'}>"
        dims = ",".join(sorted(self.dims))
        return f"{q}{self.kind}{tr}[{dims}; {self.age_scheme}; {self.unit}]{close}"

class SemanticTypeError(TypeError):
    pass

def require_kind(t: SemanticType, kind: str, op: str) -> None:
    if t.kind != kind:
        raise SemanticTypeError(f"{op}: expected {kind}, got {t.short()}")

def require_dims(t: SemanticType, dims: set[str], op: str) -> None:
    missing = dims - set(t.dims)
    if missing:
        raise SemanticTypeError(f"{op}: missing dimensions {sorted(missing)} in {t.short()}")

def require_same_universe(a: SemanticType, b: SemanticType, op: str) -> None:
    if a.universe != b.universe:
        raise SemanticTypeError(f"{op}: population-universe mismatch: {a.universe} != {b.universe}")

def require_unit(actual: Unit, expected: Unit, op: str, what: str) -> None:
    """Assert a dimension, naming what was being measured when it disagrees."""
    if actual != expected:
        raise SemanticTypeError(
            f"{op}: {what} must be measured in {expected}, got {actual}"
        )

def require_dimensionless(actual: Unit, op: str, what: str) -> None:
    if not actual.is_dimensionless():
        raise SemanticTypeError(f"{op}: {what} must be dimensionless, got {actual}")

def divide_units(numerator: Unit, denominator: Unit, op: str) -> Unit:
    """Divide two units, reporting a unit failure as a semantic type error."""
    try:
        return numerator / denominator
    except UnitError as e:
        raise SemanticTypeError(f"{op}: {e}") from e

def multiply_units(a: Unit, b: Unit, op: str) -> Unit:
    try:
        return a * b
    except UnitError as e:
        raise SemanticTypeError(f"{op}: {e}") from e

def join_quality(*types: SemanticType) -> Quality:
    return Quality.ESTIMATED if any(t.quality == Quality.ESTIMATED for t in types) else Quality.OBSERVED

def join_depends(*types: SemanticType, adding: FrozenSet[str] | set[str] | None = None) -> FrozenSet[str]:
    """Union the assumption sets of the inputs, plus any this step introduces.

    Dependency flows the same way quality does: a result rests on every
    assumption any of its inputs rested on. Tracking the set rather than a
    single flag is what lets a sensitivity sweep vary exactly the knobs an
    output can respond to.
    """
    out: set[str] = set(adding or ())
    for t in types:
        out |= t.depends_on
    return frozenset(out)
