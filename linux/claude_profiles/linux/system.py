"""Linux system access: Claude Desktop package, Claude Code CLI, updates, processes."""

import functools
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from ..core import paths

PACKAGE = "claude-desktop"

# Values from https://code.claude.com/docs/en/desktop-linux
APT_BASE = "https://downloads.claude.ai/claude-desktop/apt/stable"
KEY_URL = "https://downloads.claude.ai/claude-desktop/key.asc"
KEY_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
KEYRING = "/usr/share/keyrings/claude-desktop-archive-keyring.asc"
SOURCES_LIST = "/etc/apt/sources.list.d/claude-desktop.list"
SOURCES_LINE = (f"deb [arch=amd64,arm64 signed-by={KEYRING}] {APT_BASE} stable main")

# From https://code.claude.com/docs/en/setup
CLI_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"


class SystemError_(Exception):
    pass


def run(cmd, check=True, capture=True, timeout=None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, **kw)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# --- Claude Desktop package -------------------------------------------------

def installed_version() -> Optional[str]:
    if not have("dpkg-query"):
        return None
    r = run(["dpkg-query", "-W", "-f=${Status}\t${Version}", PACKAGE], check=False)
    if r.returncode != 0:
        return None
    status, _, version = r.stdout.partition("\t")
    return version.strip() if status.endswith("installed") else None


@functools.lru_cache(maxsize=1)
def package_files() -> tuple:
    if not have("dpkg"):
        return ()
    r = run(["dpkg", "-L", PACKAGE], check=False)
    return tuple(line for line in r.stdout.splitlines() if line.startswith("/")) if r.returncode == 0 else ()


def parse_desktop_entry(path) -> Dict[str, str]:
    """Read the [Desktop Entry] group of a .desktop file (untranslated keys only)."""
    result, in_group = {}, False
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        line = line.strip()
        if line.startswith("["):
            in_group = line == "[Desktop Entry]"
        elif in_group and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            key = key.strip()
            if "[" not in key:
                result[key] = value.strip()
    return result


@functools.lru_cache(maxsize=1)
def package_desktop_entry() -> Optional[str]:
    """Path of the .desktop file shipped by the claude-desktop package."""
    candidates = [f for f in package_files()
                  if f.endswith(".desktop") and "/applications/" in f]
    if not candidates:
        candidates = [str(p) for p in Path("/usr/share/applications").glob("*claude*.desktop")]
    # Prefer the entry that handles claude:// links; it is the main one.
    for c in candidates:
        if "x-scheme-handler/claude" in parse_desktop_entry(c).get("MimeType", ""):
            return c
    return candidates[0] if candidates else None


def desktop_bin(override: Optional[str] = None) -> Optional[str]:
    """The command that starts Claude Desktop."""
    if override:
        return override
    found = shutil.which("claude-desktop")
    if found:
        return found
    entry = package_desktop_entry()
    if entry:
        exec_line = parse_desktop_entry(entry).get("Exec", "")
        first = exec_line.split()[0].strip('"') if exec_line.split() else ""
        if first and (os.path.isabs(first) or shutil.which(first)):
            return shutil.which(first) or first
    return None


@functools.lru_cache(maxsize=1)
def find_icon() -> Optional[str]:
    """Best available Claude icon file (largest PNG, else SVG)."""
    entry = package_desktop_entry()
    icon_name = parse_desktop_entry(entry).get("Icon", "") if entry else ""
    if icon_name and os.path.isabs(icon_name) and os.path.exists(icon_name):
        return icon_name

    files = [f for f in package_files() if f.endswith((".png", ".svg"))]
    if icon_name:
        named = [f for f in files if Path(f).stem == icon_name]
        files = named or files
    if not files:
        pattern = f"{icon_name or '*claude*'}.*"
        for base in ("/usr/share/icons/hicolor", "/usr/share/pixmaps"):
            files += [str(p) for p in Path(base).rglob(pattern) if p.suffix in (".png", ".svg")]

    def score(f):
        # Icon theme folders are named like .../256x256/apps/claude.png
        for part in reversed(Path(f).parts):
            a, _, b = part.partition("x")
            if a.isdigit() and b.isdigit():
                return int(a)
        return 0

    files = [f for f in files if os.path.exists(f)]
    if not files:
        return None
    pngs = [f for f in files if f.endswith(".png")]
    return max(pngs, key=score) if pngs else files[0]


def desktop_status() -> dict:
    return {
        "version": installed_version(),
        "bin": desktop_bin(),
        "entry": package_desktop_entry(),
        "icon": find_icon(),
    }


