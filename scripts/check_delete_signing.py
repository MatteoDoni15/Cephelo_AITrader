"""Diagnostica READ-ONLY (rispetto a posizioni/ordini reali): isola perche'
DELETE /api/v1/trading/position torna "RapidX error 2000: API verification
failed" su close_position (vedi log prod: ONDO, 2026-08-07 14:32:59 e 14:46:36).

Usa un simbolo INESISTENTE ("BINANCE_PERP_DOESNOTEXIST_USDT") cosi' anche se la
richiesta passa la verifica non tocca nessuna posizione vera: al massimo torna
un errore "posizione non trovata" invece di "API verification failed", il che
basta a isolare se il problema e' la firma/trasporto oppure altro.

Confronta due varianti di trasporto per lo stesso DELETE:
  A) parametri in query string (quello che fa oggi RapidXClient.close_position)
  B) stessi parametri come body JSON (quello che fa gia' place_order via POST)

Eseguilo dalla root del progetto (venv attivato):

    python scripts/check_delete_signing.py
"""
import json
import os
import sys
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

DUMMY_SYM = "BINANCE_PERP_DOESNOTEXIST_USDT"


def show(label: str, resp: requests.Response) -> None:
    print(f"\n=== {label} (HTTP {resp.status_code}) ===")
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(resp.text[:500])


def main() -> None:
    if not ACCESS_KEY or not SECRET_KEY:
        print("LTP_ACCESS_KEY / LTP_SECRET_KEY mancanti: controlla il .env")
        return

    params = {"sym": DUMMY_SYM, "positionSide": "LONG"}
    url = f"{API_HOST}/api/v1/trading/position"

    # A) query string (come oggi in rapidx_live/rest.py)
    headers_a = auth_headers(params, ACCESS_KEY, SECRET_KEY)
    resp_a = requests.delete(url, params=params, headers=headers_a, timeout=10)
    show("DELETE con parametri in query string", resp_a)

    # B) stessi parametri, ma nel body JSON
    headers_b = auth_headers(params, ACCESS_KEY, SECRET_KEY)
    resp_b = requests.delete(url, json=params, headers=headers_b, timeout=10)
    show("DELETE con parametri in body JSON", resp_b)


if __name__ == "__main__":
    main()
