"""Usage:
  python3 -m jobsearch                          # pick a search (one folder per CV) or start a new one
  python3 -m jobsearch run                      # every search: fetch + review new jobs (no questions; for scheduling)
  python3 -m jobsearch run --search NAME        # one search (add --profile ROLE for one role)
  python3 -m jobsearch review [--search NAME]   # review unprocessed jobs now (--rescore: judge all again)
  python3 -m jobsearch setup --search NAME      # (re)plan a search from its CV
  python3 -m jobsearch list                     # show searches and their roles
"""
import argparse
import subprocess
import sys
from datetime import date

from . import llm, pipeline, questions, setup, workspace
from .agents import matcher
from .preferences import Preferences
from .profile import slug


def review(search, profiles=None, max_review=60, rescore=False):
    """Matcher on unprocessed rows (or every reviewed row with rescore). No Gemini call when nothing is new.
    Returns jobs reviewed."""
    prefs = Preferences.load(search) or Preferences()
    profiles = profiles or search.profiles()
    try:
        if rescore:
            return matcher.rescore(profiles, prefs, search)[0]
        return sum(matcher.review(p, prefs, search, max_review)[0] for p in profiles)
    except llm.MissingKey as e:
        print(f"  Review skipped: {e}")
        return 0


def run(search, profiles=None, do_review=True, max_review=60):
    print(f"\n=== Search '{search.name}' ===")
    for p in profiles or search.profiles():
        added = pipeline.run(p, search)
        # Unprocessed rows are new jobs (this run's, or ones left over by --max-review last time).
        if do_review and not review(search, [p], max_review) and not added:
            print("  No new jobs, review skipped.")
    search.save_state(last_run=date.today().isoformat())


def selected(name):
    if name:
        s = workspace.get(name)
        if not s.root.exists():
            raise SystemExit(f"No search '{name}'. Searches: "
                             f"{', '.join(x.name for x in workspace.all_searches()) or 'none'}")
        return [s]
    found = [s for s in workspace.all_searches() if s.profile_names()]
    if not found:
        raise SystemExit("No searches with roles yet. Run: python3 -m jobsearch")
    return found


def migrate_if_needed():
    if not workspace.has_legacy():
        return
    print("Found results from before search folders (cv/, profiles/, results/ in the project).")
    name = slug(questions.ask("Name for that search", "my-search"))
    search, moved = workspace.migrate_legacy(name)
    print(f"  Moved {len(moved)} files into {search.root}")


def open_finder(path):
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


def new_search():
    name = slug(questions.ask("\nName for this search (e.g. your name, or the kind of job)"))
    search = workspace.get(name)
    if search.root.exists():
        print(f"  '{name}' already exists, opening it.")
        return search
    search.create()
    open_finder(search.cv_dir)
    while not search.cv_files():
        a = questions.ask(f"\nPut your CV (PDF, one file per version) in\n  {search.cv_dir}\n"
                          "and press Enter (or type 'manual' to build a search without a CV)").lower()
        if a == "manual":
            return search
    other = workspace.same_cv(search)
    if other and questions.ask_yes(f"\nThis CV is already used in the search '{other.name}' "
                                   f"({other.summary()}). Continue that one instead?"):
        print(f"  Opening '{other.name}'. You can delete the empty copy at {search.root}")
        return other
    return search


def plan_and_maybe_run(search):
    profiles = setup.run(search)
    if profiles and questions.ask_yes("\nRun the searches now?"):
        run(search, profiles)


def open_search(search):
    if search.cv_files() and not search.profile_names():
        plan_and_maybe_run(search)
    elif search.cv_files() and search.cv_changed():
        if questions.ask_yes("\nYour CV changed since the last setup. Re-plan the roles now? "
                             "(saved preferences and results are kept)"):
            plan_and_maybe_run(search)
    while True:
        if not search.cv_files() and not search.profile_names():
            print(f"\nNo CV yet. Put it in {search.cv_dir}, or add a profile by hand.")
        action = questions.choose_one(f"Search '{search.name}': {search.summary()}", [
            ("run", "Run now (fetch, review only new jobs)"),
            ("prefs", "Change preferences"),
            ("plan", "Re-plan roles from the CV"),
            ("review", "Review unprocessed jobs"),
            ("rescore", "Re-score every reviewed job (after changing preferences)"),
            ("manual", "Add or edit a profile by hand"),
            ("done", "Done")], "run" if search.profile_names() else "plan")
        if action == "done":
            return
        if action == "run":
            run(search)
        elif action == "prefs":
            setup.change_preferences(search)
        elif action == "plan":
            plan_and_maybe_run(search)
        elif action == "review":
            review(search)
        elif action == "rescore":
            review(search, rescore=True)
        elif action == "manual":
            profile = questions.run(search)
            if profile:
                run(search, [profile])


def interactive():
    if not sys.stdin.isatty():
        print("No terminal to ask questions in; use: python3 -m jobsearch run", file=sys.stderr)
        return 2
    try:
        migrate_if_needed()
        searches = workspace.all_searches()
        options = [(s.name, f"{s.name:16} {s.summary()}") for s in searches] + [("", "New search")]
        pick = questions.choose_one("Your searches:", options, searches[0].name if searches else "")
        open_search(workspace.get(pick) if pick else new_search())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1
    except llm.MissingKey as e:
        print(e, file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Job search: one folder per CV → roles → results → matches",
                                 epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["setup", "run", "review", "list"])
    ap.add_argument("--search", help="only this search (folder name in searches/)")
    ap.add_argument("--profile", help="run: only this role of the search")
    ap.add_argument("--no-review", action="store_true", help="run: fetch only, don't call the matcher")
    ap.add_argument("--max-review", type=int, default=60, help="max jobs the matcher judges per role per run")
    ap.add_argument("--rescore", action="store_true", help="review: judge every reviewed job again")
    args = ap.parse_args(argv)

    if args.command is None:
        return interactive()
    if workspace.has_legacy():
        print("Old layout found (cv/, profiles/, results/). Run `python3 -m jobsearch` once to move it "
              "into a search folder.", file=sys.stderr)
        return 2
    if args.command == "list":
        for s in workspace.all_searches():
            print(f"{s.name}: {s.summary()}")
            for p in s.profiles():
                print(f"{p.describe(s.result_path(p))}\n")
    elif args.command == "run":
        for s in selected(args.search):
            profiles = [s.load_profile(args.profile)] if args.profile else None
            run(s, profiles, not args.no_review, args.max_review)
    elif args.command == "review":
        for s in selected(args.search):
            review(s, max_review=args.max_review, rescore=args.rescore)
    else:  # setup
        if not args.search:
            print("setup needs --search NAME (or run `python3 -m jobsearch` for the menu).", file=sys.stderr)
            return 2
        if not sys.stdin.isatty():
            print("setup asks questions; run it in a terminal.", file=sys.stderr)
            return 2
        try:
            plan_and_maybe_run(workspace.get(args.search).create())
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1
        except llm.MissingKey as e:
            print(e, file=sys.stderr)
            return 2
    return 0
