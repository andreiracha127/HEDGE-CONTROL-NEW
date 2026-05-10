from __future__ import annotations

import json
import os
from datetime import date, timedelta

from locust import HttpUser, between, task


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


LEDGER_CONTRACT_ID = _env("LOCUST_LEDGER_CONTRACT_ID", "00000000-0000-0000-0000-000000000000")
WHATIF_ORDER_ID = _env("LOCUST_WHATIF_ORDER_ID", "00000000-0000-0000-0000-000000000000")
WHATIF_CONTRACT_ID = _env("LOCUST_WHATIF_CONTRACT_ID", "11111111-1111-1111-1111-111111111111")


class HedgeControlUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task(2)
    def scenario_a_fetch_ledger(self) -> None:
        """Scenario A: fetch ledger entries for a contract (10k rows assumed)."""
        params = {
            "start": (date.today() - timedelta(days=365)).isoformat(),
            "end": date.today().isoformat(),
        }
        self.client.get(
            f"/cashflow/ledger/hedge-contracts/{LEDGER_CONTRACT_ID}",
            params=params,
            name="ScenarioA_Ledger_10k",
        )

    @task(1)
    def scenario_b_whatif(self) -> None:
        """Scenario B: what-if run with 1k deltas (explicit deltas only)."""
        today = date.today()
        payload = {
            "as_of_date": today.isoformat(),
            "period_start": today.isoformat(),
            "period_end": (today + timedelta(days=30)).isoformat(),
            "deltas": [
                {
                    "delta_type": "add_unlinked_hedge_contract",
                    "contract_id": WHATIF_CONTRACT_ID,
                    "commodity": "ALUMINUM",
                    "quantity_mt": "10",
                    "fixed_leg_side": "buy",
                    "variable_leg_side": "sell",
                    "fixed_price_value": "100",
                    "fixed_price_unit": "USD/MT",
                    "float_pricing_convention": "avg",
                },
                {
                    "delta_type": "adjust_order_quantity_mt",
                    "order_id": WHATIF_ORDER_ID,
                    "new_quantity_mt": "10",
                },
                {
                    "delta_type": "add_cash_settlement_price_override",
                    "symbol": "LME_ALU_CASH_SETTLEMENT_DAILY",
                    "settlement_date": today.isoformat(),
                    "price_usd": "120",
                },
            ]
            * 1000,
        }
        self.client.post(
            "/scenario/what-if/run",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            name="ScenarioB_WhatIf_1k",
        )
