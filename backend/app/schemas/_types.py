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

# Spread of two opposite-sign Price values can require up to
# (PRICE_NUMERIC_PRECISION + 1) integral digits + PRICE_NUMERIC_SCALE fractional.
# +2 leaves headroom for the magnitude doubling without losing fractional precision.
SPREAD_NUMERIC_PRECISION = PRICE_NUMERIC_PRECISION + 2
Spread = Annotated[
    Decimal,
    Field(max_digits=SPREAD_NUMERIC_PRECISION, decimal_places=PRICE_NUMERIC_SCALE),
]
