"""Market-data governance checks."""

from __future__ import annotations

from datetime import date, timedelta

from backend.tests.e2e._fixtures import seed_westmetall_prices, trace_id_factory
from backend.tests.e2e._personas import as_auditor, as_risk_manager, as_service


def test_canonical_westmetall_prices_are_readable_by_risk_manager() -> None:
    today = date.today()
    seed_westmetall_prices(trace_id_factory(), today, today)
    with as_risk_manager() as client:
        response = client.get(
            "/market-data/westmetall/aluminum/cash-settlement/prices",
            params={"start_date": today.isoformat(), "end_date": today.isoformat()},
        )
        assert response.status_code == 200, response.text
        assert response.json()[0]["is_canonical"] is True


def test_auditor_can_read_canonical_market_data() -> None:
    today = date.today()
    seed_westmetall_prices(trace_id_factory(), today, today)
    with as_auditor() as client:
        response = client.get(
            "/market-data/westmetall/aluminum/cash-settlement/prices",
            params={"start_date": today.isoformat(), "end_date": today.isoformat()},
        )
        assert response.status_code == 200, response.text


def test_service_identity_cannot_read_human_market_data_surface() -> None:
    with as_service("service:westmetall_ingest") as client:
        response = client.get("/market-data/westmetall/aluminum/cash-settlement/prices")
        assert response.status_code in (401, 403)


def test_price_seed_is_idempotent_for_same_date() -> None:
    today = date.today() - timedelta(days=1)
    trace_id = trace_id_factory()
    first = seed_westmetall_prices(trace_id, today, today)
    second = seed_westmetall_prices(trace_id, today, today)
    assert first == second == 1
