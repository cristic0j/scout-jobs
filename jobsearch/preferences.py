"""What the user wants from any job, shared by all profiles. Asked once during setup, then reused."""
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .profile import PROFILES, ROOT

PATH = PROFILES / "preferences.json"
CV_DIR = ROOT / "cv"
CV_TYPES = {".pdf", ".txt", ".md"}
# Optional notes the planner may use to suggest answers (Cristian's playbook).
NOTES_FILE = Path.home() / "Desktop/Jobs/JOB_SEARCH.md"


@dataclass
class Preferences:
    home: str = ""                                  # where the user lives, e.g. "Maastricht"
    location: str = "Netherlands"                   # country / region to search
    languages: list = field(default_factory=list)   # languages the user can work in
    levels: list = field(default_factory=lambda: ["internship", "junior", "medior"])
    work_modes: list = field(default_factory=list)  # empty = any
    max_days: int = 30
    dutch: str = "off"                              # key of profile.DUTCH_FILTERS
    avoid: list = field(default_factory=list)       # title words to drop in every profile
    extra_roles: list = field(default_factory=list) # roles the user asked for beyond the CV
    notes: list = field(default_factory=list)       # answers to the planner's free-form questions

    @classmethod
    def load(cls):
        if not PATH.exists():
            return None
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in json.loads(PATH.read_text()).items() if k in known})

    def save(self):
        PROFILES.mkdir(exist_ok=True)
        PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")
        return PATH

    def describe(self):
        return "\n".join([
            f"  Lives in:         {self.home or '—'}",
            f"  Search in:        {self.location}",
            f"  Languages:        {', '.join(self.languages) or '—'}",
            f"  Seniority:        {', '.join(self.levels)}",
            f"  Work mode:        {', '.join(self.work_modes) or 'any'}",
            f"  Max age:          {self.max_days} days",
            f"  Dutch filter:     {self.dutch}",
            f"  Always drop:      {', '.join(self.avoid) or '—'}",
            f"  Extra roles:      {', '.join(self.extra_roles) or '—'}",
        ])


def cv_files():
    return sorted(p for p in CV_DIR.glob("*") if p.suffix.lower() in CV_TYPES)
