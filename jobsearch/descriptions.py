"""Cache of posting texts so the matcher can read them later.

Keys are job links, plus LinkedIn job ids (used by sources.linkedin.description), in one JSON file.
"""
import json

from .http import strip_html
from .profile import ROOT

PATH = ROOT / ".desc_cache.json"
MAX_CHARS = 8000


def load():
    return json.loads(PATH.read_text()) if PATH.exists() else {}


def save(cache):
    PATH.write_text(json.dumps(cache))


def remember(cache, jobs):
    for j in jobs:
        if j.desc and j.link:
            cache[j.link] = strip_html(j.desc)[:MAX_CHARS]
