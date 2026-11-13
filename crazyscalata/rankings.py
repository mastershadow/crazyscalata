"""Classifiche e premi: estrazione dal database e generazione dei PDF.

Si parte dalle viste `arrivi` (tempo finale) e `passaggi` (tempo al traguardo volante):
chi non ha il tempo corrispondente non compare.
A pari merito si assegna la stessa posizione (1, 2, 2, 4). I premi si cumulano:
la stessa persona può vincerne più di uno.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

from .tempi import format_time

# classifiche complete: (titolo, vista, condizione SQL), nell'ordine di stampa
CLASSIFICHE = [
  ("Crazy", "arrivi", "crazy = 'SI'"),
  ("Assoluti", "arrivi", "1 = 1"),
  ("Donne cicliste", "arrivi", "tipo = 'CICLISTA' AND sesso = 'F'"),
  ("Podisti", "arrivi", "tipo = 'PODISTA'"),
  ("Donne podiste", "arrivi", "tipo = 'PODISTA' AND sesso = 'F'"),
  # solo se sono stati presi i tempi intermedi (con la pioggia può non succedere)
  ("Traguardo volante Crazy", "passaggi", "crazy = 'SI'"),
  ("Traguardo volante Tutti", "passaggi", "1 = 1"),
]
SPECIALI = "Categorie speciali"  # nome mostrato per i premi secchi (pagina e PDF)
PODIO = 5  # quanti nomi per i premi "secchi" (i vincitori li scelgono gli organizzatori)

HEADER = ["Pos.", "Nome", "Pettorale", "Tempo", "Data nascita", "Tipo", "Crazy"]
COL_W = [18, 95, 27, 35, 40, 35, 20]


@dataclass
class Tabella:
  titolo: str
  sottotitolo: str
  header: list[str]
  righe: list[list[str]]
  larghezze: list[int] | None = None  # colonne del PDF (mm), se diverse da quelle delle classifiche


def format_date(iso: str | None) -> str:
  if not iso:
    return ""
  return "/".join(reversed(iso.split("T")[0].split("-")))


def _positions(keys: list) -> list[int]:
  """Posizioni con pari merito: stessa chiave, stessa posizione (1, 2, 2, 4)."""
  pos = []
  for i, k in enumerate(keys):
    pos.append(pos[-1] if i and k == keys[i - 1] else i + 1)
  return pos


def _row(pos: int, r: sqlite3.Row) -> list[str]:
  return [str(pos), r["nome"], str(r["pettorale"]), format_time(r["ftempo"]), format_date(r["datanascita"]),
          (r["tipo"] or "").capitalize(), r["crazy"] or ""]


def _arrivi(db: sqlite3.Connection, where: str, order: str, view: str = "arrivi") -> list[sqlite3.Row]:
  return db.execute(f"SELECT * FROM {view} WHERE {where} ORDER BY {order}").fetchall()


def classifica(db: sqlite3.Connection, titolo: str, where: str, view: str = "arrivi") -> Tabella:
  rows = _arrivi(db, where, "ftempo, pettorale", view)
  pos = _positions([round(r["ftempo"], 2) for r in rows])
  sotto = f"{len(rows)} {'passaggi' if view == 'passaggi' else 'arrivati'}"
  return Tabella(titolo, sotto, HEADER, [_row(p, r) for p, r in zip(pos, rows)])


def classifiche(db: sqlite3.Connection) -> list[Tabella]:
  """Le classifiche da stampare; quelle del traguardo volante solo se ci sono tempi intermedi."""
  intermedi = has_intermedi(db)
  return [classifica(db, t, w, v) for t, v, w in CLASSIFICHE if v != "passaggi" or intermedi]


def _podio(rows: list[sqlite3.Row], keys: list) -> list[tuple[int, sqlite3.Row]]:
  """Primi PODIO con pari merito: se l'ultimo è a pari merito con il successivo, entrano entrambi."""
  return [(p, r) for p, r in zip(_positions(keys), rows) if p <= PODIO]


