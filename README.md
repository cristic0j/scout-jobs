# Job search agent

Give it your CV. It works out which roles fit you, asks only what it can't tell from the CV, fetches matching
jobs on a schedule, and has an AI matcher put the jobs that really fit into a matches sheet, locally and
(optionally) in Google Sheets, where you tick the ones you applied to.

Built for job hunting in the Netherlands: the job sources, town lists and Dutch-language filter assume it.
Other countries partly work (LinkedIn, Jooble and Adzuna take any location).

## How it works

```
CV ──► planner (Gemini) ──► roles, search terms, preferences   (asks only what the CV doesn't answer)
                               │
              every few hours  ▼
job sources ──► filters ──► results/<role>.xlsx ──► matcher (Gemini) ──► matches.xlsx ⇄ Google Sheet
```

- **Planner** reads the CV and proposes roles with search terms and title filters, plus your preferences:
  levels, languages, and your work setup (towns for on-site work, maximum travel time for hybrid, maximum
  office days). You confirm or change everything.
- **Sources**: LinkedIn (public guest search), Arbeitnow, company boards on Greenhouse / Lever / Ashby /
  Recruitee, and optionally Jooble and Adzuna (free API keys).
- **Filters**: title keywords, seniority, posting age, work mode, Dutch-only postings, travel time from home
  for hybrid jobs (estimated once per place by Gemini, then cached), and jobs already in your own tracker.
- **Matcher** reads the full description of every new job and scores it 1-10 against your CV. Only new jobs
  are judged, so a run without new jobs costs no Gemini calls. Some limits are enforced in code, not left
  to the model:
  - a job that breaks your work setup, or needs more office days than you allow, gets fit ≤ 4;
  - a job asking clearly more experience than your CV shows gets fit ≤ 6;
  - technologies on your avoid list as the main stack cap the fit too.

  Jobs at or above your threshold (default 7) go to `matches.xlsx`.

## Setup

Python 3.10+.

```sh
pip install -r requirements.txt
```

Add your [Gemini API key](https://aistudio.google.com/apikey) to `~/.zshrc`. Background runs read the
`export` lines from there (the file is never executed, and keys are never copied elsewhere):

```sh
export GEMINI_API_KEY=...
```

Optional:

| Variable | What |
|---|---|
| `GEMINI_MODEL` | model to use first (default `gemini-3.8-flash`; falls back to `gemini-3.6-flash`, then `gemini-3.5-flash-lite` when busy) |
| `JOOBLE_KEY` | enables the Jooble source |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | enable the Adzuna source |
| `JOBSEARCH_TRACKER` | your own application tracker (.xlsx with `Job title`, `Company`, `Link` columns). Jobs in it are marked and skipped. Only read, never written. |
| `JOBSEARCH_NOTES` | your own job-search notes (text/markdown). The planner uses them to suggest answers. |

Paths may start with `~`, e.g. `export JOBSEARCH_TRACKER=~/Documents/jobs.xlsx`.

## Use

```sh
python3 -m jobsearch
```

The menu walks you through it:

1. **New search**: give it a name and drop your CV (PDF, one file per version) in the folder it opens.
2. The **planner** proposes roles and preferences and asks what's missing.
3. **Run now** fetches, filters and matches. Good fits land in `searches/<name>/matches.xlsx`.
4. **Automatic runs** keeps it going in the background (e.g. every 5 hours), with notifications for new
   matches.
5. **Google Sheets** puts the matches online (see below).

From the command line:

```sh
python3 -m jobsearch run [--search NAME] [--profile ROLE]     fetch + review new jobs
python3 -m jobsearch review [--search NAME] [--rescore]       review only (--rescore: judge everything again)
python3 -m jobsearch setup --search NAME                      re-plan roles from the CV
python3 -m jobsearch list                                     searches and their roles
python3 -m jobsearch schedule --search NAME --every 5h        automatic runs (--every off to stop)
python3 -m jobsearch schedule                                 status of all searches
python3 -m jobsearch notify --test                            send a test notification
```

## Where things are

Each search has its own folder, `searches/<name>/`. It holds your CV and is never committed.

| File | What |
|---|---|
| `cv/` | your CV versions |
| `preferences.json`, `profiles/<role>.json` | what to search for and how to judge it |
| `results/<role>.xlsx` | every job found per role, with the matcher's score (`Processed` marks reviewed rows) |
| `matches.xlsx` | the jobs that fit, newest and best first, with an **Applied** column |
| `cloud.json` | the Google Sheet it syncs with |
| `state.json`, `travel.json` | last run, CV fingerprint, cached travel times |

Logs of background runs: `logs/jobsearch.log`.

## Matches in Google Sheets

One-time setup (menu → your search → **Google Sheets**, which shows these steps too):

1. In [Google Cloud Console](https://console.cloud.google.com) create a project, enable the
   **Google Sheets API**, create a **service account** and download a **JSON key** for it.
2. Put the key file (any name) in `~/.config/jobsearch/`. Keep it private: it gives access to the sheet.
3. Create an empty Google Sheet and share it, as **Editor**, with the service account's email
   (the menu shows it).
4. Paste the sheet's link in the menu. Your matches are uploaded.

How the sync works: every time matches are saved, and at the end of every run, the sheet is read first.

- **Applied** ticks and any columns or rows you add in the sheet come back into `matches.xlsx`.
- **Deleting a row** in the sheet drops that job for good: the matcher won't add it again.
- The program's own columns (fit, reasons, location, ...) always come from the local file, so editing them
  online has no effect. Sorting in the sheet resets on each sync.
- **Offline**: only the local file is saved and the sheet isn't touched, so nothing you ticked online is lost.
  The next sync catches up.

## Background runs (macOS)

One launchd agent (`com.jobsearch.tick`) wakes every 15 minutes and at login, and runs the searches that are
due. After sleep it catches up once instead of piling up, failed runs retry with backoff (30 min, 1 h, 2 h,
...), offline ticks don't count, and only one run happens at a time. Each run starts fresh, so code changes
are picked up without a restart.

Notifications: Mac banner (clickable with `brew install terminal-notifier`) and phone push via
[ntfy](https://ntfy.sh), with a minimum fit, quiet hours (queued, then one summary) and problem alerts
(a source failing 3 runs in a row, runs failing, a missing key). Set them up from the main menu →
**Notifications**.

## Tests

```sh
python3 -m pytest
```

Gemini, Google Sheets and launchd are replaced by fakes, so the tests need no network or keys.

## Ideas

- Telegram bot with Applied / Not interested buttons.
- Company board lists per job category (the current ones are tech companies).
- Daily or weekly email digest.

## Notes

This is a personal tool. It reads public job listings at a gentle pace; check the terms of the sites you
use it with. Your CV is sent to Google's Gemini API for planning and matching.

## License

[MIT](LICENSE)
