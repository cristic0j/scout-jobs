"""Planner, matcher, setup flow and matches with a fake Gemini (no network)."""
import pytest

from jobsearch import llm, matches, output, workspace
from jobsearch.agents import matcher, planner
from jobsearch.models import Job
from jobsearch.preferences import Preferences
from jobsearch.profile import Profile


@pytest.fixture
def search(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "SEARCHES", tmp_path / "searches")
    monkeypatch.setattr(planner, "NOTES_FILE", tmp_path / "missing.md")
    monkeypatch.setattr(matcher.descriptions, "PATH", tmp_path / "desc.json")
    monkeypatch.setattr("jobsearch.output.TRACKER", tmp_path / "no-tracker.xlsx")
    s = workspace.get("test").create()
    (s.cv_dir / "cv_android.txt").write_text("Android developer, Kotlin, 1.5 years.")
    return s


def fake(monkeypatch, reply):
    calls = []

    def ask_json(prompt, schema, files=(), system=""):
        calls.append(prompt)
        return reply(prompt) if callable(reply) else reply
    monkeypatch.setattr(llm, "ask_json", ask_json)
    return calls


def answers(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


ANALYSIS = {
    "summary": "Junior Android dev.",
    "roles": [{"name": "Android Developer", "label": "Android", "why": "Kotlin", "cv": ["cv_android.txt", "nope.pdf"],
               "search_terms": ["android developer", "python developer"] + [f"t{i}" for i in range(10)],
               "title_include": ["android", "full-stack", " "], "title_exclude": ["sales"]},
              {"name": "empty", "label": "x", "why": "", "cv": [], "search_terms": [], "title_include": [],
               "title_exclude": []}],
    "preferences": {"home": "Maastricht", "location": "Netherlands", "languages": ["English"],
                    "levels": ["junior", "boss"], "setups": ["hybrid", "sometimes"], "max_days": -3,
                    "dutch": "required", "avoid": ["python"]},
    "unsure": ["setups", "nonsense"],
    "questions": [{"question": "Open to Belgium?", "why": "you live near the border"}, {"question": ""}],
}


def test_planner_cleans_agent_output(monkeypatch, search):
    fake(monkeypatch, ANALYSIS)
    plan = planner.analyze(search.cv_files())
    assert [r["name"] for r in plan["roles"]] == ["android-developer"]  # empty role dropped, name slugged
    role = plan["roles"][0]
    assert role["cv"] == ["cv_android.txt"] and len(role["search_terms"]) == 8
    assert role["title_include"] == ["android", "full-stack", "full stack", "fullstack"]  # C: all spellings
    prefs = plan["preferences"]
    assert prefs.levels == ["junior"] and prefs.setups == ["hybrid"] and prefs.max_days == 30
    assert plan["unsure"] == ["setups"] and len(plan["questions"]) == 1

    prefs.max_hybrid_minutes, prefs.max_office_days = 90, 2
    p = planner.to_profile(role, prefs)
    assert "python developer" not in p.search_terms  # B: avoided technology taken out of the searches
    assert p.title_exclude == ["sales", "python"] and p.dutch == "required" and p.cv == ["cv_android.txt"]
    assert (p.setups, p.home, p.max_hybrid_minutes, p.max_office_days) == (["hybrid"], "Maastricht", 90, 2)


def test_clean_prefs_normalises_what_flash_lite_returned():
    p = planner.clean_prefs({"home": "Maastricht, Netherlands", "location": "Maastricht, Netherlands",
                             "max_days": 105, "dutch": "required",
                             "avoid": ["Dutch-only roles in general", "Sales", "Management"]})
    assert (p.home, p.location, p.max_days) == ("Maastricht", "Netherlands", 60)
    assert p.avoid == ["Sales", "Management"]


def test_planner_keeps_saved_preferences(monkeypatch, search):
    calls = fake(monkeypatch, ANALYSIS)
    saved = Preferences(home="Utrecht", levels=["medior"])
    plan = planner.analyze(search.cv_files(), saved)
    assert plan["preferences"] is saved and plan["unsure"] == []
    assert "Utrecht" in calls[0]


def test_places_cleaned(monkeypatch):
    calls = fake(monkeypatch, {"nearby_towns": ["maastricht", "Meerssen", "Li\x81ge", "Heerlen"]})
    out = planner.places("Maastricht", "Netherlands", ["Android"])
    assert out["nearby_towns"] == ["Maastricht", "Meerssen", "Heerlen"]  # home first, dupes/garbled dropped
    assert "Search country: Netherlands" in calls[0]


def test_ask_setups_flow(monkeypatch):
    from jobsearch import setup
    fake(monkeypatch, {"nearby_towns": ["Maastricht", "Meerssen"]})
    # all setups · only Meerssen · + Valkenburg · travel 1 h 30 (3rd) · office days 2 (2nd)
    answers(monkeypatch, "", "2", "Valkenburg", "3", "2")
    prefs = Preferences(home="Maastricht")
    setup.ask_setups(prefs, {"roles": []})
    assert prefs.onsite_places == ["Meerssen", "Valkenburg"]
    assert (prefs.max_hybrid_minutes, prefs.max_office_days) == (90, 2)
    assert prefs.setups_text() == ("on-site in Meerssen, Valkenburg; hybrid within 1 h 30 "
                                   "(max 2 office days/week); remote anywhere")


def test_review_preferences_asks_unknown_first_then_edits_lines(monkeypatch, capsys):
    from jobsearch import setup
    assert [f for f, _ in setup.LINES] == planner.PREF_FIELDS
    fake(monkeypatch, {"nearby_towns": ["Maastricht", "Meerssen"]})
    answers(monkeypatch, "", "", "", "", "",  # setups: all · towns: all · no extra · travel: default · days: default
            "14",                             # max_days was unsure → asked
            "8", "+python",                   # summary: change line 8 (Always drop) → add python
            "")                               # summary: all correct
    prefs = Preferences(home="Maastricht", avoid=["sales"])
    setup.review_preferences(prefs, {"unsure": ["max_days"], "roles": []}, saved=None)
    first = capsys.readouterr().out.split("Your preferences:")[0]
    assert "Work setup:    ? (I will ask)" in first and "Max age:       ? (I will ask)" in first
    assert "on-site anywhere" not in first  # no made-up default shown as fact
    assert prefs.max_days == 14 and prefs.avoid == ["sales", "python"] and prefs.max_hybrid_minutes == 90


def test_review_preferences_saved_only_confirms(monkeypatch):
    from jobsearch import setup
    calls = fake(monkeypatch, {})
    answers(monkeypatch, "")
    prefs = Preferences(home="Utrecht", max_hybrid_minutes=60)
    setup.review_preferences(prefs, {"unsure": [], "roles": []}, saved=prefs)
    assert calls == []  # nothing asked, no places lookup


def test_saved_preferences_without_travel_limit_ask_setups(monkeypatch, capsys):
    from jobsearch import setup
    fake(monkeypatch, {"nearby_towns": ["Utrecht"]})
    answers(monkeypatch, "", "", "", "2", "", "")  # setups · towns · extra · travel 1 h · days any · confirm
    prefs = Preferences(home="Utrecht")  # max_hybrid_minutes not asked yet (old preferences file)
    setup.review_preferences(prefs, {"unsure": [], "roles": []}, saved=prefs)
    assert prefs.max_hybrid_minutes == 60 and "? (I will ask)" in capsys.readouterr().out


def make(title, link, location="Maastricht", tracked=False):
    j = Job("Test", title, "Acme", location, "2026-10-24", link)
    j.level, j.tracked = "junior", tracked
    return j


def results_with(search, profile, jobs):
    path = search.result_path(profile)
    headers, rows = output.read(path)
    rows, _ = output.merge(rows, jobs, "2026-10-25")
    output.write(path, headers, rows)


def verdict(id, fit, v="match", **kw):
    return {"id": id, "fit": fit, "verdict": v, "why": "Kotlin", "caveats": "", "breaks_setup": False,
            "office_days": -1, "years_required": -1, "exceeds_experience": False, "avoided_tech": False, **kw}


def test_matcher_reviews_only_unprocessed(monkeypatch, search):
    p = Profile(name="android", cv=["cv_android.txt"])
    results_with(search, p, [make("Android Dev", "https://x/1"), make("Kotlin Dev", "https://x/2"),
                             make("Old one", "https://x/3", tracked=True)])
    calls = fake(monkeypatch, {"results": [verdict(0, 9), verdict(1, 4, "no")]})
    assert matcher.review(p, Preferences(), search, today="2026-10-25") == (2, 1)
    assert len(calls) == 1 and "Old one" not in calls[0]  # tracked rows skip the agent

    _, rows = output.read(search.result_path(p))
    assert all(r["Processed"] == "2026-10-25" for r in rows)
    by = {r["Job title"]: r for r in rows}
    assert by["Android Dev"]["AI fit"] == 9 and by["Old one"]["AI verdict"] == "in tracker"
    _, found = output.read(search.matches_path, matches.SHEET, matches.COLUMNS)
    assert [r["Job title"] for r in found] == ["Android Dev"]

    # Second run: nothing unprocessed → no Gemini call at all.
    assert matcher.review(p, Preferences(), search, today="2026-10-26") == (0, 0)
    assert len(calls) == 1


def test_matcher_caps_are_enforced_in_code(monkeypatch, search):
    p = Profile(name="android", cv=["cv_android.txt"], onsite_places=["Maastricht"], max_office_days=2)
    results_with(search, p, [make("Remote tag, hybrid in Delft", "https://x/1", "Delft"),
                             make("4 office days Amsterdam", "https://x/2", "Amsterdam"),
                             make("4 office days at home", "https://x/3", "Maastricht"),
                             make("Asks 3+ years", "https://x/4")])
    fake(monkeypatch, {"results": [verdict(0, 9, breaks_setup=True), verdict(1, 8, office_days=4),
                                   verdict(2, 8, office_days=4), verdict(3, 9, years_required=3,
                                                                        exceeds_experience=True)]})
    matcher.review(p, Preferences(), search, today="2026-10-25")
    by = {r["Job title"]: r for r in output.read(search.result_path(p))[1]}
    assert (by["Remote tag, hybrid in Delft"]["AI fit"], by["Remote tag, hybrid in Delft"]["AI verdict"]) == (4, "no")
    assert (by["4 office days Amsterdam"]["AI fit"], by["4 office days Amsterdam"]["AI verdict"]) == (4, "no")
    assert by["4 office days at home"]["AI fit"] == 8  # office-day limit only applies away from home
    assert (by["Asks 3+ years"]["AI fit"], by["Asks 3+ years"]["AI verdict"]) == (6, "maybe")
    assert "asks 3+ years" in by["Asks 3+ years"]["AI reason"]
    _, found = output.read(search.matches_path, matches.SHEET, matches.COLUMNS)
    assert [r["Job title"] for r in found] == ["4 office days at home"]


def test_rescore_filters_then_rejudges(monkeypatch, search):
    p = Profile(name="backend", cv=["cv_android.txt"], title_include=["developer"])
    results_with(search, p, [make("Python Developer", "https://x/1"), make("Kotlin Developer", "https://x/2")])
    fake(monkeypatch, {"results": [verdict(0, 9), verdict(1, 8)]})
    matcher.review(p, Preferences(), search, today="2026-10-25")
    headers, rows = output.read(search.matches_path, matches.SHEET, matches.COLUMNS)
    for r in rows:
        r["Applied?"] = "Yess" if r["Job title"] == "Kotlin Developer" else ""  # a column the user added
    output.write(search.matches_path, headers + ["Applied?"], rows, matches.SHEET)

    p.title_exclude = ["python"]  # preferences changed: Python roles are dropped now
    calls = fake(monkeypatch, {"results": [verdict(0, 7)]})
    matcher.rescore([p], Preferences(), search, today="2026-10-26")
    assert len(calls) == 1 and "Python Developer" not in calls[0]  # filtered without a Gemini call
    by = {r["Job title"]: r for r in output.read(search.result_path(p))[1]}
    assert by["Python Developer"]["AI verdict"] == "filtered" and by["Kotlin Developer"]["AI fit"] == 7
    _, found = output.read(search.matches_path, matches.SHEET, matches.COLUMNS)
    assert [(r["Job title"], r["Fit (1-10)"], r["Applied?"]) for r in found] == [("Kotlin Developer", 7, "Yess")]


def test_matcher_without_cv_is_skipped(monkeypatch, search):
    calls = fake(monkeypatch, {"results": []})
    assert matcher.review(Profile(name="x", cv=[]), Preferences(), search) == (0, 0)
    assert calls == []


def test_matches_upsert_and_fuzzy_dedupe(tmp_path):
    path = tmp_path / "m.xlsx"
    row = {"Found": "2026-10-25", "Fit (1-10)": 8, "Job title": "Android Engineer", "Company": "Vinted",
           "Link": "https://x/a"}
    assert matches.add([row], path) == 1
    twin = {**row, "Company": "Vinteden", "Link": "https://arbeitnow/a", "Found": "2026-10-26", "Fit (1-10)": 7}
    assert matches.add([twin], path) == 0  # same job from another source
    _, rows = output.read(path, matches.SHEET, matches.COLUMNS)
    assert len(rows) == 1 and rows[0]["Found"] == "2026-10-25" and rows[0]["Fit (1-10)"] == 7
    assert matches.remove(["https://arbeitnow/a"], path) == 1


def test_job_in_two_roles_is_judged_once(monkeypatch, search):
    backend = Profile(name="backend", cv=["cv_android.txt"])
    fullstack = Profile(name="full-stack", cv=["cv_android.txt"])
    both = make("Kotlin Full Stack Developer", "https://x/both")
    results_with(search, backend, [both, make("Backend only", "https://x/b")])
    results_with(search, fullstack, [make("Kotlin Full Stack Developer", "https://other-source/both"),
                                     make("Fullstack only", "https://x/f")])
    calls = fake(monkeypatch, lambda prompt: {"results": [verdict(0, 8), verdict(1, 5, "maybe")]}
                 if "Backend only" in prompt else {"results": [verdict(0, 5, "maybe")]})
    matcher.review(backend, Preferences(), search, today="2026-10-25")
    assert len(calls) == 1
    matcher.review(fullstack, Preferences(), search, today="2026-10-25")
    assert len(calls) == 2 and "Kotlin Full Stack" not in calls[1]  # only "Fullstack only" sent
    row = {r["Job title"]: r for r in output.read(search.result_path(fullstack))[1]}["Kotlin Full Stack Developer"]
    assert row["AI fit"] == 8 and row["AI reason"].endswith("(judged for backend)")
    _, found = output.read(search.matches_path, matches.SHEET, matches.COLUMNS)
    assert [r["Job title"] for r in found] == ["Kotlin Full Stack Developer"]  # one match row, not two


def test_rescore_never_copies_stale_verdicts(monkeypatch, search):
    a, b = Profile(name="a", cv=["cv_android.txt"]), Profile(name="b", cv=["cv_android.txt"])
    results_with(search, a, [make("Shared job", "https://x/s")])
    results_with(search, b, [make("Shared job", "https://x/s")])
    fake(monkeypatch, {"results": [verdict(0, 9)]})
    matcher.review(a, Preferences(), search, today="2026-10-25")
    matcher.review(b, Preferences(), search, today="2026-10-25")  # copied from a
    calls = fake(monkeypatch, {"results": [verdict(0, 3, "no")]})  # the stricter prompt now says no
    matcher.rescore([b, a], Preferences(), search, today="2026-10-25")  # same day as the old verdicts
    assert len(calls) == 1  # b is judged fresh, a copies b's new verdict
    for prof in (a, b):
        assert output.read(search.result_path(prof))[1][0]["AI fit"] == 3
    assert output.read(search.matches_path, matches.SHEET, matches.COLUMNS)[1] == []


def test_travel_limit_accepts_typed_time(monkeypatch):
    from jobsearch import setup, travel
    for typed, minutes in [("3h", 180), ("3", 180), ("2h30", 150), ("2:30", 150), ("2 h 30", 150),
                           ("150 min", 150), ("90", 90), ("3 uur", 180)]:
        assert travel.parse(typed) == minutes, typed
    assert travel.parse("soon") is None and travel.parse("~2 h 30") == 150
    answers(monkeypatch, "6", "a while", "3h")  # Other → unreadable → 3 hours
    assert setup.ask_travel_limit(90) == 180
    answers(monkeypatch, "")  # the typed value is offered next time and Enter keeps it
    assert setup.ask_travel_limit(180) == 180


def test_avoided_main_technology_is_capped(monkeypatch, search):
    p = Profile(name="backend", cv=["cv_android.txt"])
    results_with(search, p, [make("Software Engineer", "https://x/1")])
    fake(monkeypatch, {"results": [verdict(0, 8, avoided_tech=True)]})
    matcher.review(p, Preferences(avoid=["python"]), search, today="2026-10-25")
    row = output.read(search.result_path(p))[1][0]
    assert (row["AI fit"], row["AI verdict"]) == (4, "no") and "avoid list" in row["AI reason"]


def test_existing_duplicate_matches_are_merged(tmp_path):
    path = tmp_path / "m.xlsx"
    rows = [{"Found": "2026-10-25", "Fit (1-10)": 7, "Job title": "Android Engineer, Frontend Technologies",
             "Company": "Vinted", "Link": "https://linkedin/1", "Applied?": ""},
            {"Found": "2026-10-25", "Fit (1-10)": 7, "Job title": "Android Engineer, Frontend Technologies",
             "Company": "Vinteden", "Link": "https://arbeitnow/1", "Applied?": "Yess"}]
    output.write(path, matches.COLUMNS + ["Applied?"], rows, matches.SHEET)  # as an older version left it
    matches.add([{"Found": "2026-10-26", "Fit (1-10)": 8, "Job title": "Other", "Company": "X",
                  "Link": "https://x/2"}], path)
    _, out = output.read(path, matches.SHEET, matches.COLUMNS)
    vinted = [r for r in out if r["Job title"].startswith("Android")]
    assert len(vinted) == 1 and vinted[0]["Applied?"] == "Yess"  # user column kept from the duplicate


def test_model_cannot_reject_hybrid_within_travel_limit(monkeypatch, search):
    p = Profile(name="android", cv=["cv_android.txt"], onsite_places=["Maastricht"], max_hybrid_minutes=180,
                max_office_days=2)
    jobs = [make("Hybrid Amsterdam", "https://x/1", "Amsterdam"), make("Hybrid Groenlo", "https://x/2", "Groenlo"),
            make("Remote tag, Delft office", "https://x/3", "Delft"), make("Hybrid 4 days", "https://x/4", "Utrecht")]
    for j, mode in zip(jobs, ["hybrid", "hybrid", "remote", "hybrid"]):
        j.work_mode = mode
    jobs[0].travel, jobs[1].travel, jobs[3].travel = 150, 200, 120
    results_with(search, p, jobs)
    fake(monkeypatch, {"results": [verdict(0, 8, breaks_setup=True), verdict(1, 8, breaks_setup=True),
                                   verdict(2, 8, breaks_setup=True), verdict(3, 8, office_days=4)]})
    matcher.review(p, Preferences(), search, today="2026-10-25")
    by = {r["Job title"]: r for r in output.read(search.result_path(p))[1]}
    assert by["Hybrid Amsterdam"]["AI fit"] == 8          # 2 h 30 ≤ 3 h: the model's flag is overruled
    assert by["Hybrid Groenlo"]["AI verdict"] == "no"     # 3 h 20 > 3 h
    assert by["Remote tag, Delft office"]["AI verdict"] == "no"  # no travel known: the model's flag counts
    assert by["Hybrid 4 days"]["AI verdict"] == "no"      # office days still enforced
