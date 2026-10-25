"""A saved search: what to look for, which filters apply, and which sources to ask."""
import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .matching import keyword_pattern
from .presets import PRESETS

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
RESULTS = ROOT / "results"

# Company boards known (2026-10-24) to post Netherlands roles. Add slugs freely.
DEFAULT_BOARDS = {
    "greenhouse": ["adyen", "databricks", "catawiki", "fourthline", "dataiku", "gitlab",
                   "datadog", "dept", "typeform", "imc", "flowtraders", "elastic", "stripe"],
    "lever": ["mendix"],
    "ashby": ["mollie", "miro", "polarsteps", "bitvavo"],
    "recruitee": ["bunq", "ticketswap", "realworks", "sioux", "channable", "helloprint",
                  "vandebron", "greenchoice", "effectory"],
}

NL_PLACES = ["netherlands", "nederland", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven",
             "den haag", "the hague", "'s-hertogenbosch", "den bosch", "delft", "maastricht", "groningen",
             "leiden", "haarlem", "nijmegen", "tilburg", "breda", "arnhem", "enschede", "zwolle",
             "amersfoort", "hilversum", "almere", "venlo", "heerlen", "sittard", "geleen", "roermond",
             "weert", "helmond", "apeldoorn", "schiphol", "hoofddorp", "amstelveen", "zaandam", "deventer",
             "veenendaal", r"re:\bbest\b", "veldhoven"]

SOURCES = ["linkedin", "boards", "arbeitnow", "jooble", "adzuna"]
WORK_MODES = ["hybrid", "remote", "on-site"]
DUTCH_FILTERS = {"off": "Off",
                 "written": "Drop jobs written in Dutch",
                 "required": "Drop jobs written in Dutch or requiring Dutch"}


@dataclass
class Profile:
    name: str = "software"
    category: str = "software"
    search_terms: list = field(default_factory=list)
    title_include: list = field(default_factory=list)
    title_exclude: list = field(default_factory=list)
    levels: list = field(default_factory=lambda: ["internship", "junior", "medior"])
    max_days: int = 30
    work_modes: list = field(default_factory=list)  # empty = any
    keep_unknown_work_mode: bool = True
    dutch: str = "off"  # key of DUTCH_FILTERS
    location: str = "Netherlands"
    location_match: list = field(default_factory=lambda: list(NL_PLACES))
    country_code: str = "nl"
    sources: list = field(default_factory=lambda: list(SOURCES))
    boards: dict = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_BOARDS.items()})
    cv: list = field(default_factory=list)  # CV file names in cv/ that the matcher judges against
    match_threshold: int = 7                 # fit (1-10) needed to land in matches.xlsx

    @classmethod
    def from_preset(cls, key):
        p = PRESETS[key]
        return cls(name=key, category=key, search_terms=list(p["search_terms"]),
                   title_include=list(p["title_include"]), title_exclude=list(p["title_exclude"]))

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def set_location(self, location, cities=(), country_code=""):
        """NL gets the built-in city list; other places match by name plus the given cities."""
        self.location = location
        if location.lower() in ("netherlands", "nederland", "the netherlands"):
            self.location_match, self.country_code = list(NL_PLACES), "nl"
        else:
            self.location_match = [location] + [c for c in cities if c]
            self.country_code = country_code.lower()

    def location_re(self):
        return keyword_pattern(self.location_match or [self.location])

    @property
    def output(self):
        return RESULTS / f"{self.name}.xlsx"

    def describe(self):
        def lst(xs, n=8):
            return ", ".join(xs[:n]) + (f" … (+{len(xs) - n})" if len(xs) > n else "") if xs else "—"
        modes = ", ".join(self.work_modes) if self.work_modes else "any"
        if self.work_modes:
            modes += " (unknown kept)" if self.keep_unknown_work_mode else " (unknown dropped)"
        return "\n".join([
            f"  Profile:          {self.name} ({PRESETS.get(self.category, {}).get('label', self.category)})",
            f"  Search terms:     {lst(self.search_terms)}",
            f"  Title must have:  {lst(self.title_include)}",
            f"  Title must not:   {lst(self.title_exclude)}",
            f"  Seniority:        {', '.join(self.levels)}",
            f"  Max age:          {self.max_days} days",
            f"  Work mode:        {modes}",
            f"  Dutch filter:     {DUTCH_FILTERS[self.dutch]}",
            f"  Location:         {self.location}",
            f"  Sources:          {', '.join(self.sources)}",
            f"  Judged against:   {', '.join(self.cv) or 'no CV (matcher skipped)'}",
            f"  Results file:     {self.output}",
        ])


def slug(name):
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "search"


def saved_names():
    return sorted(p.stem for p in PROFILES.glob("*.json") if p.stem != "preferences")


def load(name):
    path = PROFILES / f"{slug(name)}.json"
    if not path.exists():
        raise SystemExit(f"No saved profile '{name}'. Saved: {', '.join(saved_names()) or 'none'}")
    return Profile.from_dict(json.loads(path.read_text()))


def save(profile):
    PROFILES.mkdir(exist_ok=True)
    path = PROFILES / f"{profile.name}.json"
    path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False) + "\n")
    return path
