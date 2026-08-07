"""Diagnostica READ-ONLY: mostra il JSON grezzo di GET /api/v1/trading/position
per confermare se ha la stessa forma "dict indicizzato per simbolo" di sym/info
(vedi scripts/check_sym_info.py) — nel qual caso RapidXBroker.get_positions in
aitrade/broker/rapidx_live.py perderebbe le posizioni aperte per lo stesso bug
in _as_list().

Non modifica nulla: una sola GET di lettura firmata con le stesse chiavi del bot.
Eseguilo dalla root del progetto (venv attivato):

    python scripts/check_positions.py
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


def main() -> None:
    if not ACCESS_KEY or not SECRET_KEY:
        print("LTP_ACCESS_KEY / LTP_SECRET_KEY mancanti: controlla il .env")
        return

    params = {}
    headers = auth_headers(params, ACCESS_KEY, SECRET_KEY)
    resp = requests.get(f"{API_HOST}/api/v1/trading/position", params=params, headers=headers, timeout=10)
    print(f"HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(resp.text[:1000])


if __name__ == "__main__":
    main()
