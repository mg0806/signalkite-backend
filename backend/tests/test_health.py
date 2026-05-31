from services.health import readiness, service_metadata


def test_service_metadata_has_stable_identity() -> None:
    metadata = service_metadata()

    assert metadata["service"] == "signalkite-api"
    assert metadata["version"]
    assert metadata["environment"]
    assert metadata["time_utc"]


def test_readiness_reports_required_checks() -> None:
    status_code, payload = readiness()

    assert status_code in {200, 503}
    assert payload["service"] == "signalkite-api"
    assert {"database", "kite", "notifications", "scheduler"}.issubset(payload["checks"])
