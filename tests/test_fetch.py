"""Spec daily-digest "Safe fetching": local HTTP servers behind a stubbed resolver and dialer.

Public-looking names resolve to documentation-free public addresses; the dial
seam sends those (and only those) to the local test server. Blocked addresses
go through the real policy and must never reach the dialer.
"""

from __future__ import annotations

import http.server
import socket
import threading
import time

import pytest

from daily_reading import dr_fetch

PUBLIC_IP = "93.184.216.34"


class Handler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):  # noqa: N802
        action = self.routes.get(self.path)
        if action is None:
            self.send_response(404)
            self.end_headers()
            return
        action(self)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    dialled = []
    names = {"public.test": [PUBLIC_IP]}

    def resolve(host, _port):
        return names.get(host, [])

    def dial(ip, _port, timeout):
        dialled.append(ip)
        assert ip == PUBLIC_IP, f"dialled a non-public address {ip}"
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)

    monkeypatch.setattr(dr_fetch, "_resolve_host", resolve)
    monkeypatch.setattr(dr_fetch, "_dial", dial)
    Handler.routes = {}
    yield {"routes": Handler.routes, "dialled": dialled, "names": names, "base": f"http://public.test:{port}"}
    httpd.shutdown()


def _fetch(url, **kw):
    kw.setdefault("timeout", 5)
    kw.setdefault("max_bytes", 1024 * 1024)
    return dr_fetch.fetch(url, user_agent="test", **kw)


def _body(data, status=200):
    def respond(handler):
        handler.send_response(status)
        handler.send_header("Content-Type", "application/rss+xml")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    return respond


def test_public_feed_is_fetched(server):
    server["routes"]["/feed"] = _body(b"<rss/>")
    result = _fetch(server["base"] + "/feed")
    assert result.body == b"<rss/>" and server["dialled"] == [PUBLIC_IP]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "100.64.1.1", "::ffff:127.0.0.1"])
def test_private_address_refused(server, address):
    server["names"]["sneaky.test"] = [address]
    with pytest.raises(dr_fetch.FetchError) as error:
        _fetch("http://sneaky.test/feed")
    assert error.value.reason == "blocked address"
    with pytest.raises(dr_fetch.FetchError) as literal:
        _fetch(f"http://[{address}]/feed" if ":" in address else f"http://{address}/feed")
    assert literal.value.reason == "blocked address"
    assert server["dialled"] == []


def test_one_private_address_among_public_ones_is_refused(server):
    server["names"]["mixed.test"] = [PUBLIC_IP, "10.1.2.3"]
    with pytest.raises(dr_fetch.FetchError, match="blocked address"):
        _fetch("http://mixed.test/feed")
    assert server["dialled"] == []


def test_redirect_to_a_private_address(server):
    def redirect(handler):
        handler.send_response(302)
        handler.send_header("Location", "http://127.0.0.1/feed")
        handler.end_headers()
    server["routes"]["/feed"] = redirect
    with pytest.raises(dr_fetch.FetchError) as error:
        _fetch(server["base"] + "/feed")
    assert error.value.reason == "blocked address"
    assert server["dialled"] == [PUBLIC_IP]  # only the first, public hop was dialled


def test_redirect_limit(server):
    def loop(handler):
        handler.send_response(301)
        handler.send_header("Location", "/feed")
        handler.end_headers()
    server["routes"]["/feed"] = loop
    with pytest.raises(dr_fetch.FetchError, match="too many redirects"):
        _fetch(server["base"] + "/feed")
    assert len(server["dialled"]) == dr_fetch.MAX_REDIRECTS + 1


def test_oversized_feed(server):
    server["routes"]["/big"] = _body(b"x" * 5000)

    def no_length(handler):
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b"y" * 5000)
    server["routes"]["/stream"] = no_length
    for path in ("/big", "/stream"):
        with pytest.raises(dr_fetch.FetchError) as error:
            _fetch(server["base"] + path, max_bytes=1000)
        assert error.value.reason == "too large"


def test_slow_feed(server):
    def slow(handler):
        handler.send_response(200)
        handler.end_headers()
        for _ in range(20):
            handler.wfile.write(b"<")
            handler.wfile.flush()
            time.sleep(0.2)
    server["routes"]["/slow"] = slow
    started = time.monotonic()
    with pytest.raises(dr_fetch.FetchError) as error:
        _fetch(server["base"] + "/slow", timeout=1)
    assert error.value.reason == "timeout"
    assert time.monotonic() - started < 3


def test_http_error_status(server):
    server["routes"]["/err"] = _body(b"oops", status=500)
    with pytest.raises(dr_fetch.FetchError) as error:
        _fetch(server["base"] + "/err")
    assert error.value.reason == "http 500"


def test_no_proxy_is_used(server, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    server["routes"]["/feed"] = _body(b"<rss/>")
    assert _fetch(server["base"] + "/feed").body == b"<rss/>"


@pytest.mark.parametrize("url", ["ftp://public.test/x", "file:///etc/hosts", "http://user:pw@public.test/x", "http:///x"])
def test_bad_urls(server, url):
    with pytest.raises(dr_fetch.FetchError):
        _fetch(url)
    assert server["dialled"] == []
