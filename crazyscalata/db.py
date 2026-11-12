"""Schema SQLite e accesso al database."""
from __future__ import annotations

import datetime
import re
import sqlite3
import unicodedata
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS iscritti (
  id INTEGER PRIMARY KEY,
  chiave TEXT NOT NULL UNIQUE,          -- cognome|nome|datanascita normalizzati, per i re-import
  nome TEXT NOT NULL,
  cognome TEXT NOT NULL DEFAULT '',
  datanascita TEXT,                     -- YYYY-MM-DD
  tipo TEXT,                            -- CICLISTA / PODISTA
  sesso TEXT,                           -- M / F
  crazy TEXT,                           -- SI / NO
  pettorale INTEGER UNIQUE,
  pranzo TEXT NOT NULL DEFAULT 'NO',    -- SI / NO
  ospiti_pranzo INTEGER NOT NULL DEFAULT 0,
  pagato INTEGER NOT NULL DEFAULT 0,
  email TEXT,
  form_timestamp TEXT,
  fonte TEXT NOT NULL DEFAULT 'desk',   -- form / desk / excel
  note TEXT,
  aggiornato TEXT
);

CREATE TABLE IF NOT EXISTS tempi (
  pettorale INTEGER PRIMARY KEY,
  tempo TEXT NOT NULL,                  -- come digitato
  ntempo TEXT NOT NULL,                 -- HH:MM:SS.ff
  ftempo REAL NOT NULL,                 -- secondi, per ordinare
  inserito TEXT
);

-- tempi al traguardo volante, stessa struttura di tempi
CREATE TABLE IF NOT EXISTS intermedi (
  pettorale INTEGER PRIMARY KEY,
  tempo TEXT NOT NULL,
  ntempo TEXT NOT NULL,
  ftempo REAL NOT NULL,
  inserito TEXT
);

CREATE TABLE IF NOT EXISTS impostazioni (
  chiave TEXT PRIMARY KEY,              -- es. traguardo_volante = pettorale del primo (senza intermedi)
  valore TEXT
);

-- iscritti con tempo finale: base delle classifiche (vedi rankings.py)
CREATE VIEW IF NOT EXISTS arrivi AS
  SELECT i.id, TRIM(i.nome || ' ' || i.cognome) AS nome, i.pettorale, i.tipo, i.crazy,
         i.datanascita, i.sesso, t.tempo, t.ntempo, t.ftempo
  FROM iscritti i JOIN tempi t ON i.pettorale = t.pettorale;

-- iscritti con tempo intermedio: classifica del traguardo volante
CREATE VIEW IF NOT EXISTS passaggi AS
  SELECT i.id, TRIM(i.nome || ' ' || i.cognome) AS nome, i.pettorale, i.tipo, i.crazy,
         i.datanascita, i.sesso, t.tempo, t.ntempo, t.ftempo
  FROM iscritti i JOIN intermedi t ON i.pettorale = t.pettorale;
"""

# fase di inserimento -> tabella dei tempi
FASI = {"intermedio": "intermedi", "arrivo": "tempi"}


SCHEMA_VERSION = 1


def connect(path: str | Path) -> sqlite3.Connection:
  db = sqlite3.connect(str(path))
  db.row_factory = sqlite3.Row
  db.execute("PRAGMA foreign_keys = ON")
  db.executescript(SCHEMA)
  _migrate(db)
  return db


def _migrate(db: sqlite3.Connection):
  v = db.execute("PRAGMA user_version").fetchone()[0]
  if v < 1:
    # v1: chiave persona indipendente dall'ordine nome/cognome; in caso di collisione resta la vecchia
    for r in db.execute("SELECT id, nome, cognome, datanascita FROM iscritti").fetchall():
      try:
        db.execute("UPDATE iscritti SET chiave = ? WHERE id = ?", (make_key(r["nome"], r["cognome"], r["datanascita"]), r["id"]))
      except sqlite3.IntegrityError:
        pass
  if v < SCHEMA_VERSION:
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()


def now() -> str:
  return datetime.datetime.now().isoformat(timespec="seconds")


def _fold(s: str) -> str:
  s = unicodedata.normalize("NFKD", s or "")
  s = "".join(c for c in s if not unicodedata.combining(c))
  return " ".join(s.lower().split())


def name_tokens(nome: str, cognome: str = "") -> list[str]:
  """Parole del nome completo, normalizzate e in ordine alfabetico (l'ordine nome/cognome non conta)."""
  return sorted(_fold(f"{nome} {cognome}").replace("'", " ").replace("-", " ").split())


def make_key(nome: str, cognome: str, datanascita: str | None) -> str:
  """Chiave che identifica una persona tra un import e l'altro, e tra un'edizione e l'altra.

  Nome e cognome invertiti danno la stessa chiave: serve anche per l'Excel 2025, dove nome e
  cognome sono in un'unica colonna in ordine variabile."""
  return f"{' '.join(name_tokens(nome, cognome))}|{datanascita or ''}"


def possibili_doppioni(persone: list[dict]) -> list[tuple[dict, dict, str]]:
  """Coppie di persone (con chiavi nome, cognome, datanascita) che potrebbero essere la stessa:
  stessa data di nascita e nome simile, oppure stesso nome e data diversa."""
  from difflib import SequenceMatcher
  out = []
  for i, a in enumerate(persone):
    na = " ".join(name_tokens(a["nome"], a["cognome"]))
    for b in persone[i + 1:]:
      nb = " ".join(name_tokens(b["nome"], b["cognome"]))
      if a["datanascita"] and a["datanascita"] == b["datanascita"]:
        if na != nb and SequenceMatcher(None, na, nb).ratio() >= 0.75:
          out.append((a, b, "stessa data di nascita, nome simile"))
      elif na == nb:
        out.append((a, b, "stesso nome, data di nascita diversa"))
  return out


def tidy_name(s: str) -> str:
  """Spazi puliti; maiuscole sistemate solo se il nome è tutto maiuscolo o minuscolo."""
  s = " ".join((s or "").split())
  if s and (s.isupper() or s.islower()):
    s = s.title()
  return s


def norm_date(v) -> str | None:
  """Data di nascita in formato YYYY-MM-DD (accetta anche DD/MM/YYYY e datetime)."""
  if v is None or v == "":
    return None
  if isinstance(v, (datetime.datetime, datetime.date)):
    return v.strftime("%Y-%m-%d")
  v = str(v).strip().split("T")[0].split(" ")[0]
  for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
    try:
      return datetime.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
    except ValueError:
      pass
  raise ValueError(f"Data non valida: {v!r}")


def _pick(v, mapping: dict[str, str]) -> str | None:
  f = _fold(str(v)) if v is not None else ""
  if not f:
    return None
  for prefix, out in mapping.items():
    if f.startswith(prefix):
      return out
  raise ValueError(f"Valore non riconosciuto: {v!r}")


def norm_sesso(v) -> str | None:
  return _pick(v, {"maschi": "M", "uomo": "M", "m": "M", "femmin": "F", "donna": "F", "f": "F"})


def norm_si_no(v) -> str | None:
  return _pick(v, {"si": "SI", "yes": "SI", "x": "SI", "no": "NO"})


def norm_tipo(v) -> str | None:
  return _pick(v, {"cicl": "CICLISTA", "bici": "CICLISTA", "pod": "PODISTA", "corsa": "PODISTA"})


def norm_int(v) -> int:
  """Il numero all'inizio del testo ("2", " 3 ", "2 (moglie e figlio)"); 0 se non c'è."""
  m = re.match(r"\s*(\d+)", "" if v is None else str(v))
  return int(m.group(1)) if m else 0
