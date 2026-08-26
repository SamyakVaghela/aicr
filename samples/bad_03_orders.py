"""Order reporting and inventory reservation.

SMOKE TEST FIXTURE — deliberately broken. Do not copy this code.
Expected: BLOCKED (N+1 query, unbounded result set, check-then-act race,
network call with no timeout).

These are the "boring" bugs a linter will never catch — the whole point of an
AI reviewer. If your provider misses this file, the reviewer is too weak.
"""

import requests

from app.models import Customer, Order, Product


def monthly_report():
    # No filter, no pagination — loads every order ever placed into memory.
    orders = Order.objects.all()

    rows = []
    for order in orders:
        # One extra query per order, and another per order for the customer.
        customer = Customer.objects.get(id=order.customer_id)
        items = order.items.all()
        rows.append({
            "id": order.id,
            "customer": customer.name,
            "total": sum(i.price * i.quantity for i in items),
        })
    return rows


def reserve_stock(product_id, quantity):
    product = Product.objects.get(id=product_id)

    if product.stock >= quantity:
        # Two concurrent requests both pass the check above, then both write.
        product.stock = product.stock - quantity
        product.save()
        return True
    return False


def notify_warehouse(order_id):
    # No timeout: a hung warehouse API pins this worker forever.
    response = requests.post(
        "https://warehouse.internal/api/dispatch",
        json={"order_id": order_id},
    )
    return response.json()
