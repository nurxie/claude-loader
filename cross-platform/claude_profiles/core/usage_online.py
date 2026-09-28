"""What the account itself says is left of a profile's limits.

Signing in to Claude Code from the terminal leaves an OAuth token in that
profile's own folder, as `.credentials.json`. The same token answers the
endpoint the CLI's `/usage` uses, and that answer is the only place the real
figures exist: how much of the five-hour window is gone, and the moment it
resets. Nothing on the machine knows either - a plan's allowance is not written
down anywhere, and neither is the reset time.

So this is the authoritative source, and `usage.py` - which counts tokens out
of the transcripts - is the detail next to it: which models the tokens went to,
how many messages, and a rough picture when the account cannot be reached.

**A profile signed in only through the Desktop app has no token here.** The
app's Code tab keeps its session inside the app's own encrypted storage, so
there is nothing to read and the figures stay local until the profile's
`claude-<id>` command is signed in once. `local_account()` still says *who*
that profile is, because Claude Code records the account in `.claude.json`
either way - which is what the loader puts under each profile's name.

The endpoint is not a documented, public API. It is a setting
(`CLAUDE_PROFILES_USAGE_URL`, or `usage_url` in config.json) so it can be
corrected without changing code, and every failure is reported in one sentence
and falls back to the local count.

What is read is used for one HTTPS request to Anthropic per profile. It is
never written anywhere, logged, or shown in the interface.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import VERSION
from .usage import config_dir

# Unverified; see the module docstring. Override these rather than editing them.
DEFAULT_URL = "https://api.anthropic.com/api/oauth/usage"
DEFAULT_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
TIMEOUT = 15
CREDENTIALS_FILE = ".credentials.json"
SETTINGS_FILE = ".claude.json"
CACHE_SECONDS = 45          # the usage window refreshes on a timer; don't ask every time
IDENTITY_CACHE_SECONDS = 900  # who a profile is signed in as barely ever changes


class Unavailable(Exception):
    """The account's figures cannot be read; the caller falls back to counting."""


# --- what the account reports ---------------------------------------------------------

