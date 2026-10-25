"""Usage:
  python3 -m jobsearch                          # pick a search (one folder per CV) or start a new one
  python3 -m jobsearch run                      # every search: fetch + review new jobs (no questions; for scheduling)
  python3 -m jobsearch run --search NAME        # one search (add --profile ROLE for one role)
  python3 -m jobsearch review [--search NAME]   # review unprocessed jobs now (--rescore: judge all again)
  python3 -m jobsearch setup --search NAME      # (re)plan a search from its CV
  python3 -m jobsearch list                     # show searches and their roles
  python3 -m jobsearch schedule --search NAME --every 5h   # automatic background runs (or --every off)
  python3 -m jobsearch schedule                 # status of all searches
  python3 -m jobsearch notify --test            # send a test notification
  python3 -m jobsearch tick                     # what the background agent runs every 15 min
"""
import argparse
import subprocess
import sys
from datetime import date, datetime

from . import cloud, llm, matches, notify, pipeline, questions, scheduler, setup, workspace
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
    with scheduler.lock() as got:
        if not got:
            print("A background run is busy right now; try again in a few minutes "
                  "(or check 'Show the last background run').")
            return
        print(f"\n=== Search '{search.name}' ===")
        for p in profiles or search.profiles():
            added = pipeline.run(p, search)
            # Unprocessed rows are new jobs (this run's, or ones left over by --max-review last time).
            if do_review and not review(search, [p], max_review) and not added:
                print("  No new jobs, review skipped.")
        matches.sync(search.matches_path)
        search.save_state(last_run=date.today().isoformat(),
                          last_run_at=datetime.now().isoformat(timespec="minutes"))


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
        every = search.state().get("interval_minutes", 0)
        action = questions.choose_one(f"Search '{search.name}': {search.summary()}\n  {scheduler.schedule_text(search)}", [
            ("run", "Run now (fetch, review only new jobs)"),
            ("bg", "Run now in the background (you can close the terminal)"),
            ("schedule", f"Automatic runs ({scheduler.every_text(every)})"),
            ("log", "Show the last background run"),
            ("cloud", "Google Sheets: " + ("sync now / change" if cloud.connected(search.matches_path)
                                           else "put the matches online")),
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
        elif action == "bg":
            scheduler.run_in_background(search)
            print(f"  Started. Progress goes to {scheduler.LOG}; you'll get a notification for new matches.")
        elif action == "schedule":
            ask_schedule(search)
        elif action == "log":
            print(f"\n{scheduler.last_log()}")
        elif action == "cloud":
            ask_cloud(search)
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


def ask_schedule(search):
    current = search.state().get("interval_minutes", 0)
    options = [(m, scheduler.every_text(m)) for m in (60, 180, 300, 720, 1440)]
    if current and current not in dict(options):
        options.append((current, f"{scheduler.every_text(current)} (now)"))
    options += [(-1, "Other: type an interval (e.g. 4h, 2 days)"), (0, "Off")]
    minutes = questions.choose_one(f"How often should '{search.name}' run in the background?",
                                   options, current or 300)
    while minutes == -1:
        minutes = scheduler.parse_interval(questions.ask("Interval"))
        if minutes is None:
            print(f"  Try e.g. 4h, 90 min or 2 days (at least {scheduler.MIN_INTERVAL} min).")
            minutes = -1
    scheduler.set_interval(search, minutes)
    if minutes:
        print(f"  '{search.name}' now runs {scheduler.every_text(minutes)} in the background, also after the Mac "
              "slept (it catches up once when it wakes). New matches → notification.")
        if not notify.SETTINGS.exists():
            print("  Set up notifications from the main menu → Notifications.")
    else:
        print(f"  Automatic runs for '{search.name}' are off.")


def ask_cloud(search):
    path = search.matches_path
    if cloud.connected(path):
        action = questions.choose_one(f"Matches are online: {cloud.sheet_url(path)}", [
            ("sync", "Sync now"), ("change", "Use another Google Sheet"), ("off", "Stop syncing"),
            ("done", "Back")], "sync")
        if action == "sync":
            with scheduler.lock() as got:
                if not got:
                    print("  A background run is busy right now; it syncs when it saves. Try again in a few minutes.")
                    return
                matches.sync(path)
            return
        if action == "off":
            cloud.save_config(path, sheet="", synced=[])
            print("  Not syncing any more; the Google Sheet and matches.xlsx are left as they are.")
            return
        if action == "done":
            return
    if not cloud.key():
        cloud.KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        print(f"""
  One-time setup (about 5 minutes):
  1. Go to https://console.cloud.google.com → create a project (any name, e.g. "jobsearch").
  2. APIs & Services → Library → enable "Google Sheets API".
  3. APIs & Services → Credentials → Create credentials → Service account (any name) → Done.
     Open it → Keys → Add key → Create new key → JSON. A .json file downloads.
  4. Move that file (any name) into:
       {cloud.KEY_DIR}
     (outside the project, so it never ends up in git; keep it private, it is the password to the sheet)""")
        questions.ask("Press Enter when the key file is there")
        if not cloud.key():
            print(f"  No key file in {cloud.KEY_DIR} yet. Come back to this menu when it's there.")
            return
    email = cloud.account_email()
    print(f"""
  5. Create a new, empty Google Sheet (sheets.new) and share it (Share button) with
       {email or "the client_email in the key file"}
     as Editor. Untick "Notify people".""")
    sid = cloud.sheet_id(questions.ask("Paste the sheet's link"))
    if not sid:
        print("  That doesn't look like a Google Sheets link.")
        return
    try:
        cloud.open_tab(sid)
    except cloud.Unavailable as e:
        print(f"  Couldn't open the sheet ({e}). Is it shared with {email or 'the service account'} as Editor?")
        return
    cloud.save_config(path, sheet=sid, synced=[], deleted=cloud.config(path).get("deleted", []))
    with scheduler.lock() as got:
        if got:
            matches.sync(path)
        else:
            print("  Connected; a background run is busy and will fill the sheet when it saves.")
    print(f"  {cloud.sheet_url(path)}\n  Tick Applied there; delete a row to drop a job for good.")


def ask_notifications():
    st = notify.Settings.load()
    while True:
        print(f"\nNotifications:\n{st.describe()}")
        action = questions.choose_one("Change:", [
            ("mac", f"Mac banner: turn {'off' if st.mac else 'on'}"),
            ("ntfy", "Phone push (ntfy): set up / change / turn off"),
            ("fit", "Minimum fit to announce"),
            ("quiet", "Quiet hours"),
            ("alerts", f"Problem alerts: turn {'off' if st.alerts else 'on'}"),
            ("test", "Send a test notification"),
            ("done", "Done")], "done")
        if action == "done":
            st.save()
            return
        if action == "mac":
            st.mac = not st.mac
        elif action == "alerts":
            st.alerts = not st.alerts
        elif action == "fit":
            st.min_fit = min(10, questions.ask_int("Announce matches with fit at least (1-10)", st.min_fit))
        elif action == "quiet":
            st.quiet_from = questions.ask_int("Quiet from hour (0-23; same as 'until' = no quiet hours)",
                                              st.quiet_from, allow_zero=True) % 24
            st.quiet_to = questions.ask_int("Quiet until hour (0-23)", st.quiet_to, allow_zero=True) % 24
        elif action == "ntfy":
            setup_ntfy(st)
        elif action == "test":
            st.save()
            notify.deliver([{"title": "Job search", "message": "Test notification: this is how new matches arrive.",
                             "links": [["ntfy", "https://ntfy.sh"]]}], st, now=datetime(2000, 1, 1, 12))
            print("  Sent (if nothing shows up: System Settings → Notifications → Script Editor / terminal-notifier).")


def setup_ntfy(st):
    if st.ntfy_topic and questions.ask_yes(f"Phone push is on (topic {st.ntfy_topic}). Turn it off?", False):
        st.ntfy_topic = ""
        return
    topic = st.ntfy_topic or notify.new_topic()
    print(f"""
  1. Install the free "ntfy" app (App Store / Google Play).
  2. In the app: + → Subscribe to topic → type:  {topic}
     (Server: {st.ntfy_server}. Anyone who knows this name can read the messages, so keep it to yourself.
      Messages contain job titles, companies and links, never your CV.)""")
    while True:
        typed = questions.ask("Topic (Enter = use this one)", topic).strip()
        problem = notify.topic_problem(typed)
        if not problem or questions.ask_yes(f"  {problem} Use it anyway?", False):
            break
    st.ntfy_topic = typed
    st.save()
    print(f"  Topic saved: {typed}  (in the app it must be exactly this, capitals included,"
          f" on server {st.ntfy_server})")
    if questions.ask_yes("Send a test message to your phone now?"):
        try:
            notify.ntfy(st, "Job search", "Phone notifications work. New matches will show up here.",
                        [("ntfy", "https://ntfy.sh")])
            arrived = notify.ntfy_received(st, "Phone notifications work")
            print("  Sent, and the ntfy server has it. Nothing on your phone? Then the app isn't subscribed to "
                  "exactly this topic, or notifications for the ntfy app are off in the phone's settings."
                  if arrived else "  Sent, but the server doesn't show it yet; try the test again in a minute.")
        except Exception as e:
            print(f"  Couldn't send: {e}")


def interactive():
    if not sys.stdin.isatty():
        print("No terminal to ask questions in; use: python3 -m jobsearch run", file=sys.stderr)
        return 2
    try:
        while True:
            searches = workspace.all_searches()
            options = [(s.name, f"{s.name:16} {s.summary()} · {scheduler.schedule_text(s)}") for s in searches]
            options += [("", "New search"), ("#notify", "Notifications"), ("#quit", "Quit")]
            pick = questions.choose_one("Your searches:", options, searches[0].name if searches else "")
            if pick == "#quit":
                return 0
            if pick == "#notify":
                ask_notifications()
                continue
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
    ap.add_argument("command", nargs="?", choices=["setup", "run", "review", "list", "schedule", "notify", "tick"])
    ap.add_argument("--every", help="schedule: interval like 5h, 90 min, 1d, or off")
    ap.add_argument("--force", action="store_true", help="tick: run now even if not due")
    ap.add_argument("--test", action="store_true", help="notify: send a test notification")
    ap.add_argument("--search", help="only this search (folder name in searches/)")
    ap.add_argument("--profile", help="run: only this role of the search")
    ap.add_argument("--no-review", action="store_true", help="run: fetch only, don't call the matcher")
    ap.add_argument("--max-review", type=int, default=60, help="max jobs the matcher judges per role per run")
    ap.add_argument("--rescore", action="store_true", help="review: judge every reviewed job again")
    args = ap.parse_args(argv)

    if args.command is None:
        return interactive()
    if args.command == "tick":
        scheduler.tick(force=args.force, only=args.search)
        return 0
    if args.command == "schedule":
        if args.every is not None:
            if not args.search:
                print("schedule --every needs --search NAME", file=sys.stderr)
                return 2
            minutes = scheduler.parse_interval(args.every)
            if minutes is None:
                print(f"Can't read '{args.every}'. Try 5h, 90 min, 1d or off (min {scheduler.MIN_INTERVAL} min).",
                      file=sys.stderr)
                return 2
            scheduler.set_interval(selected(args.search)[0], minutes)
        print(f"Background agent: {'running' if scheduler.installed() else 'not installed'} "
              f"(checks every {scheduler.TICK_SECONDS // 60} min; log: {scheduler.LOG})")
        for s in workspace.all_searches():
            print(f"  {s.name:16} {scheduler.schedule_text(s)}")
        return 0
    if args.command == "notify":
        st = notify.Settings.load()
        print(st.describe())
        if args.test:
            notify.deliver([{"title": "Job search", "message": "Test notification."}], st, now=datetime(2000, 1, 1, 12))
        return 0
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
