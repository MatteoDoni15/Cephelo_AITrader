"""Client REST RapidX (https://api.ltp-contest.com).

Regole di gara rispettate qui dentro:
  - rate limit per endpoint (vedi rate_limiter.py), bloccante;
  - niente retry "alla cieca" sugli ordini: un errore di rete su una scrittura
    solleva AmbiguousWriteError e il chiamante DEVE riconciliare via clientOrderId.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from ..rate_limiter import RateLimiter
from .auth import auth_headers

log = logging.getLogger(__name__)

SUCCESS_CODES = {200000, 200}


class RapidXError(RuntimeError):
    def __init__(self, code: Any, message: str, data: Any = None):
        super().__init__(f"RapidX error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class AmbiguousWriteError(RuntimeError):
    """Scrittura (ordine) dal risultato ignoto: riconciliare via query prima di ritentare."""


class RapidXClient:
    def __init__(self, access_key: str, secret_key: str, host: str,
                 limiter: RateLimiter | None = None, timeout: float = 10.0):
        if not access_key or not secret_key:
            raise ValueError("LTP_ACCESS_KEY / LTP_SECRET_KEY mancanti (compila .env)")
        self.access_key = access_key
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self.limiter = limiter or RateLimiter()
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------ core

    @staticmethod
    def _stringify(params: dict | None) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            if isinstance(v, bool):
                out[k] = "true" if v else "false"
            else:
                out[k] = str(v)
        return out

    def _request(self, method: str, path: str, params: dict | None = None,
                 bucket: str = RateLimiter.DEFAULT, retries: int = 2) -> Any:
        params = self._stringify(params)
        is_write = method in ("POST", "PUT", "DELETE")
        attempts = 1 if is_write else retries + 1

        last_exc: Exception | None = None
        for attempt in range(attempts):
            self.limiter.acquire(bucket)
            headers = auth_headers(params, self.access_key, self.secret_key)
            url = self.host + path
            try:
                if method in ("GET", "DELETE"):
                    resp = self.session.request(method, url, params=params,
                                                headers=headers, timeout=self.timeout)
                else:
                    resp = self.session.request(method, url, json=params,
                                                headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                if is_write:
                    raise AmbiguousWriteError(f"{method} {path}: {exc}") from exc
                log.warning("Errore rete %s %s (tentativo %d): %s", method, path, attempt + 1, exc)
                continue

            if resp.status_code == 429:
                raise RapidXError(429, f"rate limit superato su {path}")
            try:
                body = resp.json()
            except ValueError as exc:
                raise RapidXError(resp.status_code, f"risposta non JSON: {resp.text[:200]}") from exc

            code = body.get("code", resp.status_code)
            if code in SUCCESS_CODES:
                return body.get("data")
            raise RapidXError(code, body.get("message", ""), body.get("data"))

        raise RapidXError("network", f"{method} {path} fallito dopo {attempts} tentativi: {last_exc}")

    # --------------------------------------------------------- account/assets

    def get_account(self) -> Any:
        return self._request("GET", "/api/v1/trading/account")

    def get_portfolio_assets(self) -> Any:
        return self._request("GET", "/api/v1/trading/portfolio/assets")

    def get_trading_stats(self, begin: int | None = None, end: int | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/user/tradingStats",
                             {"begin": begin, "end": end})

    def get_fee_rate(self) -> Any:
        return self._request("GET", "/api/v1/trading/userFeeRate")

    # ----------------------------------------------------------------- orders

    def place_order(self, sym: str, side: str, position_side: str, order_type: str,
                    order_qty: str, limit_price: str | None = None,
                    time_in_force: str | None = None, client_order_id: str | None = None) -> Any:
        params = {
            "sym": sym, "side": side, "positionSide": position_side,
            "orderType": order_type, "orderQty": order_qty,
            "limitPrice": limit_price, "timeInForce": time_in_force,
            "clientOrderId": client_order_id,
        }
        return self._request("POST", "/api/v1/trading/order", params,
                             bucket=RateLimiter.ORDER_WRITE)

    def cancel_order(self, sym: str, order_id: str | None = None,
                     client_order_id: str | None = None) -> Any:
        return self._request("DELETE", "/api/v1/trading/order",
                             {"sym": sym, "orderId": order_id, "clientOrderId": client_order_id},
                             bucket=RateLimiter.ORDER_WRITE)

    def cancel_all(self, sym: str | None = None, exchange_type: str | None = None) -> Any:
        return self._request("DELETE", "/api/v1/trading/cancelAll",
                             {"sym": sym, "exchangeType": exchange_type},
                             bucket=RateLimiter.ORDER_WRITE)

    def get_order(self, sym: str | None = None, order_id: str | None = None,
                  client_order_id: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/order",
                             {"sym": sym, "orderId": order_id, "clientOrderId": client_order_id})

    def get_open_orders(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/orders", {"sym": sym})

    def get_executions(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/executions", {"sym": sym})

    # -------------------------------------------------------------- positions

    def get_positions(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/position", {"sym": sym})

    def close_position(self, sym: str, position_side: str) -> Any:
        return self._request("DELETE", "/api/v1/trading/position",
                             {"sym": sym, "positionSide": position_side},
                             bucket=RateLimiter.ORDER_WRITE)

    def close_all_positions(self, exchange_type: str = "PERP") -> Any:
        return self._request("DELETE", "/api/v1/trading/positions",
                             {"exchangeType": exchange_type, "closeAllPos": "true"},
                             bucket=RateLimiter.CLOSE_ALL)

    def get_leverage(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/perp/leverage", {"sym": sym})

    def set_leverage(self, sym: str, leverage: int) -> Any:
        return self._request("POST", "/api/v1/trading/position/leverage",
                             {"sym": sym, "leverage": leverage})

    # ------------------------------------------------------------ market data

    def get_symbol_info(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/trading/sym/info", {"sym": sym},
                             bucket=RateLimiter.MARKET_INFO)

    def get_funding_rate(self, sym: str) -> Any:
        return self._request("GET", "/api/v1/market/fundingRate", {"sym": sym},
                             bucket=RateLimiter.MARKET_INFO)

    def get_mark_price(self, sym: str | None = None) -> Any:
        return self._request("GET", "/api/v1/market/markPrice", {"sym": sym},
                             bucket=RateLimiter.MARKET_INFO)

    def get_klines(self, path: str, sym: str, interval: str, limit: int) -> Any:
        """Endpoint klines: path da config (non documentato ufficialmente nella advanced API)."""
        return self._request("GET", path,
                             {"symbol": sym, "interval": interval, "limit": limit},
                             bucket=RateLimiter.MARKET_INFO)

    # ------------------------------------------------------------------- news

    def query_news(self, start_ms: int | None = None, end_ms: int | None = None,
                   categories: str | None = None, page_size: int = 20) -> Any:
        return self._request("GET", "/api/v1/feeds/queryNews",
                             {"startTime": start_ms, "endTime": end_ms,
                              "categories": categories, "pageSize": page_size})

    def query_hot(self, start_ms: int | None = None, end_ms: int | None = None,
                  page_size: int = 20) -> Any:
        return self._request("GET", "/api/v1/feeds/queryHot",
                             {"startTime": start_ms, "endTime": end_ms, "pageSize": page_size})
