#!/usr/bin/env bash
# Installs (or updates) claude-profiles for the current user, then starts the
# setup wizard on the first run or the manager on later runs.
#
#   ./install.sh            install / update, then open setup or manager
#   ./install.sh uninstall  any claude-profiles command can be passed through
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Run this as your normal user, not with sudo. It asks for sudo when needed." >&2
    exit 1
fi
if ! command -v apt-get >/dev/null; then
    echo "This installer supports Debian-based systems (Ubuntu 22.04+, Debian 12+)." >&2
    exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$SRC/../cross-platform/claude_profiles/core"
if [[ ! -d "$CORE" ]]; then
    echo "Cannot find $CORE. Run install.sh from a full copy of the repository." >&2
    exit 1
fi
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/claude-profiles"
APP_DIR="$DATA/app"
BIN="$HOME/.local/bin/claude-profiles"

# GTK 4 + libadwaita for the loader and password prompts, curl/gnupg for the
# Claude Desktop repository key, xdg-utils for the claude:// handler.
missing=()
python3 - <<'EOF' 2>/dev/null || missing+=(python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, GdkPixbuf
EOF
for cmd in curl:curl gpg:gnupg xdg-mime:xdg-utils; do
    command -v "${cmd%%:*}" >/dev/null || missing+=("${cmd##*:}")
done
if (( ${#missing[@]} )); then
    echo "Installing required packages: ${missing[*]}"
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
fi

echo "Installing claude-profiles to $APP_DIR"
mkdir -p "$APP_DIR" "$(dirname "$BIN")"
rm -rf "$APP_DIR/claude_profiles"
mkdir -p "$APP_DIR/claude_profiles"
# claude_profiles is a namespace package: the shared core plus the Linux part.
cp -r "$CORE" "$APP_DIR/claude_profiles/core"
cp -r "$SRC/claude_profiles/linux" "$APP_DIR/claude_profiles/linux"
find "$APP_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/bin/sh
# claude-profiles launcher (installed by install.sh)
PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m claude_profiles.linux "\$@"
EOF
chmod 755 "$BIN"

# After an update, regenerate menu entries so they match the new version.
if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/claude-profiles/config.json" ]]; then
    "$BIN" apply --quiet || true
fi

exec "$BIN" "$@"
