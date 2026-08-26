"""Order reporting and inventory reservation.

SMOKE TEST FIXTURE — clean counterpart to bad_03_orders.py.
Expected: PASS with no critical or high findings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterator, List

import requests
from django.db import transaction
from django.db.models import F, Sum

from app.models import Order, Product

logger = logging.getLogger(__name__)

WAREHOUSE_TIMEOUT_S = 10
PAGE_SIZE = 500


@dataclass(frozen=True)
class ReportRow:
    order_id: int
    customer_name: str
    total: float


def monthly_report(start: date, end: date) -> Iterator[List[ReportRow]]:
    """Yield report rows one page at a time for the given date range.

    `select_related` joins the customer in the same query and `annotate` pushes
    the line-item total into SQL, so this is two queries per page rather than
    two per order.
    """
    queryset = (
        Order.objects
        .filter(created_at__gte=start, created_at__lt=end)
        .select_related("customer")
        .annotate(total=Sum(F("items__price") * F("items__quantity")))
        .order_by("id")
    )

    page: List[ReportRow] = []
    for order in queryset.iterator(chunk_size=PAGE_SIZE):
        page.append(ReportRow(
            order_id=order.id,
            customer_name=order.customer.name,
            total=float(order.total or 0),
        ))
        if len(page) >= PAGE_SIZE:
            yield page
            page = []
    if page:
        yield page


def reserve_stock(product_id: int, quantity: int) -> bool:
    """Reserve stock atomically. Returns False if there was not enough.

    The check and the decrement happen in a single conditional UPDATE, so two
    concurrent callers cannot both succeed against the same units.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    with transaction.atomic():
        updated = (
            Product.objects
            .filter(id=product_id, stock__gte=quantity)
            .update(stock=F("stock") - quantity)
        )
    return updated == 1


def notify_warehouse(order_id: int) -> dict:
    """Tell the warehouse to dispatch an order."""
    try:
        response = requests.post(
            "https://warehouse.internal/api/dispatch",
            json={"order_id": order_id},
            timeout=WAREHOUSE_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("warehouse dispatch failed order_id=%s", order_id)
        raise
    return response.json()
