"""Download HTTP com limites, gzip, verificação de Content-Type/Content-Length e SHA-256."""

from __future__ import annotations

import hashlib
import http.client
import os
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from ...domain.shared.errors import DomainError

MAX_BYTES = 300 * 1024 * 1024
CONNECT_TIMEOUT = 30.0
TOTAL_TIMEOUT = 300.0
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size: int  # bytes gravados (após gzip)
    last_modified: str = ""  # cabeçalho `Last-Modified` da resposta ("" se ausente)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Só segue redirecionamentos para http/https (urllib aceitaria ftp)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme not in ("http", "https"):
            raise urllib.error.URLError(f"redirecionamento para esquema não suportado: {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # Sem FileHandler/FTPHandler: apenas HTTP(S).
    return urllib.request.build_opener(
        urllib.request.HTTPHandler,
        urllib.request.HTTPSHandler,
        _SafeRedirect,
        urllib.request.HTTPDefaultErrorHandler,
        urllib.request.HTTPErrorProcessor,
    )


def _unavailable(message: str) -> DomainError:
    return DomainError("network_unavailable", message)


def _incomplete(message: str) -> DomainError:
    return DomainError("download_incomplete", message)


def download(
    url: str,
    part_path: Path,
    *,
    connect_timeout: float = CONNECT_TIMEOUT,
    total_timeout: float = TOTAL_TIMEOUT,
    max_bytes: int = MAX_BYTES,
) -> DownloadResult:
    """Baixa `url` para `part_path` (arquivo `.part`); em qualquer falha o `.part` é removido."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise _unavailable("esquema de URL não suportado")
    part_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _download(url, part_path, connect_timeout, total_timeout, max_bytes)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise


def _download(
    url: str, part_path: Path, connect_timeout: float, total_timeout: float, max_bytes: int
) -> DownloadResult:
    deadline = time.monotonic() + total_timeout
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    try:
        with _opener().open(request, timeout=connect_timeout) as resp:  # noqa: S310
            ctype = resp.headers.get_content_type()
            if ctype != "text/csv":
                raise DomainError(
                    "unexpected_html", f"Content-Type inesperado: {ctype!r} (esperado text/csv)"
                )
            expected = resp.headers.get("Content-Length")
            gz = (resp.headers.get("Content-Encoding") or "").lower() == "gzip"
            result = _stream(resp, part_path, expected, gz, deadline, max_bytes)
            return replace(result, last_modified=resp.headers.get("Last-Modified") or "")
    except DomainError:
        raise
    except (http.client.IncompleteRead, ConnectionResetError, zlib.error) as exc:
        raise _incomplete(f"conexão encerrada antes do fim: {exc}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise _unavailable(f"falha de rede: {exc}") from exc


def _stream(resp, part_path, expected, gz, deadline, max_bytes) -> DownloadResult:
    digest = hashlib.sha256()
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
    raw = 0
    written = 0
    with open(part_path, "wb") as out:
        while True:
            if time.monotonic() > deadline:
                raise _unavailable("tempo total de download excedido")
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            raw += len(chunk)
            data = decomp.decompress(chunk, max_bytes - written + 1) if decomp else chunk
            written += len(data)
            if written > max_bytes or raw > max_bytes:
                raise _incomplete(f"limite de {max_bytes} bytes excedido")
            digest.update(data)
            out.write(data)
        if decomp is not None:
            tail = decomp.flush()
            written += len(tail)
            digest.update(tail)
            out.write(tail)
            if not decomp.eof:
                raise _incomplete("fluxo gzip truncado")
        out.flush()
        os.fsync(out.fileno())
    if expected is not None and expected.isdigit() and int(expected) != raw:
        raise _incomplete(f"recebidos {raw} bytes, Content-Length declarou {expected}")
    return DownloadResult(path=part_path, sha256=digest.hexdigest(), size=written)


def fetch_bytes(
    url: str, *, timeout: float = CONNECT_TIMEOUT, max_bytes: int = 32 * 1024 * 1024
) -> bytes:
    """GET pequeno em memória (respostas JSON do CKAN); mesmas regras de esquema e limites."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise _unavailable("esquema de URL não suportado")
    try:
        with _opener().open(urllib.request.Request(url), timeout=timeout) as resp:  # noqa: S310
            body = resp.read(max_bytes + 1)
    except (http.client.IncompleteRead, ConnectionResetError) as exc:
        raise _incomplete(f"conexão encerrada antes do fim: {exc}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise _unavailable(f"falha de rede: {exc}") from exc
    if len(body) > max_bytes:
        raise _incomplete(f"limite de {max_bytes} bytes excedido")
    return body
