"""How much of each profile's limit is gone, and when it resets.

`collect_profile` puts together what the interface shows, from two sources:

* the profile's **account**, through `usage_online` - how full the five-hour
  window is and the moment it resets. Nothing on this machine knows either: a
  plan's allowance is not written down anywhere, and neither is the reset time.
  So when the account answers, it wins.
* the **transcripts on this PC** for what the account does not return. Claude
  Code writes one JSON line per message into
  `<config dir>/projects/<project>/<session>.jsonl`, and every assistant line
  carries that request's token counts and model. That says which models the
  tokens went to and how many messages there were, and it is also the estimate
  to fall back on when the account cannot be reached - against a limit set per
  profile, or the busiest window seen so far.

The local half covers the Claude Code CLI and the Desktop app's Code tab, which
share a profile's config folder. It does not cover Desktop chat, which Claude
Code never logs.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, Iterator, List, Optional

from . import paths

if TYPE_CHECKING:  # usage_online imports this module, so only for the annotations
    from .usage_online import Account, Limits

BLOCK_HOURS = 5                     # Claude's rolling usage window
WEEK_DAYS = 7
OPUS_MARKER = "opus"


# --- one assistant message ---------------------------------------------------------

@dataclass
class Entry:
    at: datetime
    model: str
    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_creation + self.cache_read

    @property
    def is_opus(self) -> bool:
        return OPUS_MARKER in self.model.lower()


@dataclass
class Totals:
    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    messages: int = 0
    opus: int = 0
    by_model: Dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_creation + self.cache_read

    def add(self, entry: Entry) -> None:
        self.input += entry.input
        self.output += entry.output
        self.cache_creation += entry.cache_creation
        self.cache_read += entry.cache_read
        self.messages += 1
        if entry.is_opus:
            self.opus += entry.total
        if entry.model:
            self.by_model[entry.model] = self.by_model.get(entry.model, 0) + entry.total

    def top_models(self, limit: int = 3) -> List[tuple]:
        return sorted(self.by_model.items(), key=lambda kv: -kv[1])[:limit]


@dataclass
class Block:
    """One 5-hour window, starting at the full hour of its first message."""
    start: datetime
    totals: Totals = field(default_factory=Totals)
    last_at: Optional[datetime] = None

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=BLOCK_HOURS)

    def is_active(self, now: Optional[datetime] = None) -> bool:
        return self.end > (now or _now())

    def resets_in(self, now: Optional[datetime] = None) -> timedelta:
        return max(timedelta(0), self.end - (now or _now()))


@dataclass
class ProfileUsage:
    profile_id: str
    name: str
    active: Optional[Block] = None
    week: Totals = field(default_factory=Totals)
    limit: int = 0                  # tokens per window; 0 means "unknown"
    limit_is_measured: bool = False  # True when it came from past windows, not settings
    weekly_limit: int = 0
    busiest_block: int = 0
    first_seen: Optional[datetime] = None
    source: str = "local"
    note: str = ""
    # What the account itself reports. When it is here it wins: it is the only
    # source that knows the plan's allowance and the exact reset time. The local
    # count stays for the per-model detail.
    account: Optional["Limits"] = None
    account_note: str = ""
    # Who the profile is signed in as, so several profiles can be told apart.
    identity: Optional["Account"] = None

    @property
    def used(self) -> int:
        return self.active.totals.total if self.active else 0

    @property
    def account_label(self) -> str:
        """The account this profile is signed in as, in one line. '' if unknown."""
        return self.identity.label if self.identity else ""

    @property
    def account_window(self):
        return self.account.five_hour if self.account else None

    @property
    def share(self) -> Optional[float]:
        """0.0-1.0 of the window's allowance, or None when nothing knows it.

        A limit you set is not a figure on its own: with nothing recorded here,
        the local estimate would read 0% of a window that may be half gone. So
        it only counts when there is something to count.
        """
        window = self.account_window
        if window is not None:
            return window.share
        if self.active is None or self.limit <= 0:
            return None
        return min(1.0, self.used / self.limit)

    @property
    def weekly_share(self) -> Optional[float]:
        window = self.account.seven_day if self.account else None
        if window is not None:
            return window.share
        if not self.week.total or self.weekly_limit <= 0:
            return None
        return min(1.0, self.week.total / self.weekly_limit)

    @property
    def opus_weekly_share(self) -> Optional[float]:
        window = self.account.seven_day_opus if self.account else None
        return window.share if window is not None else None

    @property
    def has_window(self) -> bool:
        """Is there an open five-hour window at all?"""
        return self.account_window is not None or self.active is not None

    @property
    def resets_at(self) -> Optional[datetime]:
        window = self.account_window
        if window is not None and window.resets_at is not None:
            return window.resets_at
        return self.active.end if self.active else None

    def resets_in(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        at = self.resets_at
        if at is None:
            return None
        return max(timedelta(0), at - (now or _now()))

    def weekly_resets_in(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        window = self.account.seven_day if self.account else None
        return window.resets_in(now) if window is not None else None


# --- reading the transcripts -------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def config_dir(profile) -> Path:
    """The Claude Code folder of a profile (its own, or the standard one)."""
    return paths.DEFAULT_CLI_DIR if profile.system_default else Path(profile.cli_config_dir)


def transcripts(profile) -> Iterator[Path]:
    root = config_dir(profile) / "projects"
    if not root.is_dir():
        return
    yield from root.rglob("*.jsonl")


def _parse_time(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _entry_from(record: dict) -> Optional[Entry]:
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return None
    usage = message.get("usage")
    at = _parse_time(record.get("timestamp"))
    if not isinstance(usage, dict) or at is None:
        return None

    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and value > 0 else 0

    return Entry(at=at, model=str(message.get("model") or "unknown"),
                 input=count("input_tokens"), output=count("output_tokens"),
                 cache_creation=count("cache_creation_input_tokens"),
                 cache_read=count("cache_read_input_tokens"))


def read_entries(profile, since: Optional[datetime] = None) -> List[Entry]:
    """Every assistant message of a profile, newest last, without duplicates.

    The same message can appear in several files when a session is resumed, so
    entries are keyed by message and request id the way Claude writes them.
    """
    entries: List[Entry] = []
    seen = set()
    # A file is only skipped when everything in it is certainly older than the
    # cutoff; the slack covers clocks and late writes.
    cutoff = (since - timedelta(hours=BLOCK_HOURS)).timestamp() if since else None
    for path in transcripts(profile):
        try:
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    entry = _entry_from(record)
                    if entry is None or (since and entry.at < since):
                        continue
                    key = (record.get("message", {}).get("id"), record.get("requestId"))
                    if key != (None, None):
                        if key in seen:
                            continue
                        seen.add(key)
                    entries.append(entry)
        except OSError:
            continue
    entries.sort(key=lambda e: e.at)
    return entries


# --- turning them into windows -------------------------------------------------------

def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def build_blocks(entries: Iterable[Entry]) -> List[Block]:
    """Group messages into 5-hour windows the way Claude's limits work: a window
    opens with the first message and lasts five hours, and a gap of five hours
    with no messages also ends it."""
    window = timedelta(hours=BLOCK_HOURS)
    blocks: List[Block] = []
    for entry in entries:
        current = blocks[-1] if blocks else None
        if (current is None or entry.at - current.start >= window
                or (current.last_at and entry.at - current.last_at >= window)):
            current = Block(start=_floor_hour(entry.at))
            blocks.append(current)
        current.totals.add(entry)
        current.last_at = entry.at
    return blocks


def collect(profile, now: Optional[datetime] = None, history_days: int = 30) -> ProfileUsage:
    """Everything the usage window shows for one profile."""
    now = now or _now()
    usage = ProfileUsage(profile_id=profile.id, name=profile.name,
                         limit=profile.usage_limit, weekly_limit=profile.usage_weekly_limit)
    if profile.system_default and not (paths.DEFAULT_CLI_DIR / "projects").is_dir():
        usage.note = "No Claude Code history in the standard folder yet."
        return usage

    entries = read_entries(profile, since=now - timedelta(days=history_days))
    if not entries:
        usage.note = "No Claude Code history on this PC yet."
        return usage
    usage.first_seen = entries[0].at

    blocks = build_blocks(entries)
    if blocks and blocks[-1].is_active(now):
        usage.active = blocks[-1]
        finished = blocks[:-1]
    else:
        finished = blocks
    usage.busiest_block = max((b.totals.total for b in finished), default=0)
    if usage.limit <= 0 and usage.busiest_block > 0:
        usage.limit = usage.busiest_block
        usage.limit_is_measured = True

    week_start = now - timedelta(days=WEEK_DAYS)
    for entry in entries:
        if entry.at >= week_start:
            usage.week.add(entry)
    return usage


def collect_profile(profile, cfg=None, now: Optional[datetime] = None,
                    online: Optional[bool] = None, force: bool = False) -> ProfileUsage:
    """One profile, with the account's figures on top of the local count.

    `online` defaults to the config's setting. Asking the account is what makes
    the percentages and the reset time real; if it cannot be reached, what is
    left is the local estimate and a sentence saying why.
    """
    data = collect(profile, now)
    ask = online if online is not None else bool(getattr(cfg, "usage_online", False))
    if ask:
        from . import usage_online  # imported here: it imports this module
        usage_online.apply_to(data, profile, cfg, force)
    return data


def collect_all(cfg, now: Optional[datetime] = None, online: Optional[bool] = None,
                force: bool = False) -> List[ProfileUsage]:
    now = now or _now()
    return [collect_profile(p, cfg, now, online, force) for p in cfg.profiles]


# --- formatting ------------------------------------------------------------------------

def human_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def parse_tokens(text: str) -> Optional[int]:
    """'2.5M', '400k', '1 200 000' -> a number of tokens. None if unreadable."""
    cleaned = (text or "").strip().lower().replace(" ", "").replace(",", "").replace("_", "")
    if not cleaned:
        return 0
    scale = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(cleaned[-1])
    if scale:
        cleaned = cleaned[:-1]
    try:
        value = float(cleaned) * (scale or 1)
    except ValueError:
        return None
    return int(value) if value >= 0 else None


def human_delta(delta: Optional[timedelta]) -> str:
    if delta is None:
        return "-"
    minutes = int(delta.total_seconds() // 60)
    if minutes <= 0:
        return "now"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def percent(share: Optional[float]) -> str:
    return f"{int(round(share * 100))}%" if share is not None else "-"


def window_summary(data: ProfileUsage, now: Optional[datetime] = None) -> str:
    """The five-hour window in one line: how full, and when it empties."""
    if not data.has_window:
        return "no open window"
    parts = []
    if data.share is not None:
        used = f"{percent(data.share)} used"
        if data.source != "account" and data.limit > 0:
            used += f" ({human_tokens(data.used)} of {human_tokens(data.limit)} counted here)"
        parts.append(used)
    elif data.used:
        parts.append(f"{human_tokens(data.used)} counted here")
    resets_in = data.resets_in(now)
    if resets_in is not None and data.resets_at is not None:
        parts.append(f"resets in {human_delta(resets_in)} "
                     f"({data.resets_at.astimezone().strftime('%H:%M')})")
    return ", ".join(parts) or "no figures yet"


def week_summary(data: ProfileUsage) -> str:
    if data.weekly_share is not None:
        text = f"{percent(data.weekly_share)} used"
        resets_in = data.weekly_resets_in()
        if resets_in is not None:
            text += f", resets in {human_delta(resets_in)}"
        return text
    if data.source == "account":
        return "no weekly limit on this plan"
    if data.weekly_limit > 0:
        return (f"{human_tokens(data.week.total)} of {human_tokens(data.weekly_limit)} "
                "counted here")
    return f"{human_tokens(data.week.total)} counted here"


class Alerts:
    """Says once per window when a profile is close to its limit.

    Both interfaces ask the same object, so the rule for *when* to warn lives in
    one place and each system only has to know how to show a notification. The
    reset time is what tells one window from the next, so a fresh window warns
    again and a re-read of the same one does not.
    """

    def __init__(self, percent: int = 90):
        self.percent = percent
        self._said: Dict[str, str] = {}      # profile id -> the window it was said for

    def due(self, data: ProfileUsage) -> Optional[str]:
        """The sentence to show, or None when there is nothing to say."""
        share = data.share
        if self.percent <= 0 or share is None or share * 100 < self.percent:
            return None
        at = data.resets_at
        window = at.isoformat() if at else "window"
        if self._said.get(data.profile_id) == window:
            return None
        self._said[data.profile_id] = window
        left = data.resets_in()
        if left is not None and at is not None:
            return (f"{percent(share)} of the 5-hour window is gone. "
                    f"It resets in {human_delta(left)} "
                    f"({at.astimezone().strftime('%H:%M')}).")
        return f"{percent(share)} of the 5-hour window is gone."

    def forget(self, profile_id: str) -> None:
        self._said.pop(profile_id, None)


def text_report(cfg, online: Optional[bool] = None, force: bool = False) -> List[str]:
    """The same figures as the usage window, for `claude-profiles usage`."""
    lines = []
    collected = collect_all(cfg, online=online, force=force)
    for data in collected:
        source = "from your account" if data.source == "account" else "counted on this PC"
        who = data.account_label
        lines.append(f"{data.name} ({data.profile_id})  -  "
                     + (f"{who}, {source}" if who else source))
        lines.append(f"    5-hour window: {window_summary(data)}")
        lines.append(f"    last 7 days:   {week_summary(data)}")
        if data.opus_weekly_share is not None:
            lines.append(f"    ... of it Opus: {percent(data.opus_weekly_share)}")
        models = ", ".join(f"{short_model(m)} {human_tokens(v)}" for m, v in data.week.top_models())
        if models:
            lines.append(f"    by model:      {models} "
                         f"({data.week.messages} messages on this PC)")
        for note in (data.account_note, data.note):
            if note:
                lines.append(f"    {note}")
        if data.source != "account" and data.limit_is_measured:
            lines.append("    (the limit shown is the busiest window so far, not your plan's)")
    for label, names in shared_accounts(collected).items():
        lines.append(f"! {' and '.join(names)} are signed in to the same account ({label}).")
    return lines or ["No profiles yet."]


def shared_accounts(collected: List[ProfileUsage]) -> Dict[str, List[str]]:
    """Accounts that more than one profile is signed into: {account: [profile names]}."""
    from . import usage_online
    return usage_online.duplicates(collected)


def short_model(name: str) -> str:
    """'claude-opus-5-5' -> 'Opus 5.5'; the date a model id may end in is dropped."""
    parts = [p for p in name.split("-") if p and p != "claude"]
    if not parts:
        return name
    family = parts[0].capitalize()
    digits = [p for p in parts[1:] if p.isdigit() and len(p) <= 2][:2]
    return f"{family} {'.'.join(digits)}" if digits else family
