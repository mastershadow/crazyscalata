"""Import/export nel formato Excel di data/template.xlsx (fogli ISCRITTI e TEMPI)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import Workbook, load_workbook

from . import db as dbm
from .tempi import parse_time

ISCRITTI_HDR = ["nome", "tipologia", "crazy", "pettorale", "datanascita", "sesso", "pranzo"]
TEMPI_HDR = ["pettorale", "tempo", "intermedio"]  # intermedio opzionale (non c'era nel 2025)


def load(db: sqlite3.Connection, path: str | Path):
  """Carica un workbook (es. quello del 2025) in un database vuoto."""
  wb = load_workbook(filename=Path(path).absolute())
  ws = wb["ISCRITTI"]
  for row in ws.iter_rows(min_row=2, values_only=True):
    if row[0] is None:
      break
    nome, tipo, crazy, pettorale, nascita, sesso, pranzo = row[:7]
    nascita = dbm.norm_date(nascita)
    db.execute(
      "INSERT INTO iscritti (chiave, nome, tipo, crazy, pettorale, datanascita, sesso, pranzo, fonte, aggiornato) "
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'excel', ?)",
      [dbm.make_key(str(nome), "", nascita), str(nome).strip(), dbm.norm_tipo(tipo), dbm.norm_si_no(crazy),
       pettorale, nascita, dbm.norm_sesso(sesso), dbm.norm_si_no(pranzo) or "NO", dbm.now()],
    )
  ws = wb["TEMPI"]
  for row in ws.iter_rows(min_row=2, values_only=True):
    if row[0] is None:
      break
    pettorale, tempo, intermedio = (list(row) + [None, None])[:3]
    for table, value in (("tempi", tempo), ("intermedi", intermedio)):
      if value is not None and str(value).strip():
        ntempo, ftempo = parse_time(str(value))
        db.execute(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", [pettorale, str(value), ntempo, ftempo, dbm.now()])
  db.commit()


def export(db: sqlite3.Connection, path: str | Path):
  """Esporta nel formato del template, così il file è rileggibile da classifiche.py."""
  wb = Workbook()
  ws = wb.active
  ws.title = "ISCRITTI"
  ws.append(ISCRITTI_HDR)
  for r in db.execute("SELECT * FROM iscritti ORDER BY cognome, nome"):
    ws.append([f"{r['nome']} {r['cognome']}".strip(), r["tipo"], r["crazy"], r["pettorale"],
               r["datanascita"], r["sesso"], r["pranzo"]])
  ws = wb.create_sheet("TEMPI")
  ws.append(TEMPI_HDR)
  rows = db.execute("SELECT p.pettorale, t.tempo, m.tempo AS intermedio FROM "
                    "(SELECT pettorale FROM tempi UNION SELECT pettorale FROM intermedi) p "
                    "LEFT JOIN tempi t ON t.pettorale = p.pettorale LEFT JOIN intermedi m ON m.pettorale = p.pettorale "
                    "ORDER BY p.pettorale")
  for r in rows:
    ws.append([r["pettorale"], r["tempo"], r["intermedio"]])
  wb.save(str(path))