@dataclass
class Window:
    """One limit window, as a share of its allowance and when it empties again."""
    share: float                                # 0.0 - 1.0
    resets_at: Optional[datetime] = None
    locked_reason: str = ""

    def resets_in(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        if self.resets_at is None:
            return None
        return max(timedelta(0), self.resets_at - (now or datetime.now(timezone.utc)))


@dataclass
class Limits:
    five_hour: Optional[Window] = None
    seven_day: Optional[Window] = None
    seven_day_opus: Optional[Window] = None
    plan: str = ""

    @property
    def empty(self) -> bool:
        return not (self.five_hour or self.seven_day or self.seven_day_opus)


@dataclass
class Account:
    """Who a profile is signed in as - so you can tell your profiles apart."""
    uuid: str = ""
    email: str = ""
    name: str = ""
    organization: str = ""
    plan: str = ""

    @property
    def label(self) -> str:
        """One line naming this account, as short as it can be.

        A personal account's organization is named after the account itself
        ("me@example.org's Organization"), which says nothing twice - and the
        cards it has to fit on are narrow.
        """
        org = self.organization
        if org and self.email and org.lower().startswith(self.email.lower()):
            org = ""
        if self.email and org:
            return f"{self.email} · {org}"
        return self.email or org or self.name or ""

    @property
    def key(self) -> str:
        """What two profiles share when they are the same account."""
        return self.uuid or self.email.lower()


# --- credentials -------------------------------------------------------------------------

def _settings(profile) -> dict:
    """The profile's `.claude.json`, which Claude Code writes whenever it runs."""
    path = config_dir(profile) / SETTINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _credentials(profile) -> dict:
    """The profile's own OAuth token.

    Claude Code writes one when you sign in to the CLI. The Desktop app's Code
    tab signs in too, but keeps its token inside the app's own encrypted
    storage, so a profile can be signed in and still have nothing to read here -
    `.claude.json` is what tells those two cases apart.
    """
    path = config_dir(profile) / CREDENTIALS_FILE
    if not path.is_file():
        account = local_account(profile)
        if account is not None:
            raise Unavailable(
                f"signed in as {account.email or account.name} in the Claude app, which keeps "
                f"its token to itself - run `{profile.cli_command}` once and sign in there")
        raise Unavailable("this profile is not signed in yet - start it once")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Unavailable("the profile's credentials file could not be read")
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        raise Unavailable("no access token in the profile's credentials file")
    return oauth


def local_account(profile) -> Optional["Account"]:
    """Who the profile is signed in as, from its own files - no token, no request.

    Claude Code records the account in `.claude.json` whether you signed in to
    the CLI or through the Desktop app, so this works for every profile that has
    been opened once. It is the only thing about the account a profile with no
    readable token can still say.
    """
    oauth = _settings(profile).get("oauthAccount")
    if not isinstance(oauth, dict):
        return None
    email = str(oauth.get("emailAddress") or "")
    uuid = str(oauth.get("accountUuid") or "")
    if not (email or uuid):
        return None
    return Account(uuid=uuid, email=email,
                   name=str(oauth.get("displayName") or oauth.get("fullName") or ""),
                   plan=_TIERS.get(str(oauth.get("seatTier") or ""), ""))


def plan_name(profile) -> str:
    """The plan this profile is signed in to, from its own credentials file."""
    try:
        oauth = _credentials(profile)
    except Unavailable:
        return ""
    label = str(oauth.get("subscriptionType") or "").strip()
    return label.replace("_", " ").title() if label else ""


def _token(oauth: dict) -> str:
    # The CLI refreshes the token when it runs; we only read it, so say plainly
    # when it has gone stale instead of failing with a bare 401.
    expires = oauth.get("expiresAt")
    if isinstance(expires, (int, float)) and expires > 0:
        seconds = expires / 1000 if expires > 10_000_000_000 else expires
        if seconds < time.time():
            raise Unavailable("the profile's sign-in has expired - start it once to refresh")
    return str(oauth["accessToken"])


# --- reading the answer ---------------------------------------------------------------------

def endpoint(cfg=None) -> str:
    return (os.environ.get("CLAUDE_PROFILES_USAGE_URL")
            or (getattr(cfg, "usage_url", "") if cfg else "") or DEFAULT_URL)


def profile_endpoint(cfg=None) -> str:
    return (os.environ.get("CLAUDE_PROFILES_PROFILE_URL")
            or (getattr(cfg, "profile_url", "") if cfg else "") or DEFAULT_PROFILE_URL)


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


def _window(block) -> Optional[Window]:
    """One block of the answer -> a Window, or None when it carries no figure.

    Shares arrive as percentages (`utilization: 7.0`, `percent: 7`).
    """
    if not isinstance(block, dict):
        return None
    share = None
    for key in ("utilization", "percent", "used_percent", "percent_used"):
        value = block.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            share = max(0.0, min(1.0, float(value) / 100))
            break
    if share is None:
        used, limit = block.get("used"), block.get("limit")
        if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
            share = max(0.0, min(1.0, used / limit))
    if share is None:
        return None
    resets_at = None
    for key in ("resets_at", "resetsAt", "reset_at"):
        resets_at = _moment(block.get(key))
        if resets_at:
            break
    return Window(share=share, resets_at=resets_at,
                  locked_reason=str(block.get("locked_reason") or ""))


def _from_limits_array(payload: dict) -> Dict[str, Window]:
    """The answer also carries a flat `limits` list; use it for anything missing."""
    found: Dict[str, Window] = {}
    for entry in payload.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        name = f"{entry.get('kind') or ''} {entry.get('group') or ''}".lower()
        window = _window(entry)
        if not window:
            continue
        if "opus" in name:
            found.setdefault("seven_day_opus", window)
        elif "session" in name or "five" in name or "5h" in name:
            found.setdefault("five_hour", window)
        elif "seven" in name or "week" in name or "7d" in name:
            found.setdefault("seven_day", window)
    return found


# Organization types the profile endpoint is known to return.
_ORGANIZATIONS = {"claude_team": "Team", "claude_enterprise": "Enterprise",
                  "claude_pro": "Pro", "claude_max": "Max"}
# Seat tiers `.claude.json` carries, for when only the local file can be read.
_TIERS = {"team_labs_standard": "Team", "enterprise": "Enterprise",
          "pro": "Pro", "max": "Max"}


def parse_account(payload: dict, fallback_plan: str = "") -> Account:
    """Read the profile answer: who this is, and on what plan."""
    account = payload.get("account") if isinstance(payload, dict) else None
    org = payload.get("organization") if isinstance(payload, dict) else None
    account = account if isinstance(account, dict) else {}
    org = org if isinstance(org, dict) else {}
    plan = _ORGANIZATIONS.get(str(org.get("organization_type") or ""))
    if not plan:
        if account.get("has_claude_max"):
            plan = "Max"
        elif account.get("has_claude_pro"):
            plan = "Pro"
    return Account(
        uuid=str(account.get("uuid") or ""),
        email=str(account.get("email") or ""),
        name=str(account.get("display_name") or account.get("full_name") or ""),
        organization=str(org.get("name") or ""),
        plan=plan or fallback_plan,
    )


def parse(payload: dict) -> Limits:
    """Read the shapes the answer is known to use, ignoring everything else."""
    limits = Limits(plan=str(payload.get("plan") or payload.get("subscription") or ""))
    limits.five_hour = _window(payload.get("five_hour") or payload.get("fiveHour")
                               or payload.get("session"))
    limits.seven_day = _window(payload.get("seven_day") or payload.get("sevenDay")
                               or payload.get("weekly"))
    limits.seven_day_opus = _window(payload.get("seven_day_opus") or payload.get("sevenDayOpus")
                                    or payload.get("weekly_opus"))
    for name, window in _from_limits_array(payload).items():
        if getattr(limits, name) is None:
            setattr(limits, name, window)
    return limits


# --- asking ------------------------------------------------------------------------------------

@dataclass
class _Cached:
    at: float
    value: Optional[object] = None
    error: str = ""


_limits_cache: Dict[str, _Cached] = {}
_identity_cache: Dict[str, _Cached] = {}


def _remembered(store: Dict[str, _Cached], key: str, seconds: float, force: bool, ask,
                error_seconds: float = CACHE_SECONDS):
    """Ask, but not more often than `seconds`.

    A failure is remembered for much less time than an answer: the usual reason
    for one is that the profile has just not been signed in yet, and when that
    changes the interface should notice in a moment rather than a quarter of an
    hour.
    """
    cached = store.get(key)
    if cached and not force:
        fresh_for = seconds if cached.value is not None else min(seconds, error_seconds)
        if time.time() - cached.at < fresh_for:
            if cached.value is not None:
                return cached.value
            raise Unavailable(cached.error)
    try:
        value = ask()
    except Unavailable as e:
        store[key] = _Cached(at=time.time(), error=str(e))
        raise
    store[key] = _Cached(at=time.time(), value=value)
    return value


def _get(url: str, oauth: dict) -> dict:
    """One signed GET, with every failure turned into a sentence."""
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token(oauth)}",
        "User-Agent": f"claude-loader/{VERSION}",
        "Accept": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Unavailable("this profile's sign-in was refused - start it once to sign in again")
        raise Unavailable(f"Claude answered {e.code}")
    except urllib.error.URLError as e:
        raise Unavailable(f"no connection to Claude ({e.reason})")
    except (OSError, ValueError) as e:
        raise Unavailable(str(e))
    if not isinstance(payload, dict):
        raise Unavailable("the answer was not in the expected form")
    return payload


