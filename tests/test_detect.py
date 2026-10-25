import pytest

from jobsearch.detect import language, level, work_mode
from jobsearch.matching import keyword_pattern
from jobsearch.models import Job


def make(title="Developer", location="Amsterdam", desc="", mode=""):
    return Job("Test", title, "Acme", location, "2026-10-20", "https://x/1", mode, desc)


@pytest.mark.parametrize("title,hit", [
    ("Go Developer", True), ("Google Ads Specialist", False), ("Softwareontwikkelaar", True),
    ("Webdeveloper", True), (".NET Engineer", True), ("Kotlin/Android dev", True), ("QA Analyst", False),
])
def test_keywords(title, hit):
    pattern = keyword_pattern(["go", "developer", "software", ".net", "android"])
    assert bool(pattern.search(title)) is hit


def test_keywords_regex_and_empty():
    assert keyword_pattern(["re:^java$"]).search("Java")
    assert not keyword_pattern(["re:^java$"]).search("Java Developer")
    assert keyword_pattern(["", " "]) is None


@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern", "internship"), ("Internal Tools Developer", "medior"),
    ("Junior Product Manager", "junior"), ("Senior Backend Engineer", "senior"),
    ("Tech Lead Android", "senior"), ("Team Leader Support", "medior"), ("Backend Developer", "medior"),
    ("Graduate Software Engineer", "junior"), ("Stagiair Marketing", "internship"),
])
def test_level(title, expected):
    assert level(title) == expected


def test_work_mode():
    assert work_mode(make(mode="on-site", desc="hybrid work")) == "on-site"  # source field beats description
    assert work_mode(make(title="Android Engineer – Amsterdam (Hybrid)", mode="remote")) == "hybrid"  # title wins
    assert work_mode(make(mode="unspecified")) == ""
    assert work_mode(make(desc="We work hybrid from Utrecht.")) == "hybrid"
    assert work_mode(make(desc="You work 3 days in the office.")) == "hybrid"
    assert work_mode(make(desc="Wij werken 2 dagen op kantoor.")) == "hybrid"
    assert work_mode(make(desc="Pensioen. Hybride werken. Laptop.")) == "hybrid"
    assert work_mode(make(desc="de mogelijkheid om hybride te werken")) == "hybrid"
    assert work_mode(make(desc="32 hours workweek Hybrid, from home or the office")) == "hybrid"
    assert work_mode(make(desc="Our hybrid model, with 2 days in the office")) == "hybrid"
    assert work_mode(make(location="Amsterdam (Hybrid)")) == "hybrid"
    assert work_mode(make(desc="This hybrid approach lets us evolve the platform.")) == ""
    assert work_mode(make(desc="Kubernetes, hybride en cloudomgevingen, on-premises")) == ""
    assert work_mode(make(desc="Experience with hybrid cloud setups.")) == ""
    assert work_mode(make(location="Remote - Netherlands")) == "remote"
    assert work_mode(make(desc="We are a fully remote team.")) == "remote"
    assert work_mode(make(desc="Our office is in Eindhoven.")) == ""


def test_language():
    assert language("Developer", "Wij zoeken een ontwikkelaar met ervaring in Java voor ons team en het project.") == "Dutch"
    assert language("Developer", "You will build our app. Dutch is a plus, but not required.") == "English"
    assert language("Developer", "You will build our app. Fluent Dutch is required for this role.") == "Dutch required"
    assert language("Developer", "") == "?"
    assert language("Java ontwikkelaar", "") == "Dutch"
