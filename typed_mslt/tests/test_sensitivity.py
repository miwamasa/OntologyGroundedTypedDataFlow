"""Estimated is a set of named assumptions, and the sweep varies exactly those."""
from pathlib import Path

import pytest

from mslt.assumptions import (
    ASSUMPTIONS, COHORT_CLOSURE, REMARRIAGE_TAIL, SHARE_EXTRAPOLATION, applicable,
)
from mslt.engine import Engine
from mslt.sensitivity import readout, sweep
from mslt.types import Quality, SemanticType, SemanticTypeError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES = REPO_ROOT / "typed_mslt" / "examples"
NO_DATA = "/nonexistent/data/root"

M2024 = str(EXAMPLES / "male_2024.mslt")
M2020 = str(EXAMPLES / "male_2020_validate.mslt")


def static(program, data_root=NO_DATA):
    return Engine(program, data_root).typecheck()


# --------------------------------------------------------------------------
# The dependency set is derived statically
# --------------------------------------------------------------------------

def test_observed_sources_rest_on_nothing():
    tenv = static(M2024)
    for node in ["deaths", "census", "first_marriage", "divorce", "widowhood", "jmd"]:
        assert tenv[node].depends_on == frozenset(), node
        assert tenv[node].quality is Quality.OBSERVED


def test_each_assumption_enters_where_it_is_introduced():
    tenv = static(M2024)
    assert tenv["remarriage_w"].depends_on == {REMARRIAGE_TAIL}
    assert tenv["share"].depends_on == {SHARE_EXTRAPOLATION}
    # Closing the open age interval is itself a modelling choice.
    assert COHORT_CLOSURE in tenv["life_table"].depends_on
    assert COHORT_CLOSURE not in tenv["probabilities"].depends_on


def test_dependency_accumulates_down_the_pipeline():
    tenv = static(M2024)
    # Death hazards never touch the remarriage table, so they cannot respond
    # to how its open cell is represented.
    assert tenv["death_rate"].depends_on == {SHARE_EXTRAPOLATION}
    assert tenv["social_rate"].depends_on == {SHARE_EXTRAPOLATION, REMARRIAGE_TAIL}
    assert tenv["indicators"].depends_on == {SHARE_EXTRAPOLATION, REMARRIAGE_TAIL, COHORT_CLOSURE}


def test_the_validation_program_rests_on_strictly_fewer_assumptions():
    # It uses observed 2020 shares, so no extrapolation can reach it.
    assert static(M2020)["indicators"].depends_on == {REMARRIAGE_TAIL, COHORT_CLOSURE}
    assert static(M2020)["indicators"].depends_on < static(M2024)["indicators"].depends_on


def test_a_type_may_not_rest_on_assumptions_while_claiming_to_be_observed():
    with pytest.raises(SemanticTypeError, match="declared Observed"):
        SemanticType("MaritalShare", frozenset({"age"}), "proportion", "5y_80plus",
                     quality=Quality.OBSERVED, depends_on={SHARE_EXTRAPOLATION})


def test_every_dependency_the_pipeline_declares_has_a_registered_knob():
    for node, t in static(M2024).items():
        assert t.depends_on <= set(ASSUMPTIONS), node


def test_applicable_selects_only_the_reachable_knobs():
    names = [a.name for a in applicable(static(M2020)["indicators"].depends_on)]
    assert SHARE_EXTRAPOLATION not in names
    assert set(names) == {REMARRIAGE_TAIL, COHORT_CLOSURE}


# --------------------------------------------------------------------------
# Overriding an assumption moves the answer -- and the baseline is unchanged
# --------------------------------------------------------------------------

def _indicators(overrides=None, program=M2024):
    env = Engine(program, str(REPO_ROOT), overrides=overrides).run()
    return readout(env["indicators"])


