"""The token usage window: one set of bars per profile.

A window of its own rather than a page in the loader, because it is something
you leave open while you work. The figures come from each profile's account
(see `core.usage_online`); the transcripts on this PC add the per-model detail
and stand in when an account cannot be reached. Both can take a moment, so the
reading happens on a background thread.
"""

import threading
from typing import Dict, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core import config as cfgmod  # noqa: E402
from ..core import usage as usagemod  # noqa: E402
from . import compat, gui  # noqa: E402

APP_ID = "io.github.claudeprofiles.Usage"
TITLE = "Claude Token Usage"

REFRESH_SECONDS = 60      # ask again
TICK_SECONDS = 20         # move the countdowns along

CSS = """
/* Taller bars than the loader's; the colours come from gui.CSS. */
.usage-bar trough, .usage-bar progress { min-height: 10px; border-radius: 6px; }
.usage-value { font-feature-settings: "tnum"; }
"""

_css_loaded = False


def _load_css() -> None:
    global _css_loaded
    gui._load_css()
    if not _css_loaded:
        compat.load_css(CSS)
        _css_loaded = True


def _level(share: Optional[float]) -> str:
    if share is None:
        return ""
    if share >= 0.9:
        return "level-high"
    if share >= 0.75:
        return "level-warn"
    return ""


class ProfileRow(Gtk.Box):
    """One profile: who it is, the two windows, and whatever needs saying."""

    def __init__(self, window, profile):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin_top=14, margin_bottom=14, margin_start=18, margin_end=18)
        self.profile = profile

        head = Gtk.Box(spacing=12)
        head.append(gui._profile_icon(profile, 36))
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True,
                        valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=profile.name, xalign=0.0)
        name.add_css_class("heading")
        names.append(name)
        self.subtitle = Gtk.Label(label="reading…", xalign=0.0, wrap=True)
        self.subtitle.add_css_class("caption")
        self.subtitle.add_css_class("dim-label")
        names.append(self.subtitle)
        head.append(names)
        limits = Gtk.Button(label="Limits…", valign=Gtk.Align.CENTER)
        limits.connect("clicked", lambda _b: window.open_limits(profile))
        head.append(limits)
        self.append(head)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.bars: Dict[str, dict] = {}
        for row, (key, label) in enumerate((("window", "5-hour window"),
                                            ("week", "Last 7 days"))):
            caption = Gtk.Label(label=label, xalign=0.0, width_chars=13)
            caption.add_css_class("caption")
            caption.add_css_class("dim-label")
            grid.attach(caption, 0, row, 1, 1)
            bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=180)
            bar.add_css_class("usage-bar")
            grid.attach(bar, 1, row, 1, 1)
            value = Gtk.Label(label="-", xalign=0.0, hexpand=True, wrap=True)
            value.add_css_class("caption")
            value.add_css_class("usage-value")
            grid.attach(value, 2, row, 1, 1)
            self.bars[key] = {"bar": bar, "value": value}
        self.append(grid)

        self.note = Gtk.Label(label="", xalign=0.0, wrap=True, visible=False)
        self.note.add_css_class("caption")
        self.note.add_css_class("dim-label")
        self.append(self.note)

    def _set_bar(self, key: str, share: Optional[float], text: str) -> None:
        bar = self.bars[key]["bar"]
        bar.set_fraction(share or 0.0)
        for level in ("level-warn", "level-high"):
            bar.remove_css_class(level)
        level = _level(share)
        if level:
            bar.add_css_class(level)
        self.bars[key]["value"].set_label(text)

    def update_from(self, data: Optional[usagemod.ProfileUsage]) -> None:
        if data is None:
            self.subtitle.set_label("reading…")
            return
        models = ", ".join(f"{usagemod.short_model(m)} {usagemod.human_tokens(v)}"
                           for m, v in data.week.top_models(3))
        source = ("figures from your account" if data.source == "account"
                  else "counted on this PC")
        parts = [p for p in (data.account_label, models, source) if p]
        self.subtitle.set_label(" · ".join(parts))

        if data.has_window:
            self._set_bar("window", data.share, usagemod.window_summary(data))
        else:
            self._set_bar("window", None, "idle - the next message opens a new window")
        self._set_bar("week", data.weekly_share, usagemod.week_summary(data))

        notes = []
        if data.opus_weekly_share is not None:
            notes.append(f"Opus over 7 days: {usagemod.percent(data.opus_weekly_share)}.")
        if data.source != "account" and data.limit_is_measured:
            notes.append("The limit shown is the busiest window so far, not your plan's - "
                         "set your own under Limits.")
        for note in (data.account_note, data.note):
            if note:
                notes.append(note)
        text = " ".join(notes)
        self.note.set_label(text)
        self.note.set_visible(bool(text))


