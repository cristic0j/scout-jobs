"""matches.xlsx ⇄ Google Sheet sync, against a fake sheet (no network)."""
import pytest

from jobsearch import cloud, matches, output


class FakeTab:
    def __init__(self):
        self.values, self.row_count, self.col_count, self.id = [], 100, 20, 0
        self.spreadsheet = self
        self.fail_read = False

    def get_all_values(self):
        if self.fail_read:
            raise ConnectionError("offline")
        return [list(r) for r in self.values if any(str(v) != "" for v in r)]

    def resize(self, rows=None, cols=None):
        self.row_count, self.col_count = rows or self.row_count, cols or self.col_count

    def update(self, values, start, value_input_option):
        self.values = [["TRUE" if v is True else "FALSE" if v is False else str(v) for v in r] for r in values]

    def batch_update(self, body):
        pass

    # helpers for the tests
    def rows(self):
        return cloud.pull(self)[1]

    def edit(self, title, column, value):
        head = self.values[0]
        for r in self.values[1:]:
            if r[head.index("Job title")] == title:
                r[head.index(column)] = value

    def delete(self, title):
        ti = self.values[0].index("Job title")
        self.values = [r for r in self.values if r[ti] != title]


@pytest.fixture
def sheet(tmp_path, monkeypatch):
    tab = FakeTab()
    monkeypatch.setattr(cloud, "tab_for", lambda path: tab)
    path = tmp_path / "matches.xlsx"
    cloud.save_config(path, sheet="x" * 30)
    return path, tab


def match(title, fit=8, found="2026-10-25"):
    return {"Found": found, "Fit (1-10)": fit, "Job title": title, "Company": f"{title} BV",
            "Link": f"https://x/{title}"}


def local(path):
    return {r["Job title"]: r for r in output.read(path, matches.SHEET, matches.COLUMNS)[1]}


def test_matches_go_online_with_applied_column(sheet):
    path, tab = sheet
    matches.add([match("A"), match("B")], path)
    assert tab.values[0][0] == "Applied"
    assert {r["Job title"]: r["Applied"] for r in tab.rows()} == {"A": "FALSE", "B": "FALSE"}


def test_tick_online_survives_a_local_save(sheet):
    path, tab = sheet
    matches.add([match("A"), match("B")], path)
    tab.edit("A", "Applied", "TRUE")
    matches.add([match("C"), match("A", fit=9)], path)  # the matcher re-scores A and finds C
    assert local(path)["A"]["Applied"] is True and local(path)["A"]["Fit (1-10)"] == 9
    assert {r["Job title"]: r["Applied"] for r in tab.rows()} == {"A": "TRUE", "B": "FALSE", "C": "FALSE"}


def test_sync_brings_ticks_in_without_changes(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    tab.edit("A", "Applied", "TRUE")
    matches.sync(path)
    assert local(path)["A"]["Applied"] is True


def test_deleted_online_stays_deleted(sheet):
    path, tab = sheet
    matches.add([match("A"), match("B")], path)
    tab.delete("A")
    matches.sync(path)
    assert set(local(path)) == {"B"}
    assert matches.add([match("A")], path) == 0  # the matcher finds it again: not re-added
    assert {r["Job title"] for r in tab.rows()} == {"B"}


def test_program_columns_come_from_local_user_columns_from_sheet(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    tab.values[0].append("Notes")
    tab.values[1].append("called them")
    tab.edit("A", "Fit (1-10)", "2")  # program column edited online: local wins
    matches.add([match("B")], path)
    assert local(path)["A"]["Notes"] == "called them" and local(path)["A"]["Fit (1-10)"] == 8


def test_row_added_online_is_kept(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    head = tab.values[0]
    tab.values.append(["TRUE" if h == "Applied" else "Mine" if h == "Job title" else "" for h in head])
    matches.sync(path)
    assert local(path)["Mine"]["Applied"] is True
    assert {r["Job title"] for r in tab.rows()} == {"A", "Mine"}


def test_spare_checkbox_rows_are_not_jobs(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    width = len(tab.values[0])
    tab.values = [r for r in tab.values if any(r)] + [["FALSE"] + [""] * (width - 1)] * 10  # rows you added
    tab.row_count = len(tab.values)
    matches.sync(path)
    assert set(local(path)) == {"A"} and {r["Job title"] for r in tab.rows()} == {"A"}
    assert tab.row_count == 12  # your spare rows stay


def test_offline_saves_locally_and_never_overwrites_the_sheet(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    tab.edit("A", "Applied", "TRUE")
    tab.fail_read = True
    matches.add([match("B")], path)
    assert set(local(path)) == {"A", "B"}
    assert tab.values[1][0] == "TRUE" and len([r for r in tab.values if any(r)]) == 2  # sheet untouched
    tab.fail_read = False
    matches.sync(path)  # back online: catches up, tick kept
    assert local(path)["A"]["Applied"] is True and {r["Job title"] for r in tab.rows()} == {"A", "B"}


def test_removed_by_matcher_leaves_the_sheet(sheet):
    path, tab = sheet
    matches.add([match("A"), match("B")], path)
    matches.remove(["https://x/A"], path)
    assert {r["Job title"] for r in tab.rows()} == {"B"}
    matches.sync(path)
    assert set(local(path)) == {"B"}


def test_empty_sheet_deletes_nothing(sheet):
    path, tab = sheet
    matches.add([match("A")], path)
    tab.values = []  # sheet wiped by hand
    matches.sync(path)
    assert set(local(path)) == {"A"} and {r["Job title"] for r in tab.rows()} == {"A"}


def test_not_connected_is_local_only(tmp_path):
    path = tmp_path / "matches.xlsx"
    matches.add([match("A")], path)
    assert set(local(path)) == {"A"} and not (tmp_path / "cloud.json").exists()


def test_sheet_id_from_link():
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    assert cloud.sheet_id(f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0") == sid
    assert cloud.sheet_id(sid) == sid and cloud.sheet_id("hello") == ""
