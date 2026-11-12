"""Import delle iscrizioni dal CSV delle risposte di Google Moduli.

Le persone sono riconosciute da cognome + nome + data di nascita (vedi db.make_key),
non dall'email: più iscrizioni possono arrivare dallo stesso indirizzo.

Regole di aggiornamento su un iscritto già presente:
- tipo, pranzo, ospiti, email, timestamp: vince il modulo (la persona può aver modificato la risposta);
- sesso, crazy: dal modulo solo se in archivio sono vuoti;
- pettorale, pagato, note: mai toccati (sono dati del banco).
"""
from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass, field

from . import db as dbm

# campo -> funzione che riconosce l'intestazione (già in minuscolo)
_COLUMNS = {
  "form_timestamp": lambda h: h in ("timestamp", "informazioni cronologiche"),
  "email": lambda h: h in ("username", "email", "indirizzo email") or h.startswith("e-mail"),
  "nome": lambda h: h == "nome",
  "cognome": lambda h: h == "cognome",
  "datanascita": lambda h: h.startswith("data di nascita"),
  "tipo": lambda h: h.startswith("tipologia"),
  "pranzo": lambda h: h.startswith("vieni al pranzo"),
  "ospiti_pranzo": lambda h: h.startswith("eventuali altri partecipanti"),
  "sesso": lambda h: h.startswith("sesso"),
  "crazy": lambda h: h.startswith("crazy"),
}
_REQUIRED = ("nome", "cognome", "datanascita")
FORM_FIELDS = ("nome", "cognome", "datanascita", "tipo", "pranzo", "ospiti_pranzo", "email", "form_timestamp")
FILL_IF_EMPTY = ("sesso", "crazy")


@dataclass
class Preview:
  nuovi: list[dict] = field(default_factory=list)
  modificati: list[tuple[dict, dict]] = field(default_factory=list)  # (record, {campo: (vecchio, nuovo)})
  invariati: int = 0
  errori: list[str] = field(default_factory=list)
  colonne_mancanti: list[str] = field(default_factory=list)


def _map_header(header: list[str]) -> dict[str, int]:
  idx = {}
  for i, h in enumerate(header):
    hn = " ".join(h.strip().lower().split())
    for fieldname, match in _COLUMNS.items():
      if fieldname not in idx and match(hn):
        idx[fieldname] = i
        break
  return idx


def parse_csv(text: str) -> tuple[list[dict], list[str], list[str]]:
  """Restituisce (record normalizzati, errori, campi opzionali assenti nel CSV)."""
  rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
  if not rows:
    return [], ["Il file è vuoto"], []
  idx = _map_header(rows[0])
  missing = [f for f in _REQUIRED if f not in idx]
  if missing:
    return [], [f"Colonne obbligatorie non trovate: {', '.join(missing)}"], []
  optional_missing = [f for f in _COLUMNS if f not in idx and f not in _REQUIRED]

  records: dict[str, dict] = {}
  errors = []
  for n, row in enumerate(rows[1:], start=2):
    if not any(c.strip() for c in row):
      continue
    get = lambda f: row[idx[f]] if f in idx and idx[f] < len(row) else ""
    try:
      r = {
        "nome": dbm.tidy_name(get("nome")),
        "cognome": dbm.tidy_name(get("cognome")),
        "datanascita": dbm.norm_date(get("datanascita")),
        "tipo": dbm.norm_tipo(get("tipo")),
        "pranzo": dbm.norm_si_no(get("pranzo")) or "NO",
        "ospiti_pranzo": dbm.norm_int(get("ospiti_pranzo")),
        "email": get("email").strip() or None,
        "form_timestamp": get("form_timestamp").strip() or None,
        "sesso": dbm.norm_sesso(get("sesso")),
        "crazy": dbm.norm_si_no(get("crazy")),
      }
    except ValueError as e:
      errors.append(f"Riga {n}: {e}")
      continue
    if not r["nome"] or not r["cognome"]:
      errors.append(f"Riga {n}: nome o cognome mancante")
      continue
    r["chiave"] = dbm.make_key(r["nome"], r["cognome"], r["datanascita"])
    records[r["chiave"]] = r  # risposte ripetute: vince l'ultima
  return list(records.values()), errors, optional_missing


def _changes(old: sqlite3.Row, new: dict) -> dict:
  ch = {}
  for f in FORM_FIELDS:
    if new[f] != old[f]:
      ch[f] = (old[f], new[f])
  for f in FILL_IF_EMPTY:
    if old[f] is None and new[f] is not None:
      ch[f] = (None, new[f])
  return ch


def preview(db: sqlite3.Connection, text: str) -> Preview:
  records, errors, optional_missing = parse_csv(text)
  p = Preview(errori=errors, colonne_mancanti=optional_missing)
  for r in records:
    old = db.execute("SELECT * FROM iscritti WHERE chiave = ?", (r["chiave"],)).fetchone()
    if old is None:
      p.nuovi.append(r)
    else:
      ch = _changes(old, r)
      if ch:
        p.modificati.append((r, ch))
      else:
        p.invariati += 1
  return p


def apply(db: sqlite3.Connection, text: str) -> Preview:
  p = preview(db, text)
  ts = dbm.now()
  for r in p.nuovi:
    cols = FORM_FIELDS + FILL_IF_EMPTY + ("chiave",)
    db.execute(
      f"INSERT INTO iscritti ({', '.join(cols)}, fonte, aggiornato) VALUES ({', '.join('?' * len(cols))}, 'form', ?)",
      [r[c] for c in cols] + [ts],
    )
  for r, ch in p.modificati:
    sets = ", ".join(f"{f} = ?" for f in ch)
    db.execute(f"UPDATE iscritti SET {sets}, aggiornato = ? WHERE chiave = ?",
               [v[1] for v in ch.values()] + [ts, r["chiave"]])
  db.commit()
  return p