def test_the_baseline_reproduces_the_published_figures():
    # strength=1.0 is the plain linear extrapolation, so adding the knob left
    # the default numbers untouched.
    base = _indicators()
    assert base["MeanAgeAtDeath/S"] == pytest.approx(76.4759, abs=1e-3)
    assert base["MeanAgeAtDeath/M"] == pytest.approx(82.1565, abs=1e-3)
    assert base["MeanAgeAtDeath/W"] == pytest.approx(90.0119, abs=1e-3)
    assert base["MeanAgeAtDeath/V"] == pytest.approx(75.4200, abs=1e-3)


def test_an_override_at_the_baseline_value_changes_nothing():
    assert _indicators({"extrapolate_share": {"strength": 1.0}}) == _indicators()


def test_the_extrapolation_moves_the_estimate_monotonically():
    """Carrying more of the trend raises the never-married figure, and steadily.

    The trend is toward a larger never-married share at older ages. Extending it
    puts more exposure under S there, which lowers the never-married death
    hazard at those ages and so pushes their deaths later. Married shares move
    the opposite way, and their mean age at death follows.
    """
    s = [_indicators({"extrapolate_share": {"strength": v}})
         for v in (0.0, 0.5, 1.0, 1.5)]
    never_married = [r["MeanAgeAtDeath/S"] for r in s]
    married = [r["MeanAgeAtDeath/M"] for r in s]
    assert never_married == sorted(never_married)
    assert married == sorted(married, reverse=True)
    # The movement is large enough to matter: over two years across the range.
    assert never_married[-1] - never_married[0] > 2.0
    # strength=1.0 is the baseline, so the third point is the published figure.
    assert never_married[2] == pytest.approx(_indicators()["MeanAgeAtDeath/S"])


def test_an_assumption_cannot_move_a_target_that_does_not_depend_on_it():
    # The 2020 program reads observed shares; the extrapolation knob is inert.
    before = _indicators(program=M2020)
    after = _indicators({"extrapolate_share": {"strength": 0.0}}, program=M2020)
    assert before == after


def test_the_source_cache_does_not_change_results():
    cache = {}
    plain = Engine(M2024, str(REPO_ROOT)).run()
    cached = Engine(M2024, str(REPO_ROOT), source_cache=cache).run()
    assert readout(cached["indicators"]) == readout(plain["indicators"])
    assert cache, "the cache should have been populated"
    # A second engine sharing the cache still agrees.
    again = Engine(M2024, str(REPO_ROOT), source_cache=cache).run()
    assert readout(again["indicators"]) == readout(plain["indicators"])


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------

def test_sweep_varies_every_reachable_assumption_and_no_others():
    r = sweep(M2020, str(REPO_ROOT), envelope=False)
    assert set(r["swept"]) == {REMARRIAGE_TAIL, COHORT_CLOSURE}
    assert r["not_applicable"] == [SHARE_EXTRAPOLATION]
    assert r["unregistered"] == []
    assert set(r["one_at_a_time"]) == {REMARRIAGE_TAIL, COHORT_CLOSURE}


def test_sweep_reports_a_span_for_each_indicator():
    r = sweep(M2024, str(REPO_ROOT), envelope=False)
    block = r["one_at_a_time"][SHARE_EXTRAPOLATION]["range"]
    # Extrapolating the marital-share trend moves the never-married figure by
    # more than a year, so it is the assumption that matters most for S.
    assert block["MeanAgeAtDeath/S"]["span"] > 1.0
    for label, span in block.items():
        assert span["min"] <= r["baseline"][label] <= span["max"], label


def test_the_envelope_contains_the_baseline_and_every_one_at_a_time_point():
    r = sweep(M2024, str(REPO_ROOT), envelope=True)
    assert r["envelope"]["combinations"] == 4 * 3 * 3
    for label, span in r["envelope"]["range"].items():
        assert span["min"] <= r["baseline"][label] <= span["max"], label
        for block in r["one_at_a_time"].values():
            oat = block["range"][label]
            assert span["min"] <= oat["min"] and oat["max"] <= span["max"], label


def test_sweeping_an_unknown_node_is_reported():
    with pytest.raises(KeyError, match="no node named"):
        sweep(M2024, str(REPO_ROOT), target="nonexistent", envelope=False)
