import argparse
import sqlite3
import datetime
from pathlib import Path
from openpyxl import load_workbook
from fpdf import FPDF

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
    cursor.execute("INSERT INTO iscritti VALUES(?, ?, ?, ?, ?, ?, ?, ?)", [row] + list(map(lambda x : x.value, ws[row])))
    row = row + 1
  db.commit()
  
  wb.active = wb["TEMPI"]
  row = 2
  ws = wb.active
  cursor = db.cursor()
  while (True):
    if ws.cell(row=row, column=1).value is None:
      break
    cursor.execute("INSERT INTO tempi VALUES(?, ?, ?, ?)", list(map(lambda x : x.value, ws[row])) + process_time(ws[row][1].value))
    row = row + 1
  db.commit()
  
def process_time(t: str) -> list[any]:
  if "." not in t and "," not in t:
    # no fractional part, add it
    t = t + ".00"
    
  if "," in t:
    t = t.replace(",", ".")
    
  whole, frac = t.split(".", 1)
  frac = frac.ljust(2, "0")[0:2]
  
  wparts = whole.split(":")
  ftime = float(frac) / 100  
  
  if len(wparts) == 1:
    secs = wparts[0].rjust(2, "0")
    ftime += float(secs)
    whole = "00:00:" + secs
  if len(wparts) == 2:
    secs = wparts[1].rjust(2, "0")
    mins = wparts[0].rjust(2, "0")
    ftime += float(secs) + 60 * float(mins)
    whole = "00:" + mins + ":" + secs
  if len(wparts) == 3:
    secs = wparts[2].rjust(2, "0")
    mins = wparts[1].rjust(2, "0")
    hours = wparts[0].rjust(2, "0")
    ftime += float(secs) + 60 * float(mins) + 60 * 60 * float(hours)
    whole = hours + ":" + mins + ":" + secs
    
  res = [whole + "." + frac, ftime]
  return res
  
  
def create_rankings():
  data = [['Pos.', 'Nome', 'Pettorale', 'Tempo', 'Data Nascita'],
          ['00', 'Mike Driscoll', '42', '34:44.23', "20/12/1983"],
          ['00', 'John Doe', '42', '34:44.23', "20/12/1983"],
          ['00', 'Nina Ma', '42', '34:44.23', "20/12/1983"]
          ]
  create_ranking("Assoluti", data)
  create_ranking("Maschile", data)
  create_ranking("Femminile", data)
  create_ranking("CrazyBikers", data)
  create_ranking("Ciclisti", data)
  create_ranking("Podisti", data)

def create_ranking(name: str, data: list[list[str]]):
  pdf = FPDF(orientation="landscape", format="A4")
  pdf.add_page()
  pdf.set_font("helvetica", style="B", size=16)
  pdf.set_font_size(18)
  pdf.write(text="CrazyScalata 2025\n")
  pdf.set_font_size(20)
  pdf.write(10, "Classifica " + name)
  pdf.write(text='\n\n')
  pdf.set_font("courier", style="B", size=16)
  spacing = 1
  row_height = pdf.font_size
  colw = [20, 100, 50, 50, 50]
  for row in data:
    for idx, item in enumerate(row):
      pdf.cell(colw[idx], row_height*spacing, text=item, border=1)
    pdf.ln(row_height*spacing)
  pdf.output("out/{0}.pdf".format(name))
  
def create_db():
  global db
  global debug
  
  if (debug):
    db = sqlite3.connect("debug.sqlite")
  else:
    db = sqlite3.connect(":memory:")
  cursor = db.cursor()
  cursor.execute("CREATE TABLE IF NOT EXISTS iscritti (id INTEGER, nome TEXT, tipo TEXT, crazy TEXT, pettorale INTEGER, datanascita DATE, sesso TEXT, pranzo TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS tempi (pettorale INTEGER, tempo TEXT, ntempo TEXT, ftempo DECIMAL)")
  cursor.execute("CREATE VIEW IF NOT EXISTS arrivi AS SELECT i.nome, i.pettorale, i.tipo, i.crazy, i.datanascita, i.sesso, t.tempo, t.ntempo, t.ftempo FROM iscritti i, tempi t WHERE i.pettorale = t.pettorale")
  db.commit()


if __name__ == "__main__":
    main()

