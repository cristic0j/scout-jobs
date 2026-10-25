from datetime import date

from jobsearch import filters
from jobsearch.models import Job
from jobsearch.profile import Profile


def make(title, posted="2026-10-20", mode="", level="medior", lang=""):
    j = Job("Test", title, "Acme", "Amsterdam", posted, f"https://x/{title}", mode)
    j.level, j.lang = level, lang
    return j


TODAY = date(2026, 10, 25)


def test_software_preset():
    p = Profile.from_preset("software")
    jobs = [make("Backend Developer"), make("Python Developer"), make("Sales Manager"),
            make("Senior Engineer", level="senior"), make("Java Developer", posted="2026-08-01")]
    kept, dropped = filters.apply(jobs, filters.build(p, TODAY))
    assert [j.title for j in kept] == ["Backend Developer"]
    assert sum(dropped.values()) == 4


def test_work_mode_unknown():
    p = Profile.from_preset("software")
    p.work_modes = ["hybrid"]
    jobs = [make("Web Developer", mode="hybrid"), make("Android Developer", mode="on-site"),
            make("Java Developer")]
    p.keep_unknown_work_mode = True
    assert len(filters.apply(jobs, filters.build(p, TODAY))[0]) == 2
    p.keep_unknown_work_mode = False
    assert [j.title for j in filters.apply(jobs, filters.build(p, TODAY))[0]] == ["Web Developer"]


def test_other_category_and_no_include():
    p = Profile.from_preset("marketing")
    kept, _ = filters.apply([make("Marketing Manager"), make("Java Developer")], filters.build(p, TODAY))
    assert [j.title for j in kept] == ["Marketing Manager"]
    p.title_include = []
    assert len(filters.apply([make("Anything")], filters.build(p, TODAY))[0]) == 1


def test_dutch_filter():
    jobs = [make("A", lang="Dutch"), make("B", lang="Dutch required"), make("C", lang="English")]
    p = Profile(dutch="written")
    assert [j.title for j in filters.apply(jobs, [filters.dutch(p)])[0]] == ["B", "C"]
    p.dutch = "required"
    assert [j.title for j in filters.apply(jobs, [filters.dutch(p)])[0]] == ["C"]
    p.dutch = "off"
    assert filters.dutch(p) is None
