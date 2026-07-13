"""Caricamento configurazione: config/config.yaml + variabili d'ambiente (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class LoopCfg:
    manage_interval_sec: int = 60
    signal_grace_sec: int = 120


@dataclass
class StrategyCfg:
    ema_fast: int = 50
    ema_slow: int = 200
    momentum_bars: int = 42
    min_abs_momentum: float = 0.02
    atr_period: int = 14
    max_longs: int = 4
    max_shorts: int = 2
    allow_short: bool = True
    entry_rank: int = 4
    exit_rank: int = 10
    warmup_bars: int = 220
    min_atr_pct: float = 0.003
    max_atr_pct: float = 0.15


@dataclass
class RiskCfg:
    leverage: int = 2
    risk_per_trade: float = 0.0075
    stop_atr_mult: float = 3.0
    max_position_notional_pct: float = 0.35
    max_gross_leverage: float = 1.5
    warn_drawdown: float = 0.08
    soft_kill_drawdown: float = 0.12
    hard_kill_drawdown: float = 0.15


@dataclass
class ExecutionCfg:
    order_style: str = "limit_ioc"
    slippage_tolerance_bps: float = 15.0
    max_order_attempts: int = 4
    paper_fee_bps: float = 5.0
    paper_slippage_bps: float = 3.0


@dataclass
class AiCfg:
    enabled: bool = False
    provider: str = "openai"
    max_calls_per_day: int = 3
    interval_hours: int = 8
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@dataclass
class RapidXCfg:
    access_key: str = ""
    secret_key: str = ""
    api_host: str = "https://api.ltp-contest.com"
    klines_path: str = "/api/v1/market/klines"


@dataclass
class DataCfg:
    cache_dir: str = "data_cache"
    history_bars: int = 1500


@dataclass
class PathsCfg:
    state_file: str = "state/state.json"
    trades_file: str = "state/trades.csv"
    log_file: str = "logs/aitrade.log"


@dataclass
class Config:
    mode: str = "paper"
    timeframe: str = "4h"
    exclude: list[str] = field(default_factory=list)
    loop: LoopCfg = field(default_factory=LoopCfg)
    strategy: StrategyCfg = field(default_factory=StrategyCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    execution: ExecutionCfg = field(default_factory=ExecutionCfg)
    ai: AiCfg = field(default_factory=AiCfg)
    rapidx: RapidXCfg = field(default_factory=RapidXCfg)
    data: DataCfg = field(default_factory=DataCfg)
    paths: PathsCfg = field(default_factory=PathsCfg)
    root: Path = field(default_factory=Path.cwd)

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p


def _build(dc_cls, section: dict):
    known = {f for f in dc_cls.__dataclass_fields__}
    return dc_cls(**{k: v for k, v in (section or {}).items() if k in known})


def load_config(root: Path | None = None) -> Config:
    root = Path(root) if root else Path.cwd()
    load_dotenv(root / ".env")

    cfg_file = root / "config" / "config.yaml"
    raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    raw = raw or {}

    cfg = Config(
        mode=raw.get("mode", "paper"),
        timeframe=raw.get("timeframe", "4h"),
        exclude=(raw.get("universe") or {}).get("exclude", []) or [],
        loop=_build(LoopCfg, raw.get("loop")),
        strategy=_build(StrategyCfg, raw.get("strategy")),
        risk=_build(RiskCfg, raw.get("risk")),
        execution=_build(ExecutionCfg, raw.get("execution")),
        ai=_build(AiCfg, raw.get("ai")),
        rapidx=_build(RapidXCfg, raw.get("rapidx")),
        data=_build(DataCfg, raw.get("data")),
        paths=_build(PathsCfg, raw.get("paths")),
        root=root,
    )

    cfg.rapidx.access_key = os.getenv("LTP_ACCESS_KEY", "")
    cfg.rapidx.secret_key = os.getenv("LTP_SECRET_KEY", "")
    cfg.rapidx.api_host = os.getenv("LTP_API_HOST", cfg.rapidx.api_host)
    cfg.ai.api_key = os.getenv("AI_API_KEY", "")
    cfg.ai.base_url = os.getenv("AI_API_BASE_URL", "")
    cfg.ai.model = os.getenv("AI_MODEL", cfg.ai.model)
    return cfg
