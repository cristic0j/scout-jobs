"""Usage:
  python3 -m jobsearch setup               # CV → agent suggests roles, asks only what's missing → profiles
  python3 -m jobsearch run                 # fetch all profiles; review new jobs against the CV (no questions)
  python3 -m jobsearch run --profile NAME  # one profile only
  python3 -m jobsearch review              # review unprocessed jobs now, without fetching
  python3 -m jobsearch manual              # build a search by hand with the question menus
  python3 -m jobsearch list                # show saved profiles
  python3 -m jobsearch                     # setup on first use, otherwise asks what to do
"""
import argparse
import sys

from . import llm, pipeline, questions, setup
from .agents import matcher
from .preferences import Preferences
from .profile import load, saved_names


def review(profiles, max_review):
    """Matcher on every unprocessed row; makes no Gemini call when there are none. Returns jobs reviewed."""
    prefs = Preferences.load() or Preferences()
    total = 0
    for p in profiles:
        try:
            total += matcher.review(p, prefs, max_review)[0]
        except llm.MissingKey as e:
            print(f"  Review skipped: {e}")
            break
    return total


def run(profiles, do_review=True, max_review=60):
    for p in profiles:
        added = pipeline.run(p)
        # Unprocessed rows are new jobs (this run's, or ones left over by --max-review last time).
        if do_review and not review([p], max_review) and not added:
            print("  No new jobs, review skipped.")


def selected(name):
    if name:
        return [load(name)]
    names = saved_names()
    if not names:
        raise SystemExit("No saved profiles yet. Run: python3 -m jobsearch setup")
    return [load(n) for n in names]


def interactive():
    if not sys.stdin.isatty():
        print("No terminal to ask questions in; use: python3 -m jobsearch run", file=sys.stderr)
        return 2
    try:
        if not saved_names():
            profiles = setup.run()
            if profiles and questions.ask_yes("\nRun the searches now?"):
                run(profiles)
            return 0
        action = questions.choose_one("What do you want to do?", [
            ("run", f"Run saved searches ({', '.join(saved_names())})"),
            ("setup", "Setup again from my CV (new roles / preferences)"),
            ("review", "Review unprocessed jobs now"),
            ("manual", "Build a search by hand")], "run")
        if action == "setup":
            profiles = setup.run()
            if profiles and questions.ask_yes("\nRun the searches now?"):
                run(profiles)
        elif action == "manual":
            profile = questions.run()
            if profile:
                run([profile])
        elif action == "review":
            review(selected(None), 60)
        else:
            run(selected(None))
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1
    except llm.MissingKey as e:
        print(e, file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Job search: CV-driven profiles → results/<profile>.xlsx → matches",
                                 epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["setup", "run", "review", "manual", "list"])
    ap.add_argument("--profile", help="only this saved profile")
    ap.add_argument("--no-review", action="store_true", help="run: fetch only, don't call the matcher")
    ap.add_argument("--max-review", type=int, default=60, help="max jobs the matcher judges per profile per run")
    args = ap.parse_args(argv)

    if args.command is None and args.profile:  # old form: --profile NAME
        args.command = "run"
    if args.command is None:
        return interactive()
    if args.command == "list":
        for name in saved_names():
            print(f"{name}\n{load(name).describe()}\n")
    elif args.command == "run":
        run(selected(args.profile), not args.no_review, args.max_review)
    elif args.command == "review":
        review(selected(args.profile), args.max_review)
    else:
        if not sys.stdin.isatty():
            print(f"'{args.command}' asks questions; run it in a terminal.", file=sys.stderr)
            return 2
        try:
            profiles = setup.run() if args.command == "setup" else [p for p in [questions.run()] if p]
            if profiles and (args.command == "manual" or questions.ask_yes("\nRun the searches now?")):
                run(profiles)
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1
        except llm.MissingKey as e:
            print(e, file=sys.stderr)
            return 2
    return 0
