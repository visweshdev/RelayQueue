"""Bounded, deterministic CSV aggregation with no external side effects."""

import asyncio
import csv
import hashlib
import io
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from relayqueue.worker.registry import Context


class SalesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=48_000)


class ProductTotal(BaseModel):
    sku: str
    units: int
    revenue: str


class SalesResult(BaseModel):
    source_sha256: str
    rows: int
    units: int
    revenue: str
    products: list[ProductTotal]


async def sales_report(payload: SalesInput, context: Context) -> SalesResult:
    reader = csv.DictReader(io.StringIO(payload.content.lstrip("\ufeff")), strict=True)
    if reader.fieldnames != ["sku", "quantity", "unit_price"]:
        raise ValueError("Expected sku,quantity,unit_price header")
    totals: dict[str, tuple[int, Decimal]] = {}
    rows = 0
    for row in reader:
        rows += 1
        if rows > 1000 or set(row) != {"sku", "quantity", "unit_price"}:
            raise ValueError("Invalid CSV shape or row limit exceeded")
        sku, quantity, price = (row.get(key) or "" for key in ("sku", "quantity", "unit_price"))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sku):
            raise ValueError("Invalid SKU")
        if not re.fullmatch(r"[1-9][0-9]{0,5}", quantity):
            raise ValueError("Quantity must be an integer from 1 to 999999")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})\.[0-9]{2}", price):
            raise ValueError("Price must be a nonnegative amount with two decimal places")
        units, revenue = totals.get(sku, (0, Decimal(0)))
        totals[sku] = (units + int(quantity), revenue + int(quantity) * Decimal(price))
        if len(totals) > 100:
            raise ValueError("At most 100 unique products are supported")
        if rows % 50 == 0:
            await asyncio.sleep(0)  # Keep cancellation and lease heartbeats responsive.
    if rows == 0:
        raise ValueError("CSV must contain at least one data row")
    return SalesResult(
        source_sha256=hashlib.sha256(payload.content.encode()).hexdigest(),
        rows=rows,
        units=sum(units for units, _ in totals.values()),
        revenue=f"{sum((value for _, value in totals.values()), Decimal(0)):.2f}",
        products=[
            ProductTotal(sku=sku, units=units, revenue=f"{revenue:.2f}")
            for sku, (units, revenue) in sorted(totals.items())
        ],
    )
