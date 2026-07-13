import hashlib
import hmac

from aitrade.rapidx.auth import auth_headers, sign


SECRET = "test-secret-key"


def _expected(payload: str) -> str:
    return hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def test_sign_sorts_params_alphabetically():
    sig, ts = sign({"sym": "BINANCE_PERP_BTC_USDT", "orderQty": "0.1"}, SECRET, timestamp="1700000000")
    assert ts == "1700000000"
    # ordinati: orderQty prima di sym, poi "&" + timestamp
    assert sig == _expected("orderQty=0.1&sym=BINANCE_PERP_BTC_USDT&1700000000")


def test_sign_empty_params_uses_ampersand_prefix():
    sig, _ = sign({}, SECRET, timestamp="1700000000")
    assert sig == _expected("&1700000000")


def test_auth_headers_complete():
    h = auth_headers({"a": "1"}, "AK", SECRET)
    assert h["X-MBX-APIKEY"] == "AK"
    assert h["Content-Type"] == "application/json"
    assert h["nonce"].isdigit()
    assert len(h["signature"]) == 64  # sha256 hex
