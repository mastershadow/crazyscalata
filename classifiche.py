import argparse
import sqlite3
import datetime
from pathlib import Path
from openpyxl import load_workbook

db = None
debug = False

def adapt_date_iso(val):
    return val.isoformat()
  
def main():
  parser = argparse.ArgumentParser(
                    prog='Classifiche',
                    description='Classifiche CrazyScalata')
  parser.add_argument('filename')
  args = parser.parse_args()
  setup(args.filename)
  db.close()
  
def setup(fname: str):
  sqlite3.register_adapter(datetime.datetime, adapt_date_iso)
  create_db()
  read_data(fname)
  create_rankings()
  
def read_data(fname: str):
  p = Path(fname)
  wb = load_workbook(filename = p.absolute())
  wb.active = wb["ISCRITTI"]
  row = 2
  ws = wb.active
  cursor = db.cursor()
  while (True):
    if ws.cell(row=row, column=1).value is None:
      break
    cursor.execute("INSERT INTO iscritti VALUES(?, ?, ?, ?, ?, ?, ?)", [row] + list(map(lambda x : x.value, ws[row])))
    row = row + 1
  db.commit()
  
  wb.active = wb["TEMPI"]
  row = 2
  ws = wb.active
  cursor = db.cursor()
  while (True):
    if ws.cell(row=row, column=1).value is None:
      break
    cursor.execute("INSERT INTO tempi VALUES(?, ?)", list(map(lambda x : x.value, ws[row])))
    row = row + 1
  db.commit()
  
def create_rankings():
  pass
  
def create_db():
  global db
  global debug
  
  if (debug):
    db = sqlite3.connect("debug.sqlite")
  else:
    db = sqlite3.connect(":memory:")
  cursor = db.cursor()
  cursor.execute("CREATE TABLE IF NOT EXISTS iscritti (id INTEGER, nome TEXT, tipo TEXT, pettorale INTEGER, datanascita DATE, sesso TEXT, pranzo TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS tempi (pettorale INTEGER, tempo TEXT)")
  cursor.execute("CREATE VIEW IF NOT EXISTS arrivi AS SELECT i.nome, i.pettorale, i.tipo, i.datanascita, i.sesso, t.tempo FROM iscritti i, tempi t WHERE i.pettorale = t.pettorale")
  db.commit()


if __name__ == "__main__":
    main()

