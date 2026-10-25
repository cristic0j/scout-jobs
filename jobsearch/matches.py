"""results/matches.xlsx: the jobs the matcher found to fit, across all profiles. Rows are only added,
deduped by link, and any columns you add yourself (e.g. Applied?) are kept."""
from . import output
from .profile import RESULTS

PATH = RESULTS / "matches.xlsx"
SHEET = "Matches"
COLUMNS = ["Found", "Fit (1-10)", "Job title", "Company", "Location", "Work mode", "Posted", "Why it fits",
           "Caveats", "CV", "Profile", "Link"]


def add(entries, path=None):
    """entries: [{column: value}]. Returns how many were new."""
    if not entries:
        return 0
    path = path or PATH
    headers, rows = output.read(path, SHEET, COLUMNS)
    links = {r.get("Link") for r in rows}
    new = [e for e in entries if e.get("Link") not in links]
    rows += new
    rows.sort(key=lambda r: int(r.get("Fit (1-10)") or 0), reverse=True)
    rows.sort(key=lambda r: str(r.get("Found") or ""), reverse=True)  # stable: newest day first, best fit first
    output.write(path, headers, rows, SHEET)
    return len(new)
