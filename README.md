# Job search agent

Give it your CV. It works out which roles fit you, asks only what it can't tell from the CV, fetches matching
jobs in the Netherlands on a schedule, and has an AI matcher put the jobs that really fit into a matches
sheet, locally and (optionally) in Google Sheets, where you tick the ones you applied to.

## Setup

```sh
pip install requests openpyxl gspread pytest
```

Add your Gemini key to `~/.zshrc` (the background runs read it from there):

```sh
export GEMINI_API_KEY=...
```

Optional job sources: `JOOBLE_KEY`, `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`. Optional model override: `GEMINI_MODEL`.

## Use

```sh
python3 -m jobsearch
```

The menu walks you through it:

1. **New search**: give it a name and drop your CV (PDF, one file per version) in the folder it opens.
2. The **planner** reads the CV and proposes roles, search terms and preferences. It always asks about your
   work setup: towns for on-site work, maximum travel time for hybrid, maximum office days.
3. **Run now** fetches jobs, filters them, and the **matcher** scores the new ones (1-10) against your CV.
   Good fits land in `searches/<name>/matches.xlsx`.
4. **Automatic runs** keeps it going in the background (e.g. every 5 hours), with notifications on your Mac
   and phone for new matches.
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

Each search has its own folder, `searches/<name>/` (not in git, it holds your CV):

| File | What |
|---|---|
| `cv/` | your CV versions |
| `preferences.json`, `profiles/<role>.json` | what to search for and how to judge it |
| `results/<role>.xlsx` | every job found per role, with the matcher's score (`Processed` marks reviewed rows) |
| `matches.xlsx` | the jobs that fit, best first, with an **Applied** column |
| `cloud.json` | the Google Sheet it syncs with |
| `state.json`, `travel.json` | last run, CV fingerprint, cached travel times |

Logs of background runs: `logs/jobsearch.log`.

Your own application tracker, `~/Desktop/Jobs/jobs.xlsx`, is only **read** (jobs already in it are marked and
skipped), never written.

## Matches in Google Sheets

One-time setup (menu → your search → **Google Sheets**, which shows these steps too):

1. In [Google Cloud Console](https://console.cloud.google.com) create a project, enable the
   **Google Sheets API**, create a **service account** and download a **JSON key** for it.
2. Put the key file (any name) in `~/.config/jobsearch/`. Keep it private, it gives access to the sheet.
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

## Background runs

One macOS launchd agent (`com.jobsearch.tick`) wakes every 15 minutes and at login, and runs the searches
that are due. After sleep it catches up once, failed runs retry with backoff, and only one run happens at a
time. Code changes are picked up automatically: each run starts fresh.

Notifications: Mac banner and phone push via [ntfy](https://ntfy.sh), with a minimum fit, quiet hours and
problem alerts. Set them up from the main menu → **Notifications**.

## Tests

```sh
python3 -m pytest
```

Gemini, Google Sheets and launchd are replaced by fakes, so the tests need no network or keys.

See `PROGRESS.md` for the history and next steps.
