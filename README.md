# Cephelo_AITrader — Bot per Liquidity Arena 2026 (Track A, Phase I)

> *Cephelo: capo carovana dei Rover, il popolo mercante di Shannara — commercia qualsiasi cosa,
> non fa niente gratis e ha un fiuto infallibile per il profitto.*

Bot di trading algoritmico per la competizione, costruito attorno ai vincoli di gara:

| Vincolo di gara | Come lo gestisce il bot |
|---|---|
| Ordini via RapidX, 1 scrittura / 5 s | Client REST con rate limiter bloccante per endpoint ([rate_limiter.py](aitrade/rate_limiter.py)) |
| Solo 50 perpetual Binance in whitelist | Universo fisso in [symbols.py](aitrade/symbols.py), esclusioni da config |
| Leva max 2x | Leva impostata a 2x, esposizione lorda cap a 1.5x equity |
| **Squalifica a Max Drawdown 20%** | Kill-switch a 3 livelli: 8% (size dimezzate) → 12% (no nuove posizioni) → 15% (chiudi tutto e fermati) |
| Solo AI API dell'organizzatore, 10 $/giorno | Advisor opzionale con budget di chiamate giornaliero ([advisor.py](aitrade/ai/advisor.py)) |
| Uptime ≥ 90% | Loop che non muore mai, stato persistente, wrapper di riavvio [run.ps1](run.ps1) |
| Conferma stato dopo ogni scrittura | Ogni ordine viene verificato via `clientOrderId`; niente retry alla cieca |

**Strategia**: momentum cross-sectional su barre 4h — long sui più forti in trend rialzista,
short sui più deboli in trend ribassista, sizing vol-targeted (ATR), trailing stop 2.5×ATR.
Punteggio gara = Return + Sharpe + MDD + Win Rate: il backtest riporta esattamente queste metriche.

Backtest sui 250 giorni fino al 13/7/2026 (46 simboli, fee e slippage inclusi):
**+26.2%, Sharpe 2.35, MDD 10.1%** — ⚠️ parametri scelti in-sample: è una baseline, non una promessa.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env        # poi compila le chiavi quando le ricevi
```

## Comandi

```powershell
python -m aitrade download-data          # scarica lo storico 4h (cache in data_cache/)
python -m aitrade backtest               # backtest con le metriche di gara
python -m aitrade backtest --refresh     # idem, riscaricando lo storico
python -m aitrade run --mode paper       # paper trading su prezzi reali (nessuna chiave richiesta)
python -m aitrade run --mode live        # trading live su RapidX (richiede .env)
python -m aitrade status                 # equity, drawdown, posizioni, stato AI
python -m aitrade close-all --yes        # EMERGENZA: chiude tutte le posizioni
python -m aitrade reset-kill             # riattiva il bot dopo un hard-kill
.\run.ps1                                # avvio con riavvio automatico (uptime)
```

Test: `python -m pytest tests/ -q` (se fallisce all'avvio per plugin estranei:
`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"` prima del comando).

## Architettura

```
aitrade/
├── config.py            carica config/config.yaml + .env
├── symbols.py           whitelist 50 coppie, conversioni RapidX<->Binance
├── rate_limiter.py      bucket per i limiti di gara (1 ordine/5s ecc.)
├── rapidx/
│   ├── auth.py          firma HMAC-SHA256 (schema documentato dall'advanced API)
│   └── rest.py          tutti gli endpoint REST (ordini, posizioni, account, news)
├── data/klines.py       candele: RapidX se disponibile, fallback Binance pubblico
├── strategy/momentum.py segnali long/short cross-sectional + isteresi di uscita
├── risk.py              drawdown kill-switch, sizing vol-targeted, trailing stop
├── portfolio.py         stato persistente (JSON) + trade log (CSV)
├── broker/
│   ├── paper.py         fill simulati (fee+slippage) su prezzi reali
│   └── rapidx_live.py   ordini veri: LIMIT IOC marketable + fallback MARKET
├── ai/                  advisor a budget + news feed della piattaforma
├── engine.py            loop principale (paper e live)
└── backtest.py          stesso codice strategia/rischio su dati storici
```

Paper, live e backtest usano **la stessa strategia e lo stesso risk manager**: quello
che testi è quello che gira.

## Roadmap gara (date dall'email del comitato)

1. **Subito**: crea il sub-portfolio su RapidX (Assets → Trading → RapidX → +Portfolio)
   e rispondi all'email con l'ID per ricevere i fondi di test.
2. **Appena hai le chiavi** (fase di test, entro il 18/7): mettile nel `.env` e verifica
   l'integrazione live — vedi checklist sotto. I portfolio di test chiudono il **18 luglio**.
3. **Entro il 18/7**: arrivano gli AI token → compila `AI_API_KEY`/`AI_API_BASE_URL`/`AI_MODEL`
   e attiva `ai.enabled: true` nel config.
4. **Dal 20/7**: gara sul main portfolio. Fai girare il bot su una macchina sempre accesa.

## Checklist di verifica live (fase di test — IMPORTANTE)

I docs pubblici non mostrano i payload completi delle risposte, quindi il parsing è
difensivo ma **va verificato con le chiavi di test**:

- [ ] `python -m aitrade status` dopo un giro live: l'equity viene letta bene da
      `GET /trading/account`? (se vedi `equity=0` guarda il log: c'è il payload raw)
- [ ] Il formato posizioni di `GET /trading/position` (campi qty/entryPrice) è corretto?
- [ ] L'endpoint klines RapidX risponde su `rapidx.klines_path`? (se no, il bot usa
      Binance pubblico in automatico — funziona comunque)
- [ ] Un ordine di prova piccolo viene piazzato, confermato via `clientOrderId` e chiuso?
- [ ] `set_leverage` a 2x funziona sui simboli?
- [ ] Confronta la firma HMAC con la CLI ufficiale se ricevi errori 1004/2002:
      `npm install -g @liquiditytech/rapidx-cli@latest` (repo skill: LiquidityTech/ltp-rapidx-skill su GitHub)

## Note operative

- **Uptime ≥ 90%**: un laptop che va in sleep ti squalifica. Usa `.\run.ps1` + disattiva
  sospensione, o meglio un VPS (anche il piano più economico basta: il bot fa poche
  richieste al minuto). Valuta anche di spostare il progetto fuori da OneDrive per la gara:
  la sincronizzazione può bloccare i file di stato.
- **Parametri**: tutti in [config/config.yaml](config/config.yaml). I default vengono da uno
  sweep su 250 giorni: prima della gara rifai `backtest --refresh` e ricontrolla che il MDD
  resti sotto il 12% con dati aggiornati.
- **AI advisor**: scala solo la size delle nuove posizioni (0..1), mai le uscite. Se l'AI API
  non risponde il bot continua da solo. Non usare API AI di terze parti: squalifica.
- **Log**: `logs/aitrade.log` (rotante), trade in `state/trades.csv`, stato in `state/state.json`.
