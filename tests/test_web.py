import pytest

from crazyscalata.web import create_app

from .test_core import HEADER, ROW1, ROW2


PIN = "2468"


def make_client(tmp_path, anno=2026):
  app = create_app(tmp_path / "data", tmp_path / "out", anno=anno)
  app.config["TESTING"] = True
  c = app.test_client()
  if not (tmp_path / "data" / "config.json").exists() or '"pin_hash"' not in (tmp_path / "data" / "config.json").read_text():
    c.post("/pin", data={"pin": PIN, "pin2": PIN})
  else:
    c.post("/login", data={"pin": PIN})
  return c


@pytest.fixture
def client(tmp_path):
  return make_client(tmp_path)


def test_event_day_flow(client, tmp_path):
  # import CSV: anteprima, poi conferma
  r = client.post("/import", data={"file": (__import__("io").BytesIO(f"{HEADER}\n{ROW1}\n{ROW2}".encode()), "f.csv")},
                  content_type="multipart/form-data")
  assert r.status_code == 200 and "2</b> nuovi" in r.text
  r = client.post("/import", data={"azione": "conferma"}, follow_redirects=True)
  assert "Import completato: 2 nuovi" in r.text

  # iscrizione al banco
  r = client.post("/iscritti/nuovo", data={"nome": "luca", "cognome": "verdi", "datanascita": "1990-01-01",
                                           "tipo": "PODISTA", "sesso": "M", "crazy": "NO", "pettorale": "12",
                                           "pranzo": "NO", "ospiti_pranzo": "0", "pagato": "1"},
                  follow_redirects=True)
  assert "Salvato: Luca Verdi" in r.text

  # pettorale duplicato rifiutato
  r = client.post("/iscritti/1", data={"nome": "Mario", "cognome": "Rossi", "datanascita": "1980-05-01",
                                       "pettorale": "12", "pranzo": "SI"})
  assert "già assegnato a Luca Verdi" in r.text

  client.post("/iscritti/1", data={"nome": "Mario", "cognome": "Rossi", "datanascita": "1980-05-01",
                                   "tipo": "CICLISTA", "sesso": "M", "crazy": "SI", "pettorale": "5", "pranzo": "SI"})
  client.post("/iscritti/1/pagato")

  # niente intermedi: classifiche del traguardo volante assenti, si può inserire solo il primo
  assert "Nessun tempo intermedio" in client.get("/classifiche").text
  assert "Nessun iscritto con pettorale 99" in client.post("/tempi/traguardo-volante", data={"pettorale": "99"}, follow_redirects=True).text
  assert "Primo: <b>12" in client.post("/tempi/traguardo-volante", data={"pettorale": "12"}, follow_redirects=True).text
  client.post("/tempi/traguardo-volante", data={"pettorale": ""})

  def salva(fase, testo):
    return client.post(f"/tempi/{fase}", data={"testo": testo, "azione": "salva"}, follow_redirects=True)

  # pagina Tempi: due pulsanti, l'ordine è libero
  r = client.get("/tempi").text
  assert "Aggiungi o correggi intermedi" in r and "Aggiungi o correggi finali" in r
  assert "TEMPI INTERMEDI" in client.get("/tempi/intermedio").text
  assert client.get("/tempi/boh").status_code == 404

  assert "Salvati 2 tempi intermedi" in salva("intermedio", "5 1:30\n12 1:40").text
  assert client.get("/api/pettorale/5").json["intermedio"] == "1:30"
  assert "deve essere minore" in salva("arrivo", "5 1:00").text
  assert client.get("/api/pettorale/99").json is None
  r = salva("arrivo", "99 3:00\n5 3x")
  assert "nessun iscritto con pettorale 99" in r.text and "Tempo non valido" in r.text
  assert "Salvati 1 tempi finali" in salva("arrivo", "5 3:12,5").text
  # correggere: basta reinserire il pettorale
  r = client.post("/tempi/arrivo", data={"testo": "5 3:00", "azione": "controlla"})
  assert "corregge 3:12,5 → 3:00" in r.text and "Salva 1 tempi" in r.text
  salva("arrivo", "5 3:00\n12 2:10")
  assert client.get("/api/pettorale/5").json["arrivo"] == "3:00"
  r = client.get("/tempi").text
  assert "1:30.00" in r and "3:00.00" in r and "2 pettorali" in r

  # non si cambia pettorale a chi ha già un tempo
  r = client.post("/iscritti/1", data={"nome": "Mario", "cognome": "Rossi", "datanascita": "1980-05-01", "pettorale": "6", "pranzo": "SI"})
  assert "ha già un tempo registrato" in r.text

  # cancellare un tempo di una fase non tocca l'altra
  assert "Tempo finale del pettorale 12 cancellato" in client.post("/tempi/arrivo/12/elimina", follow_redirects=True).text
  assert client.get("/api/pettorale/12").json == {"nome": "Luca", "cognome": "Verdi", "tipo": "PODISTA",
                                                  "arrivo": None, "intermedio": "1:40"}
  salva("arrivo", "12 2:10")

  # classifiche
  r = client.get("/classifiche")
  ass = r.text.index(">Assoluti <small>")
  assert r.text.index("Luca Verdi", ass) < r.text.index("Mario Rossi", ass)
  client.post("/classifiche/pdf")
  assert len(list((tmp_path / "out" / "2026").glob("*.pdf"))) == 8
  assert client.get("/out/Premi.pdf").status_code == 200

  # traguardo volante: Mario (intermedio 1:30) primo, anche se all'arrivo è dietro a Luca
  tv = r.text.index(">Traguardo volante Tutti <small>")
  assert r.text.index("Mario Rossi", tv) < r.text.index("Luca Verdi", tv)

  # un intermedio maggiore del finale viene rifiutato
  assert "deve essere minore" in salva("intermedio", "12 5:00").text

  # backup automatico dopo le scritture + export Excel
  assert list((tmp_path / "data" / "backup").glob("crazyscalata-2026-*.sqlite"))
  assert client.get("/export.xlsx").status_code == 200
  for page in ("/", "/import", "/tempi", "/backup", "/iscritti/1"):
    assert client.get(page).status_code == 200


