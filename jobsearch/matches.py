"""<search>/matches.xlsx: the jobs the matcher found to fit. One row per job (by link, or by the same title
at a similarly spelled company), and any columns you add yourself (e.g. Applied?) are kept."""
from . import output

SHEET = "Matches"
COLUMNS = ["Found", "Fit (1-10)", "Job title", "Company", "Location", "Work mode", "Travel", "Posted",
           "Why it fits", "Caveats", "CV", "Profile", "Link"]


def _write(path, headers, rows):
    rows.sort(key=lambda r: int(r.get("Fit (1-10)") or 0), reverse=True)
    rows.sort(key=lambda r: str(r.get("Found") or ""), reverse=True)  # stable: newest day first, best fit first
    output.write(path, headers, rows, SHEET)


def add(entries, path):
    """Insert or update matches ({column: value}); an update keeps Found and your own columns.
    Returns how many were new."""
    if not entries:
        return 0
    headers, rows = output.read(path, SHEET, COLUMNS)
    by_link = {r.get("Link"): r for r in rows}
    by_key = {output.fuzzy_key(r.get("Company"), r.get("Job title")): r for r in rows}
    new = 0
    for e in entries:
        row = by_link.get(e.get("Link")) or by_key.get(output.fuzzy_key(e.get("Company"), e.get("Job title")))
        if row is None:
            row = {}
            rows.append(row)
            new += 1
        else:
            e = {k: v for k, v in e.items() if k != "Found"}
        row.update(e)
        by_link[row.get("Link")] = row
        by_key[output.fuzzy_key(row.get("Company"), row.get("Job title"))] = row
    _write(path, headers, rows)
    return new


def remove(links, path):
    """Drop matches for these links (they were re-scored below the threshold). Returns how many went."""
    links = set(links)
    if not links or not path.exists():
        return 0
    headers, rows = output.read(path, SHEET, COLUMNS)
    kept = [r for r in rows if r.get("Link") not in links]
    if len(kept) != len(rows):
        _write(path, headers, kept)
    return len(rows) - len(kept)
