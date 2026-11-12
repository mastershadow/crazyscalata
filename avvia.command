#!/bin/bash
# Doppio clic dal Finder per avviare CrazyScalata.
# La prima volta serve internet per installare le dipendenze in .venv; poi funziona offline.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "Prima installazione: creo .venv e installo le dipendenze (serve internet)…"
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || {
    echo "Installazione fallita."; read -r -p "Premi Invio per chiudere"; exit 1; }
fi

.venv/bin/python -m crazyscalata "$@"
