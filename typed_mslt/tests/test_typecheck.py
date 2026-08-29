from pathlib import Path

import pytest

from mslt.engine import Engine
from mslt.transforms import sig_death_hazard, sig_partition_exposure, sig_transition_probabilities
from mslt.types import SemanticType, SemanticTypeError, Quality
from mslt.units import PER_YEAR, PERSON_YEAR

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES = REPO_ROOT / "typed_mslt" / "examples"

# A data root that does not exist: type checking must never touch it.
NO_DATA = "/nonexistent/data/root"


def typecheck(program: str, data_root: str = NO_DATA):
    return Engine(str(EXAMPLES / program), data_root).typecheck()


def test_typechecks_without_reading_any_data_file():
    tenv = typecheck("male_2024.mslt")
    assert len(tenv) == 16
    assert tenv["indicators"].kind == "LifeCourseIndicator"


def test_rejects_an_ill_typed_program_without_reading_any_data_file():
    with pytest.raises(SemanticTypeError, match="expected Exposure"):
        typecheck("type_error_demo.mslt")


def test_units_are_derived_along_the_whole_pipeline():
    tenv = typecheck("male_2024.mslt")
    assert str(tenv["jmd"].unit) == "person-year"
    assert str(tenv["share"].unit) == "proportion"
    assert str(tenv["state_exposure"].unit) == "person-year"
    # 1/year is computed as person / person-year, not asserted by the author.
    assert tenv["death_rate"].unit == PER_YEAR
    assert tenv["social_rate"].unit == PER_YEAR
    assert tenv["probabilities"].unit.is_dimensionless()


def test_estimated_quality_propagates_from_the_extrapolated_share():
    tenv = typecheck("male_2024.mslt")
    assert tenv["census"].quality == Quality.OBSERVED
    assert tenv["jmd"].quality == Quality.OBSERVED
    for node in ["share", "state_exposure", "death_rate", "generator", "life_table", "indicators"]:
        assert tenv[node].quality == Quality.ESTIMATED, node


def test_the_2020_validation_pipeline_keeps_observed_shares():
    tenv = typecheck("male_2020_validate.mslt")
    assert tenv["share"].quality == Quality.OBSERVED
    # Remarriage is still estimated, so the social hazards and everything past
    # them remain estimated even without the extrapolation.
    assert tenv["social_rate"].quality == Quality.ESTIMATED


def test_checker_and_evaluator_agree_on_every_type():
    """The signatures are shared, so a run can never produce a type that check did not."""
    e = Engine(str(EXAMPLES / "male_2024.mslt"), str(REPO_ROOT))
    static = Engine(str(EXAMPLES / "male_2024.mslt"), NO_DATA).typecheck()
    for name, frame in e.run().items():
        assert frame.type == static[name], name


# --------------------------------------------------------------------------
# Errors the unit algebra catches that a check on `kind` alone cannot.
# --------------------------------------------------------------------------

def _exposure(unit: str) -> SemanticType:
    return SemanticType("Exposure", frozenset({"year", "sex", "age"}), unit, "5y_80plus")


def _state_exposure(unit: str) -> SemanticType:
    return SemanticType("StateExposure", frozenset({"year", "sex", "age", "state"}), unit, "5y_80plus")


def _share() -> SemanticType:
    return SemanticType("MaritalShare", frozenset({"year", "sex", "age", "state"}), "proportion", "5y_80plus")


def _deaths() -> SemanticType:
    return SemanticType("DeathCount", frozenset({"year", "sex", "age", "state"}), "person", "5y_80plus")


def test_a_head_count_offered_as_exposure_is_rejected():
    # Right kind, wrong dimension: person instead of person-year.
    with pytest.raises(SemanticTypeError, match="person-year"):
        sig_partition_exposure(_exposure("person"), _share(), year=2024, sex="male")


def test_dividing_deaths_by_a_head_count_is_not_a_hazard():
    with pytest.raises(SemanticTypeError, match="person-year"):
        sig_death_hazard(_deaths(), _state_exposure("person"), year=2024, sex="male")


def test_a_correct_denominator_yields_a_per_year_hazard():
    t = sig_death_hazard(_deaths(), _state_exposure("person-year"), year=2024, sex="male")
    assert t.unit == PER_YEAR
    assert t.target_state == "D"


def test_exponentiating_a_generator_that_is_not_a_rate_is_rejected():
    bad = SemanticType("GeneratorMatrix", frozenset({"year", "sex", "age"}), "person", "5y_80plus")
    with pytest.raises(SemanticTypeError, match="dimensionless"):
        sig_transition_probabilities(bad, interval_years=5.0)


def test_partition_exposure_still_requires_a_matching_universe():
    other = SemanticType("MaritalShare", frozenset({"year", "sex", "age", "state"}), "proportion",
                         "5y_80plus", universe="SwedishPopulation")
    with pytest.raises(SemanticTypeError, match="universe"):
        sig_partition_exposure(_exposure(PERSON_YEAR), other, year=2024, sex="male")
