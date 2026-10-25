"""A saved search: what to look for, which filters apply, and which sources to ask."""
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from .detect import WORK_MODES
from .matching import keyword_pattern
from .presets import PRESETS

ROOT = Path(__file__).resolve().parent.parent

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

# LinkedIn sometimes gives a region instead of a city. Choosing a city also accepts its region.
REGIONS = {
    "Brabantine City Row": ["eindhoven", "tilburg", "den bosch", "'s-hertogenbosch", "breda", "helmond"],
    "Randstad": ["amsterdam", "rotterdam", "den haag", "the hague", "utrecht", "leiden", "haarlem", "delft"],
    "South Limburg": ["maastricht", "heerlen", "sittard", "geleen", "kerkrade", "valkenburg", "meerssen"],
}


def with_regions(places):
    chosen = {p.lower() for p in places}
    return list(places) + [r for r, cities in REGIONS.items() if chosen & set(cities)]


SOURCES = ["linkedin", "boards", "arbeitnow", "jooble", "adzuna"]
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
    # Work setup: on-site only in onsite_places (empty = anywhere), hybrid near home or within
    # max_hybrid_minutes of travel (0 = any), remote anywhere.
    setups: list = field(default_factory=lambda: list(WORK_MODES))
    onsite_places: list = field(default_factory=list)
    max_hybrid_minutes: int = 0
    max_office_days: int = 0  # for hybrid outside the on-site towns; 0 = any (judged by the matcher)
    home: str = ""  # centre of the near-home LinkedIn search; defaults to the first on-site place
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

    def near_home(self, place):
        onsite = keyword_pattern(with_regions(self.onsite_places))
        return onsite is None or bool(onsite.search(place or ""))

    def needs_travel(self):
        return "hybrid" in self.setups and self.max_hybrid_minutes > 0

    def setup_allowed(self):
        """fn(work_mode, job_location, travel_minutes) → bool.
        Unknown travel (None) passes, so the matcher can judge from the description.
        Unknown mode ("") passes if any chosen setup could apply there."""
        setups = set(self.setups) or set(WORK_MODES)
        onsite = keyword_pattern(with_regions(self.onsite_places))
        limit = self.max_hybrid_minutes

        def allowed(mode, place, travel=None):
            near = onsite is None or bool(onsite.search(place or ""))
            if mode == "on-site":
                return "on-site" in setups and near
            if mode == "hybrid":
                return "hybrid" in setups and (near or limit <= 0 or travel is None or travel <= limit)
            if mode == "remote":
                return "remote" in setups
            return any(allowed(m, place, travel) for m in WORK_MODES)
        return allowed

    def any_setup_anywhere(self):
        return set(self.setups) >= set(WORK_MODES) and not self.onsite_places and self.max_hybrid_minutes <= 0

    def setups_text(self):
        from .travel import text
        parts = []
        if "on-site" in self.setups:
            parts.append(f"on-site in {', '.join(self.onsite_places)}" if self.onsite_places else "on-site anywhere")
        if "hybrid" in self.setups:
            hybrid = f"hybrid within {text(self.max_hybrid_minutes)[1:]}" if self.max_hybrid_minutes > 0 else \
                "hybrid anywhere" if self.max_hybrid_minutes == 0 else "hybrid (travel limit not set yet)"
            if self.max_office_days > 0:
                hybrid += f" (max {self.max_office_days} office day{'s' if self.max_office_days > 1 else ''}/week)"
            parts.append(hybrid)
        if "remote" in self.setups:
            parts.append("remote anywhere")
        return "; ".join(parts) or "—"

    def describe(self, output=None):
        def lst(xs, n=8):
            return ", ".join(xs[:n]) + (f" … (+{len(xs) - n})" if len(xs) > n else "") if xs else "—"
        return "\n".join([
            f"  Profile:          {self.name} ({PRESETS.get(self.category, {}).get('label', self.category)})",
            f"  Search terms:     {lst(self.search_terms)}",
            f"  Title must have:  {lst(self.title_include)}",
            f"  Title must not:   {lst(self.title_exclude)}",
            f"  Seniority:        {', '.join(self.levels)}",
            f"  Max age:          {self.max_days} days",
            f"  Work setup:       {self.setups_text()}",
            f"  Dutch filter:     {DUTCH_FILTERS[self.dutch]}",
            f"  Location:         {self.location}",
            f"  Sources:          {', '.join(self.sources)}",
            f"  Judged against:   {', '.join(self.cv) or 'no CV (matcher skipped)'}",
        ] + ([f"  Results file:     {output}"] if output else []))


def slug(name):
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "search"
