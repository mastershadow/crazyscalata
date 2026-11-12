"""Configurazione dell'app, condivisa tra le edizioni: data/config.json.

Contiene la chiave segreta delle sessioni (generata al primo avvio), l'hash del PIN e
l'ultima edizione aperta. Sta in data/, quindi non finisce nel repository.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

FILE = "config.json"
PIN_MIN = 4


class Config:
  def __init__(self, data_dir: str | Path):
    self.path = Path(data_dir) / FILE
    self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}
    if "secret_key" not in self.data:
      self.data["secret_key"] = secrets.token_hex(32)
      self.save()

  def save(self):
    self.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = self.path.with_suffix(".tmp")
    tmp.write_text(json.dumps(self.data, indent=2))
    tmp.replace(self.path)

  @property
  def secret_key(self) -> str:
    return self.data["secret_key"]

  @property
  def edizione(self) -> int | None:
    return self.data.get("edizione")

  @edizione.setter
  def edizione(self, anno: int):
    self.data["edizione"] = anno
    self.save()

  # ---- PIN ----

  @property
  def has_pin(self) -> bool:
    return bool(self.data.get("pin_hash"))

  def set_pin(self, pin: str):
    if len(pin) < PIN_MIN:
      raise ValueError(f"Il PIN deve avere almeno {PIN_MIN} caratteri")
    self.data["pin_hash"] = generate_password_hash(pin)
    # cambiando PIN le sessioni aperte decadono
    self.data["pin_version"] = self.data.get("pin_version", 0) + 1
    self.save()

  def reset_pin(self):
    self.data.pop("pin_hash", None)
    self.data["pin_version"] = self.data.get("pin_version", 0) + 1
    self.save()

  @property
  def pin_version(self) -> int:
    return self.data.get("pin_version", 0)

  def check_pin(self, pin: str) -> bool:
    return self.has_pin and check_password_hash(self.data["pin_hash"], pin)
