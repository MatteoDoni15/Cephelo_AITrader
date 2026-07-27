"""Avvia Signal Agent e Strategy Agent come processi separati (A2A, localhost).

Ognuno e' un piccolo processo indipendente: se uno muore viene riavviato
senza toccare l'altro. Il bot principale (engine.py) NON dipende da questi
processi per funzionare: se sono giu' o non partono, l'Advisor degrada al
fallback neutro (vedi ai/advisor.py) senza fermare il trading ne' intaccare
l'uptime richiesto dalla gara.

Uso:  python -m aitrade.agents.run_agents
(richiamato da run.ps1 assieme al bot principale)
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time

log = logging.getLogger(__name__)

AGENT_MODULES = ["aitrade.agents.signal_agent", "aitrade.agents.strategy_agent"]
RESTART_DELAY_SEC = 5
POLL_SEC = 2


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    procs: dict[str, subprocess.Popen] = {}

    def start(module: str) -> None:
        log.info("Avvio agente %s", module)
        procs[module] = subprocess.Popen([sys.executable, "-m", module])

    for module in AGENT_MODULES:
        start(module)

    try:
        while True:
            time.sleep(POLL_SEC)
            for module, proc in list(procs.items()):
                if proc.poll() is not None:
                    log.warning("Agente %s terminato (exit %s): riavvio tra %ds",
                                module, proc.returncode, RESTART_DELAY_SEC)
                    time.sleep(RESTART_DELAY_SEC)
                    start(module)
    except KeyboardInterrupt:
        log.info("Arresto agenti...")
        for proc in procs.values():
            proc.terminate()


if __name__ == "__main__":
    main()
