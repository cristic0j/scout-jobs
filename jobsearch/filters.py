"""Filters built from a profile. Each is (reason, keep_fn); a job is dropped by the first that says no."""
from collections import Counter
from datetime import date, timedelta

from .matching import keyword_pattern


def build(profile, today=None, with_setup=True):
    cutoff = ((today or date.today()) - timedelta(days=profile.max_days)).isoformat()
    include, exclude = keyword_pattern(profile.title_include), keyword_pattern(profile.title_exclude)
    levels = set(profile.levels)
    out = []
    if include:
        out.append(("title has none of the role keywords", lambda j: bool(include.search(j.title))))
    if exclude:
        out.append(("title has an excluded keyword", lambda j: not exclude.search(j.title)))
    out.append(("seniority not selected", lambda j: j.level in levels))
    out.append((f"older than {profile.max_days} days", lambda j: not j.posted or j.posted >= cutoff))
    if with_setup and setup(profile):
        out.append(setup(profile))
    return out


def setup(profile):
    """Work setup by place and travel time; run after job.travel is filled in. None when anything goes."""
    if profile.any_setup_anywhere():
        return None
    allowed = profile.setup_allowed()
    return "work setup not allowed at that location", lambda j: allowed(j.work_mode, j.location, j.travel)


def dutch(profile):
    """Language filter, applied after descriptions are fetched; None when off."""
    if profile.dutch == "written":
        return "written in Dutch", lambda j: j.lang != "Dutch"
    if profile.dutch == "required":
        return "written in Dutch or Dutch required", lambda j: not j.lang.startswith("Dutch")
    return None


def apply(jobs, filters):
    kept, dropped = [], Counter()
    for j in jobs:
        for reason, keep in filters:
            if not keep(j):
                dropped[reason] += 1
                break
        else:
            kept.append(j)
    return kept, dropped
