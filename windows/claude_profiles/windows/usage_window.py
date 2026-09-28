"""The token usage window: one set of bars per profile.

A separate window rather than part of the loader, because it is something you
leave open while you work. The figures come from each profile's account (see
`core.usage_online`); the transcripts on this PC add the per-model detail and
stand in when an account cannot be reached. Both can take a moment, so the
reading happens on a background thread.
"""

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Dict, Optional

from ..core import config as cfgmod
from ..core import usage as usagemod

from . import gui, integration, winutil

TITLE = integration.USAGE_TITLE
USAGE_MUTEX = "ClaudeProfilesUsage"

REFRESH_MS = 60_000      # re-read the transcripts
TICK_MS = 20_000         # move the countdowns along


class ProfileRow(ttk.Frame):
    def __init__(self, parent, profile, on_limits):
        super().__init__(parent, padding=(14, 12))
        theme = gui._theme
        self.profile = profile
        self.columnconfigure(1, weight=1)
        bar_width = int(240 * theme.scale)

        icon = tk.Label(self, image=gui.profile_image(self, profile, int(36 * theme.scale)),
                        bg=theme.bg)
        icon.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))
        ttk.Label(self, text=profile.name, font=("Segoe UI Semibold", 11)).grid(
            row=0, column=1, sticky="w")
        self.summary = ttk.Label(self, text="reading…", style="Sub.TLabel")
        self.summary.grid(row=1, column=1, sticky="w")
        ttk.Button(self, text="Limits…", command=lambda: on_limits(profile)).grid(
            row=0, column=2, rowspan=2, sticky="ne")

        self.bars: Dict[str, dict] = {}
        for row, (key, label) in enumerate((("window", "5-hour window"), ("week", "Last 7 days")),
                                           start=2):
            ttk.Label(self, text=label, style="Sub.TLabel", width=14).grid(
                row=row, column=0, columnspan=1, sticky="w", pady=(8, 0))
            holder = ttk.Frame(self)
            holder.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(8, 0))
            bar = gui.Bar(holder, bar_width)
            bar.pack(side="left", pady=(4, 0))
            value = ttk.Label(holder, text="-", style="Sub.TLabel")
            value.pack(side="left", padx=(10, 0))
            self.bars[key] = {"bar": bar, "value": value}

        self.note = ttk.Label(self, text="", style="Sub.TLabel", wraplength=int(420 * theme.scale))
        self.note.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def update_from(self, data: Optional[usagemod.ProfileUsage]) -> None:
        if data is None:
            self.summary.configure(text="reading…")
            return
        human = usagemod.human_tokens
        models = ", ".join(f"{usagemod.short_model(m)} {human(v)}"
                           for m, v in data.week.top_models(3))
        parts = [p for p in (data.account_label, models) if p]
        self.summary.configure(text=" · ".join(parts) or "no activity in the last 7 days")

        window = self.bars["window"]
        window["bar"].set(data.share)
        if data.has_window:
            window["value"].configure(text=usagemod.window_summary(data),
                                      foreground=gui.level_color(data.share))
        else:
            window["bar"].set(None)
            window["value"].configure(text="idle - the next message opens a new window",
                                      foreground=gui._theme.sub)

        week = self.bars["week"]
        week["bar"].set(data.weekly_share)
        week["value"].configure(text=usagemod.week_summary(data),
                                foreground=gui.level_color(data.weekly_share))

        notes = []
        if data.source == "account":
            notes.append("Percentages and reset times come from your account.")
            if data.opus_weekly_share is not None:
                notes.append(f"Opus over 7 days: {usagemod.percent(data.opus_weekly_share)}.")
        elif data.limit > 0 and data.limit_is_measured:
            notes.append(f"The limit shown is the busiest window so far ({human(data.limit)}); "
                         "set your plan's real figure under Limits.")
        elif data.limit <= 0:
            notes.append("No limit known yet, so only the amount used is shown.")
        for note in (data.account_note, data.note):
            if note:
                notes.append(note)
        self.note.configure(text=" ".join(notes))


class LimitsDialog(gui.Dialog):
    """Per-profile token budgets, so the bars mean something."""

    def __init__(self, parent, cfg, profile, on_saved):
        super().__init__(parent, f"Token limits for {profile.name}")
        self.cfg, self.profile, self.on_saved = cfg, profile, on_saved
        body = self.body
        ttk.Label(body, text="How many tokens this account may spend before Claude stops. "
                             "Leave a field empty to let the busiest window so far stand in.",
                  wraplength=420, justify="left").pack(anchor="w", pady=(0, 10))
        self.fields = {}
        for key, label, current in (
                ("usage_limit", "Per 5-hour window", profile.usage_limit),
                ("usage_weekly_limit", "Per 7 days", profile.usage_weekly_limit)):
            ttk.Label(body, text=label).pack(anchor="w")
            var = tk.StringVar(value=usagemod.human_tokens(current) if current else "")
            entry = ttk.Entry(body, textvariable=var, width=18)
            entry.pack(anchor="w", pady=(2, 8))
            self.fields[key] = var
        ttk.Label(body, text="Write them as 2.5M, 400K or a plain number.",
                  style="Sub.TLabel").pack(anchor="w")
        self.error = ttk.Label(body, text="", style="Error.TLabel", wraplength=420)
        self.error.pack(anchor="w", pady=(8, 0))
        self.buttons(("Cancel", self.cancel, False), ("Save", self.save, True))
        self.show()

    def save(self) -> None:
        values = {}
        for key, var in self.fields.items():
            parsed = usagemod.parse_tokens(var.get())
            if parsed is None:
                self.error.configure(text=f"\"{var.get()}\" is not a number of tokens.")
                return
            values[key] = parsed
        for key, value in values.items():
            setattr(self.profile, key, value)
        try:
            cfgmod.save(self.cfg)
        except cfgmod.ConfigError as e:
            self.error.configure(text=str(e))
            return
        self.destroy()
        self.on_saved()


