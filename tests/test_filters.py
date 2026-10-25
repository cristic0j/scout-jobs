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


def at(title, place, mode="", travel=None):
    j = make(title, mode=mode)
    j.location, j.travel = place, travel
    return j


def kept(p, jobs):
    return [j.title for j in filters.apply(jobs, filters.build(p, TODAY))[0]]


def test_work_setup_by_place_and_travel():
    p = Profile.from_preset("software")
    p.onsite_places, p.max_hybrid_minutes = ["Maastricht", "Heerlen"], 90
    jobs = [at("Web Developer", "Maastricht, Limburg", "on-site"),        # on-site near home
            at("Java Developer", "Amsterdam", "on-site"),                 # on-site far away
            at("Android Developer", "Eindhoven", "hybrid", 60),           # hybrid within the limit
            at("Kotlin Developer", "Delft", "hybrid", 150),               # hybrid too far
            at("Backend Developer", "Amsterdam", "remote"),               # remote anywhere
            at("Frontend Developer", "Heerlen", "hybrid"),                # hybrid near home
            at("Mobile Developer", "Rotterdam", "hybrid", None),          # travel unknown → matcher judges
            at("Software Engineer", "Groningen", "", 200)]                # unknown mode, could be remote
    assert kept(p, jobs) == ["Web Developer", "Android Developer", "Backend Developer", "Frontend Developer",
                             "Mobile Developer", "Software Engineer"]
    assert kept(p, [at("Web Developer", "Brabantine City Row", "on-site")]) == []
    assert kept(p, [at("Web Developer", "South Limburg", "on-site")]) == ["Web Developer"]  # region of home

    p.setups = ["on-site", "hybrid"]  # no remote: unknown mode far away must be within the travel limit
    assert kept(p, jobs) == ["Web Developer", "Android Developer", "Frontend Developer", "Mobile Developer"]


def test_work_setup_defaults_allow_everything():
    p = Profile.from_preset("software")
    assert p.any_setup_anywhere()
    assert len(kept(p, [at("Java Developer", "Amsterdam", "on-site"), at("Web Developer", "Utrecht")])) == 2


def test_linkedin_plan():
    from jobsearch.sources import linkedin
    p = Profile.from_preset("software")
    assert linkedin.plan(p) == [("Netherlands", "", "")]
    p.onsite_places, p.home, p.max_hybrid_minutes = ["Maastricht", "Heerlen"], "Maastricht", 90
    assert linkedin.plan(p) == [("Maastricht, Netherlands", 25, ""), ("Netherlands", "", "hybrid"),
                                ("Netherlands", "", "remote")]
    p.setups = ["remote"]
    assert linkedin.plan(p) == [("Netherlands", "", "remote")]


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
