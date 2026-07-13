"""Rate limiter per i limiti (stringenti) della competizione.

Limiti documentati:
  - POST/PUT/DELETE /trading/order ........ 1 richiesta / 5 s
  - DELETE /trading/positions ............. 1 richiesta / 10 s
  - fundingRate / markPrice / sym info .... 3 richieste / 10 s
  - tutto il resto ........................ "produzione x 1/5" (prudenza: 1/s)
"""
from __future__ import annotations

import threading
import time


class Bucket:
    """Enforce a minimum interval between calls; blocks (sleeps) until allowed."""

    def __init__(self, min_interval_sec: float, clock=time.monotonic, sleeper=time.sleep):
        self.min_interval = min_interval_sec
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                if now >= self._next_allowed:
                    self._next_allowed = now + self.min_interval
                    return
                wait = self._next_allowed - now
            self._sleep(wait)


class RateLimiter:
    ORDER_WRITE = "order_write"
    CLOSE_ALL = "close_all"
    MARKET_INFO = "market_info"
    DEFAULT = "default"

    def __init__(self, clock=time.monotonic, sleeper=time.sleep):
        self._buckets = {
            self.ORDER_WRITE: Bucket(5.0, clock, sleeper),
            self.CLOSE_ALL: Bucket(10.0, clock, sleeper),
            self.MARKET_INFO: Bucket(10.0 / 3.0, clock, sleeper),
            self.DEFAULT: Bucket(1.0, clock, sleeper),
        }

    def acquire(self, bucket: str) -> None:
        self._buckets.get(bucket, self._buckets[self.DEFAULT]).acquire()
