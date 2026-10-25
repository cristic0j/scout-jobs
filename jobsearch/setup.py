"""Setup: the planner reads the CV(s), suggests roles and preferences, and asks only what it couldn't tell."""
from . import questions
from .agents import planner
from .detect import LEVELS
from .preferences import CV_DIR, Preferences, cv_files
from .profile import DUTCH_FILTERS, WORK_MODES, save
from .questions import ask, ask_int, ask_yes, choose_many, choose_one, edit_list, split_list


def ask_field(prefs, f):
    if f == "home":
        prefs.home = ask("\nWhere do you live (city)?", prefs.home)
    elif f == "location":
        prefs.location = ask("\nCountry / region to search", prefs.location)
    elif f == "languages":
        prefs.languages = edit_list("Languages you can work in", prefs.languages, required=True)
    elif f == "levels":
        prefs.levels = choose_many("Seniority levels to search:", [(l, l) for l in LEVELS], prefs.levels)
    elif f == "work_modes":
        prefs.work_modes = choose_many("Work mode (none = any):", [(m, m) for m in WORK_MODES],
                                       prefs.work_modes, allow_empty=True)
    elif f == "max_days":
        prefs.max_days = ask_int("\nMax posting age in days", prefs.max_days)
    elif f == "dutch":
        prefs.dutch = choose_one("Dutch filter:", list(DUTCH_FILTERS.items()), prefs.dutch)
    elif f == "avoid":
        prefs.avoid = edit_list("Title words to always drop (roles or tech you don't want)", prefs.avoid)


def run():
    """Returns the saved profiles (empty if setup couldn't finish)."""
    cvs = cv_files()
    if not cvs:
        CV_DIR.mkdir(exist_ok=True)
        print(f"Put your CV in {CV_DIR} (PDF, one file per version) and run setup again.")
        return []
    saved = Preferences.load()
    print(f"Reading {', '.join(c.name for c in cvs)} with Gemini...")
    plan = planner.analyze(cvs, saved)
    prefs = plan["preferences"]
    print(f"\n{plan['summary']}")

    print(f"\nPreferences ({'saved earlier' if saved else 'from your CV and notes'}):\n{prefs.describe()}")
    if plan["unsure"]:
        print("\nI couldn't tell these from your CV:")
        for f in plan["unsure"]:
            ask_field(prefs, f)
    if not ask_yes("\nAre these preferences right?"):
        for f in planner.PREF_FIELDS:
            ask_field(prefs, f)
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
        print(f"\n{p.describe()}")
    while ask_yes("\nEdit one of these searches in detail?", False):
        name = choose_one("Which one?", [(p.name, p.name) for p in profiles], profiles[0].name)
        questions.edit(next(p for p in profiles if p.name == name))

    print(f"\nSaved {prefs.save()}")
    for p in profiles:
        print(f"Saved {save(p)}")
    return profiles
