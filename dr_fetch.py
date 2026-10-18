"""Safe feed fetching (spec daily-digest "Safe fetching").

The address policy (`ip_is_blocked`, resolve-then-validate every address) is
adapted from hermes-newswire's SSRF gate, Copyright (c) 2026 Tony Simons, MIT
License (https://github.com/tony-simons-aiowa/hermes-newswire). The transport is
rewritten on the standard library: each hop resolves the host once, checks every
address, and connects to a checked address only (TLS still verifies the original
host name), so a second DNS answer cannot redirect the connection. No proxy is
ever used, nothing runs through a shell, and time and size are capped.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import List, Tuple
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class FetchError(Exception):
    """A feed could not be fetched; ``reason`` is a short category for the digest."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class FetchResult:
    status: int
    body: bytes
    url: str  # final URL after redirects
    content_type: str = ""


def ip_is_blocked(ip_text: str) -> bool:
    """True for any address that is not plainly public (adapted from hermes-newswire)."""
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return True
    if ip.version == 4 and ip in _CGNAT:
        return True
    return not ip.is_global


def _resolve_host(host: str, port: int) -> List[str]:
    """Resolve a host name to addresses. Test seam."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    seen: List[str] = []
    for info in infos:
        ip = str(info[4][0])
        if ip not in seen:
            seen.append(ip)
    return seen


def _dial(ip: str, port: int, timeout: float) -> socket.socket:
    """Open a TCP connection to one checked address. Test seam."""
    return socket.create_connection((ip, port), timeout=timeout)


def validated_target(url: str) -> Tuple[str, str, int, List[str]]:
    """(scheme, host, port, addresses) for a URL whose every address is public, or FetchError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("invalid url") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchError("unsupported scheme")
    if parts.username is not None or parts.password is not None:
        raise FetchError("invalid url")
    host = parts.hostname
    if not host:
        raise FetchError("invalid url")
    port = port or (443 if scheme == "https" else 80)
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        candidates = [host]
    except ValueError:
        candidates = _resolve_host(host, port)
        if not candidates:
            raise FetchError("cannot resolve host") from None
    if any(ip_is_blocked(ip) for ip in candidates):
        raise FetchError("blocked address")
    return scheme, host, port, candidates


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, addresses: List[str], timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._addresses = addresses

    def connect(self) -> None:
        last: Exception = OSError("no address")
        for ip in self._addresses:
            try:
                self.sock = _dial(ip, self.port, float(self.timeout or 15))
                return
            except OSError as exc:
                last = exc
        raise last


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    def __init__(self, host: str, port: int, addresses: List[str], timeout: float,
                 context: ssl.SSLContext):
        super().__init__(host, port, addresses, timeout)
        self._context = context

    def connect(self) -> None:
        super().connect()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def default_ssl_context() -> ssl.SSLContext:
    """System trust store, plus certifi's bundle when present (Python builds without system CAs)."""
    context = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return context


def fetch(url: str, *, timeout: float, max_bytes: int, user_agent: str,
          ssl_context: ssl.SSLContext | None = None) -> FetchResult:
    """GET a feed with checked, pinned hops. Raises FetchError with a reason category."""
    deadline = time.monotonic() + timeout
    context = ssl_context or default_ssl_context()
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        scheme, host, port, addresses = validated_target(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout")
        if scheme == "https":
            conn: http.client.HTTPConnection = _PinnedHTTPSConnection(host, port, addresses, remaining, context)
        else:
            conn = _PinnedHTTPConnection(host, port, addresses, remaining)
        parts = urlsplit(current)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            conn.request("GET", target, headers={
                "User-Agent": user_agent,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                conn.close()
                if not location:
                    raise FetchError(f"http {response.status}")
                current = urljoin(current, location.strip())
                continue
            if response.status != 200:
                conn.close()
                raise FetchError(f"http {response.status}")
            length = response.getheader("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                conn.close()
                raise FetchError("too large")
            chunks: List[bytes] = []
            size = 0
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    conn.close()
                    raise FetchError("timeout")
                if conn.sock is not None:
                    conn.sock.settimeout(left)
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    conn.close()
                    raise FetchError("too large")
                chunks.append(chunk)
            conn.close()
            return FetchResult(status=200, body=b"".join(chunks), url=current,
                               content_type=response.getheader("Content-Type") or "")
        except FetchError:
            raise
        except (socket.timeout, TimeoutError):
            conn.close()
            raise FetchError("timeout") from None
        except ssl.SSLError:
            conn.close()
            raise FetchError("tls error") from None
        except (OSError, http.client.HTTPException):
            conn.close()
            raise FetchError("network error") from None
    raise FetchError("too many redirects")
