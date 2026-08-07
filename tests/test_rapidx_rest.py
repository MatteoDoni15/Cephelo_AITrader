"""Copre la regressione in produzione: DELETE (close_position, cancel_order,
cancel_all, close_all_positions) andavano in query string come le GET, ma
RapidX verifica la firma sul body JSON per le scritture -> "2000: API
verification failed" a ogni chiusura/cancellazione (confermato con
scripts/check_delete_signing.py). Le GET restano in query string."""
from aitrade.rapidx.rest import RapidXClient


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"code": 200000, "data": {}}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "params": params, "json": json})
        return _FakeResponse()


def make_client():
    client = RapidXClient("access", "secret", "https://api.example.com")
    client.session = _FakeSession()
    return client


def test_get_sends_params_in_query_string():
    client = make_client()
    client.get_positions(sym="BINANCE_PERP_BTC_USDT")
    call = client.session.calls[0]
    assert call["method"] == "GET"
    assert call["params"] == {"sym": "BINANCE_PERP_BTC_USDT"}
    assert call["json"] is None


def test_delete_sends_params_as_json_body():
    client = make_client()
    client.close_position("BINANCE_PERP_BTC_USDT", "LONG")
    call = client.session.calls[0]
    assert call["method"] == "DELETE"
    assert call["json"] == {"sym": "BINANCE_PERP_BTC_USDT", "positionSide": "LONG"}
    assert call["params"] is None


def test_post_sends_params_as_json_body():
    client = make_client()
    client.set_leverage("BINANCE_PERP_BTC_USDT", 2)
    call = client.session.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"sym": "BINANCE_PERP_BTC_USDT", "leverage": "2"}
    assert call["params"] is None
