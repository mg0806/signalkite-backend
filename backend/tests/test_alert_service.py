from services.alert_service import _condition_met


def test_above_conditions_trigger_at_or_above_target() -> None:
    assert _condition_met("above", 101.0, 100.0)
    assert _condition_met(">=", 100.0, 100.0)
    assert not _condition_met("above", 99.0, 100.0)


def test_below_conditions_trigger_at_or_below_target() -> None:
    assert _condition_met("below", 99.0, 100.0)
    assert _condition_met("<=", 100.0, 100.0)
    assert not _condition_met("below", 101.0, 100.0)


def test_unknown_condition_does_not_trigger() -> None:
    assert not _condition_met("near", 100.0, 100.0)
