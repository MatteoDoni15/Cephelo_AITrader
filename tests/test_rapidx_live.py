"""Test di RapidXBroker.get_positions(): copre il bug scoperto in produzione
sull'account in modalita' NET, dove positionSide torna la stringa "NONE"
invece di LONG/SHORT, e il lato va dedotto dal segno della quantita' grezza."""
from aitrade.broker.rapidx_live import RapidXBroker
from aitrade.config import ExecutionCfg, RiskCfg


class _FakeClient:
    def __init__(self, positions=None, symbol_info=None):
        self._positions = positions
        self._symbol_info = symbol_info

    def get_positions(self):
        return self._positions

    def get_symbol_info(self):
        return self._symbol_info


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


def test_load_symbol_rules_handles_dict_keyed_by_symbol():
    """Riproduce la forma reale di GET /trading/sym/info scoperta in produzione:
    un dict indicizzato per simbolo, non una lista di oggetti-regola."""
    broker = RapidXBroker(_FakeClient(symbol_info={
        "BINANCE_PERP_UNI_USDT": {
            "sym": "BINANCE_PERP_UNI_USDT", "qtyPrecision": "0",
            "lotSize": "1", "tickSize": "0.0010", "minNotional": "5",
        },
        "BINANCE_PERP_DEXE_USDT": {
            "sym": "BINANCE_PERP_DEXE_USDT", "qtyPrecision": "2",
            "lotSize": "0.01", "tickSize": "0.001000", "minNotional": "5",
        },
    }), ExecutionCfg(), RiskCfg())

    broker.load_symbol_rules()

    assert broker.round_qty("BINANCE_PERP_UNI_USDT", 12.789) == 12
    assert broker.round_qty("BINANCE_PERP_DEXE_USDT", 3.456) == 3.45
