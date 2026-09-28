"""Updating Claude Loader itself from the project's GitHub releases.

The check is a plain HTTPS request to the GitHub API; nothing is installed
until someone asks for it. An update replaces the two Python packages in
`<data>/app/claude_profiles` (the shared core and this OS's part) and leaves
the private Python environment, the `claude-profiles` command and the config
alone, because those do not change between releases. If a release ever needs
more than that, run the repository installer again.
"""

import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from . import REPO, VERSION, paths

API = f"https://api.github.com/repos/{REPO}"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = f"claude-loader/{VERSION}"
STATE_FILE = paths.DATA_DIR / "update.json"

CHECK_INTERVAL = 24 * 3600      # how long a check result stays fresh
TIMEOUT = 20                    # seconds per request
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024

STAGING = paths.DATA_DIR / "update-staging"
PACKAGE_DIR = paths.APP_DIR / "claude_profiles"


class UpdateError(Exception):
    pass


# --- versions ----------------------------------------------------------------------

def parse_version(text: Optional[str]):
    """'v0.3.0' -> (0, 3, 0). Unparsable input sorts lowest."""
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:4]) or (0,)


def is_newer(latest: Optional[str], current: str = VERSION) -> bool:
    return parse_version(latest) > parse_version(current)


def os_package() -> str:
    return "windows" if paths.IS_WINDOWS else "linux"


# --- talking to GitHub ---------------------------------------------------------------

def _request(url: str, accept: str):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})


