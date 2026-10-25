from ..http import day, get
from ..models import Job

DESCRIPTION = "Arbeitnow (many arbeitnow.nl postings; occasionally rate-limited, just rerun)"
KEYS = []


def fetch(loc, pages=10):
    out = []
    for p in range(1, pages + 1):
        data = get(f"https://www.arbeitnow.com/api/job-board-api?page={p}").json().get("data", [])
        if not data:
            break
        out += [Job("Arbeitnow", j["title"], j["company_name"], j["location"], day(j["created_at"]),
                    j["url"], "remote" if j.get("remote") else "", j.get("description") or "")
                for j in data if loc.search(j["location"] or "")]
    return out


def tasks(profile):
    loc = profile.location_re()
    return [("arbeitnow", lambda: fetch(loc))]
