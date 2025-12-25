"""Trading strategy primitives with budget-aware entry and exit logic."""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position tracked by the strategy."""

    symbol: str
    quantity: int
    entry_price: float
    highest_price: float = field(default=0.0)
    entry_time: datetime.datetime = field(default_factory=datetime.datetime.utcnow)

    def update_highest(self, price: float) -> None:
        if price > self.highest_price:
            self.highest_price = price


@dataclass
class Order:
    """Simple order container produced by the strategy."""

    side: str  # "buy" or "sell"
    symbol: str
    quantity: int
    price: float


class Strategy:
    """Budget-aware strategy with stop-loss and take-profit helpers."""

    def __init__(
        self,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.05,
        trailing_stop_pct: float = 0.03,
        initial_cash: float = 1_000_000,
        max_positions: int = 5,
        time_limit_minutes: int = 0,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.initial_cash = initial_cash
        self.max_positions = max_positions
        self.time_limit_minutes = time_limit_minutes
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}

    def update_parameters(self, **kwargs) -> None:
        """Update strategy parameters such as cash or position limits."""
        if "initial_cash" in kwargs:
            self.initial_cash = float(kwargs["initial_cash"])
            self.cash = self.initial_cash
        if "max_positions" in kwargs:
            self.max_positions = int(kwargs["max_positions"])
        if "time_limit_minutes" in kwargs:
            self.time_limit_minutes = int(kwargs["time_limit_minutes"])
        self.stop_loss_pct = float(kwargs.get("stop_loss_pct", self.stop_loss_pct))
        self.take_profit_pct = float(kwargs.get("take_profit_pct", self.take_profit_pct))
        self.trailing_stop_pct = float(kwargs.get("trailing_stop_pct", self.trailing_stop_pct))

    def evaluate_entry(
        self, symbols: List[str], price_lookup: Callable[[str], float]
    ) -> List[Order]:
        """Generate buy orders based on remaining slots and available cash."""
        available_slots = self.max_positions - len(self.positions)
        if available_slots <= 0:
            return []

        remaining_cash = self.cash
        budget_per_slot = remaining_cash / max(available_slots, 1)
        orders: List[Order] = []

        for symbol in symbols:
            if symbol in self.positions:
                continue
            if len(self.positions) + len(orders) >= self.max_positions:
                break

            price = price_lookup(symbol)
            quantity = int(budget_per_slot // price)
            if quantity < 1:
                continue

            estimated_cost = quantity * price
            if estimated_cost > remaining_cash:
                quantity = int(remaining_cash // price)
                estimated_cost = quantity * price
            if quantity < 1:
                continue

            remaining_cash -= estimated_cost
            orders.append(Order(side="buy", symbol=symbol, quantity=quantity, price=price))

        return orders

    def evaluate_exit(self, price_lookup: Callable[[str], float]) -> List[Order]:
        """Generate sell orders based on stop-loss or take-profit triggers."""
        orders: List[Order] = []
        for symbol, position in list(self.positions.items()):
            price = price_lookup(symbol)
            position.update_highest(price)

            stop_loss_price = position.entry_price * (1 - self.stop_loss_pct)
            take_profit_price = position.entry_price * (1 + self.take_profit_pct)
            trailing_stop_price = position.highest_price * (1 - self.trailing_stop_pct)

            expired = False
            if self.time_limit_minutes > 0:
                delta = datetime.datetime.utcnow() - position.entry_time
                expired = delta.total_seconds() >= self.time_limit_minutes * 60

            if price <= stop_loss_price or price <= trailing_stop_price or price >= take_profit_price or expired:
                orders.append(Order(side="sell", symbol=symbol, quantity=position.quantity, price=price))
        return orders

    def register_fill(
        self, order: Order, filled_quantity: int, fill_price: float, update_cash: bool = True
    ) -> None:
        """Update internal cash and positions after a fill.

        ``update_cash`` allows callers to keep Strategy cash in sync with an
        external broker (e.g., PaperBroker already tracks cash separately).
        """

        if filled_quantity <= 0:
            return

        if order.side == "buy":
            if update_cash:
                cost = filled_quantity * fill_price
                self.cash -= cost
            if order.symbol in self.positions:
                position = self.positions[order.symbol]
                total_qty = position.quantity + filled_quantity
                position.entry_price = (
                    position.entry_price * position.quantity + fill_price * filled_quantity
                ) / total_qty
                position.quantity = total_qty
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=filled_quantity,
                    entry_price=fill_price,
                    highest_price=fill_price,
                    entry_time=datetime.datetime.utcnow(),
                )
        elif order.side == "sell":
            if update_cash:
                proceeds = filled_quantity * fill_price
                self.cash += proceeds
            if order.symbol in self.positions:
                position = self.positions[order.symbol]
                position.quantity -= filled_quantity
                if position.quantity <= 0:
                    del self.positions[order.symbol]
        logger.debug("Updated cash: %.2f, positions: %s", self.cash, list(self.positions.keys()))

    def close_all_positions(self, price_lookup: Callable[[str], float]) -> List[Order]:
        """Create sell orders that liquidate every open position."""

        orders: List[Order] = []
        for symbol, position in list(self.positions.items()):
            price = price_lookup(symbol)
            orders.append(Order(side="sell", symbol=symbol, quantity=position.quantity, price=price))
        return orders

    def snapshot(self) -> Dict[str, float]:
        """Return a summary of the strategy state."""
        equity = self.cash + sum(
            position.quantity * position.entry_price for position in self.positions.values()
        )
        return {"cash": self.cash, "equity": equity, "positions": len(self.positions)}
