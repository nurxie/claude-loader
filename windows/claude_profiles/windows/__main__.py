"""`python -m claude_profiles.windows` = the claude-profiles command on Windows."""

import sys

from ..core.cli import main
from .platform import WindowsPlatform

if __name__ == "__main__":
    sys.exit(main(WindowsPlatform()))
