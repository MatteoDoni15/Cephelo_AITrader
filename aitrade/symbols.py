"""Track A Phase I whitelist: 50 Binance USDT-margined perpetuals (fixed list).

Symbol format on RapidX: BINANCE_PERP_{BASE}_USDT  (e.g. BINANCE_PERP_BTC_USDT).
"""
from __future__ import annotations

WHITELIST_BASES: list[str] = [
    "BTC", "ETH", "BNB", "USDC", "XRP", "SOL", "TRX", "HYPE", "DOGE", "ZEC",
    "XLM", "ADA", "XMR", "LINK", "CC", "BCH", "LTC", "HBAR", "SUI", "LAB",
    "AVAX", "XAUT", "NEAR", "1000SHIB", "M", "TAO", "UNI", "PAXG", "WLFI", "ASTER",
    "ONDO", "WLD", "DOT", "SKY", "AAVE", "MORPHO", "ICP", "ETC", "DEXE", "1000PEPE",
    "QNT", "BEAT", "KAS", "STABLE", "RENDER", "ATOM", "JUP", "POL", "ALGO", "JST",
]

PREFIX = "BINANCE_PERP_"
QUOTE = "USDT"


def to_rapidx(base: str) -> str:
    """'BTC' -> 'BINANCE_PERP_BTC_USDT'"""
    return f"{PREFIX}{base}_{QUOTE}"


def to_base(sym: str) -> str:
    """'BINANCE_PERP_BTC_USDT' -> 'BTC'"""
    return sym.removeprefix(PREFIX).removesuffix(f"_{QUOTE}")


def to_binance(sym: str) -> str:
    """'BINANCE_PERP_BTC_USDT' -> 'BTCUSDT' (Binance USDT-M futures ticker)."""
    return to_base(sym) + QUOTE


def universe(exclude: list[str] | None = None) -> list[str]:
    """Whitelist in formato RapidX, meno le basi escluse da config."""
    excl = {e.upper() for e in (exclude or [])}
    return [to_rapidx(b) for b in WHITELIST_BASES if b.upper() not in excl]
