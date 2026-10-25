"""Planner and matcher with a fake Gemini (no network)."""
import pytest

from jobsearch import llm, matches, output
from jobsearch.agents import matcher, planner
from jobsearch.models import Job
from jobsearch.preferences import Preferences
from jobsearch.profile import Profile


@pytest.fixture
def cv(tmp_path, monkeypatch):
    d = tmp_path / "cv"
    d.mkdir()
    (d / "cv_android.txt").write_text("Android developer, Kotlin, 2 years.")
    monkeypatch.setattr(matcher, "CV_DIR", d)
    monkeypatch.setattr(planner, "NOTES_FILE", tmp_path / "missing.md")
    return d / "cv_android.txt"


def fake(monkeypatch, reply):
    calls = []

    def ask_json(prompt, schema, files=(), system=""):
        calls.append(prompt)
        return reply(prompt) if callable(reply) else reply
    monkeypatch.setattr(llm, "ask_json", ask_json)
    return calls


ANALYSIS = {
    "summary": "Junior Android dev.",
    "roles": [{"name": "Android Developer", "label": "Android", "why": "Kotlin", "cv": ["cv_android.txt", "nope.pdf"],
               "search_terms": ["android developer"] * 3 + [f"t{i}" for i in range(10)],
               "title_include": ["android", " "], "title_exclude": ["sales"]},
              {"name": "empty", "label": "x", "why": "", "cv": [], "search_terms": [], "title_include": [],
               "title_exclude": []}],
    "preferences": {"home": "Maastricht", "location": "Netherlands", "languages": ["English"],
                    "levels": ["junior", "boss"], "work_modes": ["hybrid", "sometimes"], "max_days": -3,
                    "dutch": "required", "avoid": ["python"]},
    "unsure": ["work_modes", "nonsense"],
    "questions": [{"question": "Open to Belgium?", "why": "you live near the border"}, {"question": ""}],
}


def test_planner_cleans_agent_output(monkeypatch, cv):
    fake(monkeypatch, ANALYSIS)
    plan = planner.analyze([cv])
    assert [r["name"] for r in plan["roles"]] == ["android-developer"]  # empty role dropped, name slugged
    role = plan["roles"][0]
    assert role["cv"] == ["cv_android.txt"] and len(role["search_terms"]) == 8 and role["title_include"] == ["android"]
    prefs = plan["preferences"]
    assert prefs.levels == ["junior"] and prefs.work_modes == ["hybrid"] and prefs.max_days == 30
    assert plan["unsure"] == ["work_modes"] and len(plan["questions"]) == 1

    p = planner.to_profile(role, prefs)
    assert p.title_exclude == ["sales", "python"] and p.dutch == "required" and p.cv == ["cv_android.txt"]


def test_planner_keeps_saved_preferences(monkeypatch, cv):
    calls = fake(monkeypatch, ANALYSIS)
    saved = Preferences(home="Utrecht", levels=["medior"])
    plan = planner.analyze([cv], saved)
    assert plan["preferences"] is saved and plan["unsure"] == []
    assert "Utrecht" in calls[0]


def results_with(path, jobs):
    headers, rows = output.read(path)
    rows, _ = output.merge(rows, jobs, "2026-10-25")
    output.write(path, headers, rows)


def make(title, link, tracked=False):
    j = Job("Test", title, "Acme", "Maastricht", "2026-10-24", link)
    j.level, j.tracked = "junior", tracked
    return j


def test_matcher_reviews_only_unprocessed(monkeypatch, tmp_path, cv):
    monkeypatch.setattr("jobsearch.profile.RESULTS", tmp_path)
    monkeypatch.setattr(matches, "PATH", tmp_path / "matches.xlsx")
    monkeypatch.setattr(matcher.descriptions, "PATH", tmp_path / "desc.json")
    p = Profile(name="android", cv=[cv.name])
    monkeypatch.setattr(Profile, "output", property(lambda self: tmp_path / f"{self.name}.xlsx"))
    results_with(p.output, [make("Android Dev", "https://x/1"), make("Kotlin Dev", "https://x/2"),
                            make("Old one", "https://x/3", tracked=True)])

    def reply(prompt):
        return {"results": [{"id": 0, "fit": 9, "verdict": "match", "why": "Kotlin", "caveats": ""},
                            {"id": 1, "fit": 4, "verdict": "no", "why": "needs 5 yrs", "caveats": "senior"}]}
    calls = fake(monkeypatch, reply)
    assert matcher.review(p, Preferences(), today="2026-10-25") == (2, 1)
    assert len(calls) == 1 and "Old one" not in calls[0]  # tracked rows skip the agent

    _, rows = output.read(p.output)
    assert all(r["Processed"] == "2026-10-25" for r in rows)
    by = {r["Job title"]: r for r in rows}
    assert by["Android Dev"]["AI fit"] == 9 and by["Old one"]["AI verdict"] == "in tracker"
    _, found = output.read(matches.PATH, matches.SHEET, matches.COLUMNS)
    assert [r["Job title"] for r in found] == ["Android Dev"]

    # Second run: nothing unprocessed → no Gemini call at all.
    assert matcher.review(p, Preferences(), today="2026-10-26") == (0, 0)
    assert len(calls) == 1


def test_matcher_without_cv_is_skipped(monkeypatch, cv):
    calls = fake(monkeypatch, {"results": []})
    assert matcher.review(Profile(name="x", cv=[]), Preferences()) == (0, 0)
    assert calls == []


def test_matches_dedupe(tmp_path):
    path = tmp_path / "m.xlsx"
    row = {"Found": "2026-10-25", "Fit (1-10)": 8, "Job title": "A", "Link": "https://x/a"}
    assert matches.add([row], path) == 1
    assert matches.add([row, {**row, "Link": "https://x/b"}], path) == 1
