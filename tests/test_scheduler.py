import fcntl
from datetime import datetime, timedelta

import pytest

from jobsearch import env, matches, notify, output, scheduler, workspace
from jobsearch.profile import Profile


@pytest.fixture(autouse=True)
def tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "SEARCHES", tmp_path / "searches")
    monkeypatch.setattr(notify, "SEARCHES", tmp_path / "searches")
    monkeypatch.setattr(notify, "SETTINGS", tmp_path / "searches" / "notifications.json")
    monkeypatch.setattr(notify, "QUEUE", tmp_path / "searches" / ".queue.json")
    monkeypatch.setattr(scheduler, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(scheduler, "LOG", tmp_path / "logs" / "jobsearch.log")
    monkeypatch.setattr(scheduler, "sync", lambda: None)  # never touch the real launchd in tests
    return tmp_path


NOON = datetime(2026, 10, 25, 12, 0)


def search_with_interval(name="s", minutes=300, last=None):
    s = workspace.get(name).create()
    s.save_profile(Profile(name="role"))
    s.save_state(interval_minutes=minutes, last_run_at=last.isoformat(timespec="minutes") if last else "")
    return s


def test_parse_interval():
    assert [scheduler.parse_interval(t) for t in ["5h", "5", "90 min", "1d", "2 days", "off", "10 min", "x"]] \
        == [300, 300, 90, 1440, 2880, 0, None, None]
    assert scheduler.every_text(300) == "every 5 h" and scheduler.every_text(2880) == "every 2 days"


def test_due_after_sleep_runs_once():
    s = search_with_interval(last=NOON - timedelta(hours=12))  # Mac slept through two 5 h slots
    assert scheduler.is_due(s, NOON)
    s.save_state(last_run_at=NOON.isoformat(timespec="minutes"))  # one catch-up run
    assert not scheduler.is_due(s, NOON + timedelta(minutes=15))
    assert scheduler.is_due(s, NOON + timedelta(hours=5))
    assert not scheduler.is_due(search_with_interval("off", 0), NOON)
    assert scheduler.is_due(search_with_interval("never-ran", 300), NOON)


def test_failed_run_retries_with_backoff(monkeypatch):
    s = search_with_interval(last=NOON - timedelta(hours=6))
    monkeypatch.setattr("jobsearch.cli.run", lambda search: (_ for _ in ()).throw(ConnectionError("down")))
    msgs = [scheduler.run_search(s, notify.Settings(), NOON) for _ in range(3)]
    assert s.state()["failures"] == 3 and s.state()["retry_after"] == "2026-10-25T14:00"  # 30, 60, 120 min
    assert not scheduler.is_due(s, NOON + timedelta(minutes=90)) and scheduler.is_due(s, NOON + timedelta(hours=2))
    assert msgs[0] == msgs[1] == [] and "failed 3 times" in msgs[2][0]["message"]  # alert once, at 3


def test_lock_is_exclusive_but_reentrant(tmp):
    with scheduler.lock() as a:
        assert a
        with scheduler.lock() as nested:
            assert nested  # cli.run inside a tick
    other = open(tmp / "logs" / ".run.lock", "w")
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # a background run holds it
    with scheduler.lock() as b:
        assert not b
    other.close()


def test_env_reads_only_plain_exports(tmp, monkeypatch):
    rc = tmp / ".zshrc"
    rc.write_text('export PATH="$HOME/bin:$PATH"\nexport GEMINI_API_KEY=abc123\nexport JOOBLE_KEY="j-1" # note\n'
                  "export GEMINI_API_KEY=newer\nexport SECRET_OTHER=x\nalias ll=ls\n")
    for n in env.NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("JOOBLE_KEY", "from-env")
    env.load([rc])
    import os
    assert os.environ["GEMINI_API_KEY"] == "newer" and os.environ["JOOBLE_KEY"] == "from-env"
    assert "SECRET_OTHER" not in os.environ


def test_quiet_hours_queue_then_one_summary(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda st, m: sent.append(m))
    st = notify.Settings(quiet_from=22, quiet_to=8)
    assert st.quiet(datetime(2026, 1, 1, 23)) and st.quiet(datetime(2026, 1, 1, 7)) and not st.quiet(NOON)
    for i in range(4):
        notify.deliver([{"title": f"m{i}", "message": "x"}], st, datetime(2026, 1, 1, 23))
    assert sent == []
    notify.deliver([], st, datetime(2026, 1, 2, 8, 15))
    assert len(sent) == 1 and sent[0]["title"] == "Job search: 4 updates"  # one summary, not a burst
    notify.deliver([], st, NOON)
    assert len(sent) == 1  # queue emptied


def test_ntfy_message(monkeypatch):
    posted = {}

    class R:
        def raise_for_status(self):
            pass
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: posted.update(url=url, body=json) or R())
    rows = [{"Fit (1-10)": 7, "Company": "TicketSwap", "Job title": "Android Developer", "Travel": "~2 h 30",
             "Link": "https://l/2"},
            {"Fit (1-10)": 8, "Company": "bol", "Job title": "Backend Engineer", "Link": "https://l/1"}]
    msg = notify.matches_message("cristian", rows, "/tmp/m.xlsx")
    assert msg["title"] == "cristian: 2 new matches" and msg["message"].startswith("8 · bol — Backend Engineer")
    notify.ntfy(notify.Settings(ntfy_topic="jobsearch-abc"), msg["title"], msg["message"], msg["links"])
    assert posted["url"] == "https://ntfy.sh" and posted["body"]["topic"] == "jobsearch-abc"
    assert posted["body"]["click"] == "https://l/1" and posted["body"]["actions"][0]["label"] == "bol"
    notify.ntfy(notify.Settings(ntfy_topic=""), "t", "m")  # off: nothing posted
    assert len(notify.new_topic()) == 24 and notify.new_topic() != notify.new_topic()


