"""Web app locale (Flask) per il giorno dell'evento."""
from __future__ import annotations

import datetime
import sqlite3
import time
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from . import db as dbm
from . import excel, importer, inserimento, rankings
from .tempi import format_time

BACKUP_EVERY_S = 300
BACKUP_KEEP = 50


def create_app(db_path: str | Path, year: int, out_dir: str | Path, backup_dir: str | Path) -> Flask:
  app = Flask(__name__)
  app.config.update(
    SECRET_KEY="crazyscalata-offline",  # solo per i messaggi flash, l'app ascolta in locale
    DB_PATH=str(db_path), YEAR=year, OUT_DIR=Path(out_dir).absolute(),
    BACKUP_DIR=Path(backup_dir).absolute(), PENDING_IMPORT=Path(db_path).with_suffix(".import.csv"),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
  )
  app.jinja_env.globals.update(year=year, format_time=format_time, format_date=rankings.format_date)
  _last_backup = [0.0]

  def get_db() -> sqlite3.Connection:
    if "db" not in g:
      g.db = dbm.connect(app.config["DB_PATH"])
    return g.db

  @app.teardown_appcontext
  def close_db(_exc):
    d = g.pop("db", None)
    if d is not None:
      d.close()

  def backup(force: bool = False) -> Path | None:
    if not force and time.time() - _last_backup[0] < BACKUP_EVERY_S:
      return None
    bdir: Path = app.config["BACKUP_DIR"]
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"{Path(app.config['DB_PATH']).stem}-{datetime.datetime.now():%Y%m%d-%H%M%S}.sqlite"
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
    return render_template("iscritti.html", rows=rows, stats=stats, missing=_missing)

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

  @app.route("/import", methods=["GET", "POST"])
  def import_csv():
    pending: Path = app.config["PENDING_IMPORT"]
    if request.method == "POST":
      if request.form.get("azione") == "conferma" and pending.exists():
        p = importer.apply(get_db(), pending.read_text(encoding="utf-8"))
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
    preview = importer.preview(get_db(), pending.read_text(encoding="utf-8")) if pending.exists() else None
    return render_template("import.html", preview=preview)

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
    return render_template("backup.html", files=files, db_path=app.config["DB_PATH"])

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
