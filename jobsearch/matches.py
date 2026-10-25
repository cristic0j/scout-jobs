"""<search>/matches.xlsx: the jobs the matcher found to fit. One row per job (by link, or by the same title
at a similarly spelled company), and any columns you add yourself are kept. Tick Applied when you apply.
When a Google Sheet is connected (cloud.py), every save syncs with it first."""
from . import cloud, output

SHEET = "Matches"
COLUMNS = [cloud.APPLIED, "Found", "Fit (1-10)", "Job title", "Company", "Location", "Work mode", "Travel", "Posted",
           "Why it fits", "Caveats", "CV", "Profile", "Link"]


def collapse(rows):
    """One row per job: later duplicates (same link, or same title at a similarly spelled company) only
    fill in what the first row is missing, so your own columns survive."""
    out, by_link, by_key = [], {}, {}
    for r in rows:
        key = output.fuzzy_key(r.get("Company"), r.get("Job title"))
        first = by_link.get(r.get("Link")) or by_key.get(key)
        if first is None:
            out.append(r)
            by_link[r.get("Link")], by_key[key] = r, r
        else:
            first.update({k: v for k, v in r.items() if v not in ("", None) and first.get(k) in ("", None)})
    return out


def fit(row):
    try:
        return int(row.get("Fit (1-10)") or 0)
    except (TypeError, ValueError):
        return 0


def _save(path, headers, rows):
    rows = collapse(rows)
    rows.sort(key=fit, reverse=True)
    rows.sort(key=lambda r: str(r.get("Found") or ""), reverse=True)  # stable: newest day first, best fit first
    headers = COLUMNS + [h for h in headers if h and h not in COLUMNS]
    output.write(path, headers, rows, SHEET)
    return headers, rows


def _write(path, headers, rows):
    """Save, syncing with the Google Sheet first when one is connected."""
    status = cloud.sync(path, headers, rows, [c for c in COLUMNS if c != cloud.APPLIED],
                        lambda h, r: _save(path, h, r))
    if status:
        print(f"  {status}")


def sync(path):
    """Sync with the Google Sheet even when nothing changed here (brings your ticks and deletions in)."""
    if cloud.connected(path):
        _write(path, *output.read(path, SHEET, COLUMNS))


def add(entries, path):
    """Insert or update matches ({column: value}); an update keeps Found and your own columns.
    Jobs you deleted from the Google Sheet are not added again. Returns how many were new."""
    deleted = cloud.deleted_keys(path)
    entries = [e for e in entries if not cloud.is_deleted(e, deleted)]
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
