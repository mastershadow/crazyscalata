import pytest

from crazyscalata import db as dbm
from crazyscalata import excel, importer, rankings
from crazyscalata.tempi import format_time, parse_time

# intestazioni come nel modulo Google 2026, più le nuove domande Sesso e Crazy
HEADER = ('Timestamp,Username,Nome,Cognome,Data di Nascita (per le classifiche),Tipologia partecipante,'
          'Vieni al pranzo sociale?,Eventuali altri partecipanti al pranzo sociale,'
          '"Acconsento all\'uso dei dati ai sensi del D.Lgs 196/2003, D.Lgs 101/2018 (GDPR) e successive evoluzioni"')
ROW1 = '2026/01/15 9:05:00 pm CET,fam@example.com,MARIO,rossi,1980-05-01,Ciclista,SI,3,Acconsento'
ROW2 = '2026/01/16 7:33:36 am CET,fam@example.com,Anna,Rossi,2010-02-03,Podista,NO,,Acconsento'


@pytest.mark.parametrize("raw,norm,secs", [
  ("45", "00:00:45.00", 45),
  ("3:12,5", "00:03:12.50", 192.5),
  ("2:58.4", "00:02:58.40", 178.4),
  ("1:02:03.45", "01:02:03.45", 3723.45),
  (" 12:03 ", "00:12:03.00", 723),
  ("75", "00:01:15.00", 75),
])
def test_parse_time(raw, norm, secs):
  n, s = parse_time(raw)
  assert n == norm
  assert s == pytest.approx(secs)


@pytest.mark.parametrize("raw", ["", "abc", "3:75", "1:61:00", "3..2", "-4"])
def test_parse_time_invalid(raw):
  with pytest.raises(ValueError):
    parse_time(raw)


def test_format_time():
  assert format_time(45) == "0:45.00"
  assert format_time(192.5) == "3:12.50"
  assert format_time(3605) == "1:00:05.00"


def test_normalizers():
  assert dbm.norm_sesso("Maschio") == "M" and dbm.norm_sesso("femmina") == "F" and dbm.norm_sesso("") is None
  assert dbm.norm_si_no("Sì") == "SI" and dbm.norm_si_no("no") == "NO"
  assert dbm.norm_tipo("Ciclista") == "CICLISTA"
  assert dbm.norm_date("03/02/2010") == "2010-02-03"
  assert dbm.make_key("Jose", "Péréz", "2000-01-01") == dbm.make_key(" josé ", "PEREZ", "2000-01-01")


def test_import_and_reimport():
  db = dbm.connect(":memory:")
  csv_text = "\n".join([HEADER, ROW1, ROW2])
  p = importer.apply(db, csv_text)
  assert len(p.nuovi) == 2 and "sesso" in p.colonne_mancanti and "crazy" in p.colonne_mancanti
  mario = db.execute("SELECT * FROM iscritti WHERE nome = 'Mario'").fetchone()
  assert mario["cognome"] == "Rossi" and mario["pranzo"] == "SI" and mario["ospiti_pranzo"] == 3
  assert mario["tipo"] == "CICLISTA"

  # dati del banco
  db.execute("UPDATE iscritti SET pettorale = 7, pagato = 1, sesso = 'M' WHERE id = ?", (mario["id"],))
  db.commit()

  # nuovo export del modulo: Mario ha cambiato pranzo, sono comparse Sesso e Crazy
  header2 = HEADER + ",Sesso,Crazy"
  csv2 = "\n".join([header2, ROW1.replace(",SI,3,", ",NO,,") + ",Femmina,Sì", ROW2 + ",Femmina,No"])
  p = importer.preview(db, csv2)
  assert not p.nuovi and len(p.modificati) == 2 and not p.colonne_mancanti
  importer.apply(db, csv2)
  mario = db.execute("SELECT * FROM iscritti WHERE nome = 'Mario'").fetchone()
  assert mario["pranzo"] == "NO" and mario["ospiti_pranzo"] == 0
  assert mario["pettorale"] == 7 and mario["pagato"] == 1
  assert mario["sesso"] == "M"  # già compilato al banco: non sovrascritto
  assert mario["crazy"] == "SI"  # era vuoto: preso dal modulo
  assert importer.preview(db, csv2).invariati == 2


