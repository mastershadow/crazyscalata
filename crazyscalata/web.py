"""Web app locale (Flask) per il giorno dell'evento.

Un'unica app per tutte le edizioni: l'edizione aperta (app.config["YEAR"]) sceglie il database
data/crazyscalata-<anno>.sqlite. L'accesso è protetto da un PIN (vedi config.py); al primo
avvio si imposta il PIN.
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

from . import db as dbm
from . import edizioni, excel, importer, inserimento, rankings
from .config import Config
from .tempi import format_time

BACKUP_EVERY_S = 300
BACKUP_KEEP = 50


SESSION_HOURS = 14  # una giornata di gara
PUBLIC_ENDPOINTS = {"static", "login", "pin"}


def create_app(data_dir: str | Path, out_dir: str | Path, backup_dir: str | Path | None = None,
               anno: int | None = None) -> Flask:
  """`anno`: edizione da aprire (creata se non esiste); altrimenti l'ultima aperta o la più recente."""
  data_dir = Path(data_dir).absolute()
  cfg = Config(data_dir)
  if anno is not None and anno not in edizioni.elenco(data_dir):
    edizioni.crea(data_dir, anno)
  esistenti = edizioni.elenco(data_dir)
  if anno is None:
    anno = cfg.edizione if cfg.edizione in esistenti else (esistenti[0] if esistenti else None)
  if anno is not None and cfg.edizione != anno:
    cfg.edizione = anno

  app = Flask(__name__)
  app.config.update(
    SECRET_KEY=cfg.secret_key, DATA_DIR=data_dir, YEAR=anno, OUT_DIR=Path(out_dir).absolute(),
    BACKUP_DIR=Path(backup_dir).absolute() if backup_dir else data_dir / "backup",
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=SESSION_HOURS),
  )
  app.jinja_env.globals.update(format_time=format_time, format_date=rankings.format_date)
  _last_backup = [0.0]

  def db_path() -> Path:
    return edizioni.path(data_dir, app.config["YEAR"])

  def pending_import() -> Path:
    return db_path().with_suffix(".import.csv")

  def get_db() -> sqlite3.Connection:
    if "db" not in g:
      g.db = dbm.connect(db_path())
    return g.db

  @app.teardown_appcontext
  def close_db(_exc):
    d = g.pop("db", None)
    if d is not None:
      d.close()

  @app.context_processor
  def globals_():
    return {"year": app.config["YEAR"], "logged_in": session.get("pin") == cfg.pin_version and cfg.has_pin}

  # ---------- accesso con PIN ----------

  @app.before_request
  def require_pin():
    if request.endpoint in PUBLIC_ENDPOINTS:
      return None
    if not cfg.has_pin:
      return redirect(url_for("pin"))
    if session.get("pin") != cfg.pin_version:
      return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
    if app.config["YEAR"] is None and request.endpoint != "edizioni_page" and request.endpoint != "logout":
      return redirect(url_for("edizioni_page"))
    return None

  def _login():
    session.clear()
    session.permanent = True
    session["pin"] = cfg.pin_version

  @app.route("/login", methods=["GET", "POST"])
  def login():
    if not cfg.has_pin:
      return redirect(url_for("pin"))
    nxt = request.values.get("next") or ""
    if not nxt.startswith("/") or nxt.startswith("//"):
      nxt = url_for("iscritti")
    if request.method == "POST":
      if cfg.check_pin(request.form.get("pin", "")):
        _login()
        return redirect(nxt)
      time.sleep(1)  # rallenta i tentativi
      flash("PIN errato", "err")
    return render_template("login.html", next=nxt)

  @app.post("/logout")
  def logout():
    session.clear()
    return redirect(url_for("login"))

  @app.route("/pin", methods=["GET", "POST"])
  def pin():
    """Primo avvio: imposta il PIN. Dopo: cambio PIN (serve quello attuale, ed essere entrati)."""
    primo = not cfg.has_pin
    if not primo and session.get("pin") != cfg.pin_version:
      return redirect(url_for("login", next=url_for("pin")))
    if request.method == "POST":
      f = request.form
      if not primo and not cfg.check_pin(f.get("attuale", "")):
        time.sleep(1)
        flash("PIN attuale errato", "err")
      elif f.get("pin", "") != f.get("pin2", ""):
        flash("I due PIN non coincidono", "err")
      else:
        try:
          cfg.set_pin(f.get("pin", ""))
        except ValueError as e:
          flash(str(e), "err")
        else:
          _login()
          flash("PIN impostato" if primo else "PIN cambiato", "ok")
          return redirect(url_for("iscritti"))
    return render_template("pin.html", primo=primo)

  # ---------- edizioni ----------

  @app.route("/edizioni", methods=["GET", "POST"])
  def edizioni_page():
    if request.method == "POST":
      f = request.form
      anno_s = f.get("anno", "").strip()
      if not (anno_s.isdigit() and 2000 <= int(anno_s) <= 2100):
        flash("Anno non valido", "err")
        return redirect(url_for("edizioni_page"))
      a = int(anno_s)
      try:
        if f.get("azione") == "nuova":
          edizioni.crea(data_dir, a)
          flash(f"Creata l'edizione {a}", "ok")
        elif f.get("azione") == "excel":
          file = request.files.get("file")
          if not file or not file.filename:
            raise ValueError("Scegli il file Excel")
          tmp = data_dir / f"upload-{a}.xlsx"
          file.save(tmp)
          try:
            edizioni.crea_da_excel(data_dir, a, tmp)
          finally:
            tmp.unlink(missing_ok=True)
          flash(f"Creata l'edizione {a} dall'Excel", "ok")
        elif a not in edizioni.elenco(data_dir):
          raise ValueError(f"L'edizione {a} non esiste")
      except Exception as e:  # anche errori di lettura dell'Excel
        flash(str(e) or "Errore", "err")
        return redirect(url_for("edizioni_page"))
      app.config["YEAR"] = a
      cfg.edizione = a
      flash(f"Edizione {a} aperta", "ok")
      return redirect(url_for("iscritti"))
    elenco = [edizioni.riepilogo(data_dir, a) for a in edizioni.elenco(data_dir)]
    proposta = max([datetime.date.today().year] + [e["anno"] + 1 for e in elenco])
    return render_template("edizioni.html", elenco=elenco, proposta=proposta)

  def backup(force: bool = False) -> Path | None:
    if not force and time.time() - _last_backup[0] < BACKUP_EVERY_S:
      return None
    bdir: Path = app.config["BACKUP_DIR"]
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"{db_path().stem}-{datetime.datetime.now():%Y%m%d-%H%M%S}.sqlite"
    with sqlite3.connect(str(dest)) as target:
      get_db().backup(target)
    _last_backup[0] = time.time()
    for old in sorted(bdir.glob("*.sqlite"))[:-BACKUP_KEEP]:
      old.unlink()
    return dest

  @app.after_request
  def auto_backup(resp):
    if request.method == "POST" and "db" in g:
      backup()
    return resp

  # ---------- iscritti ----------

  @app.get("/")
  def iscritti():
    rows = get_db().execute("SELECT i.*, t.tempo IS NOT NULL AS arrivato FROM iscritti i "
                            "LEFT JOIN tempi t ON t.pettorale = i.pettorale ORDER BY cognome, nome").fetchall()
    stats = {
      "totale": len(rows),
      "pagati": sum(r["pagato"] for r in rows),
      "con_pettorale": sum(r["pettorale"] is not None for r in rows),
      "pranzi": sum((1 + r["ospiti_pranzo"]) if r["pranzo"] == "SI" else 0 for r in rows),
      "incompleti": sum(1 for r in rows if _missing(r)),
    }
    doppioni = dbm.possibili_doppioni([dict(r) for r in rows])
    return render_template("iscritti.html", rows=rows, stats=stats, missing=_missing, doppioni=doppioni)

  @app.route("/iscritti/nuovo", methods=["GET", "POST"])
  def nuovo():
    return _edit(None)

  @app.route("/iscritti/<int:iid>", methods=["GET", "POST"])
  def modifica(iid: int):
    return _edit(iid)

  def _edit(iid: int | None):
    d = get_db()
    row = None
    if iid is not None:
      row = d.execute("SELECT * FROM iscritti WHERE id = ?", (iid,)).fetchone()
      if row is None:
        abort(404)
    form = dict(row) if row else {"pranzo": "NO", "ospiti_pranzo": 0, "pagato": 0}
    errors = []
    if request.method == "POST":
      f = request.form
      form = {k: f.get(k, "").strip() for k in
              ("nome", "cognome", "datanascita", "tipo", "sesso", "crazy", "pettorale", "pranzo", "ospiti_pranzo", "note")}
      form["pagato"] = 1 if f.get("pagato") else 0
      form["nome"], form["cognome"] = dbm.tidy_name(form["nome"]), dbm.tidy_name(form["cognome"])
      if not form["nome"]:
        errors.append("Il nome è obbligatorio")
      try:
        form["datanascita"] = dbm.norm_date(form["datanascita"])
      except ValueError as e:
        errors.append(str(e))
      pett = form["pettorale"]
      if pett and not pett.isdigit():
        errors.append("Il pettorale deve essere un numero")
      form["pettorale"] = int(pett) if pett.isdigit() else None
      if form["pettorale"] is not None:
        other = d.execute("SELECT nome, cognome FROM iscritti WHERE pettorale = ? AND id IS NOT ?",
                          (form["pettorale"], iid)).fetchone()
        if other:
          errors.append(f"Pettorale {form['pettorale']} già assegnato a {other['nome']} {other['cognome']}")
      form["ospiti_pranzo"] = dbm.norm_int(form["ospiti_pranzo"])
      for k in ("tipo", "sesso", "crazy"):
        form[k] = form[k] or None
      form["chiave"] = dbm.make_key(form["nome"], form["cognome"], form["datanascita"])
      dup = d.execute("SELECT id FROM iscritti WHERE chiave = ? AND id IS NOT ?", (form["chiave"], iid)).fetchone()
      if dup:
        errors.append("Esiste già un iscritto con stesso nome, cognome e data di nascita")
      if row and row["pettorale"] is not None and row["pettorale"] != form["pettorale"]:
        if _has_times(d, row["pettorale"]):
          errors.append(f"Il pettorale {row['pettorale']} ha già un tempo registrato: cancellalo prima di cambiare pettorale")
      presi = []
      if not errors and iid is None:
        # persona già vista in un'edizione precedente: completo i campi lasciati vuoti
        h = storico_per([form["chiave"]]).get(form["chiave"])
        for k in edizioni.STORICO_CAMPI:
          if h and form[k] is None and h.get(k):
            form[k] = h[k]
            presi.append(k)
        if presi:
          flash(f"{', '.join('tipologia' if k == 'tipo' else k for k in presi).capitalize()} "
                f"presi dall'edizione {h['anno']}: controlla", "info")
      if not errors:
        cols = ("chiave", "nome", "cognome", "datanascita", "tipo", "sesso", "crazy", "pettorale",
                "pranzo", "ospiti_pranzo", "pagato", "note")
        vals = [form[c] for c in cols] + [dbm.now()]
        if iid is None:
          d.execute(f"INSERT INTO iscritti ({', '.join(cols)}, aggiornato, fonte) "
                    f"VALUES ({', '.join('?' * len(cols))}, ?, 'desk')", vals)
        else:
          d.execute(f"UPDATE iscritti SET {', '.join(c + ' = ?' for c in cols)}, aggiornato = ? WHERE id = ?",
                    vals + [iid])
        d.commit()
        flash(f"Salvato: {form['nome']} {form['cognome']}", "ok")
        return redirect(url_for("iscritti", _anchor=f"i{iid}" if iid else None))
    return render_template("iscritto.html", form=form, iid=iid, errors=errors)

  @app.post("/iscritti/<int:iid>/pagato")
  def toggle_pagato(iid: int):
    d = get_db()
    d.execute("UPDATE iscritti SET pagato = 1 - pagato, aggiornato = ? WHERE id = ?", (dbm.now(), iid))
    d.commit()
    return redirect(url_for("iscritti", _anchor=f"i{iid}"))

  @app.post("/iscritti/<int:iid>/elimina")
  def elimina(iid: int):
    d = get_db()
    row = d.execute("SELECT * FROM iscritti WHERE id = ?", (iid,)).fetchone()
    if row is None:
      abort(404)
    if row["pettorale"] is not None and _has_times(d, row["pettorale"]):
      flash("Ha un tempo registrato: cancella prima il tempo", "err")
      return redirect(url_for("modifica", iid=iid))
    d.execute("DELETE FROM iscritti WHERE id = ?", (iid,))
    d.commit()
    flash(f"Eliminato: {row['nome']} {row['cognome']}", "ok")
    return redirect(url_for("iscritti"))

  # ---------- import ----------

  def storico_per(chiavi: list[str]) -> dict[str, dict]:
    return edizioni.storico(data_dir, app.config["YEAR"], chiavi)

  @app.route("/import", methods=["GET", "POST"])
  def import_csv():
    pending = pending_import()
    if request.method == "POST":
      if request.form.get("azione") == "conferma" and pending.exists():
        text = pending.read_text(encoding="utf-8")
        p = importer.apply(get_db(), text, storico_per(importer.chiavi(text)))
        pending.unlink()
        flash(f"Import completato: {len(p.nuovi)} nuovi, {len(p.modificati)} aggiornati", "ok")
        return redirect(url_for("iscritti"))
      if request.form.get("azione") == "annulla":
        pending.unlink(missing_ok=True)
        return redirect(url_for("import_csv"))
      file = request.files.get("file")
      if not file or not file.filename:
        flash("Scegli un file CSV", "err")
        return redirect(url_for("import_csv"))
      raw = file.read()
      try:
        text = raw.decode("utf-8-sig")
      except UnicodeDecodeError:
        text = raw.decode("latin-1")
      pending.parent.mkdir(parents=True, exist_ok=True)
      pending.write_text(text, encoding="utf-8")
    preview = None
    if pending.exists():
      text = pending.read_text(encoding="utf-8")
      preview = importer.preview(get_db(), text, storico_per(importer.chiavi(text)))
    anno = app.config["YEAR"]
    anno_sbagliato = bool(preview and preview.anni_risposte and not {anno, anno - 1} & set(preview.anni_risposte))
    return render_template("import.html", preview=preview, anno_sbagliato=anno_sbagliato)

  # ---------- tempi ----------
  # /tempi: riepilogo di intermedi e finali per pettorale.
  # /tempi/intermedio e /tempi/arrivo: inserimento a blocchi ("aggiungi o correggi"), in qualunque ordine.

  NOMI_FASE = {"intermedio": "intermedi", "arrivo": "finali"}

  @app.get("/tempi")
  def tempi():
    d = get_db()
    rows = d.execute(
      "SELECT p.pettorale, i.nome, i.cognome, i.tipo, m.tempo AS intermedio, m.ftempo AS f_intermedio, "
      "t.tempo AS arrivo, t.ftempo AS f_arrivo FROM "
      "(SELECT pettorale FROM tempi UNION SELECT pettorale FROM intermedi) p "
      "LEFT JOIN iscritti i ON i.pettorale = p.pettorale "
      "LEFT JOIN intermedi m ON m.pettorale = p.pettorale LEFT JOIN tempi t ON t.pettorale = p.pettorale "
      "ORDER BY p.pettorale").fetchall()
    counts = {f: d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for f, t in dbm.FASI.items()}
    return render_template("tempi.html", rows=rows, counts=counts, tv_primo=_tv_primo(d))

  @app.route("/tempi/<fase>", methods=["GET", "POST"])
  def inserisci_tempi(fase: str):
    """Una riga per tempo, `pettorale tempo`: prima si controlla, poi si salva.
    Un pettorale che ha già un tempo viene corretto."""
    if fase not in dbm.FASI:
      abort(404)
    d = get_db()
    testo = request.form.get("testo", "")
    righe = inserimento.check_bulk(d, fase, testo) if request.method == "POST" else None
    if request.method == "POST" and request.form.get("azione") == "salva" and righe:
      salvate, restano = inserimento.save(d, fase, righe, sovrascrivi=True)
      if salvate:
        flash(f"Salvati {len(salvate)} tempi {NOMI_FASE[fase]}", "ok")
      elif not restano:
        flash("Nessuna modifica: questi tempi erano già registrati", "info")
      if restano:
        flash(f"{len(restano)} righe da rivedere: sono rimaste nella casella", "err")
        testo = "\n".join(r.testo for r in restano)
        righe = restano
      else:
        return redirect(url_for("inserisci_tempi", fase=fase))
    return render_template("tempi_inserisci.html", fase=fase, nome_fase=NOMI_FASE[fase], testo=testo,
                           anteprima=righe, count=d.execute(f"SELECT COUNT(*) FROM {dbm.FASI[fase]}").fetchone()[0])

  @app.post("/tempi/traguardo-volante")
  def traguardo_volante():
    """Primo al traguardo volante quando i tempi intermedi non si prendono (es. pioggia)."""
    d = get_db()
    pett = request.form.get("pettorale", "").strip()
    if not pett:
      rankings.set_setting(d, "traguardo_volante", None)
      flash("Primo al traguardo volante rimosso", "ok")
    elif not pett.isdigit() or not d.execute("SELECT 1 FROM iscritti WHERE pettorale = ?", (int(pett),)).fetchone():
      flash(f"Nessun iscritto con pettorale {pett}", "err")
    else:
      rankings.set_setting(d, "traguardo_volante", pett)
      flash(f"Primo al traguardo volante: pettorale {pett}", "ok")
    return redirect(url_for("tempi"))

  @app.post("/tempi/<fase>/<int:pettorale>/elimina")
  def elimina_tempo(fase: str, pettorale: int):
    if fase not in dbm.FASI:
      abort(404)
    d = get_db()
    d.execute(f"DELETE FROM {dbm.FASI[fase]} WHERE pettorale = ?", (pettorale,))
    d.commit()
    flash(f"Tempo {'intermedio' if fase == 'intermedio' else 'finale'} del pettorale {pettorale} cancellato", "ok")
    return redirect(url_for("tempi"))

  @app.get("/api/pettorale/<int:pettorale>")
  def api_pettorale(pettorale: int):
    d = get_db()
    r = d.execute("SELECT i.nome, i.cognome, i.tipo, t.tempo AS arrivo, m.tempo AS intermedio FROM iscritti i "
                  "LEFT JOIN tempi t ON t.pettorale = i.pettorale LEFT JOIN intermedi m ON m.pettorale = i.pettorale "
                  "WHERE i.pettorale = ?", (pettorale,)).fetchone()
    return jsonify(dict(r) if r else None)

  # ---------- classifiche ----------

  def year_out() -> Path:
    return app.config["OUT_DIR"] / str(app.config["YEAR"])

  @app.get("/classifiche")
  def classifiche():
    d = get_db()
    senza_tempo = d.execute("SELECT * FROM iscritti WHERE pettorale IS NOT NULL AND pettorale NOT IN "
                            "(SELECT pettorale FROM tempi) ORDER BY pettorale").fetchall()
    files = sorted(p.name for p in year_out().glob("*.pdf")) if year_out().exists() else []
    return render_template("classifiche.html", classifiche=rankings.classifiche(d), premi=rankings.premi(d),
                           tv_primo=_tv_primo(d), has_intermedi=rankings.has_intermedi(d),
                           senza_tempo=senza_tempo, files=files)

  @app.post("/classifiche/pdf")
  def genera_pdf():
    files = rankings.write_pdfs(get_db(), app.config["YEAR"], app.config["OUT_DIR"])
    flash(f"Generati {len(files)} PDF in {year_out()}", "ok")
    return redirect(url_for("classifiche"))

  @app.get("/out/<path:name>")
  def pdf(name: str):
    return send_from_directory(year_out(), name)

  # ---------- backup ----------

  @app.get("/backup")
  def backup_page():
    bdir: Path = app.config["BACKUP_DIR"]
    files = sorted(bdir.glob("*.sqlite"), reverse=True) if bdir.exists() else []
    return render_template("backup.html", files=files, db_path=db_path())

  @app.post("/backup")
  def backup_now():
    dest = backup(force=True)
    flash(f"Backup salvato: {dest}", "ok")
    return redirect(url_for("backup_page"))

  @app.get("/export.xlsx")
  def export_xlsx():
    out: Path = app.config["OUT_DIR"]
    out.mkdir(parents=True, exist_ok=True)
    name = f"crazyscalata-{app.config['YEAR']}-{datetime.datetime.now():%Y%m%d-%H%M}.xlsx"
    excel.export(get_db(), out / name)
    return send_from_directory(out, name, as_attachment=True)

  return app


def _missing(r) -> list[str]:
  return [label for key, label in (("pettorale", "pettorale"), ("sesso", "sesso"), ("crazy", "crazy"),
                                   ("tipo", "tipologia"), ("datanascita", "data di nascita")) if r[key] is None]


def _has_times(d: sqlite3.Connection, pettorale: int) -> bool:
  return any(d.execute(f"SELECT 1 FROM {t} WHERE pettorale = ?", (pettorale,)).fetchone() for t in dbm.FASI.values())


def _tv_primo(d: sqlite3.Connection):
  """Primo al traguardo volante inserito a mano, usato solo senza tempi intermedi (o None)."""
  pett = rankings.get_setting(d, "traguardo_volante")
  if not pett:
    return None
  return d.execute("SELECT pettorale, nome, cognome FROM iscritti WHERE pettorale = ?", (int(pett),)).fetchone()
