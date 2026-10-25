import os

import requests

from ..http import day
from ..models import Job

DESCRIPTION = "Jooble (needs JOOBLE_KEY; international jooble.org, few NL results)"
KEYS = ["JOOBLE_KEY"]


def fetch(profile):
    key = os.environ.get("JOOBLE_KEY")
    if not key:
        print("  Jooble: skipped (set JOOBLE_KEY)")
        return []
    out = []
    for term in profile.search_terms:
        r = requests.post(f"https://jooble.org/api/{key}", json={"keywords": term, "location": profile.location},
                          timeout=20)
        if r.ok:
            out += [Job("Jooble", j.get("title"), j.get("company"), j.get("location"), day(j.get("updated")),
                        j.get("link"), desc=j.get("snippet") or "") for j in r.json().get("jobs", [])]
    return out


def tasks(profile):
    return [("jooble", lambda: fetch(profile))]
