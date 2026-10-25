"""API keys and settings for runs that don't start from a terminal (launchd doesn't read ~/.zshrc).

Only plain `export NAME=value` lines for the names below are read; the shell file is never executed.
"""
import os
import re
from pathlib import Path

NAMES = ["GEMINI_API_KEY", "GEMINI_MODEL", "JOOBLE_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
         "JOBSEARCH_TRACKER", "JOBSEARCH_NOTES"]
FILES = [Path.home() / ".zshrc", Path.home() / ".zprofile", Path.home() / ".bash_profile"]
LINE = re.compile(r"^\s*export\s+([A-Z_][A-Z0-9_]*)=(.*)$")


def parse(text):
    out = {}
    for line in text.splitlines():
        m = LINE.match(line)
        if m and m.group(1) in NAMES:
            value = m.group(2).split(" #")[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value and "$" not in value:  # skip values that need the shell to expand them
                out[m.group(1)] = value  # later lines win, like in the shell
    return out


def path(name):
    """A file path from an environment variable (~ allowed), or None when it isn't set."""
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def load(files=FILES):
    """Fill in missing keys from the shell startup files. Keys already in the environment win."""
    found = {}
    for f in files:
        if f.exists():
            found.update(parse(f.read_text(errors="ignore")))
    for name, value in found.items():
        os.environ.setdefault(name, value)
