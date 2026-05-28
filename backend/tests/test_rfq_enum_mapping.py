from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.models.rfqs import RFQ, RFQDirection, RFQIntent, RFQState, RFQStateEvent


def test_rfq_enums_bind_database_values_not_python_member_names() -> None:
    assert RFQ.__table__.c.intent.type.enums == [member.value for member in RFQIntent]
    assert RFQ.__table__.c.direction.type.enums == [member.value for member in RFQDirection]
    assert RFQ.__table__.c.state.type.enums == [member.value for member in RFQState]
    assert RFQStateEvent.__table__.c.from_state.type.enums == [
        member.value for member in RFQState
    ]
    assert RFQStateEvent.__table__.c.to_state.type.enums == [
        member.value for member in RFQState
    ]


def test_order_enums_bind_database_values_not_python_member_names() -> None:
    assert Order.__table__.c.order_type.type.enums == [member.value for member in OrderType]
    assert Order.__table__.c.pricing_convention.type.enums == [
        member.value for member in OrderPricingConvention
    ]


def test_order_pricing_convention_normalizes_legacy_string_assignment() -> None:
    order = Order(
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        commodity="LME_AL",
        quantity_mt=1,
        pricing_convention="avg",
        avg_entry_price=1,
    )

    assert order.pricing_convention is OrderPricingConvention.avg
