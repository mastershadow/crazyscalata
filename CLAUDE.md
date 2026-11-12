# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Offline tool for the CrazyScalata event (a timed climb for cyclists and runners). On event day it runs on a single Mac, possibly without internet: a local Flask web app (`crazyscalata/`) handles registrations imported from Google Forms, desk registrations and payments, finish-time entry and the rankings PDFs. `classifiche.py` is a CLI that builds the same PDFs from an Excel workbook (last year's format). UI, code comments and PDF text are in Italian; keep it that way.

## Commands

```bash
pip3 install --user -r requirements-dev.txt   # flask, openpyxl, fpdf2, pytest (devcontainer does this)
python3 -m crazyscalata                       # app on http://127.0.0.1:8765, DB data/crazyscalata-<year>.sqlite
python3 -m crazyscalata --no-browser --db /tmp/x.sqlite --year 2026   # throwaway DB for manual testing
python3 -m pytest -q                          # all tests
python3 -m pytest -q tests/test_core.py::test_import_and_reimport   # single test
python3 classifiche.py data/sample.xlsx --year 2026   # CLI: Excel → out/2026/*.pdf (+ debug.sqlite)
```

On the Mac the user starts the app by double-clicking `avvia.command`, which creates `.venv` on first run (needs internet once) and then runs offline. Port 8765 is deliberate: 5000 is taken by AirPlay on macOS. The app must stay fully offline: no CDN assets, everything under `crazyscalata/static/`.

Output paths are relative to the repo: `out/<year>/` (PDFs), `out/` (Excel exports), `data/` (DB, `data/backup/`, pending import CSV). Generating PDFs overwrites `out/<year>/*.pdf`, which may hold real rankings (`out/*.pdf` at top level are the 2025 originals from the old script); tests and manual checks should use `tmp_path` or a scratch dir.

## Data and privacy

- `data/` and `out/` are gitignored except `data/template.xlsx` and `data/sample.xlsx` (fictional people, used by tests). Real registrations (names, birth dates, emails) must never be committed or printed in full.
- Google Form CSV columns (2026): `Timestamp, Username, Nome, Cognome, Data di Nascita (per le classifiche), Tipologia partecipante, Vieni al pranzo sociale?, Eventuali altri partecipanti al pranzo sociale, <GDPR consent>`; `Sesso` and `Crazy` questions are being added. Headers are matched loosely in `importer._COLUMNS`.
- Excel format (`template.xlsx`): sheet `ISCRITTI` = `nome, tipologia, crazy, pettorale, datanascita, sesso, pranzo`; sheet `TEMPI` = `pettorale, tempo[, intermedio]` (the third column is new in 2026 and optional). Read positionally until the first empty cell in column A.

## Architecture

- `db.py`: schema (`iscritti`, `tempi`, `impostazioni`, view `arrivi`) and value normalizers. Stored values are canonical: `tipo` CICLISTA/PODISTA, `sesso` M/F, `crazy`/`pranzo` SI/NO, dates `YYYY-MM-DD`; missing = NULL (shown as "da completare"). `chiave` = folded `cognome|nome|datanascita` is the identity across imports; email is not unique (families share one).
- `importer.py`: CSV → preview (new/changed/unchanged) → apply. Form-owned fields are updated on re-import, `sesso`/`crazy` only fill empty values, desk fields (`pettorale`, `pagato`, `note`) are never touched.
- `tempi.py`: `parse_time` accepts `45`, `3:12,5`, `1:02:03.45` → (`HH:MM:SS.ff`, seconds); `format_time` is the display format used in rankings.
- `rankings.py`: rankings come from two views: `arrivi` (final time, table `tempi`) and `passaggi` (intermediate time at the traguardo volante, table `intermedi`); participants without the matching time are excluded. Rules agreed with the user:
  - full rankings in `CLASSIFICHE` (title, view, SQL condition), one PDF each: Crazy, Assoluti (everyone), Donne cicliste, Podisti (men and women), Donne podiste, and Traguardo volante Crazy / Tutti, generated only when intermediate times exist;
  - prizes ("valori secchi") in `premi()`, all in `Premi.pdf`: top `PODIO` = 5 closest to the average time (cyclists only; everyone; average computed on the same group), 5 youngest, 5 oldest, traguardo volante (first crazy and first overall, labelled "Crazy"/"Tutti" in the Pos. column). No prize is assigned automatically: the app only lists values, organizers pick winners outside the app — don't add winner/decision tracking;
  - intermediate times are optional (with rain they may not be taken): then only the first bib may be noted by hand (`impostazioni.traguardo_volante`), used only when there are no intermediate times; with neither, the traguardo volante is "Non disputato";
  - ties share the position (1, 2, 2, 4); the top 5 includes everyone tied at 5th; the same person can appear in several prizes.
  PDFs use core fonts, so text goes through `_latin1()`. Validated against the 2025 workbook (no intermediate times) with an independent computation.
- `inserimento.py`: validation and saving of times. Times are entered only in bulk: `/tempi` shows intermediate and final per bib with two buttons, "Aggiungi o correggi intermedi" / "finali" (`/tempi/intermedio`, `/tempi/arrivo`), in any order. One `pettorale tempo` per line (tab/space/`;`, never comma: it's the decimal separator); preview marks each line ok / sovrascrive (corrects an existing time, saved) / uguale (ignored) / errore; valid lines are saved, the others stay in the textarea with their original error. In the textarea Tab inserts a tab and Cmd/Ctrl+Enter checks (`static/app.js`); the user must be able to do everything from the keyboard.
- `web.py`: all routes in `create_app()`. `db.FASI` maps `intermedio`/`arrivo` to the `intermedi`/`tempi` tables; an intermediate must be lower than the final time for the same bib. One SQLite connection per request; one SQLite connection per request; after any POST a DB backup is taken at most every 5 minutes (last 50 kept). `excel.py` loads/exports the template format, so an app export can be reprocessed by `classifiche.py`.
- Payments are a single paid yes/no flag; bibs are typed by hand (not sequential), uniqueness enforced.
