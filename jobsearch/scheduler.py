"""Background runs.

One launchd agent wakes every 15 minutes (and at login) and runs `python3 -m jobsearch tick`. A tick runs
every search whose own interval has passed since its last run. So a Mac that slept through a run does it
once at the first tick after waking, never a pile of missed runs. A failed run (offline, API down) is retried
after 30 min, 1 h, 2 h ... and doesn't count as done.
"""
import contextlib
import fcntl
import os
import plistlib
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta

import requests

from . import notify, output, travel, workspace
from .profile import ROOT

LABEL = "com.jobsearch.tick"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
TICK_SECONDS = 15 * 60
MIN_INTERVAL = 30  # minutes; protects the job sites from hammering
LOGS = ROOT / "logs"
LOG = LOGS / "jobsearch.log"
LOG_MAX = 1_000_000
ALERT_AFTER = 3  # failures in a row before telling the user
_held = False


# --- interval ---

def parse_interval(text):
    """'5h', '5', '90 min', '1d', '2 days', 'off' → minutes (0 = off); None if unreadable or too short."""
    t = str(text).strip().lower()
    if t in ("off", "0", "none", "never", "no"):
        return 0
    m = re.fullmatch(r"(\d+)\s*(d|day|days|dag|dagen)", t)
    minutes = int(m.group(1)) * 1440 if m else travel.parse(t)
    return minutes if minutes and minutes >= MIN_INTERVAL else None


def every_text(minutes):
    if not minutes:
        return "off"
    if minutes % 1440 == 0:
        d = minutes // 1440
        return f"every {d} day{'s' if d > 1 else ''}"
    return f"every {travel.text(minutes)[1:]}"


def _time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def next_run(search):
    st = search.state()
    every = st.get("interval_minutes", 0)
    if not every:
        return None
    last, retry = _time(st.get("last_run_at")), _time(st.get("retry_after"))
    due = last + timedelta(minutes=every) if last else datetime.min  # never ran: due right away
    return max(due, retry) if retry else due


def is_due(search, now=None):
    nxt = next_run(search)
    return nxt is not None and (now or datetime.now()) >= nxt


def schedule_text(search):
    st = search.state()
    every = st.get("interval_minutes", 0)
    if not every:
        return "automatic runs off"
    nxt = next_run(search)
    when = "now" if nxt <= datetime.now() else nxt.strftime("%a %H:%M")
    return f"automatic {every_text(every)} · next {when}"


def set_interval(search, minutes):
    search.save_state(interval_minutes=minutes, retry_after="", failures=0)
    sync()


# --- launchd ---

