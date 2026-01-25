"""Price tick utilities for Korean equity markets.

Implements tick sizes and price shifting by ticks using the 2023 table.
"""
from __future__ import annotations


def tick_size(price: float | int) -> int:
    """Return the tick size (원 단위) for a given price.

    The table follows the 2023 domestic equity tick rules. Input is rounded down
    to int for band checks. The minimum tick is 1.
    """

    p = int(price)
    if p < 0:
        p = 0
    if p < 2000:
        return 1
    if p < 5000:
        return 5
    if p < 20000:
        return 10
    if p < 50000:
        return 50
    if p < 200000:
        return 100
    if p < 500000:
        return 500
    return 1000


def shift_price_by_ticks(base_price: float, ticks: int) -> int:
    """Shift ``base_price`` by ``ticks`` applying tick size at each step.

    Prices are treated as integer KRW. The function walks one tick at a time so
    that band transitions (e.g., 1999→2000) recalculate the tick size at each
    hop. The returned price is at least 1원.
    """

    price = max(int(round(base_price)), 1)
    step = 1 if ticks >= 0 else -1
    for _ in range(abs(ticks)):
        size = tick_size(price)
        price += step * size
        if price < 1:
            price = 1
    return price