def fetch(profile, cfg=None, force: bool = False) -> Limits:
    """Ask the account for its limits. Raises Unavailable on any problem."""
    def ask() -> Limits:
        limits = parse(_get(endpoint(cfg), _credentials(profile)))
        if limits.empty:
            raise Unavailable("the account reported no limits for this profile")
        limits.plan = limits.plan or plan_name(profile)
        return limits

    return _remembered(_limits_cache, profile.id, CACHE_SECONDS, force, ask)


def identity(profile, cfg=None, force: bool = False) -> Optional[Account]:
    """Who this profile is signed in as, or None when nothing knows.

    The account itself gives the fullest answer (it names the organization), but
    it needs a token; the profile's own files always answer, so they stand in.
    """
    def ask() -> Account:
        account = parse_account(_get(profile_endpoint(cfg), _credentials(profile)),
                                plan_name(profile))
        if not account.key:
            raise Unavailable("the account did not say who this profile is")
        return account

    try:
        return _remembered(_identity_cache, profile.id, IDENTITY_CACHE_SECONDS, force, ask)
    except Unavailable:
        return local_account(profile)


def apply_to(usage, profile, cfg=None, force: bool = False) -> bool:
    """Put the account's figures on a ProfileUsage. False if it could not be asked.

    The local count is left in place either way: it is what says which models
    the tokens went to, and it is all there is when the account is unreachable.
    """
    usage.identity = identity(profile, cfg, force)
    try:
        usage.account = fetch(profile, cfg, force)
    except Unavailable as e:
        usage.account = None
        usage.source = "local"
        usage.account_note = f"Exact limits unavailable: {e}."
        return False
    usage.source = "account"
    usage.account_note = ""
    return True


def duplicates(collected) -> Dict[str, List[str]]:
    """Accounts that more than one profile is signed into: {label: [profile names]}."""
    by_account: Dict[str, List[str]] = {}
    labels: Dict[str, str] = {}
    for data in collected:
        account = getattr(data, "identity", None)
        if account is None or not account.key:
            continue
        by_account.setdefault(account.key, []).append(data.name)
        labels[account.key] = account.label
    return {labels[key]: names for key, names in by_account.items() if len(names) > 1}
