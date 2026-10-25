import pytest

from jobsearch import llm, travel, workspace
from jobsearch.profile import Profile


@pytest.fixture(autouse=True)
def tmp_searches(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "SEARCHES", tmp_path / "searches")
    return tmp_path


def test_search_folder_and_cv_fingerprint():
    s = workspace.get("Anna CV!").create()
    assert s.name == "anna-cv" and s.cv_dir.is_dir() and s.cv_fingerprint() == ""
    (s.cv_dir / "cv.pdf").write_bytes(b"v1")
    (s.cv_dir / "notes.png").write_bytes(b"ignored")
    fp = s.cv_fingerprint()
    assert s.cv_changed()  # never set up
    s.save_state(cv_fingerprint=fp)
    assert not s.cv_changed()
    (s.cv_dir / "cv.pdf").write_bytes(b"v2")
    assert s.cv_changed()


def test_same_cv_in_another_search():
    a, b = workspace.get("a").create(), workspace.get("b").create()
    (a.cv_dir / "cv.pdf").write_bytes(b"same")
    (b.cv_dir / "my cv.pdf").write_bytes(b"same")
    assert workspace.same_cv(b) is None  # different file name → different fingerprint
    (b.cv_dir / "my cv.pdf").rename(b.cv_dir / "cv.pdf")
    assert workspace.same_cv(b).name == "a"


def test_profiles_live_in_their_search():
    s = workspace.get("s").create()
    s.save_profile(Profile(name="android"))
    assert s.profile_names() == ["android"] and s.load_profile("android").name == "android"
    assert s.result_path(Profile(name="android")) == s.results_dir / "android.xlsx"
    assert workspace.get("other").create().profile_names() == []



def test_travel_cache_and_place_keys(monkeypatch):
    s = workspace.get("t").create()
    calls = []

    def ask_json(prompt, schema, files=(), system=""):
        calls.append(prompt)
        return {"times": [{"place": "amsterdam", "minutes": 150}, {"place": "eindhoven", "minutes": 60},
                          {"place": "nowhere", "minutes": -1}]}
    monkeypatch.setattr(llm, "ask_json", ask_json)
    locs = ["Amsterdam Area", "Eindhoven, North Brabant, Netherlands", "Greater Amsterdam", "Nowhere"]
    assert travel.minutes(s, "Maastricht", "Netherlands", locs) == {"amsterdam": 150, "eindhoven": 60, "nowhere": None}
    assert travel.minutes(s, "Maastricht", "Netherlands", locs[:2]) == {"amsterdam": 150, "eindhoven": 60}
    assert len(calls) == 1  # second time from the cache
    assert travel.minutes(s, "Maastricht", "Netherlands", ["Netherlands"]) == {"netherlands": None}  # not a place
    assert len(calls) == 1
    assert (travel.text(150), travel.text(45), travel.text(60)) == ("~2 h 30", "~45 min", "~1 h")
