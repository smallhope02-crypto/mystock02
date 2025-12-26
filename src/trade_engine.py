"""Trade engine coordinating selector, strategy, and broker layers."""

import logging
from typing import Callable, List, Optional, Sequence

from .config import AppConfig
from .kiwoom_client import KiwoomClient
from .paper_broker import PaperBroker
from .selector import UniverseSelector
from .strategy import Order, Strategy

logger = logging.getLogger(__name__)


class TradeEngine:
    """Run trading cycles using either the real client or the paper broker."""

    def __init__(
        self,
        strategy: Strategy,
        selector: UniverseSelector,
        broker_mode: str = "paper",
        kiwoom_client: KiwoomClient | None = None,
        paper_broker: PaperBroker | None = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.strategy = strategy
        self.selector = selector
        self.broker_mode = broker_mode
        self.kiwoom_client = kiwoom_client or KiwoomClient(account_no="00000000")
        self.paper_broker = paper_broker or PaperBroker(initial_cash=self.strategy.initial_cash)
        self.log_fn = log_fn
        if hasattr(self.selector, "attach_client"):
            self.selector.attach_client(self.kiwoom_client)

    def set_mode(self, mode: str) -> None:
        if mode not in {"paper", "real"}:
            raise ValueError("mode must be 'paper' or 'real'")
        self.broker_mode = mode

    def set_paper_cash(self, cash: float) -> None:
        self.paper_broker.set_cash(cash)
        self.strategy.update_parameters(initial_cash=cash)
        self.strategy.positions.clear()

    def update_credentials(self, config: AppConfig) -> None:
        """Forward updated Kiwoom credentials to the client."""

        self.kiwoom_client.update_credentials(config)

    def _active_price_lookup(self, symbol: str) -> float:
        if self.broker_mode == "real":
            return self.kiwoom_client.get_current_price(symbol)
        # paper 모드에서도 가능한 경우 실시간 캐시를 우선 사용한다.
        price = 0.0
        try:
            price = self.kiwoom_client.get_current_price(symbol)
        except Exception:
            price = 0.0
        if price:
            return price
        return self.paper_broker.get_current_price(symbol)

    def run_once(self, condition_name: str) -> None:
        """Execute one scan/evaluation cycle."""
        self.strategy.cash = self._current_cash()
        universe = self.selector.select(condition_name)

        exit_orders = self.strategy.evaluate_exit(self._active_price_lookup)
        self._execute_orders(exit_orders)

        entry_orders = self.strategy.evaluate_entry(universe, self._active_price_lookup)
        self._execute_orders(entry_orders)

        # Keep strategy cash aligned to the active broker's view
        self.strategy.cash = self._current_cash()

    def close_all_positions(self) -> None:
        """Liquidate every position using current prices."""

        orders = self.strategy.close_all_positions(self._active_price_lookup)
        self._execute_orders(orders)
        self.strategy.cash = self._current_cash()

    def _execute_orders(self, orders: Sequence[Order]) -> None:
        for order in orders:
            if self.broker_mode == "real":
                logger.info("[주문] 실거래 모드 — SendOrder 호출 예정 (%s %s x%d)", order.side, order.symbol, order.quantity)
                broker_result = (
                    self.kiwoom_client.send_buy_order(order.symbol, order.quantity, order.price)
                    if order.side == "buy"
                    else self.kiwoom_client.send_sell_order(order.symbol, order.quantity, order.price)
                )
                self.strategy.register_fill(order, broker_result.quantity, broker_result.price)
                logger.info(
                    "Executed %s %s x%d at %.2f (%s)",
                    order.side,
                    order.symbol,
                    broker_result.quantity,
                    broker_result.price,
                    broker_result.status,
                )
                if self.log_fn:
                    self.log_fn(
                        f"[BUY] side={order.side} code={order.symbol} qty={broker_result.quantity} price={broker_result.price:.2f} mode=real"
                    )
                continue

            # paper mode
            logger.info("[주문] 시뮬레이션/더미 모드 — 실주문 전송 없음 (%s %s x%d)", order.side, order.symbol, order.quantity)
            result = (
                self.paper_broker.send_buy_order(order.symbol, order.quantity, order.price)
                if order.side == "buy"
                else self.paper_broker.send_sell_order(order.symbol, order.quantity, order.price)
            )
            filled_qty = getattr(result, "quantity", 0)
            fill_price = getattr(result, "price", order.price)
            self.strategy.register_fill(order, filled_qty, fill_price, update_cash=False)
            logger.info(
                "Executed %s %s x%d at %.2f (%s)", order.side, order.symbol, filled_qty, fill_price, result.status
            )
            if self.log_fn:
                self.log_fn(
                    f"[BUY] side={order.side} code={order.symbol} qty={filled_qty} price={fill_price:.2f} mode=paper"
                )

    def _current_cash(self) -> float:
        if self.broker_mode == "real":
            return float(self.kiwoom_client.get_real_balance())
        return float(self.paper_broker.cash)

    def account_summary(self):
        if self.broker_mode == "real":
            return self.kiwoom_client.get_account_summary()
        return self.paper_broker.get_account_summary()

    def condition_list(self):
        return self.kiwoom_client.get_condition_list()

    # -- Universe plumbing ---------------------------------------------
    def set_external_universe(self, symbols: List[str]) -> None:
        if hasattr(self.selector, "set_external_universe"):
            self.selector.set_external_universe(symbols)

    def add_universe_symbol(self, symbol: str) -> None:
        if hasattr(self.selector, "add_to_universe"):
            self.selector.add_to_universe(symbol)

    def remove_universe_symbol(self, symbol: str) -> None:
        if hasattr(self.selector, "remove_from_universe"):
            self.selector.remove_from_universe(symbol)

    # -- Price lookup --------------------------------------------------
    def get_current_price(self, symbol: str) -> float:
        return self._active_price_lookup(symbol)
