"""Questions asked before a run. Plain numbered menus; Enter keeps the default shown in [brackets]."""
import os
import re

from .detect import LEVELS
from .matching import keyword_pattern
from .presets import PRESETS
from .profile import DUTCH_FILTERS, WORK_MODES, Profile, load, save, saved_names, slug
from .sources import SOURCES

COUNTRY_CODES = {"netherlands": "nl", "germany": "de", "belgium": "be", "united kingdom": "gb", "uk": "gb",
                 "france": "fr", "spain": "es", "italy": "it", "austria": "at", "switzerland": "ch",
                 "poland": "pl", "ireland": "ie", "romania": "ro"}


def ask(prompt, default=""):
    shown = f" [{default}]" if default != "" else ""
    return input(f"{prompt}{shown}: ").strip() or str(default)


def ask_yes(prompt, default=True):
    while True:
        a = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not a:
            return default
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False


def ask_int(prompt, default):
    while True:
        a = ask(prompt, default)
        if a.isdigit() and int(a) > 0:
            return int(a)
        print("  Please type a whole number.")


def choose_one(prompt, options, default):
    """options: [(value, label)]; returns the chosen value."""
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    d = next((i for i, (v, _) in enumerate(options, 1) if v == default), 1)
    while True:
        a = ask("Choose a number", d)
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][0]
        print(f"  Type a number from 1 to {len(options)}.")


def choose_many(prompt, options, defaults, allow_empty=False):
    """options: [(value, label)]; returns the chosen values in option order."""
    print(f"\n{prompt}")
    for i, (v, label) in enumerate(options, 1):
        print(f"  {i}) [{'x' if v in defaults else ' '}] {label}")
    d = ",".join(str(i) for i, (v, _) in enumerate(options, 1) if v in defaults) or "none"
    while True:
        a = ask("Numbers separated by commas, 'all' or 'none'", d).lower()
        if a == "all":
            return [v for v, _ in options]
        if a == "none":
            if allow_empty:
                return []
            print("  Pick at least one.")
            continue
        nums = [n for n in re.split(r"[,\s]+", a) if n]
        if nums and all(n.isdigit() and 1 <= int(n) <= len(options) for n in nums):
            picked = {int(n) for n in nums}
            return [v for i, (v, _) in enumerate(options, 1) if i in picked]
        print(f"  Use numbers from 1 to {len(options)}, e.g. 1,3.")


def split_list(text):
    return [x.strip().lstrip("+-").strip() for x in text.split(",") if x.strip().lstrip("+-").strip()]


def edit_list(prompt, current, required=False):
    print(f"\n{prompt}:\n  {', '.join(current) or '—'}")
    while True:
        a = input("  Enter = keep · 'a, b' = replace · '+a, b' = add · '-a, b' = remove · 'none' = clear: ").strip()
        if not a:
            new = list(current)
        elif a.lower() == "none":
            new = []
        elif a.startswith("+"):
            new = current + [x for x in split_list(a) if x not in current]
        elif a.startswith("-"):
            gone = {x.lower() for x in split_list(a)}
            new = [x for x in current if x.lower() not in gone]
        else:
            new = split_list(a)
        try:
            keyword_pattern(new)
        except re.error as e:
            print(f"  Invalid 're:' pattern ({e}), try again.")
            continue
        if required and not new:
            print("  At least one is needed.")
            continue
        if new != current:
            print(f"  → {', '.join(new) or '—'}")
        return new


def ask_location(p, loc):
    if loc.lower() in ("netherlands", "nederland", "the netherlands"):
        p.set_location(loc)
        return
    cities = split_list(ask("Cities to also accept in location fields (comma list, optional)"))
    code = ask("Two-letter country code (used by Adzuna, Lever, Recruitee)", COUNTRY_CODES.get(loc.lower(), ""))
    p.set_location(loc, cities, code)


def edit(p):
    p.search_terms = edit_list("Search terms (sent to LinkedIn, Jooble and Adzuna)", p.search_terms, required=True)
    if p.category == "custom" and not p.title_include:
        p.title_include = list(p.search_terms)
    p.title_include = edit_list("Job title must contain one of these (none = no requirement; "
                                "short words like 'go' match whole words only)", p.title_include)
    p.title_exclude = edit_list("Drop jobs whose title contains", p.title_exclude)

    p.levels = choose_many("Seniority levels to keep:", [(l, l) for l in LEVELS], p.levels)
    p.max_days = ask_int("\nMax posting age in days", p.max_days)

    p.work_modes = choose_many("Work mode (none = any; LinkedIn then runs one search per mode):",
                               [(m, m) for m in WORK_MODES], p.work_modes, allow_empty=True)
    if p.work_modes:
        p.keep_unknown_work_mode = ask_yes("Keep jobs whose work mode can't be determined?",
                                           p.keep_unknown_work_mode)

    p.dutch = choose_one("Dutch filter (opens each LinkedIn posting: slow on the first run, cached after):",
                         list(DUTCH_FILTERS.items()), p.dutch)

    loc = ask("\nCountry / region to search", p.location)
    if loc.lower() != p.location.lower():
        ask_location(p, loc)

    options = []
    for key, mod in SOURCES.items():
        note = ""
        if mod.KEYS:
            note = " ✓ key set" if all(os.environ.get(k) for k in mod.KEYS) else " ✗ key missing, will be skipped"
        options.append((key, mod.DESCRIPTION + note))
    p.sources = choose_many("Sources:", options, p.sources)
    if "boards" in p.sources and ask_yes("Edit the company board slugs?", False):
        for ats in p.boards:
            p.boards[ats] = edit_list(f"{ats} board slugs", p.boards[ats])
    return p


def run():
    """Ask everything; returns the Profile to run, or None if the user doesn't want to start."""
    print("Job search — Enter keeps the value in [brackets].")
    p = None
    saved = saved_names()
    if saved:
        pick = choose_one("Start from:", [(n, f"Saved profile: {n}") for n in saved] + [("", "New search")],
                          saved[0])
        if pick:
            p = load(pick)
            print(f"\n{p.describe()}")
            if ask_yes("\nRun with these settings?"):
                return p
    if p is None:
        category = choose_one("What kind of job?", [(k, v["label"]) for k, v in PRESETS.items()], "software")
        p = Profile.from_preset(category)
    edit(p)

    if ask_yes("\nSave these settings as a profile (lets you rerun without questions)?"):
        p.name = slug(ask("Profile name", p.name))
        print(f"  Saved to {save(p)}")
    print(f"\n{p.describe()}")
    return p if ask_yes("\nStart the search now?") else None
