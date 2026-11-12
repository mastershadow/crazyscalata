"""Genera le classifiche PDF da un workbook Excel (formato data/template.xlsx).

Per l'evento si usa l'app (python3 -m crazyscalata); questo script resta per
rielaborare un Excel, ad esempio quello del 2025 o un export dell'app.
"""
import argparse
import datetime
import os

from crazyscalata import db as dbm
from crazyscalata import excel, rankings

DEBUG_DB = "debug.sqlite"


def main():
  parser = argparse.ArgumentParser(prog='Classifiche', description='Classifiche CrazyScalata')
  parser.add_argument('filename')
  parser.add_argument('--year', type=int, default=datetime.date.today().year,
                      help="anno dell'evento nei titoli dei PDF (default: anno corrente)")
  args = parser.parse_args()

  # il database viene ricreato a ogni esecuzione e lasciato su disco per ispezionarlo
  try:
    os.remove(DEBUG_DB)
  except OSError:
    pass
  db = dbm.connect(DEBUG_DB)
  excel.load(db, args.filename)
  rankings.write_pdfs(db, args.year, "out")
  db.close()


if __name__ == "__main__":
  main()
