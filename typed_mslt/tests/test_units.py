import pytest

from mslt.units import Unit, UnitError, PERSON, YEAR, PERSON_YEAR, PER_YEAR


def test_parses_the_units_the_pipeline_actually_uses():
    assert Unit.parse("person") == PERSON
    assert Unit.parse("persons") == PERSON
    assert Unit.parse("person-year") == PERSON_YEAR
    assert Unit.parse("1/year") == PER_YEAR
    assert Unit.parse("proportion").is_dimensionless()
    assert Unit.parse("probability").is_dimensionless()


def test_an_event_count_is_dimensionally_a_person_count():
    # An occurrence-exposure numerator counts the persons who experienced the
    # event, which is what makes both hazard paths derive to 1/year.
    assert Unit.parse("event") == PERSON


def test_occurrence_exposure_rate_derives_to_per_year():
    assert PERSON / PERSON_YEAR == PER_YEAR


def test_dividing_a_count_by_a_head_count_is_not_a_rate():
    # The classic person vs person-year error: the result is dimensionless,
    # so it cannot be a hazard.
    assert (PERSON / PERSON).is_dimensionless()
    assert PERSON / PERSON != PER_YEAR


def test_generator_times_an_interval_is_dimensionless():
    assert (PER_YEAR * YEAR).is_dimensionless()


def test_share_times_exposure_stays_person_years():
    assert PERSON_YEAR * Unit.parse("proportion") == PERSON_YEAR


def test_round_trips_through_display():
    for text in ["person", "person-year", "1/year", "year"]:
        assert str(Unit.parse(text)) == text


def test_dimensionless_units_compare_equal_but_keep_their_names():
    assert Unit.parse("proportion") == Unit.parse("probability")
    assert str(Unit.parse("proportion")) == "proportion"
    assert str(Unit.parse("probability")) == "probability"


def test_label_is_only_allowed_on_a_dimensionless_unit():
    assert str((PERSON / PERSON).labeled("proportion")) == "proportion"
    with pytest.raises(UnitError):
        PER_YEAR.labeled("proportion")


def test_unknown_dimension_is_rejected():
    with pytest.raises(UnitError):
        Unit.parse("household-year")


def test_opaque_units_refuse_dimensional_arithmetic():
    mixed = Unit.parse("mixed")
    assert str(mixed) == "mixed"
    with pytest.raises(UnitError):
        mixed * PERSON


def test_units_are_hashable_so_semantic_types_stay_frozen():
    assert len({Unit.parse("person"), PERSON, Unit.parse("persons")}) == 1
