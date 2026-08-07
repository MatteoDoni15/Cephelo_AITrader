"""Diagnostica READ-ONLY: mostra il JSON grezzo di GET /api/v1/trading/sym/info
per i simboli che stanno fallendo con 401013 ("quantity precision"), cosi' si
vede il nome vero del campo di step/precisione quantita' che RapidX restituisce
per quei simboli (vedi RapidXBroker.load_symbol_rules in aitrade/broker/rapidx_live.py).

Non piazza ordini né modifica stato: e' una sola GET pubblica di lettura firmata
con le stesse chiavi del bot. Eseguilo dalla root del progetto:

    python scripts/check_sym_info.py
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from aitrade.rapidx.auth import auth_headers  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

ACCESS_KEY = os.getenv("LTP_ACCESS_KEY", "")
SECRET_KEY = os.getenv("LTP_SECRET_KEY", "")
API_HOST = os.getenv("LTP_API_HOST", "https://api.ltp-contest.com")

SYMBOLS = [
    "BINANCE_PERP_UNI_USDT",
    "BINANCE_PERP_CC_USDT",
    "BINANCE_PERP_DEXE_USDT",
    "BINANCE_PERP_ADA_USDT",
    "BINANCE_PERP_ALGO_USDT",
    "BINANCE_PERP_XMR_USDT",
    "BINANCE_PERP_ZEC_USDT",
    "BINANCE_PERP_BTC_USDT",  # controllo: un simbolo che (presumibilmente) non fallisce
]

# Stesso bucket "market_info" del bot vero: 3 richieste / 10s (rate_limiter.py).
MIN_INTERVAL_SEC = 10.0 / 3.0
MAX_RETRIES_ON_429 = 3


def fetch_sym_info(sym: str) -> requests.Response:
    params = {"sym": sym}
    headers = auth_headers(params, ACCESS_KEY, SECRET_KEY)
    for attempt in range(1, MAX_RETRIES_ON_429 + 1):
        resp = requests.get(f"{API_HOST}/api/v1/trading/sym/info", params=params, headers=headers, timeout=10)
        if resp.status_code != 429:
            return resp
        wait = MIN_INTERVAL_SEC * attempt
        print(f"  (429 su {sym}, tentativo {attempt}/{MAX_RETRIES_ON_429}: aspetto {wait:.1f}s)")
        time.sleep(wait)
    return resp


def main() -> None:
    if not ACCESS_KEY or not SECRET_KEY:
        print("LTP_ACCESS_KEY / LTP_SECRET_KEY mancanti: controlla il .env")
        return

    for i, sym in enumerate(SYMBOLS):
        if i > 0:
            time.sleep(MIN_INTERVAL_SEC)
        resp = fetch_sym_info(sym)
        print(f"\n=== {sym} (HTTP {resp.status_code}) ===")
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(resp.text[:500])


if __name__ == "__main__":
    main()
