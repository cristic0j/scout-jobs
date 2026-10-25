"""Setup: the planner reads the CV(s), suggests roles and preferences, and asks only what it couldn't tell."""
from datetime import date

from . import questions
from .agents import planner
from .detect import LEVELS, WORK_MODES
from .preferences import NOT_ASKED, Preferences
from .profile import DUTCH_FILTERS
from .questions import ask, ask_int, ask_yes, choose_many, choose_one, edit_list, split_list


def ask_places(prompt, options, chosen, labels=None):
    """Multi-select from suggested places, then free-text extras. Returns the chosen places."""
    labels = labels or {}
    picked = []
    if options:
        picked = choose_many(prompt, [(o, labels.get(o) or o) for o in options], chosen, allow_empty=True)
    else:
        print(f"\n{prompt}")
    extra = split_list(ask("Add other places (comma list, Enter = none)"))
    return picked + [e for e in extra if e not in picked]


def ask_setups(prefs, plan):
    """On-site only near home, hybrid within a travel-time limit, remote anywhere."""
    prefs.setups = choose_many("Which work setups are you open to?", [(m, m) for m in WORK_MODES], prefs.setups)
    if not prefs.home and ({"on-site", "hybrid"} & set(prefs.setups)):
        prefs.home = ask("\nWhere do you live (city)?")
    home = prefs.home or "home"
    key = (prefs.home.lower(), prefs.location.lower())
    if prefs.home and ({"on-site", "hybrid"} & set(prefs.setups)) and plan.get("places_for") != key:
        print(f"Looking up the towns near {prefs.home}...")
        plan.update(planner.places(prefs.home, prefs.location, [r["label"] for r in plan.get("roles", [])]),
                    places_for=key)
    if "on-site" in prefs.setups:
        towns = list(dict.fromkeys(prefs.onsite_places + plan.get("nearby_towns", [])))
        prefs.onsite_places = ask_places(f"On-site only near home. These towns count as near {home}:",
                                         towns, prefs.onsite_places or towns)
        if not prefs.onsite_places:
            print("  No towns chosen: on-site jobs will be accepted anywhere.")
    if "hybrid" in prefs.setups:
        prefs.max_hybrid_minutes = choose_one(
            "Max travel time for a hybrid job (one way, public transport, from home):",
            TRAVEL_LIMITS, prefs.max_hybrid_minutes if prefs.max_hybrid_minutes != NOT_ASKED else 90)
        prefs.max_office_days = choose_one(
            "Max office days per week for hybrid jobs outside your on-site towns:",
            OFFICE_DAYS, prefs.max_office_days)


TRAVEL_LIMITS = [(45, "45 min"), (60, "1 h"), (90, "1 h 30"), (120, "2 h"), (0, "any distance")]
OFFICE_DAYS = [(1, "1 day"), (2, "2 days"), (3, "3 days"), (4, "4 days"), (0, "any")]


def ask_field(prefs, f, plan=None):
    plan = plan or {}
    if f == "home":
        prefs.home = ask("\nWhere do you live (city)?", prefs.home)
    elif f == "location":
        prefs.location = ask("\nCountry / region to search", prefs.location)
    elif f == "languages":
        prefs.languages = edit_list("Languages you can work in", prefs.languages, required=True)
    elif f == "levels":
        prefs.levels = choose_many("Seniority levels to search:", [(l, l) for l in LEVELS], prefs.levels)
    elif f == "setups":
        ask_setups(prefs, plan)
    elif f == "max_days":
        prefs.max_days = ask_int("\nMax posting age in days", prefs.max_days)
    elif f == "dutch":
        prefs.dutch = choose_one("Dutch filter:", list(DUTCH_FILTERS.items()), prefs.dutch)
    elif f == "avoid":
        prefs.avoid = edit_list("Title words to always drop (roles or tech you don't want)", prefs.avoid)


LINES = [("home", "Lives in"), ("location", "Search in"), ("languages", "Languages"), ("levels", "Seniority"),
         ("setups", "Work setup"), ("max_days", "Max age"), ("dutch", "Dutch filter"), ("avoid", "Always drop")]
ALWAYS_ASK = {"setups"}  # where someone can work isn't on a CV, so a fresh setup always asks


def value(prefs, f):
    return {"home": prefs.home or "—", "location": prefs.location, "languages": ", ".join(prefs.languages) or "—",
            "levels": ", ".join(prefs.levels), "setups": prefs.setups_text(), "max_days": f"{prefs.max_days} days",
            "dutch": DUTCH_FILTERS[prefs.dutch], "avoid": ", ".join(prefs.avoid) or "—"}[f]


