import html
import re
import time

import requests

from ..detect import LEVELS
from ..http import get, strip_html
from ..models import Job

DESCRIPTION = "LinkedIn guest search (most results, but slow: ~1.5 s per page)"
KEYS = []

# LinkedIn's own filter codes. Its work-mode tag is set by employers and is sometimes wrong.
LEVEL_CODES = {"internship": "1", "junior": "2", "medior": "3", "senior": "4,5,6"}
MODE_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}

CARD = re.compile(r'<div class="base-card.*?</li>', re.S)


def _field(card, cls):
    m = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</', card, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


NEAR_HOME_MILES = 25  # LinkedIn's distance filter is in miles (~40 km)


def plan(profile):
    """[(location, distance, work_mode)] queries per search term.
    Near home: any work mode. Elsewhere in the country: LinkedIn's hybrid / remote filters."""
    setups = set(profile.setups)
    if profile.any_setup_anywhere() or ("on-site" in setups and not profile.onsite_places):
        return [(profile.location, "", "")]
    queries = []
    home = profile.home or (profile.onsite_places or [""])[0]
    if "on-site" in setups and home:
        queries.append((f"{home}, {profile.location}", NEAR_HOME_MILES, ""))
    queries += [(profile.location, "", m) for m in ("hybrid", "remote") if m in setups]
    return queries


def search(profile):
    """Each search term × each query from plan(), sleeping between pages to avoid HTTP 429."""
    levels = ",".join(LEVEL_CODES[l] for l in LEVELS if l in profile.levels)
    out = []
    for location, distance, mode in plan(profile):
        for term in profile.search_terms:
            for start in range(0, 100, 25):
                url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                       f"?keywords={requests.utils.quote(term)}&location={requests.utils.quote(location)}"
                       f"&f_TPR=r{profile.max_days * 86400}&f_E={levels}&start={start}"
                       + (f"&distance={distance}" if distance else "")
                       + (f"&f_WT={MODE_CODES[mode]}" if mode else ""))
                for attempt in range(3):
                    r = get(url)
                    if r.status_code != 429:
                        break
                    time.sleep(10 * (attempt + 1))
                cards = CARD.findall(r.text) if r.ok else []
                for c in cards:
                    link = re.search(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)', c)
                    posted = re.search(r'datetime="([\d-]+)"', c)
                    out.append(Job("LinkedIn", _field(c, "base-search-card__title"),
                                   _field(c, "base-search-card__subtitle"),
                                   _field(c, "job-search-card__location"),
                                   posted.group(1) if posted else "", link.group(1) if link else "", mode))
                time.sleep(1.5)
                if len(cards) < 10:
                    break
    return out


def description(link, cache):
    """Full posting text for a LinkedIn job, cached by job id (~1.2 s per uncached posting)."""
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


def tasks(profile):
    return [("linkedin", lambda: search(profile))]
