#!/usr/bin/env python3
"""Pull Netherlands job postings from public job APIs into nl_jobs.xlsx.

Sources (no key): LinkedIn guest search, Arbeitnow, and company boards on
Greenhouse, Lever, Ashby and Recruitee.
Sources (free key, skipped if unset): Adzuna (ADZUNA_APP_ID, ADZUNA_APP_KEY),
Jooble (JOOBLE_KEY).

Reads ~/Desktop/Jobs/jobs.xlsx only to mark jobs already tracked; never writes it.

Usage:
  python3 fetch_nl_jobs.py            # junior/medior tech roles, last 30 days
  python3 fetch_nl_jobs.py --all      # keep senior/lead titles too
  python3 fetch_nl_jobs.py --days 7
"""
import argparse
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import openpyxl
import requests
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
OUT = HERE / "nl_jobs.xlsx"
TRACKER = Path.home() / "Desktop/Jobs/jobs.xlsx"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

# Company boards known (2026-10-24) to post Netherlands roles. Add slugs freely.
BOARDS = {
    "greenhouse": ["adyen", "databricks", "catawiki", "fourthline", "dataiku", "gitlab",
                   "datadog", "dept", "typeform", "imc", "flowtraders", "elastic", "stripe"],
    "lever": ["mendix"],
    "ashby": ["mollie", "miro", "polarsteps", "bitvavo"],
    "recruitee": ["bunq", "ticketswap", "realworks", "sioux", "channable", "helloprint",
                  "vandebron", "greenchoice", "effectory"],
}

# Search terms for the keyword-based sources (LinkedIn, Adzuna, Jooble).
SEARCH_TERMS = ["software engineer", "software developer", "full stack developer",
                "fullstack engineer", "backend developer", "frontend developer", "web developer",
                "java developer", "kotlin developer", "android developer",
                "mobile developer", "junior developer", "graduate software engineer"]

NL = re.compile(r"netherlands|nederland|holland|amsterdam|rotterdam|utrecht|eindhoven|den haag|"
                r"the hague|'s-hertogenbosch|den bosch|delft|maastricht|groningen|leiden|haarlem|"
                r"nijmegen|tilburg|breda|arnhem|enschede|zwolle|amersfoort|hilversum|almere|"
                r"venlo|heerlen|sittard|geleen|roermond|weert|helmond|apeldoorn|schiphol|"
                r"hoofddorp|amstelveen|zaandam|deventer|veenendaal|best\b|veldhoven", re.I)
# Software engineering / full-stack and close relatives (backend, frontend, web, mobile).
TECH = re.compile(r"software|developer|ontwikkelaar|programmeur|programmer|full[- ]?stack|"
                  r"back[- ]?end|front[- ]?end|\bweb\b|android|\bios\b|mobile|kotlin|java\b|"
                  r"typescript|react|node|\.net|c#|golang|\bgo\b|php|ruby|application engineer|"
                  r"product engineer|platform engineer", re.I)
NOT_SWE = re.compile(r"electrical|mechanical|hardware|support|sales|field|service engineer|"
                     r"recruit|marketing|account|data (?:engineer|analyst|scientist)|analytics|"
                     r"\bqa\b|test engineer|tester|python", re.I)
HYBRID = re.compile(r"\bhybrid\b|hybride|\d (?:days?|dagen) (?:per week )?(?:in|at|on|op) (?:the|ons|het)? ?(?:office|kantoor)", re.I)
SENIOR = re.compile(r"senior|\bsr\.?\b|staff|principal|lead\b|head of|director|manager|architect|"
                    r"\bvp\b|chief|expert", re.I)


def get(url, **kw):
    kw.setdefault("timeout", 20)
    kw.setdefault("headers", UA)
    return requests.get(url, **kw)


def job(source, title, company, location, posted, link, remote="", desc=""):
    return {"source": source, "title": (title or "").strip(), "company": (company or "").strip(),
            "location": (location or "").strip(), "remote": remote, "posted": posted or "",
            "link": link or "", "desc": desc or ""}


