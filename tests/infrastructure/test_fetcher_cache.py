"""Fetcher HTTP e cache de arquivo contra um servidor local (sem rede real)."""

from __future__ import annotations

import gzip
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.cache.file_cache import TTL, FileCache
from pc_energy_cost.infrastructure.http.fetcher import download

CSV = b'"A";"B"\n"1";"2"\n'
T0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class _Server:
    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.release = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.routes[self.path](self, outer)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


def _reply(body: bytes, ctype="text/csv", extra=None, length=None):
    def handler(h, _srv):
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body) if length is None else length))
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(body)
        h.wfile.flush()
        h.close_connection = True

    return handler


@pytest.fixture
def part(tmp_path):
    return tmp_path / "dl" / "file.part"


def test_download_writes_part_and_sha256_matches(server, part):
    server.routes["/ok"] = _reply(CSV)
    result = download(server.base + "/ok", part)
    assert part.read_bytes() == CSV
    assert result.sha256 == hashlib.sha256(CSV).hexdigest()
    assert result.size == len(CSV)


def test_gzip_is_accepted(server, part):
    server.routes["/gz"] = _reply(gzip.compress(CSV), extra={"Content-Encoding": "gzip"})
    result = download(server.base + "/gz", part)
    assert part.read_bytes() == CSV
    assert result.sha256 == hashlib.sha256(CSV).hexdigest()


def test_content_length_larger_than_body_is_download_incomplete(server, part):
    server.routes["/short"] = _reply(CSV, length=len(CSV) + 50)
    with pytest.raises(DomainError) as exc:
        download(server.base + "/short", part)
    assert exc.value.code == "download_incomplete"
    assert not part.exists()


def test_text_plain_is_rejected(server, part):
    server.routes["/p"] = _reply(CSV, ctype="text/plain")
    with pytest.raises(DomainError) as exc:
        download(server.base + "/p", part)
    assert exc.value.code == "unexpected_html"
    assert not part.exists()


def test_byte_cap_exceeded(server, part):
    server.routes["/big"] = _reply(b"x" * 100)
    with pytest.raises(DomainError) as exc:
        download(server.base + "/big", part, max_bytes=10)
    assert exc.value.code == "download_incomplete"
    assert not part.exists()


def test_timeout_is_network_unavailable(server, part):
    server.routes["/slow"] = lambda h, srv: srv.release.wait(30)
    with pytest.raises(DomainError) as exc:
        download(server.base + "/slow", part, connect_timeout=0.3, total_timeout=1)
    assert exc.value.code == "network_unavailable"
    assert not part.exists()


def test_redirect_to_non_http_scheme_is_refused(server, part):
    def redirect(h, _srv):
        h.send_response(302)
        h.send_header("Location", "ftp://127.0.0.1/x.csv")
        h.send_header("Content-Length", "0")
        h.end_headers()

    server.routes["/r"] = redirect
    with pytest.raises(DomainError) as exc:
        download(server.base + "/r", part)
    assert exc.value.code == "network_unavailable"
    assert not part.exists()


def test_redirect_to_http_keeps_content_type_check(server, part):
    def redirect(h, _srv):
        h.send_response(302)
        h.send_header("Location", "/p")
        h.send_header("Content-Length", "0")
        h.end_headers()

    server.routes["/r2"] = redirect
    server.routes["/p"] = _reply(b"<html>", ctype="text/html")
    with pytest.raises(DomainError) as exc:
        download(server.base + "/r2", part)
    assert exc.value.code == "unexpected_html"


def test_file_scheme_and_bad_cache_keys_rejected(tmp_path, part):
    with pytest.raises(DomainError):
        download("file:///etc/passwd", part)
    cache = _cache(tmp_path, [T0])
    for key in ("../x", "a/b", "..", "", "quarantine", "k.part", "k.meta.json"):
        with pytest.raises(ValueError):
            cache.path_for(key)


def test_connection_refused_is_network_unavailable(server, part):
    url = server.base + "/x"
    server.close()
    with pytest.raises(DomainError) as exc:
        download(url, part, connect_timeout=1)
    assert exc.value.code == "network_unavailable"


def _cache(tmp_path, clock):
    return FileCache(tmp_path / "cache", now=lambda: clock[0])


def _seed(cache, tmp_path, body=CSV, validator=None):
    p = cache.part_path("tarifas")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return cache.store("tarifas", p, hashlib.sha256(body).hexdigest(), validator)


