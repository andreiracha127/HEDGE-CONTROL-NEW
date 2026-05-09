from app.services.cashflow_ledger_service import SOURCE_EVENT_TYPE


def test_cashflow_ledger_service_source_event_type_is_stable() -> None:
    assert SOURCE_EVENT_TYPE == "HEDGE_CONTRACT_SETTLED"