def day(value):
    """Normalise ISO strings / epoch (s or ms) to YYYY-MM-DD."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        if value > 1e11:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    return str(value)[:10]


# ---------- sources ----------

def greenhouse(slug):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    r.raise_for_status()
    return [job("Greenhouse", j["title"], j.get("company_name") or slug, j["location"]["name"],
                day(j.get("first_published") or j.get("updated_at")), j["absolute_url"],
                desc=html.unescape(j.get("content") or ""))
            for j in r.json()["jobs"] if NL.search(j["location"]["name"])]


def lever(slug):
    r = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    r.raise_for_status()
    out = []
    for j in r.json():
        loc = (j.get("categories") or {}).get("location") or ""
        if j.get("country") == "NL" or NL.search(loc):
            out.append(job("Lever", j["text"], slug, loc, day(j.get("createdAt")), j["hostedUrl"],
                           (j.get("workplaceType") or "").replace("onsite", "on-site"),
                           " ".join([j.get("descriptionPlain") or ""] +
                                    [l.get("content", "") for l in j.get("lists", [])])))
    return out


def ashby(slug):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        locs = [j.get("location", "")] + [a.get("location", "") for a in j.get("secondaryLocations", [])]
        country = (((j.get("address") or {}).get("postalAddress")) or {}).get("addressCountry", "")
        if NL.search(" ".join(locs + [country])):
            out.append(job("Ashby", j["title"], slug, "; ".join(l for l in locs if l),
                           day(j.get("publishedAt")), j["jobUrl"], (j.get("workplaceType") or ("Remote" if j.get("isRemote") else "")).lower().replace("onsite", "on-site"),
                           j.get("descriptionPlain") or ""))
    return out


def recruitee(slug):
    r = get(f"https://{slug}.recruitee.com/api/offers/")
    r.raise_for_status()
    out = []
    for j in r.json()["offers"]:
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        if j.get("country_code") == "NL" or NL.search(f"{loc} {j.get('country') or ''}"):
            out.append(job("Recruitee", j["title"], j.get("company_name") or slug, loc,
                           day(j.get("published_at") or j.get("created_at")), j["careers_url"],
                           "hybrid" if j.get("hybrid") else "remote" if j.get("remote") else "on-site" if j.get("on_site") else "",
                           (j.get("description") or "") + " " + (j.get("requirements") or "")))
    return out


def arbeitnow(pages=10):
    out = []
    for p in range(1, pages + 1):
        data = get(f"https://www.arbeitnow.com/api/job-board-api?page={p}").json().get("data", [])
        if not data:
            break
        out += [job("Arbeitnow", j["title"], j["company_name"], j["location"], day(j["created_at"]),
                    j["url"], "remote" if j.get("remote") else "", j.get("description") or "")
                for j in data if NL.search(j["location"] or "")]
    return out


CARD = re.compile(r'<div class="base-card.*?</li>', re.S)


def _li_field(card, cls):
    m = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</', card, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def linkedin(days, hybrid=False):
    """LinkedIn's public guest search. Entry + associate level, slow to avoid HTTP 429.
    hybrid=True uses LinkedIn's own hybrid filter (f_WT=3), which employers sometimes set wrongly."""
    out = []
    for term in SEARCH_TERMS:
        for start in range(0, 100, 25):
            url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?keywords={requests.utils.quote(term)}&location=Netherlands"
                   f"&f_TPR=r{days * 86400}&f_E=1,2,3&start={start}" + ("&f_WT=3" if hybrid else ""))
            for attempt in range(3):
                r = get(url)
                if r.status_code != 429:
                    break
                time.sleep(10 * (attempt + 1))
            cards = CARD.findall(r.text) if r.ok else []
            for c in cards:
                link = re.search(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)', c)
                posted = re.search(r'datetime="([\d-]+)"', c)
                out.append(job("LinkedIn", _li_field(c, "base-search-card__title"),
                               _li_field(c, "base-search-card__subtitle"),
                               _li_field(c, "job-search-card__location"),
                               posted.group(1) if posted else "", link.group(1) if link else "",
                               "hybrid" if hybrid else ""))
            time.sleep(1.5)
            if len(cards) < 10:
                break
    return out


