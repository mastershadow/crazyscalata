"""Parsing e formattazione dei tempi di arrivo."""
from __future__ import annotations

import re

_TIME_RE = re.compile(r"^\d+(:\d{1,2}){0,2}([.,]\d+)?$")


def parse_time(t: str) -> tuple[str, float]:
  """Normalizza un tempo scritto a mano.

  Accetta `SS`, `MM:SS`, `HH:MM:SS`, con decimali opzionali separati da `.` o `,`
  (es. `45`, `3:12,5`, `1:02:03.45`). Restituisce (`HH:MM:SS.ff`, secondi).
  Solleva ValueError se il formato non è valido.
  """
  t = str(t).strip()
  if not _TIME_RE.match(t):
    raise ValueError(f"Tempo non valido: {t!r}")

  t = t.replace(",", ".")
  if "." not in t:
    t = t + ".00"

  whole, frac = t.split(".", 1)
  frac = frac.ljust(2, "0")[0:2]
  parts = [int(p) for p in whole.split(":")]
  while len(parts) < 3:
    parts.insert(0, 0)
  hours, mins, secs = parts
  if len(whole.split(":")) > 1 and secs > 59:
    raise ValueError(f"Secondi oltre 59: {t!r}")
  if len(whole.split(":")) > 2 and mins > 59:
    raise ValueError(f"Minuti oltre 59: {t!r}")

  seconds = hours * 3600 + mins * 60 + secs + int(frac) / 100
  # se i secondi/minuti erano "lunghi" (es. 75 secondi) ricalcolo HH:MM:SS
  h, rem = divmod(int(seconds), 3600)
  m, s = divmod(rem, 60)
  return f"{h:02d}:{m:02d}:{s:02d}.{frac}", seconds


def format_time(seconds: float) -> str:
  """Tempo leggibile per le classifiche: `M:SS.ff` oppure `H:MM:SS.ff`."""
  cents = round(seconds * 100)
  whole, ff = divmod(cents, 100)
  h, rem = divmod(whole, 3600)
  m, s = divmod(rem, 60)
  if h:
    return f"{h}:{m:02d}:{s:02d}.{ff:02d}"
  return f"{m}:{s:02d}.{ff:02d}"
