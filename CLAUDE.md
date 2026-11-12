# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single-script Python tool (`classifiche.py`) that builds the race rankings ("classifiche") for the CrazyScalata event: it reads an Excel workbook of registrations and finish times and writes one PDF per ranking into `out/`. Code, comments and output are mixed Italian/English; keep user-facing PDF text in Italian.

## Commands

```bash
pip3 install --user -r requirements.txt     # openpyxl, fpdf2 (devcontainer does this automatically)
python3 classifiche.py data/crazyscalata.xlsx   # generate all PDFs into out/ (titles use the current year)
python3 classifiche.py data/crazyscalata.xlsx --year 2025   # regenerate a past edition
sqlite3 debug.sqlite                        # inspect the data loaded by the last run
```

There are no tests, linter or build step; `data/sample.xlsx` (fictional participants, covers the time formats and a runner with no time) is the smoke-test input, also used by the "Test Classifiche" launch config. Run from the repo root: output paths (`out/*.pdf`, `debug.sqlite`) are relative to the CWD. Every run overwrites `out/*.pdf` and `debug.sqlite`, which may hold the real rankings: after testing with the sample, regenerate them from the real workbook.

## Data and privacy

- `data/` and `out/` are gitignored except `data/template.xlsx` and `data/sample.xlsx`: real workbooks and generated PDFs contain participants' personal data (names, birth dates) and must not be committed.
- Input workbook layout (see `data/template.xlsx`), header in row 1, reading stops at the first empty cell in column A:
  - sheet `ISCRITTI`: `nome, tipologia, crazy, pettorale, datanascita, sesso, pranzo` — values the views filter on: `tipologia` = `CICLISTA`/`PODISTA`, `crazy` = `SI`, `sesso` = `M`/`F`.
  - sheet `TEMPI`: `pettorale, tempo` — `tempo` is a free-form string like `45`, `3:12,5`, `1:02:03.45`.

## Architecture

Pipeline: Excel → SQLite → SQL views → PDF.

1. `create_db()` builds the schema. The module-level `debug = True` flag makes it delete and recreate `debug.sqlite` on every run; with `debug = False` it uses `:memory:`.
2. `read_data()` inserts rows positionally: column order in the sheets must match the table definitions (`iscritti` gets the Excel row number prepended as `id`). `process_time()` normalizes each time into `ntempo` (`HH:MM:SS.ff`) and `ftempo` (seconds as float, used for sorting).
3. Rankings are SQL views over `arrivi` (join of `iscritti` and `tempi` on `pettorale`): `c_assoluti`, `c_uomini`, `c_donne`, `c_crazy`, `c_ciclisti`, `c_podisti`, `c_eta` (crazy riders by birth date). Adding a ranking = new view in `create_db()` + a `create_ranking()` call in `create_rankings()`.
4. `extract_ranking_data()` and `create_extra()` read view rows by **index** (`r[0]` nome, `r[1]` pettorale, `r[3]` crazy, `r[4]` datanascita, `r[6]` tempo as originally typed) — changing the `arrivi` column list shifts these.
5. `create_extra()` produces `out/Media.pdf`: the 10 crazy participants closest to the overall average time.

The event year in the PDF titles comes from the module-level `year` (set by `--year`, default current year).
