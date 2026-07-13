"""Interfaccia broker: stessa API per paper trading e live RapidX."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Fill:
    sym: str
    side: str        # LONG | SHORT
    action: str      # OPEN | CLOSE
    qty: float
    price: float
    fee: float
    realized_pnl: float = 0.0


@dataclass
class BrokerPosition:
    sym: str
    side: str
    qty: float
    entry_price: float


class Broker(ABC):
    @abstractmethod
    def get_equity(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> dict[str, BrokerPosition]: ...

    @abstractmethod
    def open_position(self, sym: str, side: str, qty: float, ref_price: float) -> Fill | None: ...

    @abstractmethod
    def close_position(self, sym: str, side: str, ref_price: float) -> Fill | None: ...

    @abstractmethod
    def flatten_all(self, ref_prices: dict[str, float]) -> None: ...

    def prepare_symbol(self, sym: str) -> None:
        """Hook pre-trade (es. impostare la leva). Default: nulla."""