def plist():
    return {"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "jobsearch", "tick"],
            "WorkingDirectory": str(ROOT), "StartInterval": TICK_SECONDS, "RunAtLoad": True,
            "ProcessType": "Background", "LowPriorityIO": True,
            "StandardOutPath": str(LOGS / "launchd.log"), "StandardErrorPath": str(LOGS / "launchd.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}}


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def installed():
    return os.path.exists(PLIST) and _launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0


def install():
    LOGS.mkdir(exist_ok=True)
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist(), f)
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    r = _launchctl("bootstrap", f"gui/{os.getuid()}", PLIST)
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {r.stderr.strip() or r.stdout.strip()}")


def uninstall():
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if os.path.exists(PLIST):
        os.remove(PLIST)


def sync():
    """Agent installed while any search has an interval, removed when none has."""
    wanted = any(s.state().get("interval_minutes") for s in workspace.all_searches())
    if wanted and not installed():
        install()
    elif not wanted and os.path.exists(PLIST):
        uninstall()


# --- one run at a time ---

@contextlib.contextmanager
def lock():
    """Yields True if this process may run (re-entrant), False if another run is busy."""
    global _held
    if _held:
        yield True
        return
    LOGS.mkdir(exist_ok=True)
    f = open(LOGS / ".run.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        yield False
        return
    _held = True
    try:
        yield True
    finally:
        _held = False
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


@contextlib.contextmanager
def logging_to_file():
    LOGS.mkdir(exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > LOG_MAX:
        LOG.replace(LOG.with_suffix(".log.1"))
    with open(LOG, "a", buffering=1) as f, contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
        yield


def online():
    try:
        requests.head("https://www.linkedin.com", timeout=8)
        return True
    except requests.RequestException:
        return False


def run_in_background(search):
    """Start `tick --force --search NAME` detached; the terminal can be closed right away."""
    LOGS.mkdir(exist_ok=True)
    subprocess.Popen([sys.executable, "-m", "jobsearch", "tick", "--force", "--search", search.name],
                     cwd=ROOT, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def last_log(lines=40):
    if not LOG.exists():
        return "No background run yet."
    return "\n".join(LOG.read_text(errors="ignore").splitlines()[-lines:])


# --- the tick ---

def _match_links(search):
    from . import matches
    return {r.get("Link") for r in output.read(search.matches_path, matches.SHEET, matches.COLUMNS)[1]} \
        if search.matches_path.exists() else set()


def _source_alerts(search):
    msgs = []
    for name, n in search.state().get("source_failures", {}).items():
        if n == ALERT_AFTER:
            msgs.append(notify.alert_message(search.name, f"{name} failed {n} runs in a row. If it keeps "
                                                          "happening, the site may have changed or blocked us."))
    return msgs


def run_search(search, settings, now):
    """One scheduled run of a search. Returns the messages to send."""
    from . import matches
    from .cli import run
    before = _match_links(search)
    try:
        run(search)
    except Exception as e:
        traceback.print_exc()
        fails = search.state().get("failures", 0) + 1
        wait = min(30 * 2 ** (fails - 1), search.state().get("interval_minutes") or 30)
        search.save_state(failures=fails, retry_after=(now + timedelta(minutes=wait)).isoformat(timespec="minutes"))
        print(f"Run failed ({e.__class__.__name__}); retry in {wait} min")
        if fails == ALERT_AFTER:
            return [notify.alert_message(search.name, f"Runs failed {fails} times in a row: "
                                                      f"{e.__class__.__name__}: {str(e)[:200]}")]
        return []
    search.save_state(failures=0, retry_after="")
    msgs = _source_alerts(search)
    new = [r for r in output.read(search.matches_path, matches.SHEET, matches.COLUMNS)[1]
           if r.get("Link") not in before and matches.fit(r) >= settings.min_fit] \
        if search.matches_path.exists() else []
    if new:
        msgs.insert(0, notify.matches_message(search.name, new, search.matches_path))
    return msgs


def tick(force=False, only=None, now=None):
    """Run the due searches (or `only`, with force). Returns the number of searches run."""
    with lock() as got:
        if not got:
            print("Another run is still busy; skipping this tick.")
            return 0
        with logging_to_file():
            now = now or datetime.now()
            searches = [s for s in workspace.all_searches() if s.profile_names() and (not only or s.name == only)]
            due = [s for s in searches if force or is_due(s, now)]
            settings = notify.Settings.load()
            if not due:
                notify.deliver([], settings, now)  # quiet hours over: send what was queued
                return 0
            print(f"\n===== {now:%Y-%m-%d %H:%M} · running {', '.join(s.name for s in due)} =====")
            if not online():
                print("Offline; will try again at the next tick.")
                return 0
            msgs = []
            if not os.environ.get("GEMINI_API_KEY") and settings.alerts:
                msgs.append(notify.alert_message("all", "GEMINI_API_KEY isn't set, so new jobs can't be "
                                                        "reviewed. Add it to ~/.zshrc."))
            for s in due:
                msgs += run_search(s, settings, now)
            if not settings.alerts:
                msgs = [m for m in msgs if "problem" not in m["title"].lower()]
            sent = notify.deliver(msgs, settings, now)
            print(f"===== done · {sent} notification(s) sent{' (quiet hours: queued)' if msgs and not sent else ''}")
            return len(due)
