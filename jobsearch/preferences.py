"""What the user wants from any job, shared by all profiles of a search. Asked during setup, then reused."""
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .detect import WORK_MODES
from .profile import Profile

# Optional notes the planner may use to suggest answers (Cristian's playbook).
NOTES_FILE = Path.home() / "Desktop/Jobs/JOB_SEARCH.md"
NOT_ASKED = -1


@dataclass
class Preferences:
    home: str = ""                                  # where the user lives, e.g. "Maastricht"
    location: str = "Netherlands"                   # country / region to search
    languages: list = field(default_factory=list)   # languages the user can work in
    levels: list = field(default_factory=lambda: ["internship", "junior", "medior"])
    setups: list = field(default_factory=lambda: list(WORK_MODES))  # on-site / hybrid / remote
    onsite_places: list = field(default_factory=list)  # home + neighbouring towns
    max_hybrid_minutes: int = NOT_ASKED             # one-way travel limit for hybrid; 0 = any
    max_office_days: int = 0                        # hybrid outside the on-site towns; 0 = any
    max_days: int = 30
    dutch: str = "off"                              # key of profile.DUTCH_FILTERS
    avoid: list = field(default_factory=list)       # title words to drop in every profile
    extra_roles: list = field(default_factory=list) # roles the user asked for beyond the CV
    notes: list = field(default_factory=list)       # answers to the planner's free-form questions

    @classmethod
    def load(cls, search):
        if not search.prefs_path.exists():
            return None
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in json.loads(search.prefs_path.read_text()).items() if k in known})

    def save(self, search):
        search.root.mkdir(parents=True, exist_ok=True)
        search.prefs_path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")
        return search.prefs_path

    def setups_text(self):
        return Profile(setups=self.setups, onsite_places=self.onsite_places,
                       max_hybrid_minutes=self.max_hybrid_minutes, max_office_days=self.max_office_days).setups_text()

    def setups_complete(self):
        return "hybrid" not in self.setups or self.max_hybrid_minutes != NOT_ASKED