def adzuna(days):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("  Adzuna: skipped (set ADZUNA_APP_ID and ADZUNA_APP_KEY)")
        return []
    out = []
    for term in SEARCH_TERMS:
        for page in range(1, 4):
            r = get(f"https://api.adzuna.com/v1/api/jobs/nl/search/{page}",
                    params={"app_id": app_id, "app_key": app_key, "what": term,
                            "results_per_page": 50, "max_days_old": days})
            if not r.ok:
                break
            res = r.json().get("results", [])
            out += [job("Adzuna", j.get("title"), (j.get("company") or {}).get("display_name"),
                        (j.get("location") or {}).get("display_name"), day(j.get("created")),
                        j.get("redirect_url")) for j in res]
            if len(res) < 50:
                break
    return out


def jooble():
    key = os.environ.get("JOOBLE_KEY")
    if not key:
        print("  Jooble: skipped (set JOOBLE_KEY)")
        return []
    out = []
    for term in SEARCH_TERMS:
        r = requests.post(f"https://jooble.org/api/{key}", json={"keywords": term, "location": "Netherlands"},
                          timeout=20)
        if r.ok:
            out += [job("Jooble", j.get("title"), j.get("company"), j.get("location"), day(j.get("updated")),
                        j.get("link"), desc=j.get("snippet") or "") for j in r.json().get("jobs", [])]
    return out


# ---------- language ----------

DESC_CACHE = HERE / ".desc_cache.json"
NL_WORDS = re.compile(r"\b(de|het|een|en|van|je|jij|wij|we|voor|met|bij|zijn|ons|onze|wat|als|ook|"
                      r"naar|werk|ervaring|functie)\b", re.I)
EN_WORDS = re.compile(r"\b(the|and|to|of|you|we|for|with|our|your|is|are|will|experience|role)\b", re.I)
NEEDS_DUTCH = re.compile(r"(fluent|native|proficient|proficiency|excellent|good|strong|business|"
                         r"professional|full)[^.\n]{0,40}\bdutch\b|\bdutch\b[^.\n]{0,40}(required|"
                         r"is a must|mandatory|essential|speaking|fluency|proficiency|native|"
                         r"written and spoken|spoken and written)|nederlandstalig|"
                         r"(goede|uitstekende) beheersing van de nederlandse|vloeiend nederlands", re.I)
OPTIONAL = re.compile(r"plus|nice to have|bonus|advantage|preferred|not required|no dutch|"
                      r"not a must|don't need|do not need|optional", re.I)


