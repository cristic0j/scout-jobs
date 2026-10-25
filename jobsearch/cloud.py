"""Google Sheets copy of <search>/matches.xlsx, so you can tick "Applied" from anywhere.

Before matches.xlsx is saved, the sheet is read and your edits come back: the Applied ticks, any column you
added, rows you added, and rows you deleted (those stay deleted: the matcher won't add them again). Then the
local file is saved and the whole table is written back to the sheet. The program's own columns (fit,
reasons, location, ...) always come from the local file.

If the sheet can't be read (offline, Google down), only the local file is saved and nothing is written to the
sheet, so a tick made online is never overwritten. The next save catches up.

Login is a Google service account (no browser, so the background runs work too). Its key lives outside the
repo: any .json key file in KEY_DIR, whatever Google named it; the sheet must be shared with the account's email. <search>/cloud.json holds the sheet id, the
rows last written to it and the rows you deleted.
"""
import json
import re
from pathlib import Path

from . import output

KEY_DIR = Path.home() / ".config/jobsearch"
TAB = "Matches"
APPLIED = "Applied"


class Unavailable(Exception):
    """No key, not connected, or Google couldn't be reached."""


def config_path(matches_path):
    return matches_path.parent / "cloud.json"


def config(matches_path):
    p = config_path(matches_path)
    return json.loads(p.read_text()) if p.exists() else {}


def save_config(matches_path, **changes):
    p = config_path(matches_path)
    p.write_text(json.dumps({**config(matches_path), **changes}, indent=2) + "\n")


def connected(matches_path):
    return bool(config(matches_path).get("sheet"))


def sheet_url(matches_path):
    sid = config(matches_path).get("sheet")
    return f"https://docs.google.com/spreadsheets/d/{sid}" if sid else ""


def sheet_id(text):
    """The id from a sheet link (or the id itself)."""
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", text) or re.fullmatch(r"\s*([A-Za-z0-9_-]{20,})\s*", text)
    return m.group(1) if m else ""


