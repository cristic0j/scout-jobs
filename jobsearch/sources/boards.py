import html

from ..http import day, get
from ..models import Job

DESCRIPTION = "Company career boards (Greenhouse, Lever, Ashby, Recruitee)"
KEYS = []


def greenhouse(slug, loc, cc):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    r.raise_for_status()
    return [Job("Greenhouse", j["title"], j.get("company_name") or slug, j["location"]["name"],
                day(j.get("first_published") or j.get("updated_at")), j["absolute_url"],
                desc=html.unescape(j.get("content") or ""))
            for j in r.json()["jobs"] if loc.search(j["location"]["name"])]


def lever(slug, loc, cc):
    r = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    r.raise_for_status()
    out = []
    for j in r.json():
        place = (j.get("categories") or {}).get("location") or ""
        if (cc and j.get("country") == cc) or loc.search(place):
            out.append(Job("Lever", j["text"], slug, place, day(j.get("createdAt")), j["hostedUrl"],
                           (j.get("workplaceType") or "").replace("onsite", "on-site"),
                           " ".join([j.get("descriptionPlain") or ""] +
                                    [l.get("content", "") for l in j.get("lists", [])])))
    return out


def ashby(slug, loc, cc):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        places = [j.get("location", "")] + [a.get("location", "") for a in j.get("secondaryLocations", [])]
        country = (((j.get("address") or {}).get("postalAddress")) or {}).get("addressCountry", "")
        if loc.search(" ".join(places + [country])):
            mode = j.get("workplaceType") or ("Remote" if j.get("isRemote") else "")
            out.append(Job("Ashby", j["title"], slug, "; ".join(p for p in places if p),
                           day(j.get("publishedAt")), j["jobUrl"], mode.lower().replace("onsite", "on-site"),
                           j.get("descriptionPlain") or ""))
    return out


def recruitee(slug, loc, cc):
    r = get(f"https://{slug}.recruitee.com/api/offers/")
    r.raise_for_status()
    out = []
    for j in r.json()["offers"]:
        place = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        if (cc and j.get("country_code") == cc) or loc.search(f"{place} {j.get('country') or ''}"):
            mode = "hybrid" if j.get("hybrid") else "remote" if j.get("remote") else "on-site" if j.get("on_site") else ""
            out.append(Job("Recruitee", j["title"], j.get("company_name") or slug, place,
                           day(j.get("published_at") or j.get("created_at")), j["careers_url"], mode,
                           (j.get("description") or "") + " " + (j.get("requirements") or "")))
    return out


ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "recruitee": recruitee}


def tasks(profile):
    loc, cc = profile.location_re(), profile.country_code.upper()
    return [(f"{ats}:{slug}", lambda fn=fn, slug=slug: fn(slug, loc, cc))
            for ats, fn in ATS.items() for slug in profile.boards.get(ats, [])]
