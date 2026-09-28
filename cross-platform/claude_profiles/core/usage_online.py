"""Experimental: ask Claude for a profile's exact remaining limits.

`usage.py` counts tokens from the transcripts, which always works but cannot
know your plan's allowance. This module tries the other way round: it reads the
profile's own Claude Code credentials and asks the account for its current
limits, the way `/usage` does inside the CLI.

It is off by default and never required. Two caveats, both deliberate:

* The endpoint below is **not a documented, public API**. It is a setting so
  that it can be corrected without changing code - through
  `CLAUDE_PROFILES_USAGE_URL` or `usage_url` in config.json - and any failure
  simply falls back to the local count.
* The credentials are only read when a profile actually stores them in its own
  folder, as `.credentials.json`. Systems that keep the sign-in somewhere else
  (a keychain, the Windows Credential Manager, or the Desktop app's own store)
  report "unavailable" instead, and nothing goes looking for them.

Whatever is read is used for exactly one HTTPS request to Anthropic and is
never written anywhere, logged, or shown in the interface.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import VERSION
from .usage import config_dir

# Unverified; see the module docstring. Override it rather than editing it.
DEFAULT_URL = "https://api.anthropic.com/api/oauth/usage"
TIMEOUT = 15
CREDENTIALS_FILE = ".credentials.json"


class Unavailable(Exception):
    """The exact limits cannot be read; the caller falls back to counting."""


@dataclass
class Limits:
    five_hour: Optional[float] = None      # 0.0-1.0 of the window's allowance
    five_hour_resets_at: Optional[datetime] = None
    seven_day: Optional[float] = None
    seven_day_resets_at: Optional[datetime] = None
    opus_seven_day: Optional[float] = None
    plan: str = ""

    @property
    def empty(self) -> bool:
        return self.five_hour is None and self.seven_day is None


def endpoint(cfg=None) -> str:
    return (os.environ.get("CLAUDE_PROFILES_USAGE_URL")
            or (getattr(cfg, "usage_url", "") if cfg else "") or DEFAULT_URL)


def _token(profile) -> str:
    """The profile's own OAuth access token, if it keeps one in its folder."""
    path = config_dir(profile) / CREDENTIALS_FILE
    if not path.is_file():
        raise Unavailable("this profile does not keep its sign-in in its own folder")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Unavailable("the profile's credentials file could not be read")
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = (oauth or {}).get("accessToken") if isinstance(oauth, dict) else None
    if not token:
        raise Unavailable("no access token in the profile's credentials file")
    return str(token)


def _moment(value) -> Optional[datetime]:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _share(block) -> Optional[float]:
    """A block of the answer -> how much of that limit is used, 0.0-1.0."""
    if not isinstance(block, dict):
        return None
    for key in ("utilization", "used_percent", "percent_used"):
        value = block.get(key)
        if isinstance(value, (int, float)):
            return min(1.0, value / 100 if value > 1 else float(value))
    used, limit = block.get("used"), block.get("limit")
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        return min(1.0, used / limit)
    return None


def _resets_at(block) -> Optional[datetime]:
    if not isinstance(block, dict):
        return None
    for key in ("resets_at", "resetsAt", "reset_at"):
        moment = _moment(block.get(key))
        if moment:
            return moment
    return None


def parse(payload: dict) -> Limits:
    """Read the shapes the answer is known to use, ignoring anything else."""
    limits = Limits(plan=str(payload.get("plan") or payload.get("subscription") or ""))
    five = payload.get("five_hour") or payload.get("fiveHour") or payload.get("session")
    week = payload.get("seven_day") or payload.get("sevenDay") or payload.get("weekly")
    opus = payload.get("seven_day_opus") or payload.get("sevenDayOpus") or payload.get("weekly_opus")
    limits.five_hour = _share(five)
    limits.five_hour_resets_at = _resets_at(five)
    limits.seven_day = _share(week)
    limits.seven_day_resets_at = _resets_at(week)
    limits.opus_seven_day = _share(opus)
    return limits


def fetch(profile, cfg=None) -> Limits:
    """Ask the account for its limits. Raises Unavailable on any problem."""
    request = urllib.request.Request(endpoint(cfg), headers={
        "Authorization": f"Bearer {_token(profile)}",
        "User-Agent": f"claude-loader/{VERSION}",
        "Accept": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Unavailable(f"Claude answered {e.code} for the usage request")
    except urllib.error.URLError as e:
        raise Unavailable(f"no connection to Claude ({e.reason})")
    except (OSError, ValueError) as e:
        raise Unavailable(str(e))
    if not isinstance(payload, dict):
        raise Unavailable("the usage answer was not in the expected form")
    limits = parse(payload)
    if limits.empty:
        raise Unavailable("the usage answer did not contain any limits")
    return limits


def apply_to(usage, profile, cfg=None) -> bool:
    """Replace a ProfileUsage's local estimate with the exact figures.

    Returns False and leaves the local numbers untouched when they are not
    available, so the caller can simply try and carry on.
    """
    try:
        limits = fetch(profile, cfg)
    except Unavailable as e:
        usage.note = (usage.note + " " if usage.note else "") + f"Exact limits: {e}."
        return False
    if limits.five_hour is not None and usage.active and usage.used:
        # Turn "x% of the window" back into the limit the bar runs against.
        usage.limit = max(usage.used, int(usage.used / max(limits.five_hour, 0.01)))
        usage.limit_is_measured = False
    if limits.seven_day is not None and usage.week.total:
        usage.weekly_limit = max(usage.week.total,
                                 int(usage.week.total / max(limits.seven_day, 0.01)))
    usage.source = "account"
    if limits.plan:
        usage.note = f"Plan: {limits.plan}."
    return True
