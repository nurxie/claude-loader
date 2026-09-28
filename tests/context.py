"""Makes `claude_profiles` importable straight from the working tree.

`claude_profiles` is a namespace package split across folders, so putting the
repository's `cross-platform/`, `linux/` and `windows/` directories on the path
is all it takes - the same trick the installers use when they copy the halves
next to each other.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for folder in ("cross-platform", "linux", "windows"):
    path = str(ROOT / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
