"""How many tokens each profile has spent, and when its window resets.

Claude Code writes one JSON line per message into
`<config dir>/projects/<project>/<session>.jsonl`, and every assistant line
carries the token counts of that request. Reading those files gives a complete
picture of a profile's Claude Code use (the CLI and the Desktop app's Code tab,
which share the folder) without a network call or any credentials.

Two things this cannot know, because they are not in the files:

* the plan's real allowance - the progress bars therefore run against a limit
  you set per profile, or against the busiest window seen so far;
* anything you typed in the Desktop app's chat, which Claude Code never logs.

`usage_online` is the experimental counterpart that asks Claude for the exact
remaining limits instead.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from . import paths

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

    @property
    def used(self) -> int:
        return self.active.totals.total if self.active else 0

    @property
    def share(self) -> Optional[float]:
        """0.0-1.0 of the window's limit, or None when no limit is known."""
        return min(1.0, self.used / self.limit) if self.limit > 0 else None

    @property
    def weekly_share(self) -> Optional[float]:
        return min(1.0, self.week.total / self.weekly_limit) if self.weekly_limit > 0 else None

    def resets_in(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        return self.active.resets_in(now) if self.active else None


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
        usage.note = "No Claude Code activity recorded for this profile yet."
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


def collect_all(cfg, now: Optional[datetime] = None) -> List[ProfileUsage]:
    now = now or _now()
    return [collect(p, now) for p in cfg.profiles]


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


def text_report(cfg, online: bool = False) -> List[str]:
    """The same figures as the usage window, for `claude-profiles usage`."""
    lines = []
    for profile in cfg.profiles:
        data = collect(profile)
        if online:
            from . import usage_online  # only needed for the experimental path
            usage_online.apply_to(data, profile, cfg)
        head = f"{profile.name} ({profile.id})"
        if not data.active:
            lines.append(f"{head}: no open window. {data.note}".rstrip())
        else:
            limit = f" of {human_tokens(data.limit)}" if data.limit > 0 else ""
            share = f" [{int((data.share or 0) * 100)}%]" if data.limit > 0 else ""
            lines.append(f"{head}: {human_tokens(data.used)}{limit}{share} in the 5-hour window, "
                         f"resets in {human_delta(data.resets_in())} "
                         f"({data.active.end.astimezone().strftime('%H:%M')})")
        weekly = f" of {human_tokens(data.weekly_limit)}" if data.weekly_limit > 0 else ""
        lines.append(f"    last 7 days: {human_tokens(data.week.total)}{weekly} "
                     f"in {data.week.messages} messages")
        models = ", ".join(f"{short_model(m)} {human_tokens(v)}" for m, v in data.week.top_models())
        if models:
            lines.append(f"    by model:    {models}")
        if data.limit_is_measured:
            lines.append("    (the limit is the busiest window so far, not your plan's)")
    return lines or ["No profiles yet."]


def short_model(name: str) -> str:
    """'claude-opus-5-5' -> 'Opus 5.5'; the date a model id may end in is dropped."""
    parts = [p for p in name.split("-") if p and p != "claude"]
    if not parts:
        return name
    family = parts[0].capitalize()
    digits = [p for p in parts[1:] if p.isdigit() and len(p) <= 2][:2]
    return f"{family} {'.'.join(digits)}" if digits else family
