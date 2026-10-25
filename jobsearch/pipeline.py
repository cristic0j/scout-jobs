"""fetch → detect → filter → dedupe/mark → optional Dutch check → merge into the results xlsx."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import descriptions, detect, filters, output
from .sources import SOURCES, linkedin


def fetch(profile):
    tasks = [t for s in profile.sources for t in SOURCES[s].tasks(profile)]

    def run(task):
        name, fn = task
        try:
            return name, fn(), None
        except Exception as e:  # one broken board shouldn't stop the run
            return name, [], e

    jobs = []
    with ThreadPoolExecutor(12) as ex:
        for name, got, err in ex.map(run, tasks):
            if err:
                print(f"  {name}: failed ({err.__class__.__name__}: {err})")
            jobs += got
    return jobs


def check_language(jobs, cache):
    todo = sum(1 for j in jobs if j.source == "LinkedIn" and not j.desc and "linkedin" in j.link)
    print(f"Checking language ({todo} LinkedIn descriptions, cached ones are instant)...")
    for j in jobs:
        if j.source == "LinkedIn" and not j.desc:
            j.desc = linkedin.description(j.link, cache)
        j.lang = detect.language(j.title, j.desc)


def run(profile):
    """Fetch and merge into the profile's results file. Returns the number of new rows."""
    print(f"\nFetching {', '.join(profile.sources)} for '{profile.name}'...")
    jobs = fetch(profile)
    print(f"  {len(jobs)} postings in {profile.location} fetched")

    for j in jobs:
        if "linkedin" in j.link:
            j.link = j.link.split("?")[0]
        j.level = detect.level(j.title)
        j.work_mode = detect.work_mode(j)
    jobs, dropped = filters.apply(jobs, filters.build(profile))

    keys, links = output.tracked_keys()
    seen, unique = set(), []
    for j in jobs:
        key = output.job_key(j.company, j.title)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        j.tracked = key in keys or j.link in links
        unique.append(j)
    jobs = unique

    cache = descriptions.load()
    lang_filter = filters.dutch(profile)
    if lang_filter:
        check_language(jobs, cache)
        jobs, more = filters.apply(jobs, [lang_filter])
        dropped += more
    descriptions.remember(cache, jobs)
    descriptions.save(cache)

    headers, rows = output.read(profile.output)
    rows, added = output.merge(rows, jobs, date.today().isoformat())
    output.write(profile.output, headers, rows)

    for reason, n in dropped.most_common():
        print(f"  dropped {n:4}  {reason}")
    waiting = sum(1 for r in rows if not r.get("Processed"))
    print(f"{len(jobs)} matching jobs, {added} new. {profile.output} now has {len(rows)} rows, "
          f"{waiting} not processed yet.")
    return added