def show(prefs, unknown=()):
    for i, (f, label) in enumerate(LINES, 1):
        print(f"  {i}) {label + ':':14} {'? (I will ask)' if f in unknown else value(prefs, f)}")


def review_preferences(prefs, plan, saved):
    """Ask what the CV didn't tell, then let the user fix any line until everything is right."""
    unknown = set() if saved else set(plan["unsure"]) | ALWAYS_ASK
    if not prefs.setups_complete():  # saved before the travel-time question existed
        unknown.add("setups")
    print(f"\nPreferences ({'saved earlier' if saved else 'from your CV and notes'}):")
    show(prefs, unknown)
    for f, label in LINES:
        if f in unknown:
            ask_field(prefs, f, plan)
    while True:
        print("\nYour preferences:")
        show(prefs)
        a = ask("Enter = all correct, or the numbers of the lines to change (e.g. 2,5)").lower()
        if a in ("", "y", "yes"):
            return
        nums = sorted({int(n) for n in a.replace(",", " ").split() if n.isdigit() and 1 <= int(n) <= len(LINES)})
        if not nums:
            print(f"  Type line numbers from 1 to {len(LINES)}, or press Enter.")
            continue
        fields = [LINES[n - 1][0] for n in nums]
        for f in fields:
            ask_field(prefs, f, plan)
        # Nearby towns and hybrid cities depend on where you live.
        if {"home", "location"} & set(fields) and "setups" not in fields and {"on-site", "hybrid"} & set(prefs.setups):
            print("\nHome or country changed, so the towns for on-site / hybrid need checking:")
            ask_setups(prefs, plan)


def change_preferences(search):
    """Edit the saved preferences and push them into every profile of the search. Returns the profiles."""
    prefs = Preferences.load(search) or Preferences()
    review_preferences(prefs, {"unsure": [], "roles": []}, saved=prefs)
    prefs.save(search)
    profiles = [planner.apply_prefs(p, prefs) for p in search.profiles()]
    for p in profiles:
        search.save_profile(p)
    print(f"Saved preferences and updated {len(profiles)} profile(s) in {search.root}")
    return profiles


def run(search):
    """Plan the search from its CV(s). Returns the saved profiles (empty if setup couldn't finish)."""
    cvs = search.cv_files()
    if not cvs:
        search.create()
        print(f"Put your CV in {search.cv_dir} (PDF, one file per version) and run setup again.")
        return []
    saved = Preferences.load(search)
    print(f"Reading {', '.join(c.name for c in cvs)} with Gemini...")
    plan = planner.analyze(cvs, saved)
    prefs = plan["preferences"]
    print(f"\n{plan['summary']}")

    review_preferences(prefs, plan, saved)
    for q in plan["questions"]:
        a = ask(f"\n{q['question']}\n  ({q.get('why', '')})\n  Answer (Enter = skip)")
        if a:
            prefs.notes.append(f"{q['question']} → {a}")

    roles = plan["roles"]
    print("\nRoles that fit your CV:")
    for r in roles:
        print(f"  - {r['label']}: {r['why']}")
    extra = split_list(ask("\nBesides these, any other roles to search for? (comma list, Enter = none)"))
    if extra:
        prefs.extra_roles += [e for e in extra if e not in prefs.extra_roles]
        print("Working out searches for those...")
        names = {r["name"] for r in roles}
        roles += [r for r in planner.roles_for(extra, cvs, prefs) if r["name"] not in names]
    if not roles:
        print("No roles to search for; nothing saved.")
        return []

    chosen = choose_many("Which roles should I search for?",
                         [(r["name"], f"{r['label']} ({', '.join(r['search_terms'][:3])}…)") for r in roles],
                         [r["name"] for r in roles])
    profiles = [planner.to_profile(r, prefs) for r in roles if r["name"] in chosen]
    for p in profiles:
        print(f"\n{p.describe(search.result_path(p))}")
    while ask_yes("\nEdit one of these searches in detail?", False):
        name = choose_one("Which one?", [(p.name, p.name) for p in profiles], profiles[0].name)
        questions.edit(next(p for p in profiles if p.name == name))

    print(f"\nSaved {prefs.save(search)}")
    for p in profiles:
        print(f"Saved {search.save_profile(p)}")
    search.save_state(cv_fingerprint=search.cv_fingerprint(), last_setup=date.today().isoformat())
    return profiles