def test_a21_html_and_schema_mismatch_keep_previous_cache(server, tmp_path):
    clock = [T0]
    cache = _cache(tmp_path, clock)
    good = _seed(cache, tmp_path)

    # HTML do servidor: rejeitado pelo fetcher, cache intacto
    server.routes["/html"] = _reply(b"<html>captcha</html>", ctype="text/html")
    with pytest.raises(DomainError) as exc:
        download(server.base + "/html", cache.part_path("tarifas"))
    assert exc.value.code == "unexpected_html"
    assert cache.lookup("tarifas").sha256 == good.sha256

    # validador injetado levanta schema_mismatch: quarentena, cache intacto
    bad = b'"X";"Y"\n'
    p = cache.part_path("tarifas")
    p.write_bytes(bad)

    def validator(path):
        raise DomainError("schema_mismatch", "coluna renomeada")

    with pytest.raises(DomainError) as exc:
        cache.store("tarifas", p, hashlib.sha256(bad).hexdigest(), validator)
    assert exc.value.code == "schema_mismatch"
    assert not p.exists()
    quarantined = list(cache.quarantine_dir.iterdir())
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == bad
    assert cache.lookup("tarifas").sha256 == good.sha256
    assert cache.path_for("tarifas").read_bytes() == CSV


def test_a22_connection_cut_discards_part_and_keeps_cache(server, tmp_path):
    clock = [T0]
    cache = _cache(tmp_path, clock)
    good = _seed(cache, tmp_path)
    server.routes["/cut"] = _reply(CSV[:5], length=1000)
    with pytest.raises(DomainError) as exc:
        download(server.base + "/cut", cache.part_path("tarifas"))
    assert exc.value.code == "download_incomplete"
    assert not cache.part_path("tarifas").exists()
    assert cache.lookup("tarifas").sha256 == good.sha256


def test_poisoned_cache_is_cache_corrupted(tmp_path):
    cache = _cache(tmp_path, [T0])
    _seed(cache, tmp_path)
    cache.path_for("tarifas").write_bytes(b"envenenado")
    with pytest.raises(DomainError) as exc:
        cache.lookup("tarifas")
    assert exc.value.code == "cache_corrupted"


def test_index_hash_mismatch_is_cache_corrupted(tmp_path):
    cache = _cache(tmp_path, [T0])
    _seed(cache, tmp_path)
    with pytest.raises(DomainError) as exc:
        cache.lookup("tarifas", expected_sha256="0" * 64)
    assert exc.value.code == "cache_corrupted"


def test_ttl_24h_and_age(tmp_path):
    clock = [T0]
    cache = _cache(tmp_path, clock)
    assert cache.lookup("tarifas") is None
    _seed(cache, tmp_path)
    assert TTL == timedelta(hours=24)
    clock[0] = T0 + timedelta(hours=23)
    assert cache.is_fresh("tarifas")
    assert cache.age("tarifas") == timedelta(hours=23)
    clock[0] = T0 + timedelta(hours=30)
    assert not cache.is_fresh("tarifas")
    assert cache.age("tarifas") == timedelta(hours=30)


def test_download_captures_last_modified_header(server, part):
    server.routes["/lm"] = _reply(CSV, extra={"Last-Modified": "Sun, 18 Oct 2026 12:00:00 GMT"})
    server.routes["/nolm"] = _reply(CSV)
    assert download(server.base + "/lm", part).last_modified == "Sun, 18 Oct 2026 12:00:00 GMT"
    assert download(server.base + "/nolm", part).last_modified == ""


def test_fetch_bytes_returns_body_and_maps_errors(server):
    from pc_energy_cost.infrastructure.http.fetcher import fetch_bytes

    server.routes["/j"] = _reply(b'{"ok": true}', ctype="application/json")
    assert fetch_bytes(server.base + "/j") == b'{"ok": true}'
    server.routes["/big"] = _reply(b"x" * 100, ctype="application/json")
    with pytest.raises(DomainError) as exc:
        fetch_bytes(server.base + "/big", max_bytes=10)
    assert exc.value.code == "download_incomplete"
    with pytest.raises(DomainError) as exc:
        fetch_bytes("file:///etc/passwd")
    assert exc.value.code == "network_unavailable"
    server.close()
    with pytest.raises(DomainError) as exc:
        fetch_bytes(server.base + "/j", timeout=1)
    assert exc.value.code == "network_unavailable"
