"""Trade engine coordinating selector, strategy, and broker layers."""

import datetime
import logging
try:  # tzdata optional on Windows
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
from typing import Callable, Dict, List, Optional, Sequence

from .config import AppConfig
from .kiwoom_client import KiwoomClient
from .paper_broker import PaperBroker
from .paper_restore import restore_paper_state_from_db
from .selector import UniverseSelector
from .strategy import Order, Strategy
from .price_tick import shift_price_by_ticks
from .paper_broker import PaperPosition
from .strategy import Position

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
        self.rebuy_after_sell_today: bool = False
        self.max_buy_per_symbol_today: int = 1
        self.bought_today_symbols: set[str] = set()
        self.buy_count_today: Dict[str, int] = {}
        self._today: datetime.date | None = None
        self._tz = self._get_kst_timezone()
        self.buy_order_mode: str = "market"
        self.buy_price_offset_ticks: int = 0
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

    def set_buy_pricing(self, mode: str, offset_ticks: int) -> None:
        """Configure how entry prices are derived for new buys."""

        if mode not in {"market", "limit"}:
            raise ValueError("buy order mode must be 'market' or 'limit'")
        self.buy_order_mode = mode
        self.buy_price_offset_ticks = int(offset_ticks)

    def set_buy_limits(self, rebuy_after_sell_today: bool, max_buy_per_symbol_today: int) -> None:
        self.rebuy_after_sell_today = bool(rebuy_after_sell_today)
        self.max_buy_per_symbol_today = int(max_buy_per_symbol_today)

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

    def run_once(self, condition_name: str, allow_orders: bool = True) -> None:
        """Execute one scan/evaluation cycle.

        Parameters
        ----------
        condition_name: str
            Label passed to the selector.
        allow_orders: bool
            When False the evaluation still runs, but order execution is skipped. This
            lets callers arm monitoring before the market opens without risking
            inadvertent SendOrder calls.
        """

        self._reset_daily_if_needed()
        self.strategy.cash = self._current_cash()
        raw_universe = list(self.selector.select(condition_name))
        universe = [s for s in raw_universe if self._can_buy(s)]
        if self.log_fn:
            self.log_fn(
                f"[ENGINE] universe_raw={len(raw_universe)} filtered={len(universe)} allow_orders={allow_orders}"
            )

        exit_orders = self.strategy.evaluate_exit(self._active_price_lookup)
        if self.log_fn:
            self.log_fn(f"[ENGINE] exit_orders={len(exit_orders)}")
        self._execute_orders(exit_orders, allow_orders=allow_orders)

        entry_orders = self.strategy.evaluate_entry(universe, self._entry_price_lookup)
        if self.log_fn:
            debug = getattr(self.strategy, "last_entry_debug", {}) or {}
            self.log_fn(
                f"[ENGINE] entry_orders={len(entry_orders)} budget_per_slot={debug.get('budget_per_slot')} skips={debug.get('skip_counts')} samples={debug.get('samples')}"
            )
        self._execute_orders(entry_orders, allow_orders=allow_orders)

        # Keep strategy cash aligned to the active broker's view
        self.strategy.cash = self._current_cash()

    def close_all_positions(self) -> None:
        """Liquidate every position using current prices."""

        orders = self.strategy.close_all_positions(self._active_price_lookup)
        self._execute_orders(orders)
        self.strategy.cash = self._current_cash()

    def _execute_orders(self, orders: Sequence[Order], allow_orders: bool = True) -> None:
        for order in orders:
            if not allow_orders:
                if self.log_fn:
                    self.log_fn(
                        f"[ORDER] side={order.side} code={order.symbol} qty={order.quantity} price={order.price:.2f} mode={self.broker_mode} status=skipped (orders disabled)"
                    )
                continue
            if self.broker_mode == "real":
                logger.info("[주문] 실거래 모드 — SendOrder 호출 예정 (%s %s x%d)", order.side, order.symbol, order.quantity)
                if order.side == "buy":
                    hogagb = "03" if self.buy_order_mode == "market" else "00"
                    send_price = 0 if hogagb == "03" else order.price
                    broker_result = self.kiwoom_client.send_buy_order(
                        order.symbol, order.quantity, send_price, hogagb=hogagb, expected_price=order.price
                    )
                else:
                    broker_result = self.kiwoom_client.send_sell_order(order.symbol, order.quantity, order.price)
                if broker_result.status == "accepted" and broker_result.quantity:
                    self.strategy.register_fill(order, broker_result.quantity, broker_result.price)
                    if order.side == "buy":
                        self._record_buy_fill(order.symbol)
                elif broker_result.status == "blocked" and self.log_fn:
                    reason = ""
                    if hasattr(self.kiwoom_client, "get_last_block_reason"):
                        reason = self.kiwoom_client.get_last_block_reason()
                    self.log_fn(f"[ORDER] blocked real order: {reason or 'unknown'}")
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
                        f"[ORDER] side={order.side} code={order.symbol} qty={broker_result.quantity} price={broker_result.price:.2f} mode=real status={broker_result.status}"
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
            if order.side == "buy" and filled_qty > 0:
                self._record_buy_fill(order.symbol)
            logger.info(
                "Executed %s %s x%d at %.2f (%s)", order.side, order.symbol, filled_qty, fill_price, result.status
            )
            if self.log_fn:
                self.log_fn(
                    f"[ORDER] side={order.side} code={order.symbol} qty={filled_qty} price={fill_price:.2f} mode=paper"
                )

    def _current_cash(self) -> float:
        if self.broker_mode == "real":
            return float(self.kiwoom_client.get_real_balance())
        return float(self.paper_broker.cash)

    def _reset_daily_if_needed(self) -> None:
        today = datetime.datetime.now(self._tz).date()
        if self._today != today:
            self._today = today
            self.bought_today_symbols.clear()
            self.buy_count_today.clear()

    def _record_buy_fill(self, symbol: str) -> None:
        self._reset_daily_if_needed()
        self.bought_today_symbols.add(symbol)
        self.buy_count_today[symbol] = self.buy_count_today.get(symbol, 0) + 1

    def _can_buy(self, symbol: str) -> bool:
        if symbol in self.strategy.positions:
            if self.log_fn:
                self.log_fn(f"[ORDER] skip {symbol}: already_holding")
            return False
        self._reset_daily_if_needed()
        if not self.rebuy_after_sell_today and symbol in self.bought_today_symbols:
            if self.log_fn:
                self.log_fn(f"[ORDER] skip {symbol}: bought_today and rebuy disabled")
            return False
        max_n = self.max_buy_per_symbol_today
        if max_n > 0:
            count = self.buy_count_today.get(symbol, 0)
            if count >= max_n:
                if self.log_fn:
                    self.log_fn(f"[ORDER] skip {symbol}: max_buy_count_reached({count}/{max_n})")
                return False
        return True

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

    def _get_kst_timezone(self) -> datetime.tzinfo:
        if ZoneInfo:
            try:
                return ZoneInfo("Asia/Seoul")
            except Exception:
                pass
        return datetime.timezone(datetime.timedelta(hours=9))

    # -- Pricing helpers -----------------------------------------------
    def _entry_price_lookup(self, symbol: str) -> float:
        """Return the entry price adjusted for the configured buy mode."""

        base = self._active_price_lookup(symbol)
        if self.buy_order_mode == "limit":
            return float(shift_price_by_ticks(base, self.buy_price_offset_ticks))
        return base

    def restore_paper_state_from_history(
        self,
        history_store,
        start_ts: str,
        end_ts: str,
        fallback_cash: float,
        log_prefix: str = "PAPER_RESTORE",
    ) -> dict:
        """
        trade_history.db 기반으로 paper_broker + strategy + 당일 buy_count를 동기화.
        """
        if self.broker_mode != "paper":
            return {"ok": False, "reason": "not paper mode"}

        db_path = getattr(history_store, "db_path", None)
        if not db_path:
            return {"ok": False, "reason": "history_store.db_path missing"}

        result = restore_paper_state_from_db(db_path, start_ts, end_ts, fallback_cash)

        if result.ok:
            self.paper_broker.cash = float(result.cash)
            self.paper_broker.positions.clear()
            for sym, pos in result.positions.items():
                self.paper_broker.positions[sym] = PaperPosition(
                    symbol=sym, quantity=int(pos.qty), average_price=float(pos.avg_price)
                )

            self.strategy.cash = float(result.cash)
            self.strategy.positions.clear()
            now = datetime.datetime.utcnow()
            for sym, pos in result.positions.items():
                self.strategy.positions[sym] = Position(
                    symbol=sym,
                    quantity=int(pos.qty),
                    entry_price=float(pos.avg_price),
                    highest_price=float(pos.avg_price),
                    entry_time=now,
                )

            self._reset_daily_if_needed()
            self.bought_today_symbols.clear()
            self.buy_count_today.clear()
            for sym, cnt in (result.buy_count_today or {}).items():
                if cnt > 0:
                    self.bought_today_symbols.add(sym)
                    self.buy_count_today[sym] = int(cnt)

        payload = {
            "ok": result.ok,
            "base_cash": result.base_cash,
            "cash": result.cash,
            "positions": {k: {"qty": v.qty, "avg": v.avg_price} for k, v in result.positions.items()},
            "buy_count_today": result.buy_count_today,
            "warnings": result.warnings,
            "scanned_events": result.scanned_events,
            "used_reset": result.used_reset,
            "range": {"start": start_ts, "end": end_ts},
        }
        return payload
