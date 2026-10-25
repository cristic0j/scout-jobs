"""Job sources. Each module exposes DESCRIPTION, KEYS (env vars it needs) and tasks(profile),
which returns [(name, callable)] — each callable returns a list of Job."""
from . import adzuna, arbeitnow, boards, jooble, linkedin

SOURCES = {"linkedin": linkedin, "boards": boards, "arbeitnow": arbeitnow,
           "jooble": jooble, "adzuna": adzuna}
