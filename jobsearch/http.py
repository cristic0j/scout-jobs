"""Small HTTP and text helpers shared by the sources."""
import html
import re
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def get(url, **kw):
    kw.setdefault("timeout", 20)
    kw.setdefault("headers", UA)
    return requests.get(url, **kw)


def day(value):
    """Normalise ISO strings / epoch (s or ms) to YYYY-MM-DD."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        if value > 1e11:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    return str(value)[:10]


def strip_html(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())
