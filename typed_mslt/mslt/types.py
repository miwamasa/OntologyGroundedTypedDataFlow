from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional

class Quality(str, Enum):
    OBSERVED = "Observed"
    ESTIMATED = "Estimated"

@dataclass(frozen=True)
class SemanticType:
    kind: str
    dims: FrozenSet[str] = field(default_factory=frozenset)
    unit: str = ""
    age_scheme: str = ""
    universe: str = "JapanesePopulation"
    time_semantics: str = "Period"
    quality: Quality = Quality.OBSERVED
    source_state: Optional[str] = None
    target_state: Optional[str] = None
    note: str = ""

    def with_quality(self, q: Quality, note: str = "") -> "SemanticType":
        return SemanticType(
            self.kind, self.dims, self.unit, self.age_scheme, self.universe,
            self.time_semantics, q, self.source_state, self.target_state,
            note or self.note,
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

def join_quality(*types: SemanticType) -> Quality:
    return Quality.ESTIMATED if any(t.quality == Quality.ESTIMATED for t in types) else Quality.OBSERVED
