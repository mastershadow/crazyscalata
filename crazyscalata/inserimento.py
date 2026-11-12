"""Validazione e salvataggio dei tempi, singoli o a blocchi (una riga per tempo: `pettorale tempo`)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import db as dbm
from .tempi import parse_time

# separatori tra pettorale e tempo: spazi, tab (incolla da Excel), punto e virgola.
# Non la virgola: è il separatore dei decimali nei tempi (3:12,5).
_SPLIT = re.compile(r"[\s;]+")


@dataclass
class Riga:
  n: int                 # numero di riga nel testo (da 1)
  testo: str
  pettorale: int | None = None
  tempo: str = ""
  ntempo: str = ""
  ftempo: float = 0.0
  nome: str = ""
  stato: str = "ok"      # ok / sovrascrive / uguale (già presente, si ignora) / errore
  messaggio: str = ""


def _other(fase: str) -> str:
  return dbm.FASI["arrivo" if fase == "intermedio" else "intermedio"]


def check(d: sqlite3.Connection, fase: str, pett: str, tempo: str, n: int = 1, testo: str = "") -> Riga:
  """Valida un tempo. `stato` = errore (da correggere), sovrascrive (corregge il tempo già presente), uguale, ok."""
  r = Riga(n=n, testo=testo or f"{pett} {tempo}".strip(), tempo=tempo.strip())
  pett = pett.strip()
  if not pett.isdigit():
    r.stato, r.messaggio = "errore", f"pettorale non valido: {pett!r}" if pett else "manca il pettorale"
    return r
  r.pettorale = int(pett)
  who = d.execute("SELECT nome, cognome FROM iscritti WHERE pettorale = ?", (r.pettorale,)).fetchone()
  if who is None:
    r.stato, r.messaggio = "errore", f"nessun iscritto con pettorale {pett}"
    return r
  r.nome = f"{who['nome']} {who['cognome']}".strip()
  if not r.tempo:
    r.stato, r.messaggio = "errore", "manca il tempo"
    return r
  try:
    r.ntempo, r.ftempo = parse_time(r.tempo)
  except ValueError as e:
    r.stato, r.messaggio = "errore", str(e)
    return r
  o = d.execute(f"SELECT tempo, ftempo FROM {_other(fase)} WHERE pettorale = ?", (r.pettorale,)).fetchone()
  if o and (r.ftempo >= o["ftempo"] if fase == "intermedio" else r.ftempo <= o["ftempo"]):
    altro = "arrivo" if fase == "intermedio" else "intermedio"
    r.stato, r.messaggio = "errore", f"ha {altro} {o['tempo']}: l'intermedio deve essere minore del tempo finale"
    return r
  existing = d.execute(f"SELECT tempo FROM {dbm.FASI[fase]} WHERE pettorale = ?", (r.pettorale,)).fetchone()
  if existing:
    if existing["tempo"] == r.tempo:
      r.stato, r.messaggio = "uguale", "già registrato con lo stesso tempo"
    else:
      r.stato, r.messaggio = "sovrascrive", f"corregge {existing['tempo']} → {r.tempo}"
  return r


def check_bulk(d: sqlite3.Connection, fase: str, text: str) -> list[Riga]:
  righe = []
  seen: dict[int, int] = {}
  for n, line in enumerate(text.splitlines(), start=1):
    line = line.strip()
    if not line:
      continue
    parts = _SPLIT.split(line, maxsplit=1)
    r = check(d, fase, parts[0], parts[1] if len(parts) > 1 else "", n, line)
    if r.pettorale is not None and r.stato != "errore":
      if r.pettorale in seen:
        r.stato, r.messaggio = "errore", f"pettorale ripetuto (riga {seen[r.pettorale]})"
      else:
        seen[r.pettorale] = n
    righe.append(r)
  return righe


def save(d: sqlite3.Connection, fase: str, righe: list[Riga], sovrascrivi: bool) -> tuple[list[Riga], list[Riga]]:
  """Salva le righe valide. Restituisce (salvate, da rivedere): da rivedere = errori + sovrascritture non autorizzate."""
  salvate, restano = [], []
  for r in righe:
    if r.stato == "ok" or (r.stato == "sovrascrive" and sovrascrivi):
      d.execute(f"INSERT OR REPLACE INTO {dbm.FASI[fase]} VALUES (?, ?, ?, ?, ?)",
                (r.pettorale, r.tempo, r.ntempo, r.ftempo, dbm.now()))
      salvate.append(r)
    elif r.stato != "uguale":
      restano.append(r)
  d.commit()
  # le righe rimaste tornano nella casella: rinumero e tengo l'errore originale
  # (un pettorale ripetuto, ricontrollato da solo, sembrerebbe una correzione legittima)
  for i, r in enumerate(restano, start=1):
    r.n = i
    if r.messaggio.startswith("pettorale ripetuto"):
      r.messaggio = "pettorale ripetuto nel blocco: salvata la prima riga"
  return salvate, restano
