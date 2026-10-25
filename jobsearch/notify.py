"""Notifications for background runs: a Mac banner and/or a phone push via ntfy (https://ntfy.sh).

Settings: searches/notifications.json. Messages that come in during quiet hours are queued and sent
together at the first run after them.
"""
import json
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime

import requests

from .workspace import SEARCHES

SETTINGS = SEARCHES / "notifications.json"
QUEUE = SEARCHES / ".notify_queue.json"
NOTIFIER_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]


@dataclass
class Settings:
    mac: bool = True
    ntfy_topic: str = ""                 # empty = phone push off
    ntfy_server: str = "https://ntfy.sh"
    min_fit: int = 7                     # only matches with at least this fit are announced
    quiet_from: int = 22                 # hour; quiet_from == quiet_to means no quiet hours
    quiet_to: int = 8
    alerts: bool = True                  # also tell about problems (key invalid, a source keeps failing)

    @classmethod
    def load(cls):
        if not SETTINGS.exists():
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in json.loads(SETTINGS.read_text()).items() if k in known})

    def save(self):
        SEARCHES.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def quiet(self, now=None):
        h = (now or datetime.now()).hour
        if self.quiet_from == self.quiet_to:
            return False
        if self.quiet_from < self.quiet_to:
            return self.quiet_from <= h < self.quiet_to
        return h >= self.quiet_from or h < self.quiet_to

    def describe(self):
        quiet = "none" if self.quiet_from == self.quiet_to else f"{self.quiet_from:02d}:00–{self.quiet_to:02d}:00"
        return "\n".join([
            f"  Mac banner:      {'on' if self.mac else 'off'}"
            + ("" if not self.mac or notifier() else " (not clickable; `brew install terminal-notifier` to fix)"),
            f"  Phone (ntfy):    {self.ntfy_topic and 'topic ' + self.ntfy_topic or 'off'}",
            f"  Announce fit ≥:  {self.min_fit}",
            f"  Quiet hours:     {quiet}",
            f"  Problem alerts:  {'on' if self.alerts else 'off'}",
        ])


def new_topic():
    """Hard-to-guess ntfy topic: anyone who knows the name can read the messages."""
    return "jobsearch-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "").lower()[:14]


COMMON_TOPICS = {"test", "testing", "jobs", "job", "jobsearch", "alerts", "notify", "phone", "mytopic", "topic"}


def topic_problem(topic):
    """Why a topic name is a bad idea, or None. Topics are public: a guessable one is shared with strangers."""
    if not topic or not all(c.isalnum() or c in "-_" for c in topic):
        return "Only letters, digits, - and _ are allowed."
    if topic.lower() in COMMON_TOPICS or len(topic) < 12:
        return (f"'{topic}' is short or common: other people may use it too, and they'd see your messages "
                "(and you theirs). The suggested name is private.")
    return None


def ntfy_received(settings, text, since="5m"):
    """Did the server get a message containing `text` recently? Tells server problems from phone problems."""
    r = requests.get(f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}/json",
                     params={"poll": 1, "since": since}, timeout=15)
    return any(text in line for line in r.text.splitlines())


def notifier():
    return shutil.which("terminal-notifier") or next(
        (f"{d}/terminal-notifier" for d in NOTIFIER_DIRS if shutil.which("terminal-notifier", path=d)), None)


# --- channels ---

def mac(title, message, open_path=None):
    if sys.platform != "darwin":
        return
    tool = notifier()
    if tool:
        cmd = [tool, "-title", title, "-message", message, "-group", "jobsearch"]
        if open_path:
            cmd += ["-open", f"file://{open_path}"]
        subprocess.run(cmd, check=False, capture_output=True)
    else:
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"'],
                       check=False, capture_output=True)


def ntfy(settings, title, message, links=(), priority=3, tags=("briefcase",)):
    """JSON publish, so titles/emoji/umlauts are safe. links: [(label, url)] → up to 3 buttons."""
    if not settings.ntfy_topic:
        return
    body = {"topic": settings.ntfy_topic, "title": title, "message": message, "priority": priority,
            "tags": list(tags)}
    if links:
        body["click"] = links[0][1]
        body["actions"] = [{"action": "view", "label": label[:40], "url": url} for label, url in links[:3]]
    requests.post(settings.ntfy_server.rstrip("/"), json=body, timeout=15).raise_for_status()


def send(settings, msg):
    """msg: {title, message, links: [[label, url]], open, priority, tags}"""
    errors = []
    if settings.mac:
        try:
            mac(msg["title"], msg["message"], msg.get("open"))
        except Exception as e:  # a missing notifier must never break a run
            errors.append(f"mac: {e}")
    try:
        ntfy(settings, msg["title"], msg["message"], [tuple(l) for l in msg.get("links", [])],
             msg.get("priority", 3), msg.get("tags", ("briefcase",)))
    except Exception as e:
        errors.append(f"ntfy: {e}")
    for e in errors:
        print(f"  Notification failed ({e})")


# --- messages ---

def matches_message(search, rows, matches_path):
    from .matches import fit
    rows = sorted(rows, key=lambda r: -fit(r))
    lines = [f"{r.get('Fit (1-10)')} · {r.get('Company')} — {r.get('Job title')}"
             + (f" · {r.get('Travel')}" if r.get("Travel") else "") for r in rows[:6]]
    if len(rows) > 6:
        lines.append(f"…and {len(rows) - 6} more")
    n = len(rows)
    return {"title": f"{search}: {n} new match{'es' if n > 1 else ''}", "message": "\n".join(lines),
            "links": [[f"{r.get('Company')}", r.get("Link")] for r in rows[:3] if r.get("Link")],
            "open": str(matches_path)}


def alert_message(search, problem):
    return {"title": f"Job search problem ({search})", "message": problem, "priority": 4, "tags": ["warning"]}


# --- queue for quiet hours ---

def _queue():
    return json.loads(QUEUE.read_text()) if QUEUE.exists() else []


def deliver(msgs, settings=None, now=None):
    """Send now, or queue during quiet hours. Queued messages go out (merged) at the first call after."""
    settings = settings or Settings.load()
    pending = _queue() + list(msgs)
    if not pending:
        return 0
    if settings.quiet(now):
        SEARCHES.mkdir(parents=True, exist_ok=True)
        QUEUE.write_text(json.dumps(pending))
        return 0
    if len(pending) > 3:  # after a quiet night: one summary instead of a burst
        pending = [{"title": f"Job search: {len(pending)} updates",
                    "message": "\n\n".join(f"{m['title']}\n{m['message']}" for m in pending)[:3500],
                    "links": [l for m in pending for l in m.get("links", [])][:3],
                    "open": next((m["open"] for m in pending if m.get("open")), None)}]
    for m in pending:
        send(settings, m)
    QUEUE.unlink(missing_ok=True)
    return len(pending)
