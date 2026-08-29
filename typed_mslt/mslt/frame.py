from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable
from .types import SemanticType

@dataclass
class SemanticFrame:
    name: str
    type: SemanticType
    rows: list[dict]
    provenance: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def copy(self, *, name: str | None = None, type: SemanticType | None = None, rows=None) -> "SemanticFrame":
        return SemanticFrame(name or self.name, type or self.type, self.rows if rows is None else rows,
                             list(self.provenance), list(self.assumptions))

    def explain(self) -> str:
        q = [f"{self.name}: {self.type.short()}", f"  rows={len(self.rows)}"]
        if self.provenance:
            q.append("  provenance=" + " | ".join(self.provenance))
        if self.assumptions:
            q.append("  assumptions=" + " | ".join(self.assumptions))
        return "\n".join(q)
