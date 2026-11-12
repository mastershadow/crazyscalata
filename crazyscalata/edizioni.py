"""Edizioni: un database SQLite per anno, data/crazyscalata-<anno>.sqlite.

Un file per anno è semplice da salvare e archiviare. Le edizioni passate servono anche come
storico: per chi torna (stessa chiave persona, vedi db.make_key) si propongono sesso, crazy e
tipologia dell'ultima edizione a cui ha partecipato.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import db as dbm
from . import excel

_NAME = re.compile(r"^crazyscalata-(\d{4})\.sqlite$")
STORICO_CAMPI = ("sesso", "crazy", "tipo")


def path(data_dir: str | Path, anno: int) -> Path:
  return Path(data_dir) / f"crazyscalata-{anno}.sqlite"


def elenco(data_dir: str | Path) -> list[int]:
  """Anni delle edizioni esistenti, dal più recente."""
  d = Path(data_dir)
  anni = [int(m.group(1)) for f in d.glob("crazyscalata-*.sqlite") if (m := _NAME.match(f.name))] if d.exists() else []
  return sorted(anni, reverse=True)


def riepilogo(data_dir: str | Path, anno: int) -> dict:
  db = dbm.connect(path(data_dir, anno))
  try:
    q = lambda sql: db.execute(sql).fetchone()[0]
    return {"anno": anno, "iscritti": q("SELECT COUNT(*) FROM iscritti"), "arrivi": q("SELECT COUNT(*) FROM tempi"),
            "intermedi": q("SELECT COUNT(*) FROM intermedi")}
  finally:
    db.close()


def crea(data_dir: str | Path, anno: int) -> Path:
  p = path(data_dir, anno)
  if p.exists():
    raise ValueError(f"L'edizione {anno} esiste già")
  p.parent.mkdir(parents=True, exist_ok=True)
  dbm.connect(p).close()
  return p


def crea_da_excel(data_dir: str | Path, anno: int, xlsx: str | Path) -> Path:
  """Nuova edizione caricata da un workbook nel formato di data/template.xlsx (es. il 2025)."""
  p = path(data_dir, anno)
  if p.exists():
    raise ValueError(f"L'edizione {anno} esiste già")
  p.parent.mkdir(parents=True, exist_ok=True)
  db = dbm.connect(p)
  try:
    excel.load(db, xlsx)
  except Exception:
    db.close()
    p.unlink()
    raise
  db.close()
  return p


def svuota(db: sqlite3.Connection) -> dict:
  """Cancella iscritti, tempi e impostazioni dell'edizione (es. dopo le prove), lasciando il file.
  Restituisce quante righe c'erano."""
  tabelle = ("iscritti", "tempi", "intermedi", "impostazioni")
  prima = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabelle}
  for t in ("tempi", "intermedi", "impostazioni", "iscritti"):
    db.execute(f"DELETE FROM {t}")
  db.commit()
  return prima


def storico(data_dir: str | Path, anno: int, chiavi: list[str]) -> dict[str, dict]:
  """Per ogni chiave, sesso/crazy/tipo dall'edizione precedente più recente in cui c'è
  (solo valori non vuoti) e l'anno da cui vengono: {chiave: {"anno": 2025, "sesso": "M", ...}}."""
  out: dict[str, dict] = {}
  restano = set(chiavi)
  for prec in elenco(data_dir):
    if prec >= anno or not restano:
      continue
    db = sqlite3.connect(f"file:{path(data_dir, prec)}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
      for k in list(restano):
        r = db.execute(f"SELECT {', '.join(STORICO_CAMPI)} FROM iscritti WHERE chiave = ?", (k,)).fetchone()
        if r and any(r[c] for c in STORICO_CAMPI):
          out[k] = {"anno": prec, **{c: r[c] for c in STORICO_CAMPI}}
          restano.discard(k)
    finally:
      db.close()
  return out
