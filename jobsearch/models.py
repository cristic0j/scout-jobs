from dataclasses import dataclass


@dataclass
class Job:
    """One posting, the same shape for every source."""
    source: str
    title: str
    company: str
    location: str
    posted: str          # YYYY-MM-DD or ""
    link: str
    work_mode: str = ""  # "hybrid" | "remote" | "on-site" | "" (unknown)
    desc: str = ""
    # Filled in by the pipeline:
    level: str = ""      # "internship" | "junior" | "medior" | "senior"
    lang: str = ""       # "Dutch" | "Dutch required" | "English" | "?" | "" (not checked)
    travel: object = None  # minutes from home (int), None = not needed or unknown
    tracked: bool = False
    new: bool = False

    def __post_init__(self):
        for f in ("source", "title", "company", "location", "posted", "link", "work_mode", "desc"):
            setattr(self, f, (getattr(self, f) or "").strip())
