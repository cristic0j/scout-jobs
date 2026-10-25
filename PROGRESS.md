# Job search agent — progress & roadmap

Goal: give it a CV, let an agent work out which jobs fit, ask only what it can't tell, fetch those jobs
every 5 hours, and have a second agent put the genuinely fitting new jobs in a matches file.

Related: the manual playbook and tracker live in `~/Desktop/Jobs` (`JOB_SEARCH.md`, `jobs.xlsx`).
The code only **reads** `jobs.xlsx` (to skip jobs already tracked); it never writes it.

## How it works
Every search has its own folder, `searches/<name>/` (gitignored): `cv/`, `preferences.json`,
`profiles/<role>.json`, `results/<role>.xlsx`, `matches.xlsx`, `state.json`, `travel.json`.
```
python3 -m jobsearch              menu: pick a search or "New search" (asks a name, makes the folder,
                                  waits for the CV, warns if that CV is already used in another search)
  new / CV changed → planner agent (Gemini): roles + preferences, asks only what's missing
                     (work setup always: on-site towns, hybrid max travel time, max office days)
  existing        → Run now · Change preferences · Re-plan roles · Review · Re-score · Manual profile
python3 -m jobsearch run          every search (or --search NAME): fetch → filter (incl. travel time for
                                  hybrid) → merge → matcher on unprocessed rows only → matches.xlsx
python3 -m jobsearch review [--rescore]   matcher only; --rescore re-filters + re-judges all rows
python3 -m jobsearch list         searches and their roles
```
Matcher limits are enforced in code: a job that breaks the work setup, or needs more office days than
allowed away from home → fit ≤ 4, "no". Asking clearly more experience than the CV shows → fit ≤ 6.

Needs `GEMINI_API_KEY` in `~/.zshrc` (`gemini-3.8-flash`, falling back to 3.6-flash / 3.5-flash-lite when busy;
override with `GEMINI_MODEL`). `fetch_nl_jobs.py` still works and is the same as `python3 -m jobsearch`.

## Done
**2026-10-24**: single-script NL fetcher (LinkedIn guest search, Arbeitnow, Greenhouse/Lever/Ashby/Recruitee
boards, Jooble, Adzuna), role/seniority/age filters, Dutch-language detection with description cache.

**2026-10-25**
- Refactored into the `jobsearch/` package: `sources/` (one module per source), `filters.py`, `detect.py`,
  `matching.py`, `profile.py`, `presets.py`, `output.py`, `pipeline.py`, `questions.py`, `cli.py`.
- Searches are fully configurable per profile: job category presets (software, data, design, marketing,
  sales, support, finance, HR, operations, custom), search terms, title include/exclude keywords,
  seniority (internship/junior/medior/senior), max age, work mode, Dutch filter, location, sources, boards.
- Hybrid feature finished as a general work-mode filter (hybrid/remote/on-site + keep-unknown option).
  Verified on a real run; tightened the description regex after spot-checking ("hybrid approach",
  "hybride cloudomgevingen" were false positives).
- Results: one `Jobs` sheet per profile, merged in place by link. `Processed`/`First seen` are never
  overwritten, unknown columns are kept, unprocessed rows are sorted first.
- Agents (Gemini): `agents/planner.py` (CV → roles, preferences, open questions), `agents/matcher.py`
  (unprocessed rows, batches of 8, full descriptions, max 60 per profile per run, tracked rows skipped
  without a call), `matches.py`. Runs with no unprocessed rows make no Gemini call.
- First real run with the CV (3 roles, 94 jobs). Then: one folder per search, hybrid by max travel time
  (Gemini estimates, cached), matcher limits enforced in code, verdicts reused across roles, fuzzy
  duplicate merging, re-score. Re-scored real matches: 35 → 11, all inside the user's rules.
- Background runs: one launchd agent (`com.jobsearch.tick`) wakes every 15 min and at login; each search
  has its own interval and runs when due, once after sleep (no pile-up). Failed runs retry with backoff
  (30 min, 1 h, 2 h …), offline ticks don't count, one run at a time (lock), log in `logs/jobsearch.log`.
  Keys are read from the `export` lines in `~/.zshrc` (never copied into the plist).
- Notifications: Mac banner + phone push via ntfy, fit threshold, quiet hours (queued, then one summary),
  problem alerts (a source failing 3 runs in a row, runs failing, missing key).
- 61 tests (`pytest tests/`), agents and launchd tested with fakes; agent install verified on macOS.

## Background runs & notifications
```
python3 -m jobsearch                              menu → search → "Automatic runs" / "Run now in the background"
                                                  menu → "Notifications" (Mac, phone/ntfy, fit, quiet hours)
python3 -m jobsearch schedule --search NAME --every 5h    (or --every off; no args = status)
python3 -m jobsearch notify --test
python3 -m jobsearch tick [--force --search NAME]         what the agent runs
```

## Next steps
1. Optional: Telegram bot with Applied / Not interested buttons that write back into matches.xlsx.
2. Optional: board slugs per category (current boards are tech companies).
3. Optional: email digest (daily/weekly).