def test_import_errors():
  db = dbm.connect(":memory:")
  p = importer.preview(db, "a,b\n1,2")
  assert p.errori and not p.nuovi
  p = importer.preview(db, HEADER + "\n" + ROW1.replace("1980-05-01", "boh"))
  assert p.errori and not p.nuovi


def test_sample_rankings(tmp_path):
  db = dbm.connect(":memory:")
  excel.load(db, "data/sample.xlsx")
  ass = rankings.classifica(db, "Assoluti", "1 = 1").righe
  assert [r[0] for r in ass] == [str(i) for i in range(1, len(ass) + 1)]
  assert ass[0][3] == "0:45.00"
  assert db.execute("SELECT COUNT(*) FROM iscritti").fetchone()[0] == len(ass) + 1  # uno senza tempo
  files = rankings.write_pdfs(db, 2026, tmp_path)
  assert [f.name for f in files] == ["Crazy.pdf", "Assoluti.pdf", "Donne cicliste.pdf", "Podisti.pdf",
                                     "Donne podiste.pdf", "Traguardo volante Crazy.pdf", "Traguardo volante Tutti.pdf",
                                     "Premi.pdf", "Pranzo.pdf"]
  tv = rankings.classifica(db, "TV", "1 = 1", "passaggi").righe
  assert len(tv) == len(ass) - 1  # uno senza intermedio
  assert all(f.parent == tmp_path / "2026" and f.stat().st_size > 0 for f in files)

  # l'export Excel si rilegge identico
  excel.export(db, tmp_path / "x.xlsx")
  db2 = dbm.connect(":memory:")
  excel.load(db2, tmp_path / "x.xlsx")
  assert rankings.classifica(db2, "Assoluti", "1 = 1").righe == ass
  assert rankings.classifica(db2, "TV", "1 = 1", "passaggi").righe == tv


def _people(db, people, intermedi=None):
  """people: (pettorale, tipo, sesso, crazy, nascita, tempo); intermedi: {pettorale: tempo}"""
  for pett, t in (intermedi or {}).items():
    n, f = parse_time(t)
    db.execute("INSERT INTO intermedi VALUES (?,?,?,?,?)", (pett, t, n, f, None))
  for pett, tipo, sesso, crazy, nascita, tempo in people:
    db.execute("INSERT INTO iscritti (chiave, nome, pettorale, tipo, sesso, crazy, datanascita) VALUES (?,?,?,?,?,?,?)",
               (f"k{pett}", f"P{pett}", pett, tipo, sesso, crazy, nascita))
    if tempo is not None:
      n, f = parse_time(tempo)
      db.execute("INSERT INTO tempi VALUES (?,?,?,?,?)", (pett, tempo, n, f, None))
  db.commit()


def _names(t):
  return [(r[0], r[1]) for r in t.righe]


