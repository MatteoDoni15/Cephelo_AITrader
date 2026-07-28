<p align="center">
  <img src="assets/Logo.png" alt="Cephelo AITrader" width="300">
</p>

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

Richiede **Python >= 3.11** (per il framework degli agenti AI).

```powershell
pip install -r requirements.txt
copy .env.example .env        # poi compila le chiavi quando le ricevi
```

L'installazione include il [BeeAI Framework](https://github.com/i-am-bee/beeai-framework)
(agenti + protocollo A2A + adapter MiniMax), LangChain (ricerca DuckDuckGo) e
`transformers`/`torch` (classificatore locale anti prompt-injection): il
download puo' richiedere qualche minuto e qualche centinaio di MB in piu'
rispetto al solo bot di trading. Tutto questo serve solo all'AI advisor
opzionale (`ai.enabled`) — il bot funziona in paper/backtest/live anche
senza, o se questi pacchetti non sono installati.

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
python -m aitrade ai-budget              # spesa reale sull'AI Gateway (GET /key/info)
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
├── ai/
│   ├── advisor.py       client A2A verso lo Strategy Agent (mai l'AI Gateway direttamente)
│   └── news.py          news feed della piattaforma RapidX
├── agents/              Signal Agent + Strategy Agent (BeeAI, A2A, localhost) — vedi sotto
├── engine.py            loop principale (paper e live)
└── backtest.py          stesso codice strategia/rischio su dati storici
```

Paper, live e backtest usano **la stessa strategia e lo stesso risk manager**: quello
che testi è quello che gira.

## Agenti AI (Signal + Strategy, opzionale)

L'AI advisor non parla piu' direttamente con l'AI Gateway: e' diviso in due
piccoli agenti [BeeAI](https://github.com/i-am-bee/beeai-framework), avviati
come processi separati e raggiunti via protocollo **A2A su localhost**
(mai esposti in rete):

```
engine.py --(A2A)--> Strategy Agent --(A2A)--> Signal Agent
                          |
                          v
                 AI Gateway organizzatore
                 (MiniMax-M3, adapter BeeAI nativo)
```

- **Signal Agent** (`agents/signal_agent.py`): ricerca web + news via
  LangChain/DuckDuckGo (gratuita, nessuna chiave). Non genera nulla, non
  detiene credenziali — la sua unica responsabilita' e' passare al filtro
  prompt-injection locale (`agents/injection_scanner.py`, un classificatore
  HuggingFace che gira in CPU) tutto il testo esterno prima di restituirlo.
- **Strategy Agent** (`agents/strategy_agent.py`): l'unico posto che detiene
  `AI_API_KEY`/`AI_API_BASE_URL`/`AI_MODEL` e chiama l'AI Gateway
  dell'organizzatore (adapter MiniMax nativo di BeeAI). Interroga il Signal
  Agent per contesto fresco, scansiona anche le headline della piattaforma
  RapidX (difesa in profondita'), e fa **una sola chiamata al modello per
  valutazione**, con output vincolato allo schema `RiskAssessment`
  (`risk_multiplier` 0..1, `regime`, `comment` — validato in generazione,
  non solo dopo).
- **Advisor** (`ai/advisor.py`, nel processo principale): client leggero
  che interroga lo Strategy Agent via A2A. Non detiene ne' le credenziali
  RapidX (quelle restano solo in `engine.py`) ne' quelle dell'AI Gateway.

Proprieta' invariate rispetto alla versione precedente: **una sola chiamata
AI per valutazione** (budget $10/giorno rispettato), il multiplier scala
solo la size delle nuove posizioni (mai aperture/chiusure dirette), e
qualunque errore in qualsiasi punto della catena (agente giu', timeout,
output fuori schema) fa ripiegare su multiplier invariato — mai un punto di
rottura per il trading.

**Controllo budget reale** (`agents/budget_guard.py`): il conteggio locale
(`max_calls_per_day`) non vede i retry sullo schema ne' le chiamate di
eventuali compagni di squadra sulla stessa chiave — solo l'organizzatore sa
la spesa vera. Prima di ogni chiamata, lo Strategy Agent interroga
`GET {AI_API_BASE_URL}/key/info`: se `spend` supera `budget_safety_margin`
(default 90% di `max_budget`, in `config.yaml`) la chiamata viene saltata
con errore esplicito invece di rischiare di sforare. A differenza del resto
della pipeline questo controllo e' fail-*aperto*: se `/key/info` non
risponde, si procede comunque (il costo di bloccare per errore e' peggiore
del costo di un tentativo in piu'). Controllo manuale in qualsiasi momento:
`python -m aitrade ai-budget`.

**Correlazione decisione-AI <-> ordine** (richiesta dal regolamento: "the
Organizer will verify AI usage by analyzing the correlation between AI
decision logs and executed trading orders"): ogni trade **OPEN** in
`state/trades.csv` porta le colonne `ai_multiplier`/`ai_trace_id` con il
multiplier e il trace_id in vigore in quel momento (join diretto con
`logs/traces.jsonl` per il ciclo di valutazione completo). I trade **CLOSE**
le lasciano vuote per costruzione — l'AI non tocca mai le uscite, e il log
lo dimostra invece di limitarsi ad affermarlo.

Avvio: `python -m aitrade.agents.run_agents` (gia' incluso in `run.ps1`).
Se questi processi non partono o muoiono, il bot principale continua
normalmente senza il multiplier AI.

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
- **AI advisor**: scala solo la size delle nuove posizioni (0..1), mai le uscite. Se lo
  Strategy Agent non risponde (o non e' avviato) il bot continua da solo. L'unica AI
  generativa usata e' MiniMax-M3 via l'AI Gateway dell'organizzatore (vedi sezione
  "Agenti AI" sopra) — non usare API AI di terze parti: squalifica.
- **Log**: `logs/aitrade.log` (rotante), trade in `state/trades.csv`, stato in `state/state.json`.
  Gli agenti AI (`agents/run_agents.py`) loggano su stdout del proprio processo.