class LimitsDialog:
    """Token budgets to fall back on when the account cannot be asked."""

    def __init__(self, parent, cfg, profile, on_saved):
        self.cfg, self.profile, self.on_saved = cfg, profile, on_saved
        self.win = gui._dialog_window(parent, f"Limits for {profile.name}", width=460)

        view = compat.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.win.close())
        header.pack_start(cancel)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_end(save)
        view.add_top_bar(header)

        self.toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()
        self.toasts.set_child(page)
        view.set_content(self.toasts)
        self.win.set_content(view)

        group = Adw.PreferencesGroup(
            title="Token budget",
            description="Only used when your account cannot be reached: the bars then run "
                        "against these instead. Write them as 2.5M, 400K or a plain number; "
                        "leave a field empty to use the busiest window seen so far.")
        self.rows = {}
        for key, title, current in (("usage_limit", "Per 5-hour window", profile.usage_limit),
                                    ("usage_weekly_limit", "Per 7 days",
                                     profile.usage_weekly_limit)):
            row = compat.EntryRow(title=title)
            row.set_text(usagemod.human_tokens(current) if current else "")
            group.add(row)
            self.rows[key] = row
        page.add(group)
        self.win.present()

    def _save(self, _btn) -> None:
        values = {}
        for key, row in self.rows.items():
            parsed = usagemod.parse_tokens(row.get_text())
            if parsed is None:
                self.toasts.add_toast(Adw.Toast.new(f"\"{row.get_text()}\" is not a number "
                                                    "of tokens."))
                return
            values[key] = parsed
        for key, value in values.items():
            setattr(self.profile, key, value)
        try:
            cfgmod.save(self.cfg)
        except cfgmod.ConfigError as e:
            self.toasts.add_toast(Adw.Toast.new(str(e)))
            return
        self.win.close()
        self.on_saved()


class UsageWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=TITLE, default_width=680, default_height=520)
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.rows: Dict[str, ProfileRow] = {}
        self.data: Dict[str, usagemod.ProfileUsage] = {}
        self.alerts = usagemod.Alerts(self.cfg.usage_alert_percent)
        self.busy = False

        view = compat.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title=TITLE, subtitle="")
        header.set_title_widget(self.title)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_btn.connect("clicked", lambda _b: self.refresh())
        header.pack_end(self.refresh_btn)
        view.add_top_bar(header)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self.box)
        view.set_content(scroller)

        footer = Gtk.Label(label="Percentages and reset times come from each profile's account; "
                                "the per-model detail is read from this PC's Claude Code history.",
                           wrap=True, margin_top=8, margin_bottom=10,
                           margin_start=18, margin_end=18)
        footer.add_css_class("caption")
        footer.add_css_class("dim-label")
        view.add_bottom_bar(footer)
        self.set_content(view)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.build()
        self.refresh()
        GLib.timeout_add_seconds(TICK_SECONDS, self._tick)
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._auto_refresh)

    def _on_key(self, _c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval == Gdk.KEY_F5:
            self.refresh()
            return True
        return False

    # --- building ------------------------------------------------------------------

    def build(self) -> None:
        child = self.box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.box.remove(child)
            child = nxt
        self.rows = {}
        if not self.cfg.profiles:
            self.box.append(Adw.StatusPage(icon_name="utilities-system-monitor-symbolic",
                                           title="No profiles yet",
                                           description="Add one in the loader."))
            return
        for index, profile in enumerate(self.cfg.profiles):
            if index:
                self.box.append(Gtk.Separator())
            row = ProfileRow(self, profile)
            self.box.append(row)
            self.rows[profile.id] = row
        self._paint()

    def _paint(self) -> None:
        for pid, row in self.rows.items():
            row.update_from(self.data.get(pid))
        if self.data:
            counted = sum(d.week.total for d in self.data.values())
            self.title.set_subtitle(
                f"{usagemod.human_tokens(counted)} over 7 days on this PC · "
                f"checked {GLib.DateTime.new_now_local().format('%H:%M')}")

    # --- reading -------------------------------------------------------------------

    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.refresh_btn.set_sensitive(False)
        cfg = self.cfg

        def work():
            collected = {}
            for profile in cfg.profiles:
                try:
                    collected[profile.id] = usagemod.collect_profile(profile, cfg, force=True)
                except Exception as e:  # one broken profile must not stop the rest
                    collected[profile.id] = usagemod.ProfileUsage(
                        profile_id=profile.id, name=profile.name,
                        note=f"Could not read this profile: {e}")
            GLib.idle_add(self._done, collected)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, collected) -> bool:
        self.busy = False
        self.refresh_btn.set_sensitive(True)
        self.data = collected
        self._paint()
        for data in collected.values():
            message = self.alerts.due(data)
            if message:
                self.notify(data.name, message)
        return False

    def notify(self, profile_name: str, body: str) -> None:
        """A desktop notification; GNOME shows it under this window's menu entry."""
        app = self.get_application()
        if app is None:
            return
        note = Gio.Notification.new(f"Claude ({profile_name})")
        note.set_body(body)
        app.send_notification(f"claude-usage-{profile_name}", note)

    def _tick(self) -> bool:
        self._paint()          # the countdowns move without asking again
        return True

    def _auto_refresh(self) -> bool:
        self.refresh()
        return True

    # --- actions -------------------------------------------------------------------

    def open_limits(self, profile) -> None:
        LimitsDialog(self, self.cfg, profile, self.reload)

    def reload(self) -> None:
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.build()
        self.refresh()


class UsageApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        _load_css()
        win = self.props.active_window or UsageWindow(self)
        win.present()


def run(plat) -> int:
    return UsageApp().run([])