def _get_json(url: str):
    try:
        with urllib.request.urlopen(_request(url, "application/vnd.github+json"),
                                    timeout=TIMEOUT) as response:
            return json.loads(response.read(MAX_DOWNLOAD).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise
        raise UpdateError(f"GitHub answered {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise UpdateError(f"no connection to github.com ({e.reason})")
    except (OSError, ValueError) as e:
        raise UpdateError(str(e))


def latest_release() -> Dict[str, str]:
    """The newest published release, or the newest tag if there is no release."""
    try:
        data = _get_json(f"{API}/releases/latest")
        tag = (data.get("tag_name") or data.get("name") or "").strip()
        if tag:
            return {"version": tag.lstrip("vV"),
                    "url": data.get("zipball_url") or f"{API}/zipball/{tag}",
                    "notes": (data.get("body") or "").strip()[:2000],
                    "page": data.get("html_url") or RELEASES_PAGE}
    except urllib.error.HTTPError:
        pass  # no published release yet; fall back to the tags
    tags = _get_json(f"{API}/tags")
    names = [t["name"] for t in tags
             if isinstance(t, dict) and t.get("name") and "-" not in t["name"]]
    if not names:
        raise UpdateError("this project has no releases yet")
    newest = max(names, key=parse_version)
    return {"version": newest.lstrip("vV"), "url": f"{API}/zipball/{newest}",
            "notes": "", "page": RELEASES_PAGE}


# --- remembering the last check ---------------------------------------------------------

def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def _result(release: Dict[str, str]) -> dict:
    version = release.get("version") or ""
    available = is_newer(version)
    if available:
        message = f"Claude Loader {version} is available (you have {VERSION})."
    else:
        message = f"Claude Loader {VERSION} is up to date."
    return {"current": VERSION, "latest": version, "available": available,
            "url": release.get("url", ""), "notes": release.get("notes", ""),
            "page": release.get("page", RELEASES_PAGE),
            "message": message, "action": f"Update to {version}" if available else ""}


def check(force: bool = False) -> dict:
    """Look for a newer release. Cached for a day unless `force`. Raises UpdateError."""
    state = _load_state()
    fresh = time.time() - float(state.get("checked_at") or 0) < CHECK_INTERVAL
    if state.get("version") and fresh and not force:
        return _result(state)
    release = latest_release()
    _save_state({**release, "checked_at": time.time()})
    return _result(release)


def last_result() -> Optional[dict]:
    """What the last check found, without going online. None if never checked."""
    state = _load_state()
    return _result(state) if state.get("version") else None


# --- installing -------------------------------------------------------------------------

def _download(url: str, target: Path) -> None:
    # The zipball endpoint answers 415 to a narrow Accept header, so ask for anything.
    try:
        with urllib.request.urlopen(_request(url, "*/*"),
                                    timeout=TIMEOUT) as response, open(target, "wb") as out:
            total = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise UpdateError("the download is larger than expected; stopped")
                out.write(chunk)
    except urllib.error.URLError as e:
        raise UpdateError(f"could not download the update ({e.reason})")
    except OSError as e:
        raise UpdateError(f"could not download the update ({e})")


def _wanted_trees() -> List[str]:
    """Folders inside the repository that make up the installed program."""
    return ["cross-platform/claude_profiles/core", f"{os_package()}/claude_profiles/{os_package()}"]


def _extract_tree(zf: zipfile.ZipFile, root: str, source: str, destination: Path) -> int:
    """Copy one folder out of the zip. Returns the number of files written."""
    prefix = f"{root}{source}/"
    written = 0
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        relative = info.filename[len(prefix):]
        if not relative.endswith(".py"):
            continue  # the program is Python only; never unpack anything else
        target = (destination / relative).resolve()
        if not str(target).startswith(str(destination.resolve()) + os.sep):
            raise UpdateError("the update archive contains an unexpected path")
        if info.file_size > MAX_FILE:
            raise UpdateError(f"{relative} in the update is unexpectedly large")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 64 * 1024)
        written += 1
    return written


def _stage(archive: Path) -> Path:
    """Unpack the new program into a folder next to the installed one."""
    if STAGING.exists():
        shutil.rmtree(STAGING, ignore_errors=True)
    package = STAGING / "claude_profiles"
    package.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if not names:
                raise UpdateError("the update archive is empty")
            # A GitHub source archive has one top folder, e.g. "owner-repo-<sha>/".
            root = names[0].split("/")[0] + "/" if "/" in names[0] else ""
            for source in _wanted_trees():
                name = source.rsplit("/", 1)[-1]
                if not _extract_tree(zf, root, source, package / name):
                    raise UpdateError(f"the update does not contain {source}")
    except zipfile.BadZipFile:
        raise UpdateError("the downloaded update is not a valid archive")
    if not (package / "core" / "__init__.py").exists():
        raise UpdateError("the update is missing the shared core")
    if not (package / os_package() / "__main__.py").exists():
        raise UpdateError(f"the update is missing the {os_package()} part")
    return package


def _swap(staged: Path) -> None:
    """Put the new package in place, keeping the old one until it succeeded."""
    backup = paths.APP_DIR / "claude_profiles.previous"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    paths.APP_DIR.mkdir(parents=True, exist_ok=True)
    had_old = PACKAGE_DIR.exists()
    try:
        if had_old:
            os.rename(PACKAGE_DIR, backup)
    except OSError as e:
        raise UpdateError(f"the installed program is in use and could not be replaced ({e})")
    try:
        os.rename(staged, PACKAGE_DIR)
    except OSError as e:
        if had_old:
            os.rename(backup, PACKAGE_DIR)
        raise UpdateError(f"could not put the new version in place ({e})")
    shutil.rmtree(backup, ignore_errors=True)


def install(url: str) -> None:
    """Download and install the release at `url`. Raises UpdateError."""
    if not url.startswith("https://"):
        raise UpdateError("refusing to download an update over a plain connection")
    if not paths.APP_DIR.exists():
        raise UpdateError(f"{paths.short(paths.APP_DIR)} is missing; run the installer instead")
    STAGING.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(suffix=".zip", dir=str(paths.DATA_DIR))
    os.close(handle)
    archive = Path(temp_name)
    try:
        _download(url, archive)
        staged = _stage(archive)
        _swap(staged)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(STAGING, ignore_errors=True)
    _save_state({**_load_state(), "installed": VERSION, "installed_at": time.time()})
