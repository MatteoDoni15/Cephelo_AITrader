"""Firma HMAC-SHA256 per l'API RapidX (schema V2, dai docs advanced-api).

Algoritmo documentato:
  1. ordina i parametri alfabeticamente:  key1=val1&key2=val2&...
  2. accoda "&" + timestamp (Unix seconds, stringa)
  3. HMAC-SHA256 con la Secret Key, hex-encoded

Headers richiesti: X-MBX-APIKEY, nonce (=timestamp), signature, Content-Type.
"""
from __future__ import annotations

import hashlib
import hmac
import time


def sign(params: dict, secret_key: str, timestamp: str | None = None) -> tuple[str, str]:
    """Restituisce (signature_hex, timestamp). `params` con valori gia' stringhe."""
    ts = timestamp or str(int(time.time()))
    sorted_payload = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    payload = (sorted_payload + "&" if sorted_payload else "&") + ts
    sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return sig, ts


def auth_headers(params: dict, access_key: str, secret_key: str) -> dict:
    sig, ts = sign(params, secret_key)
    return {
        "X-MBX-APIKEY": access_key,
        "nonce": ts,
        "signature": sig,
        "Content-Type": "application/json",
    }


def ws_login_sign(secret_key: str, timestamp: str | None = None) -> tuple[str, str]:
    """Firma per il login sul WebSocket privato: HMAC(timestamp + 'GET' + '/users/self/verify')."""
    ts = timestamp or str(int(time.time()))
    message = ts + "GET" + "/users/self/verify"
    sig = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return sig, ts
