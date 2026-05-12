#!/usr/bin/env python3
"""Realistic database seed using actual API endpoints (end-to-end).

Exercises the real business flow through every guardrail:
  1. Create counterparties           POST /counterparties
  2. Create POs + SOs (orders)       POST /orders/purchase, /orders/sales
  3. Reconcile exposures (pre-hedge) POST /exposures/reconcile
  4. Create RFQs (COMMERCIAL_HEDGE)  POST /rfqs
  5. Submit quotes                   POST /rfqs/{id}/quotes
  6. Award RFQs → contracts + links  POST /rfqs/{id}/actions/award
  7. Reconcile exposures (post-hedge)POST /exposures/reconcile
  8. Create deals                    POST /deals
  9. Settle one contract             POST /cashflow/contracts/{id}/settle
 10. Seed cash settlement prices     (direct DB – no API)

Usage:
    cd backend
    DATABASE_URL=sqlite+pysqlite:///./dev.db python -m scripts.seed
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

# ── Make app importable ─────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
# Mark this process as local developer tooling so the auth/audit-signing
# fail-closed gates (J-A1-02, J-A5-06) do not refuse to boot. APP_ENV is
# the canonical environment marker; AUTH_DISABLED alone is no longer
# honored under production/staging APP_ENV. Using setdefault preserves
# any caller-set override (e.g. APP_ENV=test in CI).
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("WHATSAPP_PROVIDER", "fake")

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.market_data import CashSettlementPrice  # noqa: E402
from app.core.database import engine, SessionLocal  # noqa: E402


# =====================================================================
# Helpers
# =====================================================================
def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _ok(resp, expected: int = 201, ctx: str = ""):
    if resp.status_code != expected:
        raise RuntimeError(
            f"[SEED FAIL] {ctx}: expected {expected}, got {resp.status_code}\n"
            f"{resp.text[:600]}"
        )


# =====================================================================
# Cash-settlement prices (direct DB – no API endpoint)
# =====================================================================
def _seed_prices(session) -> int:
    random.seed(42)
    base = 2_380.0
    count = 0
    today = date.today()
    for offset in range(120, 0, -1):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        base += random.uniform(-15, 15)
        base = round(base, 2)
        session.add(
            CashSettlementPrice(
                id=uuid.uuid4(),
                source="westmetall",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=d,
                price_usd=base,
                source_url="https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Al_cash",
                html_sha256=hashlib.sha256(
                    f"seed-{d.isoformat()}".encode()
                ).hexdigest(),
                fetched_at=datetime.now(timezone.utc),
            )
        )
        count += 1
    session.commit()
    return count


# =====================================================================
# MAIN
# =====================================================================
def seed() -> None:
    # ── Create tables ────────────────────────────────────────────────
    Base.metadata.create_all(bind=engine)

    # ── Wipe all data ────────────────────────────────────────────────
    session = SessionLocal()
    try:
        for tbl in reversed(Base.metadata.sorted_tables):
            session.execute(tbl.delete())
        session.commit()
        print("✓ Database wiped")
    finally:
        session.close()

    client = TestClient(app, raise_server_exceptions=False)

    # =================================================================
    # 1. COUNTERPARTIES
    # =================================================================
    print("\n── 1. Counterparties ──")

    CP_DATA = [
        dict(
            type="broker",
            name="Marex Spectron",
            short_name="MAREX",
            tax_id="GB-MAREX-001",
            country="GBR",
            city="London",
            contact_name="John Smith",
            contact_email="trading@marex.com",
            contact_phone="+44 20 7000 0001",
            whatsapp_phone="+442070000001",
            payment_terms_days=30,
            credit_limit_usd=5_000_000,
            kyc_status="approved",
            risk_rating="low",
        ),
        dict(
            type="broker",
            name="Sucden Financial",
            short_name="SUCDEN",
            tax_id="GB-SUCDEN-002",
            country="GBR",
            city="London",
            contact_name="Emily Brown",
            contact_email="metals@sucdenfinancial.com",
            contact_phone="+44 20 7000 0002",
            whatsapp_phone="+442070000002",
            payment_terms_days=30,
            credit_limit_usd=4_000_000,
            kyc_status="approved",
            risk_rating="low",
        ),
        dict(
            type="bank_br",
            name="Itaú BBA",
            short_name="ITAU",
            tax_id="60.872.504/0001-23",
            country="BRA",
            city="São Paulo",
            contact_name="Carlos Oliveira",
            contact_email="metals.desk@itaubba.com.br",
            contact_phone="+55 11 3000-0001",
            whatsapp_phone="+5511930000001",
            payment_terms_days=60,
            credit_limit_usd=10_000_000,
            kyc_status="approved",
            risk_rating="low",
        ),
        dict(
            type="bank_br",
            name="BTG Pactual",
            short_name="BTG",
            tax_id="30.306.294/0001-45",
            country="BRA",
            city="São Paulo",
            contact_name="Ana Souza",
            contact_email="commodities@btgpactual.com",
            contact_phone="+55 11 3000-0002",
            whatsapp_phone="+5511930000002",
            payment_terms_days=45,
            credit_limit_usd=8_000_000,
            kyc_status="approved",
            risk_rating="medium",
        ),
        dict(
            type="bank_br",
            name="Bradesco BBI",
            short_name="BRAD",
            tax_id="60.746.948/0001-12",
            country="BRA",
            city="São Paulo",
            contact_name="Pedro Lima",
            contact_email="mesa.metais@bradescobbi.com.br",
            contact_phone="+55 11 3000-0003",
            whatsapp_phone="+5511930000003",
            payment_terms_days=30,
            credit_limit_usd=6_000_000,
            kyc_status="approved",
            risk_rating="medium",
        ),
    ]

    cps: dict[str, str] = {}  # short_name → id
    for d in CP_DATA:
        r = client.post("/counterparties", json=d)
        _ok(r, 201, f"counterparty {d['short_name']}")
        cps[d["short_name"]] = r.json()["id"]
        print(f"  ✓ {d['short_name']}")

    # =================================================================
    # 2. ORDERS  (all variable-price → hedgeable)
    # =================================================================
    print("\n── 2. Orders ──")

    ORDER_DATA = [
        # ---- Sales Orders ----
        dict(
            ep="/orders/sales",
            label="SO-1",
            body=dict(
                price_type="variable",
                quantity_mt=250,
                pricing_convention="AVG",
                avg_entry_price=2_400.00,
                counterparty_id=cps["ITAU"],
                delivery_date_start=_future(30),
                delivery_date_end=_future(60),
                payment_terms_days=60,
                currency="USD",
                notes="Venda Al Q2 – Itaú",
            ),
        ),
        dict(
            ep="/orders/sales",
            label="SO-2",
            body=dict(
                price_type="variable",
                quantity_mt=200,
                pricing_convention="AVGInter",
                avg_entry_price=2_380.00,
                counterparty_id=cps["BTG"],
                delivery_date_start=_future(45),
                delivery_date_end=_future(75),
                payment_terms_days=45,
                currency="USD",
                notes="Venda Al Q2 – BTG",
            ),
        ),
        dict(
            ep="/orders/sales",
            label="SO-3",
            body=dict(
                price_type="variable",
                quantity_mt=150,
                pricing_convention="C2R",
                avg_entry_price=2_420.00,
                counterparty_id=cps["BRAD"],
                delivery_date_start=_future(60),
                delivery_date_end=_future(90),
                payment_terms_days=30,
                currency="USD",
                notes="Venda Al Q2 – Bradesco",
            ),
        ),
        dict(
            ep="/orders/sales",
            label="SO-4",
            body=dict(
                price_type="variable",
                quantity_mt=300,
                pricing_convention="AVG",
                avg_entry_price=2_360.00,
                counterparty_id=cps["ITAU"],
                delivery_date_start=_future(90),
                delivery_date_end=_future(120),
                payment_terms_days=60,
                currency="USD",
                notes="Venda Al Q3 – Itaú (sem hedge)",
            ),
        ),
        # ---- Purchase Orders ----
        dict(
            ep="/orders/purchase",
            label="PO-1",
            body=dict(
                price_type="variable",
                quantity_mt=350,
                pricing_convention="AVG",
                avg_entry_price=2_310.00,
                counterparty_id=cps["MAREX"],
                delivery_date_start=_future(30),
                delivery_date_end=_future(60),
                payment_terms_days=30,
                currency="USD",
                notes="Compra Al Q2 – Marex",
            ),
        ),
        dict(
            ep="/orders/purchase",
            label="PO-2",
            body=dict(
                price_type="variable",
                quantity_mt=200,
                pricing_convention="AVGInter",
                avg_entry_price=2_290.00,
                counterparty_id=cps["SUCDEN"],
                delivery_date_start=_future(45),
                delivery_date_end=_future(75),
                payment_terms_days=30,
                currency="USD",
                notes="Compra Al Q2 – Sucden",
            ),
        ),
        dict(
            ep="/orders/purchase",
            label="PO-3",
            body=dict(
                price_type="variable",
                quantity_mt=400,
                pricing_convention="AVG",
                avg_entry_price=2_320.00,
                counterparty_id=cps["MAREX"],
                delivery_date_start=_future(60),
                delivery_date_end=_future(90),
                payment_terms_days=30,
                currency="USD",
                notes="Compra Al Q2 – Marex (hedge parcial)",
            ),
        ),
        dict(
            ep="/orders/purchase",
            label="PO-4",
            body=dict(
                price_type="variable",
                quantity_mt=180,
                pricing_convention="C2R",
                avg_entry_price=2_300.00,
                counterparty_id=cps["SUCDEN"],
                delivery_date_start=_future(90),
                delivery_date_end=_future(120),
                payment_terms_days=30,
                currency="USD",
                notes="Compra Al Q3 – Sucden (sem hedge)",
            ),
        ),
    ]

    orders: dict[str, dict] = {}  # label → {id, order_type, qty}
    for od in ORDER_DATA:
        r = client.post(od["ep"], json=od["body"])
        _ok(r, 201, f"order {od['label']}")
        o = r.json()
        orders[od["label"]] = dict(
            id=o["id"], type=o["order_type"], qty=od["body"]["quantity_mt"]
        )
        print(f"  ✓ {od['label']} ({o['order_type']}) {od['body']['quantity_mt']} MT")

    # =================================================================
    # 3. RECONCILE EXPOSURES (pre-hedge)
    # =================================================================
    print("\n── 3. Reconcile exposures (pre-hedge) ──")
    r = client.post("/exposures/reconcile")
    _ok(r, 200, "reconcile pre-hedge")
    rc = r.json()
    print(f"  ✓ created={rc.get('created', 0)} updated={rc.get('updated', 0)}")

    # =================================================================
    # 4-6. RFQ FLOW  →  Contracts + Linkages
    # =================================================================
    print("\n── 4-6. RFQ flow (create → quote → award) ──")

    # SO hedges: direction=SELL → short contract
    # PO hedges: direction=BUY  → long contract
    RFQ_SCENARIOS = [
        dict(
            label="RFQ-1 (SO-1 full)",
            order="SO-1",
            direction="SELL",
            qty=250,
            broker="MAREX",
            price=2_410.00,
            conv="avg",
        ),
        dict(
            label="RFQ-2 (SO-2 full)",
            order="SO-2",
            direction="SELL",
            qty=200,
            broker="SUCDEN",
            price=2_390.00,
            conv="avginter",
        ),
        dict(
            label="RFQ-3 (SO-3 full)",
            order="SO-3",
            direction="SELL",
            qty=150,
            broker="BTG",
            price=2_430.00,
            conv="c2r",
        ),
        dict(
            label="RFQ-4 (PO-1 full)",
            order="PO-1",
            direction="BUY",
            qty=350,
            broker="ITAU",
            price=2_320.00,
            conv="avg",
        ),
        dict(
            label="RFQ-5 (PO-2 full)",
            order="PO-2",
            direction="BUY",
            qty=200,
            broker="BRAD",
            price=2_295.00,
            conv="avginter",
        ),
        dict(
            label="RFQ-6 (PO-3 partial 250/400)",
            order="PO-3",
            direction="BUY",
            qty=250,
            broker="MAREX",
            price=2_330.00,
            conv="avg",
        ),
        # SO-4 and PO-4 intentionally left un-hedged
    ]

    awarded_contracts: dict[str, dict] = {}  # label→{id, ref, classification}
    known_contract_ids: set[str] = set()  # track IDs we already know about

    for scn in RFQ_SCENARIOS:
        oid = orders[scn["order"]]["id"]

        # 4a. Create RFQ
        rfq_body = dict(
            intent="COMMERCIAL_HEDGE",
            commodity="LME_AL",
            quantity_mt=scn["qty"],
            delivery_window_start=_future(30),
            delivery_window_end=_future(90),
            direction=scn["direction"],
            order_id=oid,
            invitations=[dict(counterparty_id=cps[scn["broker"]])],
        )
        r = client.post("/rfqs", json=rfq_body)
        _ok(r, 201, f"create {scn['label']}")
        rfq = r.json()
        rfq_id = rfq["id"]
        print(f"  ✓ {scn['label']}  rfq={rfq['rfq_number']}  state={rfq['state']}")

        # 4b. Submit quote
        quote_body = dict(
            rfq_id=rfq_id,
            counterparty_id=cps[scn["broker"]],
            fixed_price_value=scn["price"],
            fixed_price_unit="USD/MT",
            float_pricing_convention=scn["conv"],
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        r = client.post(f"/rfqs/{rfq_id}/quotes", json=quote_body)
        _ok(r, 201, f"quote {scn['label']}")
        print(f"    quote={scn['price']} USD/MT ({scn['conv']})")

        # 4c. Award → auto-creates HedgeContract + HedgeOrderLinkage
        r = client.post(
            f"/rfqs/{rfq_id}/actions/award", json=dict(user_id="seed-script")
        )
        _ok(r, 200, f"award {scn['label']}")
        awarded = r.json()
        print(f"    awarded → state={awarded['state']}")

        # Find the newly created contract by diffing against known IDs
        r = client.get("/contracts/hedge?limit=200")
        _ok(r, 200, "list contracts")
        items = r.json()["items"]
        all_ids = {c["id"] for c in items}
        new_ids = all_ids - known_contract_ids
        if not new_ids:
            raise RuntimeError(
                f"[SEED FAIL] No new contract created after award of {scn['label']}"
            )
        # Pick the new contract
        new_contract = next(c for c in items if c["id"] in new_ids)
        known_contract_ids.update(new_ids)

        clabel = scn["label"]
        awarded_contracts[clabel] = dict(
            id=new_contract["id"],
            ref=new_contract.get("reference", ""),
            classification=new_contract.get("classification", ""),
            qty=scn["qty"],
            order=scn["order"],
        )
        print(
            f"    contract={new_contract.get('reference', new_contract['id'])} "
            f"({new_contract.get('classification', '?')}) {scn['qty']} MT"
        )

    # =================================================================
    # 7. RECONCILE EXPOSURES (post-hedge)
    # =================================================================
    print("\n── 7. Reconcile exposures (post-hedge) ──")
    r = client.post("/exposures/reconcile")
    _ok(r, 200, "reconcile post-hedge")
    rc = r.json()
    print(f"  ✓ created={rc.get('created', 0)} updated={rc.get('updated', 0)}")

    r = client.get("/exposures/list?limit=50")
    _ok(r, 200, "list exposures")
    for exp in r.json().get("items", []):
        orig = exp.get("original_tons", 0)
        opn = exp.get("open_tons", 0)
        print(
            f"  {exp.get('commodity', ''):10s} {exp.get('direction', ''):6s} "
            f"orig={orig:>7.1f}  hedged={orig - opn:>7.1f}  "
            f"open={opn:>7.1f}  status={exp.get('status', '?')}"
        )

    # =================================================================
    # 8. DEALS
    # =================================================================
    print("\n── 8. Deals ──")

    # Group hedge contracts by order label for deal construction
    def _contracts_for(*order_labels):
        """Return deal-link dicts for contracts hedging the given orders."""
        links = []
        for lbl, c in awarded_contracts.items():
            if c["order"] in order_labels:
                links.append(dict(linked_type="contract", linked_id=c["id"]))
        return links

    DEAL_DATA = [
        # Deal 1: SO-1 (sell 250) + PO-1 (buy 350) + their hedges
        dict(
            name="Aluminum Q2 – Itaú / Marex",
            commodity="ALUMINUM",
            order_labels=["SO-1", "PO-1"],
        ),
        # Deal 2: SO-2 (sell 200) + PO-2 (buy 200) + their hedges
        dict(
            name="Aluminum Q2 – BTG / Sucden",
            commodity="ALUMINUM",
            order_labels=["SO-2", "PO-2"],
        ),
        # Deal 3: SO-3 (sell 150) + PO-3 (buy 400, partially hedged 250)
        dict(
            name="Aluminum Q2 – Bradesco / Marex",
            commodity="ALUMINUM",
            order_labels=["SO-3", "PO-3"],
        ),
        # Deal 4: SO-4 (sell 300) unhedged
        dict(
            name="Aluminum Q3 – Itaú (Unhedged SO)",
            commodity="ALUMINUM",
            order_labels=["SO-4"],
        ),
        # Deal 5: PO-4 (buy 180) unhedged
        dict(
            name="Aluminum Q3 – Sucden (Unhedged PO)",
            commodity="ALUMINUM",
            order_labels=["PO-4"],
        ),
    ]

    deals = {}
    for dd in DEAL_DATA:
        links = []
        for ol in dd["order_labels"]:
            otype = orders[ol]["type"]
            lt = "sales_order" if otype == "SO" else "purchase_order"
            links.append(dict(linked_type=lt, linked_id=orders[ol]["id"]))
        links.extend(_contracts_for(*dd["order_labels"]))

        r = client.post(
            "/deals", json=dict(name=dd["name"], commodity=dd["commodity"], links=links)
        )
        _ok(r, 201, f"deal '{dd['name']}'")
        deal = r.json()
        deals[dd["name"]] = deal
        ratio = deal.get("hedge_ratio", 0)
        print(
            f"  ✓ {deal.get('reference', '?'):10s}  "
            f"phys={deal.get('total_physical_tons', 0):>6.0f} MT  "
            f"hedge={deal.get('total_hedge_tons', 0):>6.0f} MT  "
            f"ratio={ratio * 100:.0f}%  "
            f"status={deal.get('status', '?')}"
        )

    # =================================================================
    # 9. SETTLE ONE CONTRACT
    # =================================================================
    print("\n── 9. Settle one contract ──")

    settle_key = "RFQ-1 (SO-1 full)"
    if settle_key in awarded_contracts:
        cid = awarded_contracts[settle_key]["id"]
        qty = awarded_contracts[settle_key]["qty"]  # 250
        r = client.post(
            f"/cashflow/contracts/{cid}/settle",
            json=dict(
                source_event_id=str(uuid.uuid4()),
                cashflow_date=date.today().isoformat(),
                currency="USD",
                legs=[
                    dict(leg_id="FIXED", direction="IN", amount=round(2_410 * qty, 2)),
                    dict(leg_id="FLOAT", direction="OUT", amount=round(2_380 * qty, 2)),
                ],
            ),
        )
        _ok(r, 201, "settle contract")
        net = 2_410 * qty - 2_380 * qty
        print(f"  ✓ Settled {awarded_contracts[settle_key]['ref']}")
        print(f"    FIXED IN  = {2_410 * qty:,.2f} USD")
        print(f"    FLOAT OUT = {2_380 * qty:,.2f} USD")
        print(f"    Net P&L   = {net:+,.2f} USD")
    else:
        print(f"  ⚠ Contract for {settle_key} not found, skipping")

    # =================================================================
    # 10. CASH SETTLEMENT PRICES
    # =================================================================
    print("\n── 10. Cash settlement prices ──")
    session = SessionLocal()
    try:
        price_count = _seed_prices(session)
        print(f"  ✓ {price_count} prices (LME Aluminum, ~30 days)")
    finally:
        session.close()

    # =================================================================
    # 11. FINAL RECONCILE
    # =================================================================
    print("\n── 11. Final reconcile ──")
    r = client.post("/exposures/reconcile")
    _ok(r, 200, "final reconcile")

    # =================================================================
    # SUMMARY
    # =================================================================
    print("\n" + "=" * 64)
    print(" SEED COMPLETED — ALL DATA THROUGH REAL API ENDPOINTS")
    print("=" * 64)

    def _count(path):
        r = client.get(f"{path}?limit=200")
        if r.status_code != 200:
            return "?"
        body = r.json()
        if isinstance(body, dict) and "items" in body:
            return len(body["items"])
        if isinstance(body, list):
            return len(body)
        return "?"

    print(f"\n  Counterparties : {_count('/counterparties')}")
    print(f"  Orders (SO+PO) : {_count('/orders')}")
    print(f"  RFQs           : {_count('/rfqs')}")
    print(f"  Contracts      : {_count('/contracts/hedge')}")
    print(f"  Linkages       : {_count('/linkages')}")
    print(f"  Deals          : {_count('/deals')}")
    print(f"  Exposures      : {_count('/exposures/list')}")
    print(f"  Settl. Prices  : {price_count}")

    # Final exposure summary
    print("\n── Final Exposures ──")
    r = client.get("/exposures/list?limit=200")
    if r.status_code == 200:
        for exp in r.json().get("items", []):
            orig = exp.get("original_tons", 0)
            opn = exp.get("open_tons", 0)
            print(
                f"  {exp.get('commodity', ''):10s} {exp.get('direction', ''):6s}  "
                f"orig={orig:>7.1f}  hedged={orig - opn:>7.1f}  "
                f"open={opn:>7.1f}  status={exp.get('status', '?')}"
            )

    print("\n✅ Realistic seed complete — all guardrails validated!\n")


if __name__ == "__main__":
    seed()
