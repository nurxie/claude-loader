"""`python3 -m claude_profiles.linux` = the claude-profiles command on Linux."""

import sys

from ..core.cli import main
from .platform import LinuxPlatform

if __name__ == "__main__":
    sys.exit(main(LinuxPlatform()))