class UsageWindow:
    def __init__(self, root: tk.Tk, plat):
        self.root, self.plat = root, plat
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.data: Dict[str, usagemod.ProfileUsage] = {}
        self.rows: Dict[str, ProfileRow] = {}
        self.events: "queue.Queue" = queue.Queue()
        self.busy = False
        theme = gui._theme

        root.title(TITLE)
        root.minsize(int(560 * theme.scale), int(300 * theme.scale))

        header = ttk.Frame(root, padding=(18, 14, 18, 4))
        header.pack(fill="x")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="Token usage", style="Title.TLabel").pack(anchor="w")
        self.subtitle = ttk.Label(titles, text="", style="Sub.TLabel")
        self.subtitle.pack(anchor="w")
        self.refresh_btn = ttk.Button(header, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side="right")

        self.content = ttk.Frame(root, padding=(4, 4))
        self.content.pack(fill="both", expand=True)

        footer = ttk.Frame(root, padding=(18, 4, 18, 14))
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text="Counted from this PC's Claude Code history "
                               "(the CLI and the Desktop app's Code tab).",
                  style="Sub.TLabel").pack(side="left")

        self.build()
        root.bind("<Escape>", lambda _e: root.destroy())
        root.bind("<F5>", lambda _e: self.refresh())
        root.after(200, self._poll)
        self.refresh()
        root.after(TICK_MS, self._tick)
        root.after(REFRESH_MS, self._auto_refresh)

    # --- building --------------------------------------------------------------

    def build(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self.rows = {}
        if not self.cfg.profiles:
            ttk.Label(self.content, text="No profiles yet.", padding=20).pack()
            return
        for index, profile in enumerate(self.cfg.profiles):
            if index:
                ttk.Separator(self.content).pack(fill="x", padx=14)
            row = ProfileRow(self.content, profile, self.open_limits)
            row.pack(fill="x")
            self.rows[profile.id] = row
        self._paint()

    def _paint(self) -> None:
        for pid, row in self.rows.items():
            row.update_from(self.data.get(pid))
        total = sum(d.used for d in self.data.values())
        week = sum(d.week.total for d in self.data.values())
        if self.data:
            self.subtitle.configure(
                text=f"{usagemod.human_tokens(total)} in the open windows · "
                     f"{usagemod.human_tokens(week)} over 7 days · "
                     f"checked {datetime.now().strftime('%H:%M')}")

    # --- refreshing -------------------------------------------------------------

    def _poll(self) -> None:
        try:
            while True:
                callback, args = self.events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.refresh_btn.state(["disabled"])
        cfg = self.cfg

        def work():
            collected = {}
            for profile in cfg.profiles:
                try:
                    data = usagemod.collect_profile(profile, cfg, force=True)
                except Exception as e:  # a broken transcript must not stop the rest
                    data = usagemod.ProfileUsage(profile_id=profile.id, name=profile.name,
                                                 note=f"Could not read the history: {e}")
                collected[profile.id] = data
            return collected

        def run():
            try:
                result = work()
            except Exception:
                result = {}
            self.events.put((self._done, (result,)))

        threading.Thread(target=run, daemon=True).start()

    def _done(self, collected: Dict[str, usagemod.ProfileUsage]) -> None:
        self.busy = False
        self.refresh_btn.state(["!disabled"])
        self.data = collected
        self._paint()

    def _tick(self) -> None:
        self._paint()
        self.root.after(TICK_MS, self._tick)

    def _auto_refresh(self) -> None:
        self.refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    # --- actions -----------------------------------------------------------------

    def open_limits(self, profile) -> None:
        LimitsDialog(self.root, self.cfg, profile, self.reload)

    def reload(self) -> None:
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.build()
        self.refresh()


def run(plat) -> int:
    mutex = winutil.NamedMutex(USAGE_MUTEX)
    if mutex.already_exists:
        winutil.focus_window(TITLE)
        return 0
    winutil.set_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    gui._prepare_root(root)
    gui._PLAT = plat
    UsageWindow(root, plat)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.mainloop()
    mutex.close()
    return 0
