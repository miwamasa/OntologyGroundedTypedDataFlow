"""The state-transition ontology, and the state space it induces.

The ontology is not only a validation table. It determines the shape of the
model: which states exist, which cells of the generator matrix may carry
hazard mass, and therefore how large G(x) is and how a synthetic cohort is
propagated through it. Swapping the YAML swaps the model.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import yaml


@dataclass(frozen=True)
class Transition:
    name: str
    source: str
    target: str
    semantics: str


class OntologyError(ValueError):
    pass


@dataclass(frozen=True)
class StateSpace:
    """The indexed state space a generator matrix is built over.

    Each living state is paired with an absorbing state that records the state
    occupied at the moment of absorption, which is what makes "mean age at
    death by state at death" recoverable from the cohort.
    """

    living: tuple[str, ...]
    absorbing: str

    @cached_property
    def absorbed(self) -> tuple[str, ...]:
        return tuple(f"{self.absorbing}_{s}" for s in self.living)

    @cached_property
    def order(self) -> tuple[str, ...]:
        return self.living + self.absorbed

    @cached_property
    def index(self) -> dict[str, int]:
        return {s: i for i, s in enumerate(self.order)}

    @property
    def size(self) -> int:
        return len(self.order)

    @property
    def n_living(self) -> int:
        return len(self.living)

    def absorbed_from(self, origin: str) -> str:
        if origin not in self.living:
            raise OntologyError(f"{origin!r} is not a living state")
        return f"{self.absorbing}_{origin}"


@dataclass
class Ontology:
    states: dict[str, str]
    transitions: dict[str, Transition]
    absorbing: str
    reference_state: str
    name: str = "ontology"

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        p = Path(path)
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        states = d["states"]
        absorbing = d.get("absorbing", "D")
        if absorbing not in states:
            raise OntologyError(f"absorbing state {absorbing!r} is not declared in states")
        trans = {}
        for k, v in d["transitions"].items():
            src, dst = v["from"], v["to"]
            for s in (src, dst):
                if s not in states:
                    raise OntologyError(f"transition {k}: unknown state {s!r}")
            if src == absorbing:
                raise OntologyError(f"transition {k}: cannot leave absorbing state {absorbing!r}")
            trans[k] = Transition(k, src, dst, v.get("semantics", ""))
        living = tuple(s for s in states if s != absorbing)
        if not living:
            raise OntologyError("ontology declares no living states")
        reference = d.get("reference_state", living[0])
        if reference not in living:
            raise OntologyError(f"reference_state {reference!r} is not a living state")
        return cls(states, trans, absorbing, reference, d.get("name", p.stem))

    # -- induced structure ----------------------------------------------
    @property
    def living_states(self) -> tuple[str, ...]:
        return tuple(s for s in self.states if s != self.absorbing)

    @property
    def state_space(self) -> StateSpace:
        return StateSpace(self.living_states, self.absorbing)

    @property
    def social_transitions(self) -> tuple[Transition, ...]:
        """Licensed transitions between living states, i.e. everything but death."""
        return tuple(t for t in self.transitions.values() if t.target != self.absorbing)

    def is_licensed(self, source: str, target: str) -> bool:
        return any(t.source == source and t.target == target for t in self.transitions.values())

    def validate_transition(self, source: str, target: str) -> None:
        if source not in self.states or target not in self.states:
            raise ValueError(f"unknown state transition {source}->{target}")
        if not self.is_licensed(source, target):
            raise ValueError(f"transition {source}->{target} is not licensed by ontology")

    def describe(self) -> str:
        space = self.state_space
        living = ", ".join(f"{s} {self.states[s]}" for s in space.living)
        edges = ", ".join(f"{t.source}->{t.target}" for t in self.social_transitions)
        return (f"ontology {self.name}: living [{living}]; absorbing {self.absorbing} "
                f"split by origin into {len(space.absorbed)}; "
                f"generator {space.size}x{space.size}; social transitions {edges}")
