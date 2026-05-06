import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.core.precision import MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE


class HedgeOrderLinkage(Base):
    __tablename__ = "hedge_order_linkages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hedge_contracts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_mt: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
