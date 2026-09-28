"""Cross-platform core of claude-profiles.

Everything here works the same on Linux and Windows. OS-specific work
(installing Claude, menu entries, hotkeys, the loader window) lives in the
`claude_profiles.linux` and `claude_profiles.windows` packages, which plug into
the core through `core.platform.Platform`.
"""

VERSION = "1.0.0"

# Where `claude-profiles self-update` looks for new releases.
REPO = "nurxie/claude-loader"