def test_classifiche_and_premi():
  db = dbm.connect(":memory:")
  _people(db, [
    (1, "CICLISTA", "M", "SI", "1950-01-01", "10:00"),
    (2, "CICLISTA", "F", "NO", "2010-06-01", "12:00"),
    (3, "CICLISTA", "M", "SI", "1990-01-01", "12:00"),   # pari merito con 2
    (4, "CICLISTA", "F", "SI", "1980-01-01", "20:00"),
    (5, "PODISTA", "F", "NO", "2012-01-01", "30:00"),
    (6, "PODISTA", "M", "NO", "1945-01-01", "40:00"),
    (7, "CICLISTA", "M", "SI", "2015-01-01", None),      # senza tempo finale: escluso, tranne dal traguardo volante
  ], intermedi={1: "5:00", 3: "4:30", 7: "4:30", 5: "15:00"})
  by = {t.titolo: t for t in rankings.classifiche(db)}
  assert _names(by["Assoluti"]) == [("1", "P1"), ("2", "P2"), ("2", "P3"), ("4", "P4"), ("5", "P5"), ("6", "P6")]
  assert _names(by["Crazy"]) == [("1", "P1"), ("2", "P3"), ("3", "P4")]
  assert _names(by["Donne cicliste"]) == [("1", "P2"), ("2", "P4")]
  assert _names(by["Podisti"]) == [("1", "P5"), ("2", "P6")]
  assert _names(by["Donne podiste"]) == [("1", "P5")]
  assert _names(by["Traguardo volante Tutti"]) == [("1", "P3"), ("1", "P7"), ("3", "P1"), ("4", "P5")]
  assert _names(by["Traguardo volante Crazy"]) == [("1", "P3"), ("1", "P7"), ("3", "P1")]
  assert by["Traguardo volante Tutti"].righe[0][3] == "4:30.00"  # tempo intermedio, non finale

  pr = {t.titolo: t for t in rankings.premi(db)}
  # ciclisti: media (10+12+12+20)/4 = 13:30 -> scarti 1:30, 1:30, 3:30, 6:30; i podisti non entrano
  t = pr["Tempo medio ciclisti"]
  assert t.sottotitolo == "Tempo medio 13:30.00"
  assert _names(t) == [("1", "P2"), ("1", "P3"), ("3", "P1"), ("4", "P4")]
  assert t.righe[0][-1] == "1:30.00"
  # tutti: media 124/6 = 20:40 -> P4 0:40, P2/P3 8:40, P1 10:40, P5 9:20 -> P4, P2, P3, P5, P1 (P6 19:20 fuori)
  t = pr["Tempo medio ciclisti e podisti"]
  assert _names(t) == [("1", "P4"), ("2", "P2"), ("2", "P3"), ("4", "P5"), ("5", "P1")]
  assert _names(pr["Più giovani"]) == [("1", "P5"), ("2", "P2"), ("3", "P3"), ("4", "P4"), ("5", "P1")]  # P7 non ha tempo
  assert _names(pr["Meno giovani"]) == [("1", "P6"), ("2", "P1"), ("3", "P4"), ("4", "P3"), ("5", "P2")]
  # premio: il primo, entrambi se a pari merito; P7 non ha concluso ma vale
  # primo crazy e primo di tutti (pari merito: entrambi)
  assert _names(pr["Traguardo volante"]) == [("Crazy", "P3"), ("Crazy", "P7"), ("Tutti", "P3"), ("Tutti", "P7")]
  # con i tempi intermedi il pettorale inserito a mano è ignorato
  rankings.set_setting(db, "traguardo_volante", "5")
  assert _names(rankings.premio_traguardo_volante(db)) == _names(pr["Traguardo volante"])


def test_traguardo_volante_senza_intermedi(tmp_path):
  db = dbm.connect(":memory:")
  _people(db, [(1, "CICLISTA", "M", "SI", "1950-01-01", "10:00"), (2, "PODISTA", "F", "NO", "1990-01-01", "20:00")])
  # niente intermedi: niente classifiche del traguardo volante, premio non disputato
  assert [t.titolo for t in rankings.classifiche(db)] == ["Crazy", "Assoluti", "Donne cicliste", "Podisti", "Donne podiste"]
  t = rankings.premio_traguardo_volante(db)
  assert t.righe == [] and t.sottotitolo == "Non disputato"
  assert len(rankings.write_pdfs(db, 2026, tmp_path)) == 7
  # solo il pettorale del primo, senza tempo
  rankings.set_setting(db, "traguardo_volante", "2")
  t = rankings.premio_traguardo_volante(db)
  assert _names(t) == [("1", "P2")] and t.righe[0][3] == ""


def test_podio_tie_at_last():
  db = dbm.connect(":memory:")
  nascite = ["2000-01-01", "2001-01-01", "2002-01-01", "2003-01-01", "2004-01-01", "2004-01-01", "2005-01-01"]
  _people(db, [(i, "CICLISTA", "M", "NO", n, "1:00") for i, n in enumerate(nascite, 1)])
  # P5 e P6 nati lo stesso giorno, a pari merito al 5° posto tra i meno giovani: entrano entrambi, P7 no
  assert [n for _, n in _names(rankings.premio_eta(db, "x", giovani=False))] == ["P1", "P2", "P3", "P4", "P5", "P6"]


def test_norm_int():
  assert [dbm.norm_int(v) for v in ("3", " 2 ", "2 (moglie e figlio)", "", None, "nessuno")] == [3, 2, 2, 0, 0, 0]
