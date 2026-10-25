import os

from ..http import day, get
from ..models import Job

DESCRIPTION = "Adzuna (needs ADZUNA_APP_ID and ADZUNA_APP_KEY)"
KEYS = ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"]


def fetch(profile):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("  Adzuna: skipped (set ADZUNA_APP_ID and ADZUNA_APP_KEY)")
        return []
    out = []
    for term in profile.search_terms:
        for page in range(1, 4):
            r = get(f"https://api.adzuna.com/v1/api/jobs/{profile.country_code}/search/{page}",
                    params={"app_id": app_id, "app_key": app_key, "what": term,
                            "results_per_page": 50, "max_days_old": profile.max_days})
            if not r.ok:
                break
            res = r.json().get("results", [])
            out += [Job("Adzuna", j.get("title"), (j.get("company") or {}).get("display_name"),
                        (j.get("location") or {}).get("display_name"), day(j.get("created")),
                        j.get("redirect_url")) for j in res]
            if len(res) < 50:
                break
    return out


def tasks(profile):
    return [("adzuna", lambda: fetch(profile))]
