from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class Transition:
    name: str
    source: str
    target: str
    semantics: str

@dataclass
class Ontology:
    states: dict[str, str]
    transitions: dict[str, Transition]
    absorbing: str

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        trans = {
            k: Transition(k, v["from"], v["to"], v.get("semantics", ""))
            for k, v in d["transitions"].items()
        }
        return cls(d["states"], trans, d.get("absorbing", "D"))

    def validate_transition(self, source: str, target: str) -> None:
        if source not in self.states or target not in self.states:
            raise ValueError(f"unknown state transition {source}->{target}")
        if not any(t.source == source and t.target == target for t in self.transitions.values()):
            raise ValueError(f"transition {source}->{target} is not licensed by ontology")