def test_bulk_entry(client):
  for pett, nome, nascita in ((1, "Uno", "1990-01-01"), (2, "Due", "1991-01-01"), (3, "Tre", "1992-01-01")):
    client.post("/iscritti/nuovo", data={"nome": nome, "cognome": "Test", "datanascita": nascita, "pettorale": str(pett),
                                         "tipo": "CICLISTA", "sesso": "M", "crazy": "SI", "pranzo": "NO"})
  client.post("/tempi/arrivo", data={"testo": "3 9:00", "azione": "salva"})

  testo = "1\t10:00\n\n2 11:30,5\n99\t12:00\n1;10:05\n3\t9:30\n2x 4\n"
  r = client.post("/tempi/arrivo", data={"testo": testo, "azione": "controlla"})
  assert "<b>2</b> nuovi" in r.text and "<b>1</b> correzioni" in r.text and "<b>3</b> errori" in r.text
  assert "nessun iscritto con pettorale 99" in r.text and "pettorale ripetuto (riga 1)" in r.text
  assert "corregge 9:00 → 9:30" in r.text and "Salva 3 tempi" in r.text

  # salva nuovi e correzioni; gli errori restano nella casella
  r = client.post("/tempi/arrivo", data={"testo": testo, "azione": "salva"})
  assert "Salvati 3 tempi finali" in r.text and "3 righe da rivedere" in r.text
  assert ">99\t12:00\n1;10:05\n2x 4</textarea>" in r.text
  assert "Niente da salvare" in r.text  # e il fuoco torna nella casella
  assert "pettorale ripetuto nel blocco: salvata la prima riga" in r.text
  assert client.get("/api/pettorale/2").json["arrivo"] == "11:30,5"
  assert client.get("/api/pettorale/3").json["arrivo"] == "9:30"

  # una riga identica a quella già salvata viene ignorata senza errori; tutto ok -> casella vuota
  r = client.post("/tempi/arrivo", data={"testo": "3 9:30\n1 10:05", "azione": "salva"}, follow_redirects=True)
  assert "Salvati 1 tempi finali" in r.text and "da rivedere" not in r.text and "></textarea>" in r.text
  r = client.post("/tempi/arrivo", data={"testo": "3 9:30", "azione": "salva"}, follow_redirects=True)
  assert "Nessuna modifica" in r.text

  # intermedio maggiore del finale: errore
  r = client.post("/tempi/intermedio", data={"testo": "1 4:00\n2 20:00", "azione": "controlla"})
  assert "<b>1</b> nuovi" in r.text and "deve essere minore" in r.text


def test_pin(tmp_path, monkeypatch):
  monkeypatch.setattr("time.sleep", lambda s: None)
  app = create_app(tmp_path / "data", tmp_path / "out", anno=2026)
  c = app.test_client()
  # primo avvio: ogni pagina porta all'impostazione del PIN
  assert c.get("/tempi").headers["Location"].endswith("/pin")
  assert "Imposta il PIN" in c.get("/pin").text
  assert "almeno 4" in c.post("/pin", data={"pin": "12", "pin2": "12"}).text
  assert "non coincidono" in c.post("/pin", data={"pin": "1234", "pin2": "1235"}).text
  assert "PIN impostato" in c.post("/pin", data={"pin": "1234", "pin2": "1234"}, follow_redirects=True).text
  assert c.get("/tempi").status_code == 200

  # un altro browser deve entrare col PIN, e torna alla pagina chiesta
  c2 = app.test_client()
  assert "/login" in c2.get("/tempi").headers["Location"]
  assert "/pin" in c2.get("/pin").headers["Location"]  # cambiare PIN richiede di essere entrati
  assert "PIN errato" in c2.post("/login", data={"pin": "0000", "next": "/tempi"}).text
  r = c2.post("/login", data={"pin": "1234", "next": "/tempi"})
  assert r.headers["Location"] == "/tempi"
  assert c2.post("/login", data={"pin": "1234", "next": "//evil.example"}).headers["Location"] == "/"

  # cambio PIN: serve quello attuale; le altre sessioni decadono
  assert "PIN attuale errato" in c.post("/pin", data={"attuale": "9999", "pin": "5678", "pin2": "5678"}).text
  assert "PIN cambiato" in c.post("/pin", data={"attuale": "1234", "pin": "5678", "pin2": "5678"}, follow_redirects=True).text
  assert c.get("/tempi").status_code == 200
  assert "/login" in c2.get("/tempi").headers["Location"]

  c.post("/logout")
  assert "/login" in c.get("/").headers["Location"]

  # --reset-pin (si fa ad app chiusa, poi si riavvia)
  from crazyscalata.config import Config
  Config(tmp_path / "data").reset_pin()
  c3 = create_app(tmp_path / "data", tmp_path / "out").test_client()
  assert c3.get("/").headers["Location"].endswith("/pin")


