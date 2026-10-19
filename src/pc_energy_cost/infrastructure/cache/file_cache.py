"""Cache de arquivos: troca atômica, SHA-256, TTL de 24 h (D7) e quarentena."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...domain.shared.errors import DomainError

TTL = timedelta(hours=24)
_KEY = re.compile(r"[A-Za-z0-9_.-]+")

Validator = Callable[[Path], None]


@dataclass(frozen=True)
class CachedFile:
    key: str
    path: Path
    sha256: str
    stored_at: datetime


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileCache:
    def __init__(self, root: Path, now: Callable[[], datetime] | None = None) -> None:
        self.root = root
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.quarantine_dir = root / "quarantine"

    def _check(self, key: str) -> None:
        if (
            not _KEY.fullmatch(key)
            or key in (".", "..", "quarantine")
            or key.endswith((".part", ".meta.json"))
        ):
            raise ValueError(f"chave de cache inválida: {key!r}")

    def path_for(self, key: str) -> Path:
        self._check(key)
        return self.root / key

    def part_path(self, key: str) -> Path:
        return self.path_for(key).with_name(key + ".part")

    def _meta_path(self, key: str) -> Path:
        return self.path_for(key).with_name(key + ".meta.json")

    def store(
        self, key: str, part: Path, sha256: str, validator: Validator | None = None
    ) -> CachedFile:
        """Valida o `.part` e o promove atomicamente; falha de schema o põe em quarentena."""
        target = self.path_for(key)
        if validator is not None:
            try:
                validator(part)
            except DomainError as exc:
                if exc.code == "schema_mismatch":
                    self._quarantine(key, part)
                else:
                    part.unlink(missing_ok=True)
                raise
        stored_at = self._now()
        meta = {"sha256": sha256, "stored_at": stored_at.isoformat()}
        meta_tmp = self._meta_path(key).with_suffix(".json.part")
        meta_tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(part, target)
        os.replace(meta_tmp, self._meta_path(key))
        return CachedFile(key, target, sha256, stored_at)

    def _quarantine(self, key: str, part: Path) -> None:
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%dT%H%M%S%f")
        os.replace(part, self.quarantine_dir / f"{key}.{stamp}")

    def lookup(self, key: str, expected_sha256: str | None = None) -> CachedFile | None:
        """Entrada validada (hash do arquivo = hash registrado/esperado) ou None se ausente."""
        target, meta_path = self.path_for(key), self._meta_path(key)
        if not target.exists() and not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            recorded = meta["sha256"]
            stored_at = datetime.fromisoformat(meta["stored_at"])
            actual = _sha256(target)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError("cache_corrupted", f"cache '{key}' ilegível: {exc}") from exc
        if actual != recorded or (expected_sha256 is not None and actual != expected_sha256):
            raise DomainError("cache_corrupted", f"hash do cache '{key}' não confere")
        return CachedFile(key, target, actual, stored_at)

    def age(self, key: str) -> timedelta | None:
        entry = self.lookup(key)
        return None if entry is None else self._now() - entry.stored_at

    def is_fresh(self, key: str, ttl: timedelta = TTL) -> bool:
        age = self.age(key)
        return age is not None and age < ttl
