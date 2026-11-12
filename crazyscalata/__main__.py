"""Avvio dell'app: python3 -m crazyscalata [--year 2026] [--port 8765] [--no-browser] [--reset-pin]."""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from .config import Config
from .web import create_app

ROOT = Path(__file__).resolve().parent.parent


def main():
  p = argparse.ArgumentParser(prog="crazyscalata", description="CrazyScalata offline")
  p.add_argument("--year", type=int, help="edizione da aprire, creata se non esiste (default: l'ultima aperta)")
  p.add_argument("--data-dir", default=str(ROOT / "data"), help="cartella con edizioni, backup e config (default: data/)")
  p.add_argument("--port", type=int, default=8765)  # non 5000: su macOS lo usa AirPlay
  p.add_argument("--no-browser", action="store_true")
  p.add_argument("--reset-pin", action="store_true", help="cancella il PIN: al prossimo accesso se ne imposta uno nuovo")
  args = p.parse_args()

  if args.reset_pin:
    Config(args.data_dir).reset_pin()
    print("PIN cancellato: aprendo l'app ne imposterai uno nuovo.")

  app = create_app(args.data_dir, ROOT / "out", anno=args.year)
  url = f"http://127.0.0.1:{args.port}/"
  edizione = app.config["YEAR"] or "nessuna (creala dall'app)"
  print(f"CrazyScalata: {url}  edizione {edizione}, dati in {args.data_dir}  — Ctrl+C per chiudere", flush=True)
  if not args.no_browser:
    threading.Timer(1.0, webbrowser.open, [url]).start()
  app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
  main()