def premio_media(db: sqlite3.Connection, titolo: str, where: str) -> Tabella:
  avg = db.execute(f"SELECT AVG(ftempo) FROM arrivi WHERE {where}").fetchone()[0]
  hdr = HEADER + ["Scarto"]
  if avg is None:
    return Tabella(titolo, "nessun arrivo", hdr, [])
  rows = _arrivi(db, where, f"ABS(ftempo - {avg!r}), pettorale")
  diffs = [round(abs(r["ftempo"] - avg), 2) for r in rows]
  righe = [_row(p, r) + [format_time(d)] for (p, r), d in zip(_podio(rows, diffs), diffs)]
  return Tabella(titolo, f"Tempo medio {format_time(avg)}", hdr, righe)


def premio_eta(db: sqlite3.Connection, titolo: str, giovani: bool) -> Tabella:
  rows = _arrivi(db, "datanascita IS NOT NULL", f"datanascita {'DESC' if giovani else 'ASC'}, pettorale")
  righe = [_row(p, r) for p, r in _podio(rows, [r["datanascita"] for r in rows])]
  return Tabella(titolo, "Tra chi ha concluso la gara", HEADER, righe)


def premio_traguardo_volante(db: sqlite3.Connection) -> Tabella:
  """Traguardo volante: il primo crazy e il primo di tutti (colonna Pos. = "Crazy"/"Tutti").

  Senza tempi intermedi (es. pioggia) si usa il pettorale del primo annotato a mano
  (impostazione `traguardo_volante`); senza nemmeno quello: non disputato.
  """
  if has_intermedi(db):
    righe = []
    for label, where in (("Crazy", "crazy = 'SI'"), ("Tutti", "1 = 1")):
      t = classifica(db, label, where, "passaggi")
      righe += [[label] + r[1:] for r in t.righe if r[0] == "1"]
    return Tabella("Traguardo volante", "Primo crazy e primo di tutti (tempo intermedio)", HEADER, righe)
  pett = get_setting(db, "traguardo_volante")
  r = db.execute("SELECT TRIM(nome || ' ' || cognome) AS nome, pettorale, tipo, crazy, datanascita "
                 "FROM iscritti WHERE pettorale = ?", (int(pett),)).fetchone() if pett else None
  if r is None:
    return Tabella("Traguardo volante", "Non disputato", HEADER, [])
  return Tabella("Traguardo volante", "Primo al passaggio (senza tempi intermedi)", HEADER,
                 [["1", r["nome"], str(r["pettorale"]), "", format_date(r["datanascita"]),
                   (r["tipo"] or "").capitalize(), r["crazy"] or ""]])


def pranzo(db: sqlite3.Connection) -> Tabella:
  """Chi viene al pranzo sociale, in ordine alfabetico, con le persone (lui/lei più gli ospiti).
  L'ultima riga è il totale."""
  rows = db.execute("SELECT * FROM iscritti WHERE pranzo = 'SI' ORDER BY cognome, nome").fetchall()
  righe = [[str(i), f"{r['cognome']} {r['nome']}".strip(), str(r["pettorale"] or ""),
            str(r["ospiti_pranzo"]), str(1 + r["ospiti_pranzo"])] for i, r in enumerate(rows, 1)]
  ospiti = sum(r["ospiti_pranzo"] for r in rows)
  if rows:
    righe.append(["", "Totale", "", str(ospiti), str(len(rows) + ospiti)])
  return Tabella("Pranzo sociale",
                 f"{len(rows)} iscritti al pranzo, {len(rows) + ospiti} persone in tutto (ospiti compresi)",
                 ["N.", "Cognome Nome", "Pettorale", "Ospiti", "Persone"], righe,
                 larghezze=[18, 120, 30, 30, 30])


def has_intermedi(db: sqlite3.Connection) -> bool:
  return db.execute("SELECT 1 FROM passaggi LIMIT 1").fetchone() is not None


def premi(db: sqlite3.Connection) -> list[Tabella]:
  return [
    premio_media(db, "Tempo medio ciclisti", "tipo = 'CICLISTA'"),
    premio_media(db, "Tempo medio ciclisti e podisti", "1 = 1"),
    premio_eta(db, "Più giovani", giovani=True),
    premio_eta(db, "Meno giovani", giovani=False),
    premio_traguardo_volante(db),
  ]


