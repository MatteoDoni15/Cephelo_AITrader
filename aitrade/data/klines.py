"""Servizio klines.

Sorgente primaria: endpoint klines RapidX (path da config; la CLI ufficiale lo espone
ma la advanced API non lo documenta). Se non disponibile -> fallback automatico sui
dati pubblici Binance USDT-M futures: sono gli stessi mercati (BINANCE_PERP_*), e la
regola di gara vincola l'ESECUZIONE su RapidX, non la fonte dei dati per i segnali.

Le candele restituite sono sempre SOLO candele chiuse (l'ultima riga parziale viene
scartata) per evitare segnali su barre incomplete.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

from .. import symbols

log = logging.getLogger(__name__)

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"
COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000,
}


def interval_ms(interval: str) -> int:
    return _INTERVAL_MS[interval]


class KlineService:
    def __init__(self, cache_dir: str | Path, rapidx_client=None,
                 rapidx_klines_path: str = "", pace_sec: float = 0.15):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rapidx = rapidx_client
        self.rapidx_path = rapidx_klines_path
        self.pace_sec = pace_sec
        self._rapidx_klines_ok: bool | None = None  # None = mai provato
        self.session = requests.Session()

    # ------------------------------------------------------------- fetch live

    def fetch(self, sym: str, interval: str, limit: int) -> pd.DataFrame:
        """Ultime `limit` candele CHIUSE per un simbolo RapidX (BINANCE_PERP_X_USDT)."""
        df = None
        if self.rapidx is not None and self._rapidx_klines_ok is not False:
            try:
                raw = self.rapidx.get_klines(self.rapidx_path, sym, interval, limit + 1)
                df = self._parse_generic(raw)
                self._rapidx_klines_ok = True
            except Exception as exc:
                if self._rapidx_klines_ok is None:
                    log.warning("Klines RapidX non disponibili (%s): uso dati pubblici Binance", exc)
                self._rapidx_klines_ok = False
        if df is None or df.empty:
            df = self._fetch_binance(symbols.to_binance(sym), interval, limit + 1)
        return self._drop_open_candle(df, interval)

    def _fetch_binance(self, ticker: str, interval: str, limit: int) -> pd.DataFrame:
        time.sleep(self.pace_sec)  # gentile con l'API pubblica: ~6-7 req/s max
        resp = self.session.get(
            BINANCE_FAPI,
            params={"symbol": ticker, "interval": interval, "limit": min(limit, 1500)},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        df = pd.DataFrame(
            [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
             for r in rows],
            columns=COLUMNS,
        )
        return df

    @staticmethod
    def _parse_generic(raw) -> pd.DataFrame:
        """Parser difensivo per l'endpoint klines RapidX (formato da verificare in test)."""
        if raw is None:
            return pd.DataFrame(columns=COLUMNS)
        items = raw.get("list", raw) if isinstance(raw, dict) else raw
        parsed = []
        for r in items:
            if isinstance(r, dict):
                parsed.append([
                    int(r.get("openTime") or r.get("time") or r.get("t") or 0),
                    float(r.get("open") or r.get("o") or 0),
                    float(r.get("high") or r.get("h") or 0),
                    float(r.get("low") or r.get("l") or 0),
                    float(r.get("close") or r.get("c") or 0),
                    float(r.get("volume") or r.get("v") or 0),
                ])
            else:  # formato array stile Binance
                parsed.append([int(r[0]), float(r[1]), float(r[2]),
                               float(r[3]), float(r[4]), float(r[5])])
        return pd.DataFrame(parsed, columns=COLUMNS)

    @staticmethod
    def _drop_open_candle(df: pd.DataFrame, interval: str) -> pd.DataFrame:
        if df.empty:
            return df
        now_ms = int(time.time() * 1000)
        step = interval_ms(interval)
        df = df[df["open_time"] + step <= now_ms].reset_index(drop=True)
        return df

    # ---------------------------------------------------------------- storico

    def download_history(self, syms: list[str], interval: str, bars: int) -> dict[str, pd.DataFrame]:
        """Scarica e mette in cache lo storico (per backtest/warmup). Usa Binance pubblico."""
        out: dict[str, pd.DataFrame] = {}
        for sym in syms:
            try:
                df = self._fetch_binance(symbols.to_binance(sym), interval, bars)
                df = self._drop_open_candle(df, interval)
                out[sym] = df
                df.to_csv(self._cache_file(sym, interval), index=False)
                log.info("Storico %s: %d barre", sym, len(df))
            except Exception as exc:
                log.warning("Storico %s non disponibile: %s (simbolo saltato)", sym, exc)
        return out

    def load_cached(self, syms: list[str], interval: str) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for sym in syms:
            f = self._cache_file(sym, interval)
            if not f.exists():
                continue
            try:
                df = pd.read_csv(f)
                if not df.empty:
                    out[sym] = df
            except Exception as exc:
                log.warning("Cache %s corrotta (%s): la ignoro", f.name, exc)
        return out

    def _cache_file(self, sym: str, interval: str) -> Path:
        return self.cache_dir / f"{sym}_{interval}.csv"
