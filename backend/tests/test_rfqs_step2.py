import uuid
from datetime import datetime, timezone
from decimal import Decimal


def _create_counterparty(
    client, name: str = "CP-Step2", phone: str | None = None
) -> str:
    """Create a counterparty with whatsapp_phone and return its UUID."""
    if phone is None:
        phone = f"+55119999{uuid.uuid4().int % 10_000:04d}"
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": f"{name}-{uuid.uuid4().hex[:6]}",
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_trade_rfq(client, direction: str, cp_id: str | None = None) -> str:
    if cp_id is None:
        cp_id = _create_counterparty(client)
    response = client.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": direction,
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "SENT"
    return response.json()["id"]


def _create_spread_rfq(client, buy_trade_id: str, sell_trade_id: str) -> str:
    response = client.post(
        "/rfqs",
        json={
            "intent": "SPREAD",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "buy_trade_id": buy_trade_id,
            "sell_trade_id": sell_trade_id,
            "invitations": [],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_quote(client, rfq_id: str, payload: dict):
    return client.post(f"/rfqs/{rfq_id}/quotes", json=payload)


def _quote_payload(rfq_id: str, cp_id: str, price: str, unit: str = "USD/MT") -> dict:
    return {
        "rfq_id": rfq_id,
        "counterparty_id": cp_id,
        "fixed_price_value": price,
        "fixed_price_unit": unit,
        "float_pricing_convention": "avg",
        "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
    }


def _get_rfq(client, rfq_id: str) -> dict:
    response = client.get(f"/rfqs/{rfq_id}")
    assert response.status_code == 200
    return response.json()


def _get_ranking(client, rfq_id: str):
    return client.get(f"/rfqs/{rfq_id}/ranking")


def _get_trade_ranking(client, rfq_id: str):
    return client.get(f"/rfqs/{rfq_id}/trade-ranking")


def test_incomplete_quote_is_rejected(client) -> None:
    cp_id = _create_counterparty(client)
    trade_rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_id)
    response = _create_quote(
        client,
        trade_rfq_id,
        {
            "rfq_id": trade_rfq_id,
            "counterparty_id": cp_id,
            "fixed_price_value": "100.000000",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 422


def test_first_quote_transitions_rfq_to_quoted(client) -> None:
    cp_id = _create_counterparty(client)
    trade_rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_id)
    assert _get_rfq(client, trade_rfq_id)["state"] == "SENT"

    response = _create_quote(
        client,
        trade_rfq_id,
        _quote_payload(trade_rfq_id, cp_id, "100.000000"),
    )
    assert response.status_code == 201
    assert _get_rfq(client, trade_rfq_id)["state"] == "QUOTED"


def test_quote_payload_rejects_non_uuid_counterparty(client) -> None:
    """J-A2-OPUS-05: counterparty_id is a UUID at the schema boundary.

    The model-level FK to ``counterparties.id`` is enforced by migration 033
    at the Postgres layer (preflight + ``ondelete=RESTRICT``); SQLite does
    not enforce FKs by default, so this test asserts only the Pydantic
    boundary rejection. The migration preflight covers the database side.
    """
    cp_id = _create_counterparty(client)
    trade_rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_id)

    response = _create_quote(
        client,
        trade_rfq_id,
        _quote_payload(trade_rfq_id, "not-a-uuid", "100.000000"),
    )
    assert response.status_code == 422
    assert _get_rfq(client, trade_rfq_id)["state"] == "SENT"


def test_quote_payload_rejects_unknown_counterparty_uuid(client) -> None:
    """A syntactically valid UUID for a counterparty that doesn't exist must
    be rejected at the application layer with a controlled 404, rather than
    propagating to the database and surfacing as an unhandled
    ``IntegrityError`` (HTTP 500) from the FK added in migration 033.

    SQLite does not enforce the FK in tests, so without the application
    check this insert would silently succeed locally and only blow up in
    production Postgres.
    """
    cp_id = _create_counterparty(client)
    trade_rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_id)

    unknown_cp = "00000000-0000-0000-0000-000000000000"
    response = _create_quote(
        client,
        trade_rfq_id,
        _quote_payload(trade_rfq_id, unknown_cp, "100.000000"),
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    assert _get_rfq(client, trade_rfq_id)["state"] == "SENT"


def test_spread_ranking_descending_and_ignores_missing_counterparty(client) -> None:
    cp1 = _create_counterparty(client, "CP1")
    cp2 = _create_counterparty(client, "CP2")
    cp3 = _create_counterparty(client, "CP3")

    buy_trade_id = _create_trade_rfq(client, "BUY", cp_id=cp1)
    sell_trade_id = _create_trade_rfq(client, "SELL", cp_id=cp1)
    spread_rfq_id = _create_spread_rfq(client, buy_trade_id, sell_trade_id)

    # CP1 spread = 110 - 100 = 10
    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp1, "100.000000"))
    _create_quote(
        client,
        sell_trade_id,
        _quote_payload(sell_trade_id, cp1, "110.000000", unit="usd-mt"),
    )

    # CP2 spread = 115 - 102 = 13
    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp2, "102.000000"))
    _create_quote(
        client,
        sell_trade_id,
        _quote_payload(sell_trade_id, cp2, "115.000000", unit="USDMT"),
    )

    # CP3 only quotes one side -> ignored
    _create_quote(
        client, sell_trade_id, _quote_payload(sell_trade_id, cp3, "150.000000")
    )

    ranking = _get_ranking(client, spread_rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "SUCCESS"
    assert payload["failure_code"] is None

    data = payload["ranking"]
    assert data[0]["counterparty_id"] == cp2
    assert Decimal(data[0]["spread_value"]) == Decimal("13.000000")
    assert data[1]["counterparty_id"] == cp1
    assert Decimal(data[1]["spread_value"]) == Decimal("10.000000")


def test_spread_ranking_zero_eligible_quotes_returns_failure_payload(client) -> None:
    cp1 = _create_counterparty(client, "CP1")
    buy_trade_id = _create_trade_rfq(client, "BUY", cp_id=cp1)
    sell_trade_id = _create_trade_rfq(client, "SELL", cp_id=cp1)
    spread_rfq_id = _create_spread_rfq(client, buy_trade_id, sell_trade_id)

    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp1, "100.000000"))

    ranking = _get_ranking(client, spread_rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "FAILURE"
    assert payload["failure_code"] == "NO_ELIGIBLE_QUOTES"
    assert payload["ranking"] == []


def test_spread_ranking_non_canonical_unit_fails(client) -> None:
    cp1 = _create_counterparty(client, "CP1")
    buy_trade_id = _create_trade_rfq(client, "BUY", cp_id=cp1)
    sell_trade_id = _create_trade_rfq(client, "SELL", cp_id=cp1)
    spread_rfq_id = _create_spread_rfq(client, buy_trade_id, sell_trade_id)

    _create_quote(
        client,
        buy_trade_id,
        _quote_payload(buy_trade_id, cp1, "100.000000", unit="USD/KG"),
    )
    _create_quote(client, sell_trade_id, _quote_payload(sell_trade_id, cp1, "110.000000"))

    ranking = _get_ranking(client, spread_rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "FAILURE"
    assert payload["failure_code"] == "NON_COMPARABLE"


def test_spread_ranking_tie_fails(client) -> None:
    cp1 = _create_counterparty(client, "CP1")
    cp2 = _create_counterparty(client, "CP2")
    buy_trade_id = _create_trade_rfq(client, "BUY", cp_id=cp1)
    sell_trade_id = _create_trade_rfq(client, "SELL", cp_id=cp1)
    spread_rfq_id = _create_spread_rfq(client, buy_trade_id, sell_trade_id)

    # CP1 spread = 10
    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp1, "100.000000"))
    _create_quote(client, sell_trade_id, _quote_payload(sell_trade_id, cp1, "110.000000"))

    # CP2 spread = 10 (tie)
    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp2, "105.000000"))
    _create_quote(client, sell_trade_id, _quote_payload(sell_trade_id, cp2, "115.000000"))

    ranking = _get_ranking(client, spread_rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "FAILURE"
    assert payload["failure_code"] == "TIE"


# ─────────────────────────────────────────────────────────────────────────
# Phase A2 PR-1 — Decimal substrate adversarial tests (J-A2-02)
# ─────────────────────────────────────────────────────────────────────────


def test_trade_ranking_disambiguates_within_storage_precision(client) -> None:
    """Two prices that differ in the 6th decimal rank distinctly under Decimal.

    The pre-PR-1 path coerced quote prices to float64 before sorting and
    tie-detection. At scale 6 the float64 representations of 100.000001 and
    100.000002 happen to remain distinct, but the Decimal equality used here
    is exact regardless of whatever the float round-trip would have done.
    """
    cp_a = _create_counterparty(client, "CP-A")
    cp_b = _create_counterparty(client, "CP-B")
    rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_a)

    _create_quote(client, rfq_id, _quote_payload(rfq_id, cp_a, "100.000001"))
    _create_quote(client, rfq_id, _quote_payload(rfq_id, cp_b, "100.000002"))

    ranking = _get_trade_ranking(client, rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "SUCCESS"
    assert len(payload["ranking"]) == 2
    # BUY direction → ascending, lowest price ranked first
    assert payload["ranking"][0]["quote"]["counterparty_id"] == cp_a
    assert Decimal(payload["ranking"][0]["quote"]["fixed_price_value"]) == Decimal(
        "100.000001"
    )


def test_trade_ranking_unit_disambiguates_pair_that_collides_in_float64() -> None:
    """At magnitudes where float64 cannot resolve 6 decimal places, two
    Decimals would have collapsed into a spurious TIE under the pre-PR-1
    ``set(float(...))`` tie detector. The Decimal sort path preserves the
    distinction.

    Exercised at the service layer rather than through the API to bypass
    the test sqlite ``NUMERIC`` affinity, which stores values as float64
    and would itself collapse the pair before ranking sees them.
    Postgres ``Numeric(18, 6)`` storage preserves the distinction in prod.
    """
    from datetime import datetime as _dt, timezone as _tz
    from app.models.quotes import RFQQuote
    from app.models.rfqs import RFQ, RFQDirection, RFQIntent, RFQState
    from app.services.rfq_service import RFQService

    a = Decimal("100000000000.000001")
    b = Decimal("100000000000.000002")
    assert float(a) == float(b)
    assert a != b

    rfq_uuid = uuid.uuid4()
    rfq = RFQ(
        id=rfq_uuid,
        rfq_number="RFQ-UNIT-0001",
        intent=RFQIntent.global_position,
        commodity="LME_AL",
        quantity_mt=Decimal("1.000"),
        delivery_window_start=_dt(2026, 3, 1).date(),
        delivery_window_end=_dt(2026, 3, 31).date(),
        direction=RFQDirection.buy,
        commercial_active_mt=Decimal("0.000"),
        commercial_passive_mt=Decimal("0.000"),
        commercial_net_mt=Decimal("0.000"),
        commercial_reduction_applied_mt=Decimal("0.000"),
        exposure_snapshot_timestamp=_dt(2026, 3, 1, tzinfo=_tz.utc),
        state=RFQState.quoted,
    )
    cp_a, cp_b = uuid.uuid4(), uuid.uuid4()
    received = _dt(2026, 3, 1, tzinfo=_tz.utc)
    quote_a = RFQQuote(
        id=uuid.uuid4(),
        rfq_id=rfq_uuid,
        counterparty_id=cp_a,
        fixed_price_value=a,
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        received_at=received,
        created_at=received,
    )
    quote_b = RFQQuote(
        id=uuid.uuid4(),
        rfq_id=rfq_uuid,
        counterparty_id=cp_b,
        fixed_price_value=b,
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        received_at=received,
        created_at=received,
    )

    ranking = RFQService.compute_trade_ranking(rfq, {cp_a: quote_a, cp_b: quote_b})
    assert ranking.status == "SUCCESS"
    assert [entry.quote.counterparty_id for entry in ranking.ranking] == [cp_a, cp_b]
    assert ranking.ranking[0].quote.fixed_price_value == a
    assert ranking.ranking[1].quote.fixed_price_value == b


def test_trade_ranking_true_tie_detected_under_decimal(client) -> None:
    cp_a = _create_counterparty(client, "CP-A")
    cp_b = _create_counterparty(client, "CP-B")
    rfq_id = _create_trade_rfq(client, "BUY", cp_id=cp_a)

    _create_quote(client, rfq_id, _quote_payload(rfq_id, cp_a, "100.123456"))
    _create_quote(client, rfq_id, _quote_payload(rfq_id, cp_b, "100.123456"))

    ranking = _get_trade_ranking(client, rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "FAILURE"
    assert payload["failure_code"] == "TIE"


def test_spread_arithmetic_is_exact_on_decimals(client) -> None:
    """`Decimal("100.000003") - Decimal("99.999998")` is exactly `0.000005`.

    Under float64 the same subtraction drifts at ~5e-6 + epsilon. The
    ranking surface should reflect the exact value.
    """
    cp = _create_counterparty(client, "CP-Exact")
    buy_trade_id = _create_trade_rfq(client, "BUY", cp_id=cp)
    sell_trade_id = _create_trade_rfq(client, "SELL", cp_id=cp)
    spread_rfq_id = _create_spread_rfq(client, buy_trade_id, sell_trade_id)

    _create_quote(client, buy_trade_id, _quote_payload(buy_trade_id, cp, "99.999998"))
    _create_quote(client, sell_trade_id, _quote_payload(sell_trade_id, cp, "100.000003"))

    ranking = _get_ranking(client, spread_rfq_id)
    assert ranking.status_code == 200
    payload = ranking.json()
    assert payload["status"] == "SUCCESS"
    assert Decimal(payload["ranking"][0]["spread_value"]) == Decimal("0.000005")
