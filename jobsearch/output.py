"""The results workbook: one `Jobs` sheet per profile, merged in place on every run.

Rows are matched by link (company+title as fallback). `Processed` and `First seen` are never
touched once a row exists, so a later reviewer (the AI step) can mark rows and keep its work.
Unknown columns (added by that reviewer) are kept as they are.
"""
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import travel

TRACKER = Path.home() / "Desktop/Jobs/jobs.xlsx"
SHEET = "Jobs"
COLUMNS = ["Processed", "First seen", "Last seen", "Already in tracker", "Posted", "Job title", "Company",
           "Location", "Work mode", "Travel", "Level", "Language", "Source", "Link"]
WIDTHS = {"Processed": 11, "First seen": 11, "Last seen": 11, "Already in tracker": 10, "Posted": 11,
          "Job title": 50, "Company": 24, "Location": 30, "Work mode": 10, "Travel": 9, "Level": 11, "Language": 14,
          "Source": 11, "Link": 60, "AI fit": 7, "AI verdict": 10, "AI reason": 60,
          "Found": 11, "Fit (1-10)": 9, "Why it fits": 60, "Caveats": 40, "CV": 24, "Profile": 18}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def job_key(company, title):
    return norm(company) + "|" + norm(title)


def fuzzy_key(company, title):
    """Same posting from two sources often spells the company differently (Vinted / Vinteden)."""
    return norm(title) + "|" + norm(company)[:5]


def tracked_keys():
    """(company+title) keys and links already in Cristian's tracker, any sheet. Read only."""
    keys, links = set(), set()
    if not TRACKER.exists():
        return keys, links
    wb = openpyxl.load_workbook(TRACKER, read_only=True)
    for ws in wb:
        rows = ws.iter_rows(values_only=True)
        head = [str(h or "") for h in next(rows, [])]
        try:
            ti, ci, li = head.index("Job title"), head.index("Company"), head.index("Link")
        except ValueError:
            continue
        for row in rows:
            if row[ti]:
                keys.add(job_key(row[ci], row[ti]))
            if row[li]:
                links.add(str(row[li]).split("?")[0])
    return keys, links


def job_fields(j):
    """Columns refreshed from the latest fetch. Language only when it was checked this run."""
    out = {"Already in tracker": "yes" if j.tracked else "", "Posted": j.posted, "Job title": j.title,
           "Company": j.company, "Location": j.location, "Work mode": j.work_mode, "Travel": travel.text(j.travel),
           "Level": j.level, "Source": j.source, "Link": j.link}
    if j.lang:
        out["Language"] = j.lang
    return out


def merge(rows, jobs, today):
    """Merge fetched jobs into existing rows (list of {column: value}). Returns (rows, added)."""
    by_link = {r["Link"]: r for r in rows if r.get("Link")}
    by_key = {job_key(r.get("Company"), r.get("Job title")): r for r in rows}
    added = 0
    for j in jobs:
        row = by_link.get(j.link) or by_key.get(job_key(j.company, j.title))
        if row is None:
            row = {c: "" for c in COLUMNS}
            row["First seen"] = today
            rows.append(row)
            added += 1
        row.update(job_fields(j))
        row["Last seen"] = today
        by_link[row["Link"]] = row
        by_key[job_key(row["Company"], row["Job title"])] = row
    rows.sort(key=lambda r: str(r.get("Posted") or ""), reverse=True)
    rows.sort(key=lambda r: bool(r.get("Processed")))  # stable: unprocessed first, newest first within
    return rows, added


def read(path, sheet=SHEET, columns=COLUMNS):
    """(headers, rows) from the sheet, or (columns, []) for a new file."""
    if not path.exists():
        return list(columns), []
    ws = openpyxl.load_workbook(path)[sheet]
    it = ws.iter_rows(values_only=True)
    head = [str(h) if h is not None else "" for h in next(it, [])]
    rows = [{h: ("" if v is None else v) for h, v in zip(head, r) if h} for r in it if any(v is not None for v in r)]
    return head + [c for c in columns if c not in head], rows


def write(path, headers, rows, sheet=SHEET):
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    headers = [h for h in headers if h]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(h, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)  # never leave a half-written results file
