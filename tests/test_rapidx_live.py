"""Test di RapidXBroker.get_positions(): copre il bug scoperto in produzione
sull'account in modalita' NET, dove positionSide torna la stringa "NONE"
invece di LONG/SHORT, e il lato va dedotto dal segno della quantita' grezza."""
from aitrade.broker.rapidx_live import RapidXBroker
from aitrade.config import ExecutionCfg, RiskCfg


class _FakeClient:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return self._positions


def make_broker(positions):
    return RapidXBroker(_FakeClient(positions), ExecutionCfg(), RiskCfg())


def test_uses_explicit_side_when_present():
    broker = make_broker([
        {"sym": "BINANCE_PERP_BTC_USDT", "positionSide": "LONG", "positionQty": "0.5", "entryPrice": "60000"},
    ])
    pos = broker.get_positions()["BINANCE_PERP_BTC_USDT"]
    assert pos.side == "LONG"
    assert pos.qty == 0.5


def test_infers_long_from_positive_qty_when_positionSide_is_none():
    """Riproduce esattamente il caso reale: account NET, positionSide='NONE'."""
    broker = make_broker([
        {"sym": "BINANCE_PERP_AVAX_USDT", "positionSide": "NONE", "positionQty": "12", "entryPrice": "6.41"},
    ])
    pos = broker.get_positions()["BINANCE_PERP_AVAX_USDT"]
    assert pos.side == "LONG"
    assert pos.qty == 12


def test_infers_short_from_negative_qty_when_positionSide_is_none():
    broker = make_broker([
        {"sym": "BINANCE_PERP_DOGE_USDT", "positionSide": "NONE", "positionQty": "-500", "entryPrice": "0.12"},
    ])
    pos = broker.get_positions()["BINANCE_PERP_DOGE_USDT"]
    assert pos.side == "SHORT"
    assert pos.qty == 500  # valore assoluto, il segno serve solo a dedurre il lato


def test_skips_zero_quantity_positions():
    broker = make_broker([
        {"sym": "BINANCE_PERP_ETH_USDT", "positionSide": "NONE", "positionQty": "0", "entryPrice": "1900"},
    ])
    assert broker.get_positions() == {}


def test_skips_entries_without_symbol():
    broker = make_broker([
        {"positionSide": "NONE", "positionQty": "5", "entryPrice": "1"},
    ])
    assert broker.get_positions() == {}