def get_setting(db: sqlite3.Connection, key: str) -> str | None:
  r = db.execute("SELECT valore FROM impostazioni WHERE chiave = ?", (key,)).fetchone()
  return r["valore"] if r else None


def set_setting(db: sqlite3.Connection, key: str, value: str | None):
  if value is None:
    db.execute("DELETE FROM impostazioni WHERE chiave = ?", (key,))
  else:
    db.execute("INSERT OR REPLACE INTO impostazioni VALUES (?, ?)", (key, value))
  db.commit()


# ---------- PDF ----------

def _latin1(s: str) -> str:
  """I font base dei PDF supportano solo latin-1: sostituisco i caratteri fuori set."""
  out = []
  for c in s:
    try:
      c.encode("latin-1")
      out.append(c)
    except UnicodeEncodeError:
      base = unicodedata.normalize("NFKD", c)[0]
      out.append(base if base.isascii() else "?")
  return "".join(out)


def _new_pdf(year: int) -> FPDF:
  pdf = FPDF(orientation="landscape", format="A4")
  pdf.add_page()
  pdf.set_font("helvetica", style="B", size=18)
  pdf.write(text=f"CrazyScalata {year}\n")
  return pdf


def _table(pdf: FPDF, t: Tabella):
  """Titolo + tabella. Una tabella che sta in una pagina non viene mai spezzata;
  una più lunga (es. Assoluti) continua sulla pagina dopo ripetendo l'intestazione."""
  widths = t.larghezze or (COL_W if len(t.header) == len(COL_W) else [18, 85, 25, 30, 35, 30, 20, 30])
  pdf.set_font("helvetica", style="", size=11)
  h = pdf.font_size * 1.6
  n_rows = max(len(t.righe), 1) + 1
  needed = 10 + (6 if t.sottotitolo else 0) + 2 + n_rows * h
  page_room = pdf.page_break_trigger - pdf.t_margin
  if pdf.get_y() + needed > pdf.page_break_trigger and needed <= page_room:
    pdf.add_page()

  pdf.set_font("helvetica", style="B", size=13)
  pdf.write(10, _latin1(t.titolo) + "\n")
  pdf.set_font("helvetica", style="", size=11)
  if t.sottotitolo:
    pdf.write(6, _latin1(t.sottotitolo) + "\n")
  pdf.ln(2)

  def header():
    pdf.set_font(style="B")
    for w, item in zip(widths, t.header):
      pdf.cell(w, h, text=_latin1(item), border=1)
    pdf.ln(h)
    pdf.set_font(style="")

  header()
  if not t.righe:
    pdf.cell(sum(widths), h, text="Nessun dato", border=1)
    pdf.ln(h)
  for row in t.righe:
    if pdf.get_y() + h > pdf.page_break_trigger:
      pdf.add_page()
      header()
    for w, item in zip(widths, row):
      pdf.cell(w, h, text=_latin1(item), border=1)
    pdf.ln(h)
  pdf.ln(6)


def write_pdfs(db: sqlite3.Connection, year: int, out_dir: str | Path) -> list[Path]:
  """Un PDF per classifica più "Categorie speciali.pdf" (i premi secchi), in out_dir/<anno>/."""
  out = Path(out_dir) / str(year)
  out.mkdir(parents=True, exist_ok=True)
  files = []
  for t in classifiche(db):
    pdf = _new_pdf(year)
    _table(pdf, t)
    p = out / f"{t.titolo}.pdf"
    pdf.output(str(p))
    files.append(p)
  pdf = _new_pdf(year)
  for t in premi(db):
    _table(pdf, t)
  p = out / f"{SPECIALI}.pdf"
  pdf.output(str(p))
  files.append(p)
  files.append(write_pranzo_pdf(db, year, out_dir))
  return files


def write_pranzo_pdf(db: sqlite3.Connection, year: int, out_dir: str | Path) -> Path:
  """Pranzo.pdf in out_dir/<anno>/: elenco di chi viene al pranzo con il totale delle persone."""
  out = Path(out_dir) / str(year)
  out.mkdir(parents=True, exist_ok=True)
  pdf = _new_pdf(year)
  _table(pdf, pranzo(db))
  p = out / "Pranzo.pdf"
  pdf.output(str(p))
  return p