def test_plist_runs_tick_every_15_minutes_and_at_login():
    p = scheduler.plist()
    assert p["ProgramArguments"][-2:] == ["jobsearch", "tick"] and p["StartInterval"] == 900 and p["RunAtLoad"]
    assert "/opt/homebrew/bin" in p["EnvironmentVariables"]["PATH"]
    assert "GEMINI_API_KEY" not in p["EnvironmentVariables"]  # keys are read from ~/.zshrc, never copied


def test_tick_runs_due_searches_and_notifies_new_matches(monkeypatch):
    due = search_with_interval("due", last=NOON - timedelta(hours=6))
    search_with_interval("later", last=NOON - timedelta(hours=1))
    monkeypatch.setattr(scheduler, "online", lambda: True)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    ran, sent = [], []

    def fake_run(search):
        ran.append(search.name)
        matches.add([{"Found": "2026-10-25", "Fit (1-10)": 8, "Job title": "Android Developer", "Company": "Garmin",
                      "Link": "https://l/new"},
                     {"Found": "2026-10-25", "Fit (1-10)": 7, "Job title": "Meh", "Company": "X", "Link": "https://l/7"}],
                    search.matches_path)
        search.save_state(last_run_at=NOON.isoformat(timespec="minutes"))
    monkeypatch.setattr("jobsearch.cli.run", fake_run)
    monkeypatch.setattr(notify, "send", lambda st, m: sent.append(m))
    notify.Settings(min_fit=8, quiet_from=0, quiet_to=0).save()

    assert scheduler.tick(now=NOON) == 1 and ran == ["due"]
    assert [m["title"] for m in sent] == ["due: 1 new match"] and "Garmin" in sent[0]["message"]
    assert scheduler.tick(now=NOON + timedelta(minutes=15)) == 0  # nothing due any more
    assert "running due" in scheduler.LOG.read_text()


def test_tick_offline_does_not_count_as_run(monkeypatch):
    s = search_with_interval(last=NOON - timedelta(hours=6))
    monkeypatch.setattr(scheduler, "online", lambda: False)
    monkeypatch.setattr("jobsearch.cli.run", lambda search: pytest.fail("must not run offline"))
    scheduler.tick(now=NOON)
    assert scheduler.is_due(s, NOON)


def test_topic_names():
    assert notify.topic_problem("Test") and notify.topic_problem("jobs") and notify.topic_problem("a b")
    assert notify.topic_problem(notify.new_topic()) is None