def strip_html(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def linkedin_desc(link, cache):
    m = re.search(r"(\d{6,})/?$", link)
    if not m:
        return ""
    jid = m.group(1)
    if jid not in cache:
        r = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
        if r.status_code == 429:
            time.sleep(15)
            r = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
        d = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", r.text, re.S) if r.ok else None
        if not d:
            return ""  # don't cache failures, retry next run
        cache[jid] = strip_html(d.group(1))
        time.sleep(1.2)
    return cache[jid]


def language(title, desc):
    """'Dutch' (posting written in Dutch), 'Dutch required', 'English', or '?' (no text)."""
    text = strip_html(desc)
    if not text:
        return "Dutch" if re.search(r"ontwikkelaar|medewerker|\bbij\b|programmeur", title, re.I) else "?"
    if len(NL_WORDS.findall(text)) > 1.2 * len(EN_WORDS.findall(text)):
        return "Dutch"
    for sentence in re.split(r"(?<=[.!?•\n])\s+", text):
        if NEEDS_DUTCH.search(sentence) and not OPTIONAL.search(sentence):
            return "Dutch required"
    return "English"


# ---------- pipeline ----------

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tracked_keys():
    """(company+title) and links already in Cristian's tracker, any sheet."""
    keys, links = set(), set()
    if not TRACKER.exists():
        return keys, links
    wb = openpyxl.load_workbook(TRACKER, read_only=True)
    for ws in wb:
        rows = ws.iter_rows(values_only=True)
        head = [str(h or "") for h in next(rows, [])]
        try:
            ti, ci, li = head.index("Job title"), head.index("Company"), head.index("Link")
        except ValueError:
            continue
        for row in rows:
            if row[ti]:
                keys.add(norm(row[ci]) + "|" + norm(row[ti]))
            if row[li]:
                links.add(str(row[li]).split("?")[0])
    return keys, links


def previous_links():
    if not OUT.exists():
        return set()
    wb = openpyxl.load_workbook(OUT, read_only=True)
    return {str(r[-1]) for ws in wb for r in ws.iter_rows(min_row=2, values_only=True) if r and r[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="max posting age (default 30)")
    ap.add_argument("--all", action="store_true", help="keep senior/lead/manager titles")
    ap.add_argument("--no-linkedin", action="store_true", help="skip LinkedIn (slowest source)")
    ap.add_argument("--hybrid", action="store_true", help="only hybrid jobs")
    ap.add_argument("--dutch-filter", action="store_true",
                    help="drop Dutch-language / Dutch-required jobs (slower: opens each LinkedIn posting)")
    args = ap.parse_args()

    tasks = [(f"{ats}:{s}", fn, (s,)) for ats, fn in
             [("greenhouse", greenhouse), ("lever", lever), ("ashby", ashby), ("recruitee", recruitee)]
             for s in BOARDS[ats]]
    tasks += [("arbeitnow", arbeitnow, ()), ("adzuna", adzuna, (args.days,)), ("jooble", jooble, ())]
    if not args.no_linkedin:
        tasks.append(("linkedin", linkedin, (args.days, args.hybrid)))

    jobs = []

    def run(task):
        name, fn, a = task
        try:
            return name, fn(*a), None
        except Exception as e:  # one broken board shouldn't stop the run
            return name, [], e

    print("Fetching...")
    with ThreadPoolExecutor(12) as ex:
        for name, got, err in ex.map(run, tasks):
            if err:
                print(f"  {name}: failed ({err.__class__.__name__}: {err})")
            jobs += got
    print(f"  {len(jobs)} Netherlands postings fetched")

    cutoff = (date.today() - timedelta(days=args.days)).isoformat()
    keys, links = tracked_keys()
    before = previous_links()
    seen, rows = set(), []
    for j in jobs:
        if not TECH.search(j["title"]) or NOT_SWE.search(j["title"]):
            continue
        if not args.all and SENIOR.search(j["title"]):
            continue
        if not j["remote"] and HYBRID.search(" ".join([j["title"], j["location"], strip_html(j["desc"])])):
            j["remote"] = "hybrid"
        if args.hybrid and j["remote"] != "hybrid":
            continue
        if j["posted"] and j["posted"] < cutoff:
            continue
        key = norm(j["company"]) + "|" + norm(j["title"])
        if key in seen:
            continue
        seen.add(key)
        link = j["link"].split("?")[0] if "linkedin" in j["link"] else j["link"]
        j["link"] = link
        j["tracked"] = "yes" if key in keys or link in links else ""
        j["new"] = "" if link in before else "new"
        rows.append(j)

    for j in rows:
        j["lang"] = ""
    if args.dutch_filter:
        cache = json.loads(DESC_CACHE.read_text()) if DESC_CACHE.exists() else {}
        todo = sum(1 for j in rows if j["source"] == "LinkedIn" and not j["desc"])
        print(f"Checking language ({todo} LinkedIn descriptions, cached ones are instant)...")
        for j in rows:
            if j["source"] == "LinkedIn" and not j["desc"]:
                j["desc"] = linkedin_desc(j["link"], cache)
            j["lang"] = language(j["title"], j["desc"])
        DESC_CACHE.write_text(json.dumps(cache))
        before_n = len(rows)
        rows = [j for j in rows if not j["lang"].startswith("Dutch")]
        print(f"  {before_n - len(rows)} Dutch-only jobs removed")
    rows.sort(key=lambda j: j["posted"], reverse=True)

    wb = openpyxl.load_workbook(OUT) if OUT.exists() else openpyxl.Workbook()
    if not OUT.exists():
        wb.remove(wb.active)
    title = f"NL {date.today().isoformat()}"
    if title in wb.sheetnames:
        del wb[title]
    ws = wb.create_sheet(title, 0)
    head = ["New since last run", "Already in tracker", "Posted", "Job title", "Company", "Location",
            "Work mode", "Language", "Source", "Link"]
    ws.append(head)
    for j in rows:
        ws.append([j["new"], j["tracked"], j["posted"], j["title"], j["company"], j["location"],
                   j["remote"], j["lang"], j["source"], j["link"]])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, w in enumerate([10, 10, 11, 50, 24, 30, 9, 14, 11, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(OUT)

    new = sum(1 for j in rows if j["new"] and not j["tracked"])
    print(f"Wrote {len(rows)} matching jobs ({new} new, untracked) to {OUT} [sheet '{title}']")


if __name__ == "__main__":
    sys.exit(main())
