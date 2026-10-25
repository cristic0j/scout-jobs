from jobsearch import output
from jobsearch.models import Job


def make(title, link, posted="2026-10-20", lang=""):
    j = Job("Test", title, "Acme", "Amsterdam", posted, link)
    j.level, j.lang = "medior", lang
    return j


def test_merge_keeps_processed_and_first_seen(tmp_path):
    path = tmp_path / "r.xlsx"
    headers, rows = output.read(path)
    rows, added = output.merge(rows, [make("A", "https://x/a", lang="English"), make("B", "https://x/b")],
                               "2026-10-24")
    assert added == 2
    rows[0]["Processed"] = "x"
    headers.append("AI fit")  # a column the later AI step might add
    rows[0]["AI fit"] = "good"
    output.write(path, headers, rows)

    headers, rows = output.read(path)
    rows, added = output.merge(rows, [make("A", "https://x/a"), make("B", "https://x/b"),
                                      make("C", "https://x/c", posted="2026-10-25")], "2026-10-25")
    output.write(path, headers, rows)
    headers, rows = output.read(path)

    assert added == 1 and len(rows) == 3
    by_title = {r["Job title"]: r for r in rows}
    processed = [r for r in rows if r["Processed"]][0]
    assert processed["First seen"] == "2026-10-24" and processed["Last seen"] == "2026-10-25"
    assert processed["AI fit"] == "good"
    assert by_title["A"]["Language"] == "English"  # not wiped by a run without the Dutch check
    assert by_title["C"]["First seen"] == "2026-10-25" and by_title["C"]["Processed"] == ""
    assert rows[-1] is processed  # unprocessed rows first
    assert rows[0]["Job title"] == "C"  # newest unprocessed on top


def test_merge_falls_back_to_company_title():
    rows = [{"Processed": "x", "First seen": "2026-10-01", "Company": "Acme", "Job title": "A",
             "Link": "https://old/a"}]
    rows, added = output.merge(rows, [make("A", "https://new/a")], "2026-10-25")
    assert added == 0 and len(rows) == 1 and rows[0]["Link"] == "https://new/a"
