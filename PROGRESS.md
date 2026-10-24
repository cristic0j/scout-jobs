# NL job fetcher — progress & roadmap

Goal: automatically find software engineering jobs in the Netherlands that fit Cristian,
and get notified only about the ones that truly fit.

Related: the manual job-search playbook and tracker live in `~/Desktop/Jobs`
(`JOB_SEARCH.md`, `jobs.xlsx`). This script only **reads** `jobs.xlsx`; it never writes it.

## Done (2026-10-24)

`fetch_nl_jobs.py` — one script that pulls NL postings into `nl_jobs.xlsx`
(one sheet per day, `NL YYYY-MM-DD`, newest first).

**Sources**
| Source | Key | Notes |
|---|---|---|
| LinkedIn guest search | none | Most results (~210/run). Sleeps between requests to avoid HTTP 429. |
| Arbeitnow | none | Has many arbeitnow.nl postings. Occasionally returns non-JSON (rate limit), just rerun. |
| Greenhouse / Lever / Ashby / Recruitee company boards | none | Slugs in `BOARDS` at the top of the script (26 companies). Add more freely. |
| Jooble | `JOOBLE_KEY` (in `~/.zshrc`) | Key only works on international jooble.org, few NL results. `nl.jooble.org` rejects the key. |
| Adzuna | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Not free for us, skipped automatically when keys are unset. |

**Filters**
- Roles: software engineering, full-stack, backend, frontend, web, mobile/Android, Java, Kotlin, .NET, etc. (`SEARCH_TERMS`, `TECH`).
- Dropped: any title mentioning Python, data/analytics, QA/test, support, sales, electrical/mechanical (`NOT_SWE`).
- Dropped: senior/lead/staff/manager titles unless `--all`.
- Max age `--days` (default 30).
- Dedup by company+title; marks `Already in tracker` (vs `jobs.xlsx`) and `New since last run`.

**Dutch-only filter** — done but opt-in (`--dutch-filter`) because it is slow on the first run:
it opens every LinkedIn posting (~1.2 s each) to read the description. Descriptions are cached in
`.desc_cache.json` (209 cached), so later runs only fetch new ones. Labels: `Dutch` (posting
written in Dutch), `Dutch required`, `English`. Spot-checked: "Dutch is a plus" / "no Dutch
required" are correctly treated as English. Last full run: 253 jobs → 125 English, 116 Dutch,
12 Dutch required.

**Usage**
```
python3 fetch_nl_jobs.py                 # fast, all matching jobs
python3 fetch_nl_jobs.py --days 7
python3 fetch_nl_jobs.py --all           # include senior titles
python3 fetch_nl_jobs.py --no-linkedin   # seconds, but far fewer jobs
python3 fetch_nl_jobs.py --dutch-filter  # drop Dutch-only jobs
python3 fetch_nl_jobs.py --hybrid        # (in progress, see below)
```

Note: `nl_jobs.xlsx` is not in the folder right now (generated, not committed); the next run recreates it.

## Next steps (in order)

### 1. Refactor
Split the single script into a small package so new sources/filters are easy to add:
- `sources/` — one module per source, each returning a common `Job` dataclass
  (title, company, location, posted, link, work_mode, desc, source).
- `filters.py` — role/seniority/age/Python/Dutch/hybrid filters as composable functions.
- `config` (YAML or TOML) — search terms, board slugs, regexes, defaults, instead of constants in code.
- `output.py` — Excel writer + dedup/"new since last run" state (move state to a small JSON/SQLite file
  instead of re-reading the xlsx).
- Tests for the language and work-mode detectors with saved sample postings.

### 2. Finish the hybrid feature
Code is written but **not yet run or verified**:
- `--hybrid` flag keeps only hybrid jobs; column renamed `Remote` → `Work mode`.
- Work mode from structured fields: Ashby `workplaceType`, Lever `workplaceType`,
  Recruitee `hybrid`/`remote`/`on_site`.
- LinkedIn: adds `f_WT=3` to the search when `--hybrid` (LinkedIn's hybrid tag is often wrong).
- Others (Greenhouse, Arbeitnow, Jooble): regex `HYBRID` on title/location/description
  ("hybrid", "hybride", "N days in the office").
- To do: run it, spot-check results, decide whether jobs with unknown work mode should be kept.

### 3. Run every 5 hours
Schedule the fetch (launchd on macOS, or a Claude Code scheduled routine) so `nl_jobs.xlsx` always has the newest jobs.
Needs `JOOBLE_KEY` in the job's environment (launchd doesn't read `~/.zshrc`).

### 4. AI agent that keeps only truly fitting jobs
After each fetch, an agent reads the new jobs (with descriptions) and scores them against
Cristian's profile (`~/Desktop/Jobs/JOB_SEARCH.md`: junior/medior, no Dutch, Android/Kotlin/Java/full-stack,
lives in Maastricht). Returns only genuine fits with a short reason. Never invent links or dates.

### 5. MCP tools for the agent
- Tool to append the fitting new jobs to a file (e.g. a `Fits` sheet / jobs file).
- Tool to send a notification (e.g. macOS notification / push) when something new is found.
