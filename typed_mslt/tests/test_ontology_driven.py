"""The ontology determines the model's shape, not just its validity."""
from pathlib import Path

import numpy as np
import pytest

from mslt.engine import Engine
from mslt.frame import SemanticFrame
from mslt.ontology import Ontology, OntologyError
from mslt.transforms import (
    generator_matrix, indicators, multistate_life_table, sig_multistate_life_table,
    transition_probabilities,
)
from mslt.types import SemanticType, SemanticTypeError
from mslt.utils import CANON_BANDS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TYPED = REPO_ROOT / "typed_mslt"
EXAMPLES = TYPED / "examples"
ONTOLOGIES = TYPED / "ontology"
NO_DATA = "/nonexistent/data/root"

MARITAL = ONTOLOGIES / "marital.yaml"
NO_REMARRIAGE = ONTOLOGIES / "marital_absorbing_dissolution.yaml"


# --------------------------------------------------------------------------
# The state space is read off the ontology
# --------------------------------------------------------------------------

def test_state_space_is_derived_from_the_ontology():
    space = Ontology.load(MARITAL).state_space
    assert space.living == ("S", "M", "W", "V")
    # Death is split by the state it was reached from, so mean age at death
    # stays attributable to a marital status.
    assert space.absorbed == ("D_S", "D_M", "D_W", "D_V")
    assert space.size == 8
    assert space.index["S"] == 0 and space.index["D_S"] == 4
    assert space.absorbed_from("M") == "D_M"


def test_social_transitions_exclude_death():
    ont = Ontology.load(MARITAL)
    assert {(t.source, t.target) for t in ont.social_transitions} == {
        ("S", "M"), ("M", "W"), ("M", "V"), ("W", "M"), ("V", "M"),
    }


def test_dropping_edges_changes_what_the_model_licenses():
    full, reduced = Ontology.load(MARITAL), Ontology.load(NO_REMARRIAGE)
    assert full.is_licensed("W", "M")
    assert not reduced.is_licensed("W", "M")
    # Same states, so the same matrix shape; a different set of legal cells.
    assert full.state_space.size == reduced.state_space.size == 8
    assert len(reduced.social_transitions) == len(full.social_transitions) - 2


# --------------------------------------------------------------------------
# Unlicensed transitions are rejected before any data is read
# --------------------------------------------------------------------------

def test_a_program_using_an_unlicensed_transition_fails_to_typecheck():
    e = Engine(str(EXAMPLES / "male_2024.mslt"), NO_DATA, str(NO_REMARRIAGE))
    with pytest.raises(SemanticTypeError, match=r"W->M is not licensed"):
        e.typecheck()


def test_the_same_program_typechecks_against_the_full_ontology():
    tenv = Engine(str(EXAMPLES / "male_2024.mslt"), NO_DATA, str(MARITAL)).typecheck()
    assert tenv["indicators"].kind == "LifeCourseIndicator"


def test_an_initial_state_outside_the_ontology_is_rejected():
    probabilities = SemanticType("TransitionMatrix", frozenset({"year", "sex", "age"}),
                                 "probability", "5y_80plus", time_semantics="Interval")
    ont = Ontology.load(MARITAL)
    with pytest.raises(SemanticTypeError, match="not a living state"):
        sig_multistate_life_table(probabilities, initial_state="D", ontology=ont)
    with pytest.raises(SemanticTypeError, match="not a living state"):
        sig_multistate_life_table(probabilities, initial_state="Cohabiting", ontology=ont)


def test_generator_rejects_a_hazard_on_an_unlicensed_edge():
    ont = Ontology.load(MARITAL)
    # S->W is not licensed: nobody is widowed without having married.
    hazards = _hazard_frame([("S", "W", 0.1)])
    with pytest.raises(SemanticTypeError, match=r"S->W is not licensed"):
        generator_matrix(_hazard_frame([]), hazards, year=2024, sex="male", ontology=ont)


def _hazard_frame(edges, year=2024, sex="male"):
    t = SemanticType("HazardRate", frozenset({"year", "sex", "age", "from_state", "to_state"}),
                     "1/year", "5y_80plus")
    rows = [{"year": year, "sex": sex, "age": "30-34", "from_state": s, "to_state": d, "value": v}
            for s, d, v in edges]
    return SemanticFrame("hazards", t, rows)


# --------------------------------------------------------------------------
# Ontology files are validated on load
# --------------------------------------------------------------------------

def _write(tmp_path, text):
    p = tmp_path / "ont.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_absorbing_state_must_be_declared(tmp_path):
    with pytest.raises(OntologyError, match="absorbing state"):
        Ontology.load(_write(tmp_path, "states: {A: Alive}\nabsorbing: Z\ntransitions: {}\n"))


def test_transitions_may_not_name_unknown_states(tmp_path):
    with pytest.raises(OntologyError, match="unknown state"):
        Ontology.load(_write(tmp_path,
            "states: {A: Alive, D: Dead}\nabsorbing: D\n"
            "transitions: {t: {from: A, to: Q}}\n"))


def test_nothing_may_leave_the_absorbing_state(tmp_path):
    with pytest.raises(OntologyError, match="cannot leave absorbing"):
        Ontology.load(_write(tmp_path,
            "states: {A: Alive, D: Dead}\nabsorbing: D\n"
            "transitions: {t: {from: D, to: A}}\n"))


