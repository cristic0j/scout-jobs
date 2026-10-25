import sys

from .env import load

load()  # before anything reads the keys (background runs don't get ~/.zshrc)

from .cli import main  # noqa: E402

sys.exit(main())
