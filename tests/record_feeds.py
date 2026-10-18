"""Record real feeds into tests/fixtures/feeds/ (run by hand; tests never use the network).

    .venv/bin/python tests/record_feeds.py
"""

from __future__ import annotations

import ssl
import urllib.request

import certifi
from pathlib import Path

FEEDS = {
    "rss2-brunosouzas.xml": "https://brunosouzas.com/rss.xml",
    "atom-martinfowler.xml": "https://martinfowler.com/feed.atom",
    "rss2-html-cloudflare.xml": "https://blog.cloudflare.com/rss/",
}
OUT = Path(__file__).resolve().parent / "fixtures" / "feeds"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    for name, url in FEEDS.items():
        request = urllib.request.Request(url, headers={"User-Agent": "hermes-daily-reading fixture recorder"})
        with opener.open(request, timeout=30) as response:
            body = response.read()
        (OUT / name).write_bytes(body)
        print(f"{name}: {len(body)} bytes from {url}")


if __name__ == "__main__":
    main()