def _read(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def key():
    """The service-account key file in KEY_DIR, or None."""
    found = [p for p in sorted(KEY_DIR.glob("*.json")) if _read(p).get("type") == "service_account"]
    return found[0] if found else None


def account_email():
    return _read(key()).get("client_email", "") if key() else ""


def checked(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "y", "x", "1", "✓", "✔")


def deleted_keys(matches_path):
    return set(config(matches_path).get("deleted", []))


def ident(row):
    return row.get("Link") or output.fuzzy_key(row.get("Company"), row.get("Job title"))


def is_deleted(row, deleted):
    return row.get("Link") in deleted or output.fuzzy_key(row.get("Company"), row.get("Job title")) in deleted


# --- Google ---

def open_tab(sid):
    """The Matches tab of the sheet (created if missing). Raises Unavailable."""
    if not key():
        raise Unavailable(f"no Google key file in {KEY_DIR}")
    try:
        import gspread
        book = gspread.service_account(filename=str(key())).open_by_key(sid)
        try:
            return book.worksheet(TAB)
        except gspread.WorksheetNotFound:
            tabs = book.worksheets()
            if len(tabs) == 1 and not any(tabs[0].get_all_values()):  # a new, empty sheet: use its first tab
                tabs[0].update_title(TAB)
                return tabs[0]
            return book.add_worksheet(TAB, rows=100, cols=20)
    except Unavailable:
        raise
    except Exception as e:
        raise Unavailable(f"{e.__class__.__name__}: {str(e)[:200]}") from e


def tab_for(matches_path):
    sid = config(matches_path).get("sheet")
    if not sid:
        raise Unavailable("not connected")
    return open_tab(sid)


def pull(ws):
    """(headers, rows) in the sheet. Rows with nothing but a checkbox (spare rows you added) are skipped."""
    values = ws.get_all_values()
    if not values:
        return [], []
    head = [h.strip() for h in values[0]]
    rows = [{h: v for h, v in zip(head, r) if h} for r in values[1:]]
    return [h for h in head if h], [r for r in rows if any(str(v).strip() for h, v in r.items() if h != APPLIED)]


def push(ws, headers, rows):
    """Write the whole table in one update, padded with blanks over what was there (so a failure halfway can't
    leave the sheet empty, and spare rows you added stay), and style it: bold frozen header, filter, Applied as
    checkboxes on every row."""
    values = [headers] + [[cell(h, r.get(h, "")) for h in headers] for r in rows]
    height, width = max(len(values), ws.row_count), max(len(headers), ws.col_count)
    if ws.row_count < height or ws.col_count < width:
        ws.resize(rows=height, cols=width)
    padded = [v + [""] * (width - len(v)) for v in values] + [[""] * width] * (height - len(values))
    ws.update(padded, "A1", value_input_option="RAW")
    if width > len(headers):
        ws.resize(cols=len(headers))  # columns nobody uses any more
    ws.spreadsheet.batch_update({"requests": style(ws.id, headers, height)})


def cell(header, v):
    if header == APPLIED:
        return checked(v)
    return v if isinstance(v, (int, float, bool)) else str(v)


def style(tab_id, headers, nrows):
    whole = {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": max(nrows, 2),
             "startColumnIndex": 0, "endColumnIndex": len(headers)}
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": tab_id, "gridProperties": {"frozenRowCount": 1}},
                                       "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {**whole, "endRowIndex": 1}, "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}},
            {"setBasicFilter": {"filter": {"range": whole}}}]
    for i, h in enumerate(headers):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": tab_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": output.WIDTHS.get(h, 16) * 7}, "fields": "pixelSize"}})
    if APPLIED in headers:
        col = headers.index(APPLIED)
        reqs.append({"setDataValidation": {
            "range": {**whole, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {"condition": {"type": "BOOLEAN"}}}})
    return reqs


# --- merging ---

def merge(headers, rows, cloud_headers, cloud_rows, synced, deleted, own_columns):
    """Bring the sheet's edits into the local rows. Returns (headers, rows, deleted).

    synced: rows (ident) written to the sheet last time. A synced row missing from the sheet was deleted there; a
    sheet row the program doesn't know (and never wrote) was added there."""
    if "Link" not in cloud_headers:  # empty or unrecognisable sheet: nothing to take from it
        return headers, rows, deleted
    deleted = set(deleted)
    by_link = {r.get("Link"): r for r in cloud_rows if r.get("Link")}
    by_key = {output.fuzzy_key(r.get("Company"), r.get("Job title")): r for r in cloud_rows}
    used, kept = set(), []
    for r in rows:
        online = by_link.get(r.get("Link")) or by_key.get(output.fuzzy_key(r.get("Company"), r.get("Job title")))
        if online is None:
            if ident(r) in synced:
                deleted |= {r.get("Link"), output.fuzzy_key(r.get("Company"), r.get("Job title"))}
                continue
        else:
            used.add(id(online))
            for h, v in online.items():
                if h == APPLIED:
                    r[h] = True if checked(v) else ""
                elif h not in own_columns:
                    r[h] = v
        kept.append(r)
    added = [r for r in cloud_rows if id(r) not in used and ident(r) not in synced]
    for r in added:
        if APPLIED in r:
            r[APPLIED] = True if checked(r[APPLIED]) else ""
    headers = list(headers) + [h for h in cloud_headers if h not in headers]
    return headers, kept + added, deleted - {""}


def sync(matches_path, headers, rows, own_columns, write_local):
    """Pull → merge → write_local(headers, rows) → push. Without the sheet, only write_local.
    Returns a short status for the log, or "" when not connected."""
    if not connected(matches_path):
        write_local(headers, rows)
        return ""
    cfg = config(matches_path)
    try:
        ws = tab_for(matches_path)
        cloud_headers, cloud_rows = pull(ws)
    except Exception as e:
        write_local(headers, rows)
        return f"Google Sheets not synced ({e}); saved locally, will sync next time."
    headers, rows, deleted = merge(headers, rows, cloud_headers, cloud_rows, set(cfg.get("synced", [])),
                                   set(cfg.get("deleted", [])), own_columns)
    headers, rows = write_local(headers, rows)
    save_config(matches_path, deleted=sorted(deleted))
    try:
        push(ws, headers, rows)
    except Exception as e:
        return f"Google Sheets not updated ({e.__class__.__name__}: {str(e)[:200]}); will sync next time."
    save_config(matches_path, synced=sorted({ident(r) for r in rows}))
    return f"Google Sheets synced ({len(rows)} matches)."
