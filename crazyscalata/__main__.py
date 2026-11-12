"""Avvio dell'app: python3 -m crazyscalata [--year 2026] [--port 8765] [--no-browser]."""
from __future__ import annotations

import argparse
import datetime
import threading
import webbrowser
from pathlib import Path

from .web import create_app

ROOT = Path(__file__).resolve().parent.parent


def main():
  year = datetime.date.today().year
  p = argparse.ArgumentParser(prog="crazyscalata", description="CrazyScalata offline")
  p.add_argument("--year", type=int, default=year, help="anno dell'evento (default: anno corrente)")
  p.add_argument("--db", help="file SQLite (default: data/crazyscalata-<anno>.sqlite)")
  p.add_argument("--port", type=int, default=8765)  # non 5000: su macOS lo usa AirPlay
  p.add_argument("--no-browser", action="store_true")
  args = p.parse_args()

  db_path = Path(args.db) if args.db else ROOT / "data" / f"crazyscalata-{args.year}.sqlite"
  db_path.parent.mkdir(parents=True, exist_ok=True)
  app = create_app(db_path, args.year, ROOT / "out", ROOT / "data" / "backup")

  url = f"http://127.0.0.1:{args.port}/"
  print(f"CrazyScalata {args.year}: {url}  (database: {db_path})  — Ctrl+C per chiudere")
  if not args.no_browser:
    threading.Timer(1.0, webbrowser.open, [url]).start()
  app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
  main()