def install_desktop(echo=print) -> None:
    """Install Claude Desktop from Anthropic's apt repository (interactive sudo)."""
    if os.geteuid() == 0:
        raise SystemError_("Run claude-profiles as your normal user, not as root.")
    if not have("apt-get"):
        raise SystemError_("This needs a Debian-based system (Ubuntu 22.04+ or Debian 12+).")

    if not (have("curl") and have("gpg")):
        echo("Installing curl and gnupg...")
        run(["sudo", "apt-get", "install", "-y", "curl", "gnupg"], capture=False)

    if not os.path.exists(KEYRING):
        echo("Downloading Anthropic's signing key...")
        with tempfile.TemporaryDirectory() as tmp:
            key = os.path.join(tmp, "key.asc")
            run(["curl", "-fsSLo", key, KEY_URL])
            r = run(["gpg", "--show-keys", "--with-colons", key])
            fingerprints = [line.split(":")[9] for line in r.stdout.splitlines()
                            if line.startswith("fpr:")]
            if KEY_FINGERPRINT not in fingerprints:
                raise SystemError_("The downloaded key does not have Anthropic's fingerprint. "
                                   "Stopping for safety.")
            echo(f"  Key fingerprint OK ({KEY_FINGERPRINT}).")
            run(["sudo", "install", "-m", "0644", key, KEYRING], capture=False)

    if not os.path.exists(SOURCES_LIST):
        echo("Registering the apt repository...")
        run(["sudo", "tee", SOURCES_LIST], input=SOURCES_LINE + "\n", capture=True)

    echo("Installing claude-desktop (this can take a minute)...")
    run(["sudo", "apt-get", "update"], capture=False)
    run(["sudo", "apt-get", "install", "-y", PACKAGE], capture=False)
    package_files.cache_clear()
    package_desktop_entry.cache_clear()
    find_icon.cache_clear()
    if not installed_version():
        raise SystemError_("claude-desktop does not seem to be installed after apt finished.")


# --- updates ------------------------------------------------------------------

def compare_versions(a: str, b: str) -> int:
    try:
        import apt_pkg  # python3-apt, present on most Ubuntu installs
        apt_pkg.init_system()
        c = apt_pkg.version_compare(a, b)
        return (c > 0) - (c < 0)
    except ImportError:
        pass
    if run(["dpkg", "--compare-versions", a, "gt", b], check=False).returncode == 0:
        return 1
    if run(["dpkg", "--compare-versions", a, "lt", b], check=False).returncode == 0:
        return -1
    return 0


def parse_packages_index(text: str, package: str = PACKAGE) -> List[str]:
    versions = []
    for stanza in text.split("\n\n"):
        fields = {}
        for line in stanza.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
        if fields.get("Package") == package and fields.get("Version"):
            versions.append(fields["Version"])
    return versions


def latest_version(timeout=10) -> Optional[str]:
    """Newest claude-desktop version in Anthropic's repository (no root needed)."""
    arch = run(["dpkg", "--print-architecture"]).stdout.strip() if have("dpkg") else "amd64"
    url = f"{APT_BASE}/dists/stable/main/binary-{arch}/Packages"
    req = urllib.request.Request(url, headers={"User-Agent": "claude-profiles"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    versions = parse_packages_index(text)
    if not versions:
        return None
    return max(versions, key=functools.cmp_to_key(compare_versions))


def check_update() -> dict:
    installed = installed_version()
    latest = latest_version()
    available = bool(installed and latest and compare_versions(latest, installed) > 0)
    message = (f"Claude Desktop {latest} is available (installed: {installed})" if available
               else f"Claude Desktop is up to date ({installed or 'not installed'}).")
    return {"installed": installed, "latest": latest, "available": available,
            "message": message, "action": "Update"}


def update_command(gui: bool) -> List[str]:
    """Upgrade only claude-desktop, refreshing only Anthropic's repository."""
    script = (f"apt-get update -o Dir::Etc::sourcelist={SOURCES_LIST} "
              "-o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 && "
              f"apt-get install -y --only-upgrade {PACKAGE}")
    return (["pkexec"] if gui else ["sudo"]) + ["/bin/sh", "-c", script]


# --- Claude Code CLI ----------------------------------------------------------

def cli_bin() -> Optional[str]:
    """The real `claude` CLI (not one of our claude-<id> wrappers)."""
    found = shutil.which("claude")
    if found:
        return found
    if paths.NATIVE_CLI.exists():
        return str(paths.NATIVE_CLI)
    return None


def install_cli() -> None:
    run(["bash", "-c", CLI_INSTALL], capture=False)


# --- running instances --------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _package_executables() -> frozenset:
    result = set()
    for f in package_files():
        try:
            if os.path.isfile(f) and os.access(f, os.X_OK):
                result.add(os.path.realpath(f))
        except OSError:
            pass
    return frozenset(result)


def running_data_dirs() -> Dict[str, List[int]]:
    """Map of Claude Desktop main processes by data folder.

    Key is the --user-data-dir value, or "" for instances using the standard folder.
    """
    found: Dict[str, List[int]] = {}
    exes = _package_executables()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not args or any(a.startswith("--type=") for a in args):
            continue  # Electron helper process
        data_dir = None
        for i, a in enumerate(args):
            if a.startswith("--user-data-dir="):
                data_dir = a.split("=", 1)[1]
            elif a == "--user-data-dir" and i + 1 < len(args):
                data_dir = args[i + 1]
        if data_dir is None:
            try:
                exe = os.path.realpath(f"/proc/{pid}/exe")
            except OSError:
                continue
            if exe not in exes:
                continue
            data_dir = ""
        found.setdefault(os.path.normpath(data_dir) if data_dir else "", []).append(int(pid))
    return found


def running_profile_ids(cfg) -> List[str]:
    running = running_data_dirs()
    ids = []
    for p in cfg.profiles:
        key = "" if p.system_default else os.path.normpath(str(p.desktop_data_dir))
        if key in running:
            ids.append(p.id)
    return ids
