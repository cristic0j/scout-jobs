"""fetch → detect → filter → dedupe/mark → optional Dutch check → merge into the results xlsx."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import descriptions, detect, filters, output, travel
from .sources import SOURCES, linkedin


def fetch(profile):
    tasks = [t for s in profile.sources for t in SOURCES[s].tasks(profile)]

    def run(task):
        name, fn = task
        try:
            return name, fn(), None
        except Exception as e:  # one broken board shouldn't stop the run
            return name, [], e

    jobs, failed = [], []
    with ThreadPoolExecutor(12) as ex:
        for name, got, err in ex.map(run, tasks):
            if err:
                print(f"  {name}: failed ({err.__class__.__name__}: {err})")
                failed.append(name)
            elif name == "linkedin" and profile.search_terms and not got:
                print("  linkedin: no results at all (blocked or changed?)")
                failed.append(name)
            jobs += got
    return jobs, [n for n, _ in tasks], failed


def track_failures(search, names, failed):
    """Failures in a row per source, so the scheduler can warn when one keeps failing."""
    counts = search.state().get("source_failures", {})
    for n in names:
        counts[n] = counts.get(n, 0) + 1 if n in failed else 0
    search.save_state(source_failures={n: c for n, c in counts.items() if c})


def check_language(jobs, cache):
    todo = sum(1 for j in jobs if j.source == "LinkedIn" and not j.desc and "linkedin" in j.link)
    print(f"Checking language ({todo} LinkedIn descriptions, cached ones are instant)...")
    for j in jobs:
        if j.source == "LinkedIn" and not j.desc:
            j.desc = linkedin.description(j.link, cache)
        j.lang = detect.language(j.title, j.desc)


def add_travel(jobs, profile, search):
    """Travel minutes for jobs that could be hybrid away from home (only those are limited by it)."""
    if not profile.needs_travel() or not profile.home:
        return
    todo = [j for j in jobs if j.work_mode in ("hybrid", "") and not profile.near_home(j.location)]
    times = travel.minutes(search, profile.home, profile.location, [j.location for j in todo])
    for j in todo:
        j.travel = times.get(travel.place_key(j.location))


def run(profile, search):
    """Fetch and merge into the profile's results file. Returns the number of new rows."""
    print(f"\nFetching {', '.join(profile.sources)} for '{profile.name}'...")
    jobs, names, failed = fetch(profile)
    track_failures(search, names, failed)
    print(f"  {len(jobs)} postings in {profile.location} fetched")

    for j in jobs:
        if "linkedin" in j.link:
            j.link = j.link.split("?")[0]
        j.level = detect.level(j.title)
        j.work_mode = detect.work_mode(j)
    jobs, dropped = filters.apply(jobs, filters.build(profile, with_setup=False))
    add_travel(jobs, profile, search)
    if filters.setup(profile):
        jobs, more = filters.apply(jobs, [filters.setup(profile)])
        dropped += more

    keys, links = output.tracked_keys()
    seen, unique = set(), []
    for j in jobs:
        key = output.fuzzy_key(j.company, j.title)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        j.tracked = output.job_key(j.company, j.title) in keys or j.link in links
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

    path = search.result_path(profile)
    headers, rows = output.read(path)
    rows, added = output.merge(rows, jobs, date.today().isoformat())
    output.write(path, headers, rows)

    for reason, n in dropped.most_common():
        print(f"  dropped {n:4}  {reason}")
    waiting = sum(1 for r in rows if not r.get("Processed"))
    print(f"{len(jobs)} matching jobs, {added} new. {path.name} now has {len(rows)} rows, "
          f"{waiting} not processed yet.")
    return added
