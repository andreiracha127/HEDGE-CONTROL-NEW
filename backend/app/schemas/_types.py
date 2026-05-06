from decimal import Decimal
from typing import Annotated

from pydantic import Field

from app.core.precision import (
    MT_NUMERIC_PRECISION,
    MT_NUMERIC_SCALE,
    PRICE_NUMERIC_PRECISION,
    PRICE_NUMERIC_SCALE,
)

MTQuantity = Annotated[
    Decimal, Field(max_digits=MT_NUMERIC_PRECISION, decimal_places=MT_NUMERIC_SCALE)
]
Price = Annotated[
    Decimal,
    Field(max_digits=PRICE_NUMERIC_PRECISION, decimal_places=PRICE_NUMERIC_SCALE),
]
Money = Price
