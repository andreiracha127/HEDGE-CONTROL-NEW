"""Unit tests for cashflow projection routes."""

from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.models.orders import Order, OrderType, PriceType


def test_projection_route_translates_PriceReferenceUnprovable_to_424(client: TestClient, session) -> None:
    # Insert an order for a commodity that has NO seeded settlement
    o = Order(
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        commodity="ALUMINUM",
        quantity_mt=10,
        delivery_date_end=date.today() + timedelta(days=1),
    )
    session.add(o)
    session.commit()

    # Call the route
    response = client.get(f"/cashflow/projection?as_of_date={date.today().isoformat()}")

    # Assert 424 Failed Dependency
    assert response.status_code == 424
    assert "cash settlement" in response.text.lower()


def test_projection_route_translates_unmapped_commodity_to_424(client: TestClient, session) -> None:
    # Insert an order for a commodity that has no mapping in COMMODITY_SYMBOL_MAP
    o = Order(
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        commodity="RARE_EARTH",
        quantity_mt=10,
        delivery_date_end=date.today() + timedelta(days=1),
    )
    session.add(o)
    session.commit()

    # Call the route
    response = client.get(f"/cashflow/projection?as_of_date={date.today().isoformat()}")

    # Assert 424 Failed Dependency
    assert response.status_code == 424
    assert "no price-symbol mapping" in response.text.lower() or "cannot project" in response.text.lower()
