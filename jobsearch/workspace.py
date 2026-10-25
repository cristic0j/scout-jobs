"""A search folder: the CV(s) it is about, its preferences, profiles and results.

searches/<name>/cv/                 CV versions for this search
searches/<name>/preferences.json
searches/<name>/profiles/<role>.json
searches/<name>/results/<role>.xlsx
searches/<name>/matches.xlsx
searches/<name>/cloud.json          the Google Sheet it syncs with (see cloud.py)
searches/<name>/state.json          CV fingerprint, last setup, last run
searches/<name>/travel.json         cached travel times from home
"""
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .profile import ROOT, Profile, slug

SEARCHES = ROOT / "searches"
CV_TYPES = {".pdf", ".txt", ".md", ".docx"}


@dataclass
class Search:
    root: Path

    @property
    def name(self):
        return self.root.name

    @property
    def cv_dir(self):
        return self.root / "cv"

    @property
    def profiles_dir(self):
        return self.root / "profiles"

    @property
    def results_dir(self):
        return self.root / "results"

    @property
    def prefs_path(self):
        return self.root / "preferences.json"

    @property
    def matches_path(self):
        return self.root / "matches.xlsx"

    @property
    def state_path(self):
        return self.root / "state.json"

    @property
    def travel_path(self):
        return self.root / "travel.json"

    def create(self):
        for d in (self.cv_dir, self.profiles_dir, self.results_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    # --- CV ---
    def cv_files(self):
        return sorted(p for p in self.cv_dir.glob("*") if p.suffix.lower() in CV_TYPES) if self.cv_dir.exists() else []

    def cv_fingerprint(self):
        """Changes whenever a CV file is added, removed or edited."""
        h = hashlib.sha256()
        for p in self.cv_files():
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
        return h.hexdigest() if self.cv_files() else ""

    def cv_changed(self):
        return self.cv_fingerprint() != self.state().get("cv_fingerprint", "")

    # --- state ---
    def state(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

    def save_state(self, **changes):
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({**self.state(), **changes}, indent=2) + "\n")

    # --- profiles ---
    def profile_names(self):
        return sorted(p.stem for p in self.profiles_dir.glob("*.json")) if self.profiles_dir.exists() else []

    def load_profile(self, name):
        path = self.profiles_dir / f"{slug(name)}.json"
        if not path.exists():
            raise SystemExit(f"No profile '{name}' in search '{self.name}'. "
                             f"Profiles: {', '.join(self.profile_names()) or 'none'}")
        return Profile.from_dict(json.loads(path.read_text()))

    def profiles(self):
        return [self.load_profile(n) for n in self.profile_names()]

    def save_profile(self, profile):
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        path = self.profiles_dir / f"{profile.name}.json"
        path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False) + "\n")
        return path

    def result_path(self, profile):
        return self.results_dir / f"{profile.name}.xlsx"

    def summary(self):
        from . import matches, output
        st = self.state()
        n = len(output.read(self.matches_path, matches.SHEET, matches.COLUMNS)[1]) if self.matches_path.exists() else 0
        cv = ("no CV yet" if not self.cv_files() else "CV changed since setup" if self.cv_changed()
              else "CV unchanged")
        return (f"{len(self.profile_names())} roles · last run {st.get('last_run', 'never')} · "
                f"{n} matches · {cv}")


def get(name):
    return Search(SEARCHES / slug(name))


def all_searches():
    return sorted((Search(p) for p in SEARCHES.iterdir() if p.is_dir()), key=lambda s: s.name) \
        if SEARCHES.exists() else []


def same_cv(search):
    """Another search whose CV files are identical to this one's, or None."""
    fp = search.cv_fingerprint()
    return next((s for s in all_searches() if fp and s.name != search.name and s.cv_fingerprint() == fp), None)


LEGACY = {"cv": ROOT / "cv", "profiles": ROOT / "profiles", "results": ROOT / "results"}


def has_legacy():
    return any(p.exists() and any(p.iterdir()) for p in LEGACY.values())


def migrate_legacy(name):
    """Move the pre-folders layout (cv/, profiles/, results/ in the project root) into searches/<name>/."""
    search = get(name).create()
    moves = []
    for kind, src in LEGACY.items():
        if not src.exists():
            continue
        for f in src.iterdir():
            if f.name == "preferences.json":
                dest = search.prefs_path
            elif f.name == "matches.xlsx":
                dest = search.matches_path
            else:
                dest = {"cv": search.cv_dir, "profiles": search.profiles_dir, "results": search.results_dir}[kind] / f.name
            shutil.move(str(f), dest)
            moves.append(dest)
        src.rmdir()
    if search.cv_files() and search.profile_names():
        search.save_state(cv_fingerprint=search.cv_fingerprint())
    return search, moves