def test_edizioni(tmp_path):
  # nessuna edizione: si va alla pagina Edizioni
  app = create_app(tmp_path / "data", tmp_path / "out")
  assert app.config["YEAR"] is None
  c = app.test_client()
  c.post("/pin", data={"pin": PIN, "pin2": PIN})
  assert c.get("/").headers["Location"].endswith("/edizioni")
  assert "Nessuna edizione" in c.get("/edizioni").text

  # il 2025 dall'Excel (qui il campione), poi il 2026 nuovo
  with open("data/sample.xlsx", "rb") as f:
    r = c.post("/edizioni", data={"anno": "2025", "azione": "excel", "file": (f, "s.xlsx")},
               content_type="multipart/form-data", follow_redirects=True)
  assert "Creata l&#39;edizione 2025 dall&#39;Excel" in r.text and "CrazyScalata <b>2025</b>" in r.text
  assert "Mario Rossi" in r.text
  assert "esiste già" in c.post("/edizioni", data={"anno": "2025", "azione": "nuova"}, follow_redirects=True).text
  r = c.post("/edizioni", data={"anno": "2026", "azione": "nuova"}, follow_redirects=True)
  assert "CrazyScalata <b>2026</b>" in r.text and "Nessun iscritto" in r.text
  assert (tmp_path / "data" / "crazyscalata-2026.sqlite").exists()

  # l'edizione aperta resta tale al riavvio
  assert create_app(tmp_path / "data", tmp_path / "out").config["YEAR"] == 2026
  r = c.get("/edizioni").text
  assert "12 iscritti" in r and "11 arrivi" in r

  # import 2026: chi c'era nel 2025 riceve sesso e crazy (Mario Rossi nel campione: M; nel CSV nome e cognome invertiti)
  from .test_core import HEADER
  csv = (f"{HEADER}\n2026/02/01 9:00:00 am CET,a@b.it,Rossi,Mario,{_nascita(tmp_path, 'Mario Rossi')},Ciclista,NO,,Acconsento\n"
         "2026/02/01 9:10:00 am CET,a@b.it,Nuovo,Arrivato,2001-01-01,Ciclista,NO,,Acconsento\n")
  r = c.post("/import", data={"file": (__import__("io").BytesIO(csv.encode()), "f.csv")}, content_type="multipart/form-data")
  assert 'title="dall\'edizione 2025">2025</span>' in r.text and "Le risposte sono del" not in r.text
  c.post("/import", data={"azione": "conferma"})
  import sqlite3
  row = sqlite3.connect(tmp_path / "data" / "crazyscalata-2026.sqlite").execute(
    "select sesso, crazy from iscritti where cognome = 'Mario'").fetchone()
  assert row[0] == "M" and row[1] in ("SI", "NO")

  # CSV di un altro anno: avviso
  r = c.post("/import", data={"file": (__import__("io").BytesIO(csv.replace("2026/02", "2023/02").encode()), "f.csv")},
             content_type="multipart/form-data")
  assert "Le risposte sono del 2023" in r.text
  c.post("/import", data={"azione": "annulla"})

  # al banco: persona del 2025 senza sesso/crazy -> presi dal 2025
  nome, cognome = "Anna", "Bianchi"
  r = c.post("/iscritti/nuovo", data={"nome": cognome, "cognome": nome, "datanascita": _nascita(tmp_path, "Anna Bianchi"),
                                      "pranzo": "NO"}, follow_redirects=True)
  assert "presi dall&#39;edizione 2025" in r.text

  # possibili doppioni nella lista
  c.post("/iscritti/nuovo", data={"nome": "Arrivata", "cognome": "Nuova", "datanascita": "2001-01-01", "pranzo": "NO"})
  assert "Possibili doppioni" in c.get("/").text

  # torno al 2025
  r = c.post("/edizioni", data={"anno": "2025", "azione": "apri"}, follow_redirects=True)
  assert "CrazyScalata <b>2025</b>" in r.text and "Mario Rossi" in r.text


def _nascita(tmp_path, nome):
  import sqlite3
  return sqlite3.connect(tmp_path / "data" / "crazyscalata-2025.sqlite").execute(
    "select datanascita from iscritti where nome = ?", (nome,)).fetchone()[0]