def test_reference_state_must_be_a_living_state(tmp_path):
    with pytest.raises(OntologyError, match="reference_state"):
        Ontology.load(_write(tmp_path,
            "states: {A: Alive, D: Dead}\nabsorbing: D\nreference_state: D\n"
            "transitions: {d: {from: A, to: D}}\n"))


# --------------------------------------------------------------------------
# The machinery is not marital-specific
# --------------------------------------------------------------------------

HEALTH = """
name: health
states:
  H: Healthy
  C: NeedingCare
  D: Dead
absorbing: D
reference_state: H
transitions:
  onset: {from: H, to: C, semantics: "onset of care need"}
  recovery: {from: C, to: H, semantics: "recovery"}
  death_H: {from: H, to: D}
  death_C: {from: C, to: D}
"""


def test_a_two_living_state_ontology_yields_a_four_by_four_generator(tmp_path):
    ont = Ontology.load(_write(tmp_path, HEALTH))
    space = ont.state_space
    assert space.living == ("H", "C")
    assert space.absorbed == ("D_H", "D_C")
    assert space.size == 4

    death = _hazard_frame([("H", "D", 0.01), ("C", "D", 0.10)])
    social = _hazard_frame([("H", "C", 0.05), ("C", "H", 0.20)])
    g = generator_matrix(death, social, year=2024, sex="male", ontology=ont)
    G = np.asarray(next(r["matrix"] for r in g.rows if r["age"] == "30-34"))

    assert G.shape == (4, 4)
    # Rows of a generator sum to zero, and the death of a healthy member lands
    # in the absorbing state that remembers "healthy".
    assert np.allclose(G.sum(axis=1), 0)
    assert G[space.index["H"], space.index["D_H"]] == pytest.approx(0.01)
    assert G[space.index["C"], space.index["D_C"]] == pytest.approx(0.10)
    assert G[space.index["H"], space.index["C"]] == pytest.approx(0.05)
    # An unlicensed cell stays empty: there is no H -> D_C edge.
    assert G[space.index["H"], space.index["D_C"]] == 0


def test_the_whole_pipeline_runs_on_a_non_marital_ontology(tmp_path):
    ont = Ontology.load(_write(tmp_path, HEALTH))
    # Same hazards in every age band, so the cohort is closed by the 80+ rule.
    death = _hazard_frame_all_bands([("H", "D", 0.02), ("C", "D", 0.12)])
    social = _hazard_frame_all_bands([("H", "C", 0.04), ("C", "H", 0.15)])

    g = generator_matrix(death, social, year=2024, sex="male", ontology=ont)
    p = transition_probabilities(g, interval_years=5.0)
    lt = multistate_life_table(p, start_age=15, initial_state="H", radix=100000,
                               max_age=120, ontology=ont)
    ind = indicators(lt, ontology=ont)

    assert lt.rows and {"live_H", "live_C", "death_H", "death_C"} <= set(lt.rows[0])
    reported = {(r["indicator"], r["state"]) for r in ind.rows}
    assert ("MeanAgeAtDeath", "H") in reported
    assert ("MeanAgeAtDeath", "C") in reported
    # The contrast state is named after the ontology's reference state.
    assert ("MeanAgeAtDeath", "NON_H") in reported
    assert ("DeathShare", "H") in reported
    # The cohort starts wholly healthy, so a member must first pass through
    # onset before they can die needing care. Deaths in C therefore fall later
    # than deaths in H despite C's higher mortality -- the same selection effect
    # that makes widowhood the oldest mean age at death in the marital model.
    mean = {r["state"]: r["value"] for r in ind.rows if r["indicator"] == "MeanAgeAtDeath"}
    assert mean["C"] > mean["H"]


def _hazard_frame_all_bands(edges, year=2024, sex="male"):
    t = SemanticType("HazardRate", frozenset({"year", "sex", "age", "from_state", "to_state"}),
                     "1/year", "5y_80plus")
    rows = [{"year": year, "sex": sex, "age": band, "from_state": s, "to_state": d, "value": v}
            for band in CANON_BANDS for s, d, v in edges]
    return SemanticFrame("hazards", t, rows)


# --------------------------------------------------------------------------
# Selecting the ontology
# --------------------------------------------------------------------------

def test_a_program_may_declare_its_own_ontology(tmp_path):
    program = tmp_path / "p.mslt"
    program.write_text(
        'pipeline declares_ontology\n'
        f'set ontology = "{NO_REMARRIAGE}"\n'
        'source census :: MaritalPopulation = estat_census5("x.csv")\n',
        encoding="utf-8")
    assert Engine(str(program), NO_DATA).ontology.name == "marital_absorbing_dissolution"


def test_an_explicit_ontology_argument_wins():
    e = Engine(str(EXAMPLES / "male_2024.mslt"), NO_DATA, str(NO_REMARRIAGE))
    assert e.ontology.name == "marital_absorbing_dissolution"
    assert Engine(str(EXAMPLES / "male_2024.mslt"), NO_DATA).ontology.name == "marital"


def test_describe_reports_the_induced_model_shape():
    text = Ontology.load(MARITAL).describe()
    assert "generator 8x8" in text
    assert "S->M" in text
