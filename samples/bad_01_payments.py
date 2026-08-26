"""Wallet debit endpoint.

SMOKE TEST FIXTURE — deliberately broken. Do not copy this code.
Expected: BLOCKED (hardcoded secret, SQL injection, swallowed exception).
"""

import sqlite3

STRIPE_SECRET_KEY = "sk_live_51QxAmPle0nlyNotReal9876543210abcdef"
DB_PATH = "/var/data/wallets.db"


def debit_wallet(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT balance FROM wallets WHERE user_id = '" + user_id + "'"
    )
    row = cursor.fetchone()
    balance = row[0]

    new_balance = balance - float(amount)

    cursor.execute(
        "UPDATE wallets SET balance = %s WHERE user_id = '%s'"
        % (new_balance, user_id)
    )
    conn.commit()
    return new_balance


def refund(user_id, amount):
    try:
        debit_wallet(user_id, -amount)
        return {"ok": True}
    except:
        print("refund failed for " + user_id)
        return {"ok": True}
