"""Wallet debit endpoint.

SMOKE TEST FIXTURE — this is the clean counterpart to bad_01_payments.py.
Expected: PASS with no critical or high findings.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Optional

import psycopg

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]


class InsufficientFunds(Exception):
    """Raised when a wallet cannot cover the requested debit."""


def debit_wallet(conn: psycopg.Connection, user_id: str, amount: Decimal) -> Decimal:
    """Atomically debit `amount` from a user's wallet and return the new balance.

    Raises InsufficientFunds if the balance would go negative.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    with conn.transaction():
        with conn.cursor() as cur:
            # SELECT ... FOR UPDATE holds the row lock for the whole
            # transaction, so concurrent debits serialize instead of racing.
            cur.execute(
                "SELECT balance FROM wallets WHERE user_id = %s FOR UPDATE",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"no wallet for user {user_id}")

            balance: Decimal = row[0]
            if balance < amount:
                raise InsufficientFunds(
                    f"balance {balance} is less than requested {amount}"
                )

            new_balance = balance - amount
            cur.execute(
                "UPDATE wallets SET balance = %s WHERE user_id = %s",
                (new_balance, user_id),
            )

    return new_balance


def refund(conn: psycopg.Connection, user_id: str, amount: Decimal) -> Optional[Decimal]:
    """Credit a refund back to the wallet. Returns None if the wallet is missing."""
    if amount <= 0:
        raise ValueError("amount must be positive")

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE wallets SET balance = balance + %s "
                    "WHERE user_id = %s RETURNING balance",
                    (amount, user_id),
                )
                row = cur.fetchone()
                if row is None:
                    logger.warning("refund for unknown wallet user_id=%s", user_id)
                    return None
                return row[0]
    except psycopg.DatabaseError:
        logger.exception("refund failed for user_id=%s", user_id)
        raise
