#!/usr/bin/env python3
"""Old entry point, kept so `python3 fetch_nl_jobs.py` still works. See jobsearch/cli.py."""
import sys

from jobsearch.cli import main

if __name__ == "__main__":
    sys.exit(main())
