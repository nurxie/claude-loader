"""GTK 4 / libadwaita user interface: the loader and small dialogs."""

import shutil
import subprocess
import threading
from typing import Callable, List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ..core import VERSION  # noqa: E402
from ..core import config as cfgmod  # noqa: E402
from ..core import launch, paths, security  # noqa: E402
from ..core.tui import profile_folders  # noqa: E402
from . import integration, system  # noqa: E402

APP_ID = integration.LOADER_APP_ID
_PLAT = None  # set by run_loader()

CSS = """
.profile-card {
  padding: 14px 10px 12px 10px;
  border-radius: 16px;
  min-width: 128px;
}
.profile-card:hover { background: alpha(currentColor, 0.06); }
.profile-card.selected {
  background: alpha(@accent_bg_color, 0.18);
  box-shadow: inset 0 0 0 2px @accent_bg_color;
}
.profile-card:focus-visible { box-shadow: inset 0 0 0 2px alpha(@accent_bg_color, 0.6); }
.profile-name { font-weight: bold; }
.badge {
  border-radius: 999px;
  padding: 3px;
  min-width: 14px;
  min-height: 14px;
}
.badge.check { background: @accent_bg_color; color: @accent_fg_color; }
.badge.lock { background: alpha(@window_bg_color, 0.9); }
.running-dot { color: @success_color; }
.hint { opacity: 0.65; }
.capture-key { font-size: 20px; font-weight: bold; }
"""

_css_loaded = False


def _load_css() -> None:
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(CSS)
    else:
        provider.load_from_data(CSS.encode("utf-8"), -1)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


def _icon_widget(path: str, size: int) -> Gtk.Image:
    try:
        image = Gtk.Image.new_from_paintable(Gdk.Texture.new_from_filename(path))
    except GLib.Error:
        image = Gtk.Image.new_from_icon_name("application-x-executable")
    image.set_pixel_size(size)
    return image


def _profile_icon(profile, size: int) -> Gtk.Image:
    path = integration.icon_path(profile)
    if not path.exists():
        try:
            integration.build_icons(cfgmod.load() or cfgmod.Config(profiles=[profile]))
        except Exception:
            pass
    return _icon_widget(str(path), size)


def confirm(parent, heading: str, body: str, responses, callback: Callable[[str], None]) -> None:
    """responses: [(id, label, destructive_or_suggested_or_None)], first is the cancel one."""
    if hasattr(Adw, "AlertDialog"):
        dialog = Adw.AlertDialog.new(heading, body)
    else:
        dialog = Adw.MessageDialog.new(parent, heading, body)
    for rid, label, look in responses:
        dialog.add_response(rid, label)
        if look == "destructive":
            dialog.set_response_appearance(rid, Adw.ResponseAppearance.DESTRUCTIVE)
        elif look == "suggested":
            dialog.set_response_appearance(rid, Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response(responses[0][0])
    dialog.set_default_response(responses[0][0])
    dialog.connect("response", lambda _d, rid: callback(rid))
    if hasattr(Adw, "AlertDialog") and isinstance(dialog, Adw.AlertDialog):
        dialog.present(parent)
    else:
        dialog.present()


def _dialog_window(parent, title: str, width=460, height=-1) -> Adw.Window:
    win = Adw.Window(title=title, modal=parent is not None, default_width=width,
                     default_height=height)
    if parent is not None:
        win.set_transient_for(parent)
    esc = Gtk.EventControllerKey()
    esc.connect("key-pressed", lambda _c, kv, _k, _s: kv == Gdk.KEY_Escape and (win.close() or True))
    win.add_controller(esc)
    return win


# --- password prompt ----------------------------------------------------------------

class PasswordWindow:
    """Asks for a password; calls on_done(True/False) exactly once."""

    MAX_ATTEMPTS = 5

    def __init__(self, parent, title: str, verify: Callable[[str], bool],
                 on_done: Callable[[bool], None]):
        self.verify, self.on_done, self.finished, self.attempts = verify, on_done, False, 0
        self.win = _dialog_window(parent, "Password required", width=380)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        lock = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
        lock.set_pixel_size(48)
        lock.add_css_class("dim-label")
        box.append(lock)
        heading = Gtk.Label(label=title, wrap=True, justify=Gtk.Justification.CENTER)
        heading.add_css_class("title-3")
        box.append(heading)

        self.entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        self.entry.set_property("placeholder-text", "Password")
        self.entry.connect("activate", self._submit)
        box.append(self.entry)

        self.error = Gtk.Label(label="", visible=False)
        self.error.add_css_class("error")
        box.append(self.error)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.win.close())
        ok = Gtk.Button(label="Unlock")
        ok.add_css_class("suggested-action")
        ok.connect("clicked", self._submit)
        buttons.append(cancel)
        buttons.append(ok)
        box.append(buttons)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_title=False)
        view.add_top_bar(header)
        view.set_content(box)
        self.win.set_content(view)
        self.win.connect("close-request", self._on_close)
        self.win.present()
        self.entry.grab_focus()

    def _finish(self, ok: bool) -> None:
        if not self.finished:
            self.finished = True
            self.on_done(ok)

    def _on_close(self, _win) -> bool:
        self._finish(False)
        return False

    def _submit(self, *_a) -> None:
        if self.verify(self.entry.get_text()):
            self._finish(True)
            self.win.close()
            return
        self.attempts += 1
        self.entry.set_text("")
        if self.attempts >= self.MAX_ATTEMPTS:
            self.win.close()
            return
        self.error.set_label("Wrong password, try again.")
        self.error.set_visible(True)
        self.entry.add_css_class("error")


def _run_blocking(build) -> object:
    """Run a one-window app until it reports a result; used outside the loader."""
    result = {"value": None}
    app = Adw.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)

    def done(value):
        result["value"] = value
        GLib.idle_add(app.quit)

    def on_activate(a):
        _load_css()
        win = build(done)
        a.add_window(win)

    app.connect("activate", on_activate)
    app.run([])
    return result["value"]


def ask_password_blocking(title: str, verify: Callable[[str], bool]) -> bool:
    return bool(_run_blocking(lambda done: PasswordWindow(None, title, verify, done).win))


def choose_profile_blocking(profiles, question: str):
    def build(done):
        win = _dialog_window(None, "Choose a Claude profile", width=420)
        chosen = {"done": False}

        def pick(profile):
            chosen["done"] = True
            done(profile)
            win.close()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        label = Gtk.Label(label=question, wrap=True)
        label.add_css_class("title-4")
        box.append(label)
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        for p in profiles:
            row = Adw.ActionRow(title=p.name, activatable=True)
            row.add_prefix(_profile_icon(p, 32))
            row.connect("activated", lambda _r, p=p: pick(p))
            listbox.append(row)
        box.append(listbox)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(box)
        win.set_content(view)
        win.connect("close-request", lambda _w: (chosen["done"] or done(None)) and False)
        win.present()
        return win

    return _run_blocking(build)


# --- hotkey capture ---------------------------------------------------------------------

MODIFIER_KEYS = {Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
                 Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
                 Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
                 Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_Caps_Lock}


def capture_hotkey(parent, on_done: Callable[[Optional[str]], None]) -> None:
    """Let the user press a shortcut. on_done(accel) or nothing if cancelled."""
    win = Adw.Window(title="New shortcut", modal=True, transient_for=parent, default_width=380)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                  margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
    box.append(Gtk.Label(label="Press the new shortcut for the loader", wrap=True))
    shown = Gtk.Label(label="…")
    shown.add_css_class("capture-key")
    box.append(shown)
    hint = Gtk.Label(label="Use at least one of Ctrl, Alt or Super. Esc cancels.", wrap=True)
    hint.add_css_class("hint")
    box.append(hint)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar(show_title=False))
    view.set_content(box)
    win.set_content(view)

    ctrl = Gtk.EventControllerKey()

    def on_key(_c, keyval, _code, state):
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if keyval == Gdk.KEY_Escape and not mods:
            win.close()
            return True
        if keyval in MODIFIER_KEYS:
            return True
        keyval = Gdk.keyval_to_lower(keyval)
        useful = mods & ~Gdk.ModifierType.SHIFT_MASK
        if not useful:
            hint.set_label("Add Ctrl, Alt or Super to the key.")
            return True
        accel = Gtk.accelerator_name(keyval, mods)
        if not integration.valid_hotkey(accel):
            hint.set_label(f"{accel} cannot be used, try another key.")
            return True
        shown.set_label(integration.hotkey_label(accel))
        GLib.timeout_add(350, lambda: (win.close(), on_done(accel)) and False)
        return True

    ctrl.connect("key-pressed", on_key)
    win.add_controller(ctrl)
    win.present()


# --- add / edit profile ------------------------------------------------------------------

COLOR_KEYS = list(cfgmod.COLORS)


class ProfileDialog:
    """Add a new profile (profile=None) or edit an existing one."""

    def __init__(self, parent, cfg, profile, on_saved: Callable[[], None]):
        self.parent, self.cfg, self.profile, self.on_saved = parent, cfg, profile, on_saved
        self.is_new = profile is None
        self.custom_dir: Optional[str] = None
        title = "Add profile" if self.is_new else f"Edit {profile.name}"
        self.win = _dialog_window(parent, title, width=520, height=640)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.win.close())
        header.pack_start(cancel)
        self.save_btn = Gtk.Button(label="Add" if self.is_new else "Save")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._save)
        header.pack_end(self.save_btn)
        view.add_top_bar(header)

        self.toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()
        self.toasts.set_child(page)
        view.set_content(self.toasts)
        self.win.set_content(view)

        # Profile
        group = Adw.PreferencesGroup(title="Profile")
        self.name_row = Adw.EntryRow(title="Name")
        self.name_row.set_text(profile.name if profile else self._default_name())
        group.add(self.name_row)
        self.color_row = Adw.ComboRow(title="Icon color")
        self.color_row.set_model(Gtk.StringList.new([cfgmod.COLORS[k][0] for k in COLOR_KEYS]))
        color = profile.color if profile else cfgmod.next_color(cfg)
        self.color_row.set_selected(COLOR_KEYS.index(color))
        group.add(self.color_row)
        page.add(group)

        # Data folder
        group = Adw.PreferencesGroup(title="Data folder",
                                     description="Where this profile keeps its login, settings "
                                                 "and history.")
        if self.is_new:
            self.location_keys = ["own"]
            labels = ["Separate folder"]
            if not cfg.system_default_profile():
                self.location_keys.append("std")
                labels.append("Standard Claude folders")
            self.location_keys.append("custom")
            labels.append("Custom folder")
            self.location_row = Adw.ComboRow(title="Location")
            self.location_row.set_model(Gtk.StringList.new(labels))
            group.add(self.location_row)
            self.path_row = Adw.ActionRow(title="Folder")
            self.pick_btn = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
            self.pick_btn.connect("clicked", self._pick_folder)
            self.path_row.add_suffix(self.pick_btn)
            group.add(self.path_row)
        else:
            row = Adw.ActionRow(title="Folder", subtitle=profile.data_location)
            row.set_subtitle_selectable(True)
            group.add(row)
            note = Adw.ActionRow(title="The folder of an existing profile cannot be changed",
                                 subtitle="Create a new profile to use a different folder.")
            note.add_css_class("dim-label")
            group.add(note)
        page.add(group)

        # Password
        group = Adw.PreferencesGroup(
            title="Password",
            description="A simple lock: the loader and the menu entry ask for it before "
                        "starting this profile. Files are not encrypted.")
        self.pw_switch = Adw.SwitchRow(title="Ask for a password")
        self.pw_switch.set_active(bool(profile and profile.password))
        group.add(self.pw_switch)
        self.pw1 = Adw.PasswordEntryRow(title="New password" if self.is_new or not
                                        (profile and profile.password) else
                                        "New password (empty keeps the current one)")
        self.pw2 = Adw.PasswordEntryRow(title="Repeat password")
        group.add(self.pw1)
        group.add(self.pw2)
        page.add(group)

        # CLI
        group = Adw.PreferencesGroup(title="Terminal")
        self.cli_switch = Adw.SwitchRow(title="Claude Code terminal command")
        self.cli_switch.set_active(profile.cli if profile else
                                   (any(p.cli for p in cfg.profiles) or not cfg.profiles))
        group.add(self.cli_switch)
        page.add(group)

        # Connect only now: the handlers touch rows created above.
        self.name_row.connect("changed", lambda *_: self._update_ids())
        if self.is_new:
            self.location_row.connect("notify::selected", lambda *_: self._update_ids())
        self.pw_switch.connect("notify::active", lambda *_: self._update_pw_rows())
        self._update_ids()
        self._update_pw_rows()
        self.win.present()

    def _default_name(self) -> str:
        taken = {p.name.lower() for p in self.cfg.profiles}
        for n in ["Work", "Personal", "Profile 3", "Profile 4", "Profile 5", "Profile 6"]:
            if n.lower() not in taken:
                return n
        return "Profile"

    def _new_id(self) -> str:
        return cfgmod.make_id(self.name_row.get_text() or "profile",
                              {p.id for p in self.cfg.profiles})

    def _location(self) -> str:
        return self.location_keys[self.location_row.get_selected()] if self.is_new else ""

    def _update_ids(self) -> None:
        pid = self._new_id() if self.is_new else self.profile.id
        self.cli_switch.set_subtitle(f"claude-{pid}")
        if not self.is_new:
            return
        loc = self._location()
        self.pick_btn.set_visible(loc == "custom")
        if loc == "std":
            self.path_row.set_subtitle("~/.config/Claude and ~/.claude")
        elif loc == "custom":
            self.path_row.set_subtitle(paths.short(self.custom_dir) if self.custom_dir
                                       else "Not chosen yet")
        else:
            self.path_row.set_subtitle(paths.short(cfgmod.default_data_dir(pid)))

    def _update_pw_rows(self) -> None:
        on = self.pw_switch.get_active()
        self.pw1.set_visible(on)
        self.pw2.set_visible(on)

    def _pick_folder(self, _btn) -> None:
        dialog = Gtk.FileDialog(title="Choose the profile data folder")

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:
                return
            if folder and folder.get_path():
                self.custom_dir = folder.get_path()
                self._update_ids()

        dialog.select_folder(self.win, None, done)

    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    def _save(self, _btn) -> None:
        name = self.name_row.get_text().strip()
        others = [p for p in self.cfg.profiles if p is not self.profile]
        if not name:
            return self._toast("Enter a name.")
        if len(name) > 40:
            return self._toast("Keep the name under 40 characters.")
        if name.lower() in {p.name.lower() for p in others}:
            return self._toast("A profile with this name already exists.")

        password = self.profile.password if self.profile else None
        if self.pw_switch.get_active():
            pw1, pw2 = self.pw1.get_text(), self.pw2.get_text()
            if pw1 or pw2 or not password:
                if not pw1:
                    return self._toast("Enter a password or turn the switch off.")
                if pw1 != pw2:
                    return self._toast("The passwords do not match.")
                password = security.hash_password(pw1)
        else:
            password = None

        color = COLOR_KEYS[self.color_row.get_selected()]
        if self.is_new:
            if len(self.cfg.profiles) >= cfgmod.MAX_PROFILES:
                return self._toast(f"At most {cfgmod.MAX_PROFILES} profiles are supported.")
            pid = self._new_id()
            loc = self._location()
            if loc == "custom" and not self.custom_dir:
                return self._toast("Choose a folder first.")
            data_dir = {"own": cfgmod.default_data_dir(pid), "std": "",
                        "custom": self.custom_dir}[loc]
            profile = cfgmod.Profile(id=pid, name=name, color=color, data_dir=data_dir or "",
                                     system_default=loc == "std", password=password,
                                     cli=self.cli_switch.get_active())
            self.cfg.profiles.append(profile)
        else:
            profile = self.profile
            profile.name, profile.color, profile.password = name, color, password
            profile.cli = self.cli_switch.get_active()

        try:
            cfgmod.save(self.cfg)
            integration.apply(self.cfg)
            cfgmod.save(self.cfg)
        except cfgmod.ConfigError as e:
            if self.is_new:
                self.cfg.profiles.remove(profile)
            return self._toast(str(e))
        self.win.close()
        self.on_saved()


# --- settings ------------------------------------------------------------------------------

class SettingsDialog:
    def __init__(self, parent, cfg, on_saved: Callable[[], None]):
        self.parent, self.cfg, self.on_saved = parent, cfg, on_saved
        self.hotkey = cfg.loader.hotkey
        self.win = _dialog_window(parent, "Loader settings", width=540, height=660)

        view = Adw.ToolbarView()
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

        group = Adw.PreferencesGroup(title="Hotkey")
        self.hotkey_row = Adw.ActionRow(title="Open the loader")
        change = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda _b: capture_hotkey(self.win, self._set_hotkey))
        clear = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="No hotkey")
        clear.add_css_class("flat")
        clear.connect("clicked", lambda _b: self._set_hotkey(None))
        self.hotkey_row.add_suffix(change)
        self.hotkey_row.add_suffix(clear)
        group.add(self.hotkey_row)
        page.add(group)

        group = Adw.PreferencesGroup(title="Loader")
        self.close_switch = Adw.SwitchRow(title="Close after starting a profile")
        self.close_switch.set_active(cfg.loader.close_after_launch)
        group.add(self.close_switch)
        self.update_switch = Adw.SwitchRow(title="Check for Claude Desktop updates on start")
        self.update_switch.set_active(cfg.loader.check_updates)
        group.add(self.update_switch)
        self.pw_switch = Adw.SwitchRow(title="Ask for a password when the loader opens")
        self.pw_switch.set_active(bool(cfg.loader.password))
        self.pw_switch.connect("notify::active", lambda *_: self._update_pw_rows())
        group.add(self.pw_switch)
        self.pw1 = Adw.PasswordEntryRow(title="New password" if not cfg.loader.password
                                        else "New password (empty keeps the current one)")
        self.pw2 = Adw.PasswordEntryRow(title="Repeat password")
        group.add(self.pw1)
        group.add(self.pw2)
        page.add(group)

        group = Adw.PreferencesGroup(title="When I sign in",
                                     description="Profiles with a password ask for it first.")
        self.login_switch = Adw.SwitchRow(title="Open the loader")
        self.login_switch.set_active(cfg.loader.open_at_login)
        group.add(self.login_switch)
        self.autostart_switches = {}
        for p in cfg.profiles:
            row = Adw.SwitchRow(title=f"Start {p.name}")
            row.set_active(p.id in cfg.autostart_profiles)
            self.autostart_switches[p.id] = row
            group.add(row)
        page.add(group)

        group = Adw.PreferencesGroup(
            title="Sign-in links",
            description="\"Continue with Google\" returns to Claude through a claude:// link. "
                        "With routing on, the link goes to the profile that is running, or you "
                        "are asked which one should get it.")
        self.url_switch = Adw.SwitchRow(title="Route claude:// links to the right profile")
        self.url_switch.set_active(cfg.url_handler)
        group.add(self.url_switch)
        page.add(group)

        group = Adw.PreferencesGroup(title="Maintenance")
        repair = Adw.ActionRow(title="Recreate menu entries, icons and commands",
                               subtitle="Useful after Claude Desktop changed its icon")
        btn = Gtk.Button(label="Repair", valign=Gtk.Align.CENTER)
        btn.connect("clicked", self._repair)
        repair.add_suffix(btn)
        group.add(repair)
        uninstall = Adw.ActionRow(title="Uninstall claude-profiles",
                                  subtitle="Opens a terminal with `claude-profiles uninstall`")
        btn = Gtk.Button(label="Uninstall…", valign=Gtk.Align.CENTER)
        btn.add_css_class("destructive-action")
        btn.connect("clicked", self._uninstall)
        uninstall.add_suffix(btn)
        group.add(uninstall)
        page.add(group)

        self._update_hotkey_row()
        self._update_pw_rows()
        self.win.present()

    def _set_hotkey(self, accel: Optional[str]) -> None:
        self.hotkey = accel
        self._update_hotkey_row()
        if accel:
            conflicts = integration.hotkey_conflicts(accel)
            if conflicts:
                self.toasts.add_toast(Adw.Toast.new(f"Also used by: {', '.join(conflicts)}"))

    def _update_hotkey_row(self) -> None:
        self.hotkey_row.set_subtitle(integration.hotkey_label(self.hotkey))

    def _update_pw_rows(self) -> None:
        on = self.pw_switch.get_active()
        self.pw1.set_visible(on)
        self.pw2.set_visible(on)

    def _repair(self, _btn) -> None:
        integration.rebuild_icons()
        warnings = integration.apply(self.cfg)
        cfgmod.save(self.cfg)
        self.toasts.add_toast(Adw.Toast.new(warnings[0] if warnings else "Done."))
        self.on_saved()

    def _uninstall(self, _btn) -> None:
        cmd = [str(paths.MAIN_CMD), "uninstall"]
        for term in (["gnome-terminal", "--"], ["kgx", "--"], ["x-terminal-emulator", "-e"]):
            if shutil.which(term[0]):
                subprocess.Popen(term + cmd, start_new_session=True)
                self.parent.get_application().quit()
                return
        self.toasts.add_toast(Adw.Toast.new("Run `claude-profiles uninstall` in a terminal."))

    def _save(self, _btn) -> None:
        loader = self.cfg.loader
        if self.pw_switch.get_active():
            pw1, pw2 = self.pw1.get_text(), self.pw2.get_text()
            if pw1 or pw2 or not loader.password:
                if not pw1:
                    self.toasts.add_toast(Adw.Toast.new("Enter a password or turn it off."))
                    return
                if pw1 != pw2:
                    self.toasts.add_toast(Adw.Toast.new("The passwords do not match."))
                    return
                loader.password = security.hash_password(pw1)
        else:
            loader.password = None
        loader.hotkey = self.hotkey
        loader.close_after_launch = self.close_switch.get_active()
        loader.check_updates = self.update_switch.get_active()
        loader.open_at_login = self.login_switch.get_active()
        self.cfg.autostart_profiles = [pid for pid, row in self.autostart_switches.items()
                                       if row.get_active()]
        self.cfg.url_handler = self.url_switch.get_active()
        cfgmod.save(self.cfg)
        warnings = integration.apply(self.cfg)
        cfgmod.save(self.cfg)
        self.win.close()
        self.on_saved(warnings)


# --- the loader ----------------------------------------------------------------------------

class ProfileCard(Gtk.Box):
    def __init__(self, window, profile):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, focusable=True)
        self.window, self.profile = window, profile
        self.add_css_class("profile-card")
        self.set_tooltip_text("Click to start. Hold to select several. Right-click for options.")
        self._long_pressed = False

        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER)
        overlay.set_child(_profile_icon(profile, 88))
        self.check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        self.check.add_css_class("badge")
        self.check.add_css_class("check")
        self.check.set_halign(Gtk.Align.END)
        self.check.set_valign(Gtk.Align.START)
        self.check.set_visible(False)
        overlay.add_overlay(self.check)
        if profile.password:
            lock = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
            lock.add_css_class("badge")
            lock.add_css_class("lock")
            lock.set_halign(Gtk.Align.START)
            lock.set_valign(Gtk.Align.END)
            overlay.add_overlay(lock)
        self.append(overlay)

        name = Gtk.Label(label=profile.name, ellipsize=Pango.EllipsizeMode.END,
                         max_width_chars=16)
        name.add_css_class("profile-name")
        self.append(name)
        self.status = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.END, max_width_chars=18)
        self.status.add_css_class("caption")
        self.append(self.status)

        menu = Gio.Menu()
        for label, action in (("Start", "win.start-profile"), ("Edit…", "win.edit-profile"),
                              ("Remove…", "win.remove-profile")):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, GLib.Variant.new_string(profile.id))
            menu.append_item(item)
        self.menu_btn = Gtk.MenuButton(menu_model=menu, icon_name="view-more-symbolic",
                                       halign=Gtk.Align.CENTER, tooltip_text="Options")
        self.menu_btn.add_css_class("flat")
        self.menu_btn.add_css_class("circular")
        self.append(self.menu_btn)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        self.add_controller(click)
        long = Gtk.GestureLongPress()
        long.connect("pressed", self._on_long_press)
        self.add_controller(long)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_pressed(self, gesture, n_press, _x, _y):
        self._long_pressed = False
        self.grab_focus()

    def _on_released(self, gesture, n_press, _x, _y):
        button = gesture.get_current_button()
        if button == 3:
            self.menu_btn.popup()
            return
        if button != 1 or n_press != 1:
            return
        if self._long_pressed:
            self._long_pressed = False
            return
        self.window.card_clicked(self.profile)

    def _on_long_press(self, _gesture, _x, _y):
        self._long_pressed = True
        self.window.card_long_pressed(self.profile)

    def _on_key(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.window.card_clicked(self.profile)
            return True
        if keyval == Gdk.KEY_Menu:
            self.menu_btn.popup()
            return True
        return False

    def set_selected(self, selected: bool, selection_mode: bool) -> None:
        self.check.set_visible(selected)
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")

    def set_running(self, running: bool) -> None:
        if running:
            self.status.set_label("● running")
            self.status.remove_css_class("dim-label")
            self.status.add_css_class("running-dot")
        else:
            self.status.set_label(self.profile.cli_command if self.profile.cli else "")
            self.status.remove_css_class("running-dot")
            self.status.add_css_class("dim-label")


class LoaderWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Claude Loader",
                         default_width=660, default_height=460)
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.cards = {}
        self.selection_mode = False
        self.selected: set = set()
        self.update_info = None
        self.locked = bool(self.cfg.loader.password)

        for name, handler in (("start-profile", self._act_start), ("edit-profile", self._act_edit),
                              ("remove-profile", self._act_remove)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", handler)
            self.add_action(action)
        for name, handler in (("add-profile", lambda *_: self.add_profile()),
                              ("settings", lambda *_: self.open_settings()),
                              ("check-updates", lambda *_: self.check_updates(manual=True)),
                              ("paste-link", lambda *_: self.paste_link()),
                              ("about", lambda *_: self.show_about())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        self.toasts = Adw.ToastOverlay()
        self.view = Adw.ToolbarView()
        self.toasts.set_child(self.view)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="Claude Loader", subtitle="")
        header.set_title_widget(self.title)
        self.select_btn = Gtk.ToggleButton(icon_name="object-select-symbolic",
                                           tooltip_text="Select several profiles")
        self.select_btn.connect("toggled", self._on_select_toggled)
        header.pack_start(self.select_btn)
        menu = Gio.Menu()
        menu.append("Add profile…", "win.add-profile")
        menu.append("Paste sign-in link…", "win.paste-link")
        menu.append("Check for updates", "win.check-updates")
        menu.append("Settings…", "win.settings")
        menu.append("About", "win.about")
        self.menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       primary=True, tooltip_text="Menu")
        header.pack_end(self.menu_btn)
        self.view.add_top_bar(header)

        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", lambda _b: self.run_update())
        self.view.add_top_bar(self.banner)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.view.set_content(self.stack)
        self._build_locked_page()
        self._build_empty_page()
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                max_children_per_line=5, min_children_per_line=2,
                                column_spacing=12, row_spacing=12,
                                valign=Gtk.Align.START, halign=Gtk.Align.CENTER,
                                margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self.flow)
        self.stack.add_named(scroller, "profiles")

        self.action_bar = Gtk.ActionBar()
        self.hint = Gtk.Label(label="Click to start · hold to select several")
        self.hint.add_css_class("hint")
        self.action_bar.pack_start(self.hint)
        self.cancel_btn = Gtk.Button(label="Cancel")
        self.cancel_btn.connect("clicked", lambda _b: self.set_selection_mode(False))
        self.start_selected_btn = Gtk.Button(label="Start selected")
        self.start_selected_btn.add_css_class("suggested-action")
        self.start_selected_btn.connect("clicked", lambda _b: self.start(sorted(
            self.selected, key=lambda i: [p.id for p in self.cfg.profiles].index(i)),
            remember=True))
        self.start_all_btn = Gtk.Button(label="Start all")
        self.start_all_btn.connect("clicked", lambda _b: self.start([p.id for p in self.cfg.profiles]))
        self.start_group_btn = Gtk.Button(label="")
        self.start_group_btn.add_css_class("suggested-action")
        self.start_group_btn.connect("clicked", lambda _b: self.start(
            [p.id for p in self.cfg.group()]))
        for b in (self.start_group_btn, self.start_all_btn, self.start_selected_btn,
                  self.cancel_btn):
            self.action_bar.pack_end(b)
        self.view.add_bottom_bar(self.action_bar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.rebuild()
        GLib.timeout_add_seconds(3, self._refresh_running)
        if not self.locked:
            self._after_unlock()

    # --- pages -----------------------------------------------------------------

    def _build_locked_page(self) -> None:
        page = Adw.StatusPage(icon_name="system-lock-screen-symbolic", title="Loader locked",
                              description="Enter the loader password.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        self.lock_entry = Gtk.PasswordEntry(show_peek_icon=True, width_request=260)
        self.lock_entry.connect("activate", self._try_unlock)
        box.append(self.lock_entry)
        self.lock_error = Gtk.Label(label="", visible=False)
        self.lock_error.add_css_class("error")
        box.append(self.lock_error)
        btn = Gtk.Button(label="Unlock", halign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.connect("clicked", self._try_unlock)
        box.append(btn)
        page.set_child(box)
        self.stack.add_named(page, "locked")

    def _build_empty_page(self) -> None:
        page = Adw.StatusPage(icon_name="list-add-symbolic", title="No profiles yet",
                              description="Add a profile for each Claude account you use.")
        btn = Gtk.Button(label="Add profile", halign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.connect("clicked", lambda _b: self.add_profile())
        page.set_child(btn)
        self.stack.add_named(page, "empty")

    def _try_unlock(self, *_a) -> None:
        if security.verify_password(self.lock_entry.get_text(), self.cfg.loader.password):
            self.locked = False
            self.lock_entry.set_text("")
            self.rebuild()
            self._after_unlock()
        else:
            self.lock_entry.set_text("")
            self.lock_error.set_label("Wrong password.")
            self.lock_error.set_visible(True)

    def _after_unlock(self) -> None:
        if self.cfg.loader.check_updates:
            self.check_updates(manual=False)

    # --- building ----------------------------------------------------------------

    def reload(self) -> None:
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.rebuild()

    def rebuild(self) -> None:
        version = system.installed_version()
        self.title.set_subtitle(f"Claude Desktop {version}" if version
                                else "Claude Desktop is not installed")
        child = self.flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt
        self.cards = {}
        for p in self.cfg.profiles:
            card = ProfileCard(self, p)
            self.cards[p.id] = card
            self.flow.append(card)
        self.selected &= set(self.cards)

        if self.locked:
            self.stack.set_visible_child_name("locked")
            self.lock_entry.grab_focus()
        elif not self.cfg.profiles:
            self.stack.set_visible_child_name("empty")
        else:
            self.stack.set_visible_child_name("profiles")
        interactive = not self.locked
        self.menu_btn.set_sensitive(interactive)
        self.select_btn.set_sensitive(interactive and len(self.cfg.profiles) > 1)
        self.action_bar.set_revealed(interactive and bool(self.cfg.profiles))
        self.lookup_action("add-profile").set_enabled(
            interactive and len(self.cfg.profiles) < cfgmod.MAX_PROFILES)
        self._refresh_running()
        self._update_selection_ui()

    def _refresh_running(self) -> bool:
        try:
            running = set(system.running_profile_ids(self.cfg))
        except Exception:
            running = set()
        for pid, card in self.cards.items():
            card.set_running(pid in running)
        return True  # keep the timer

    # --- selection -----------------------------------------------------------------

    def _on_select_toggled(self, btn) -> None:
        if btn.get_active() != self.selection_mode:
            self.set_selection_mode(btn.get_active())

    def set_selection_mode(self, on: bool, first=None) -> None:
        self.selection_mode = on
        # Start from the group used last time, plus the profile that was pressed.
        self.selected = set()
        if on:
            self.selected = {p.id for p in self.cfg.group()}
            if first:
                self.selected.add(first.id)
        if self.select_btn.get_active() != on:
            self.select_btn.set_active(on)
        self._update_selection_ui()

    def _update_selection_ui(self) -> None:
        for pid, card in self.cards.items():
            card.set_selected(pid in self.selected, self.selection_mode)
        n = len(self.selected)
        self.cancel_btn.set_visible(self.selection_mode)
        self.start_selected_btn.set_visible(self.selection_mode)
        self.start_selected_btn.set_sensitive(n > 0)
        self.start_selected_btn.set_label(f"Start selected ({n})" if n else "Start selected")
        self.start_all_btn.set_visible(not self.selection_mode and len(self.cfg.profiles) > 1)
        group = self.cfg.group()
        show_group = (not self.selection_mode and bool(group)
                      and len(group) < len(self.cfg.profiles))
        self.start_group_btn.set_visible(show_group)
        if show_group:
            self.start_group_btn.set_label(f"Start {self.cfg.group_label()}")
        self.hint.set_label("Click profiles to select them" if self.selection_mode
                            else "Click to start · hold to select several")

    def card_clicked(self, profile) -> None:
        if self.selection_mode:
            self.selected ^= {profile.id}
            self._update_selection_ui()
        else:
            self.start([profile.id])

    def card_long_pressed(self, profile) -> None:
        if not self.selection_mode:
            self.set_selection_mode(True, profile)
        else:
            self.selected ^= {profile.id}
            self._update_selection_ui()

    def _on_key(self, _c, keyval, _code, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            if self.selection_mode:
                self.set_selection_mode(False)
            else:
                self.close()
            return True
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_A) and not self.locked:
            self.set_selection_mode(True)
            self.selected = set(self.cards)
            self._update_selection_ui()
            return True
        # Number keys start profile 1..5 directly.
        if not self.locked and not self.selection_mode and Gdk.KEY_1 <= keyval <= Gdk.KEY_5:
            idx = keyval - Gdk.KEY_1
            if idx < len(self.cfg.profiles):
                self.start([self.cfg.profiles[idx].id])
                return True
        return False

    # --- starting ------------------------------------------------------------------

    def start(self, ids: List[str], remember: bool = False) -> None:
        """Start profiles (asking passwords one by one). `remember` saves them as the group."""
        if not ids:
            return
        if remember and self.cfg.remember_group(ids):
            cfgmod.save(self.cfg)
        try:
            running = set(system.running_profile_ids(self.cfg))
        except Exception:
            running = set()
        queue, unlocked, failed = list(ids), set(), []

        def step():
            if not queue:
                finish()
                return
            pid = queue.pop(0)
            p = self.cfg.get(pid)
            if p.password and pid not in running:
                def done(ok, pid=pid, p=p):
                    (unlocked.add(pid) if ok else failed.append(p.name))
                    GLib.idle_add(lambda: step() and False)
                PasswordWindow(self, f"Claude ({p.name})",
                               lambda pw, rec=p.password: security.verify_password(pw, rec), done)
            else:
                unlocked.add(pid)
                step()

        def finish():
            to_start = [i for i in ids if i in unlocked]
            started = []
            if to_start:
                try:
                    started = launch.cmd_launch(_PLAT, self.cfg, to_start, gui=True,
                                                unlocked=unlocked)
                except launch.LaunchError as e:
                    self.toast(str(e))
                    return
            if failed:
                self.toast(f"Not started (password): {', '.join(failed)}")
            if self.selection_mode:
                self.set_selection_mode(False)
            if started and self.cfg.loader.close_after_launch and not failed:
                GLib.timeout_add(400, lambda: self.close() or False)
            elif started:
                names = [self.cfg.get(i).name for i in started]
                self.toast(f"Starting {', '.join(names)}…")
                GLib.timeout_add_seconds(2, lambda: self._refresh_running() and False)

        step()

    # --- actions -------------------------------------------------------------------

    def _act_start(self, _a, value) -> None:
        self.start([value.get_string()])

    def _act_edit(self, _a, value) -> None:
        ProfileDialog(self, self.cfg, self.cfg.get(value.get_string()), self.reload)

    def _act_remove(self, _a, value) -> None:
        profile = self.cfg.get(value.get_string())
        body = f"The menu entry, icon and terminal command of \"{profile.name}\" are removed."
        responses = [("cancel", "Cancel", None), ("remove", "Remove", "destructive")]
        folders = profile_folders(profile)
        if folders:
            body += (f"\n\nIts data ({', '.join(paths.short(f) for f in folders)}) is kept unless "
                     "you choose to delete it. Deleting removes this account's login, settings "
                     "and history on this PC and cannot be undone.")
            responses.append(("delete", "Remove and delete data", "destructive"))
        if profile.id in system.running_profile_ids(self.cfg):
            body += "\n\nThis profile is running. Close its window first."

        def done(rid):
            if rid not in ("remove", "delete"):
                return
            self.cfg.profiles = [p for p in self.cfg.profiles if p.id != profile.id]
            cfgmod.save(self.cfg)
            integration.apply(self.cfg)
            cfgmod.save(self.cfg)
            if rid == "delete":
                for folder in folders:
                    try:
                        shutil.rmtree(folder)
                    except OSError as e:
                        self.toast(f"Could not delete {paths.short(folder)}: {e}")
            self.reload()
            self.toast(f"Removed \"{profile.name}\".")

        confirm(self, f"Remove \"{profile.name}\"?", body, responses, done)

    def add_profile(self) -> None:
        if len(self.cfg.profiles) >= cfgmod.MAX_PROFILES:
            self.toast(f"At most {cfgmod.MAX_PROFILES} profiles are supported.")
            return
        ProfileDialog(self, self.cfg, None, self.reload)

    def open_settings(self) -> None:
        def saved(warnings=None):
            self.reload()
            self.toast(warnings[0] if warnings else "Settings saved.")
        SettingsDialog(self, self.cfg, saved)

    def show_about(self) -> None:
        about = Adw.AboutWindow(transient_for=self, application_name="Claude Loader",
                                application_icon="application-x-executable", version=VERSION,
                                comments="Run several Claude accounts and agents side by side.\n"
                                         "Unofficial, not affiliated with Anthropic.",
                                website="https://github.com/nurxie/claude-loader",
                                license_type=Gtk.License.MIT_X11)
        about.present()

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    def paste_link(self) -> None:
        if not self.cfg.profiles:
            self.toast("Add a profile first.")
            return
        PasteLinkDialog(self, self.cfg, self.toast)

    # --- updates -------------------------------------------------------------------

    def check_updates(self, manual: bool) -> None:
        def work():
            try:
                info = system.check_update()
                error = None
            except Exception as e:
                info, error = None, str(e)
            GLib.idle_add(self._show_update, info, error, manual)

        threading.Thread(target=work, daemon=True).start()

    def _show_update(self, info, error, manual) -> bool:
        self.update_info = info
        if error:
            if manual:
                self.toast(f"Could not check for updates: {error}")
        elif info["available"]:
            self.banner.set_title(info["message"])
            self.banner.set_button_label(info.get("action") or "Update")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)
            if manual:
                self.toast(info["message"])
        return False

    def run_update(self) -> None:
        running = system.running_profile_ids(self.cfg)

        def go(rid):
            if rid != "update":
                return
            self.banner.set_button_label("Updating…")
            self.banner.set_sensitive(False)

            def work():
                try:
                    ok, msg = _PLAT.run_update(self.cfg, gui=True)
                except OSError as e:
                    ok, msg = False, str(e)
                GLib.idle_add(self._update_done, ok, msg)

            threading.Thread(target=work, daemon=True).start()

        body = "Your system password will be asked to install the update."
        if running:
            body += "\n\nSome Claude windows are open. Close them first; they need a restart " \
                    "to use the new version."
        confirm(self, "Update Claude Desktop?", body,
                [("cancel", "Cancel", None), ("update", "Update", "suggested")], go)

    def _update_done(self, ok: bool, msg: str) -> bool:
        self.banner.set_sensitive(True)
        if ok:
            self.banner.set_revealed(False)
            self.toast("Claude Desktop updated.")
            system.package_files.cache_clear()
            self.rebuild()
        else:
            self.banner.set_button_label("Update")
            self.toast("Update failed or was cancelled." + (f" {msg}" if msg else ""))
        return False


class PasteLinkDialog:
    """Send a copied claude:// sign-in link to a chosen profile."""

    def __init__(self, parent, cfg, toast: Callable[[str], None]):
        self.parent, self.cfg, self.toast = parent, cfg, toast
        self.win = _dialog_window(parent, "Paste sign-in link", width=520)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.win.close())
        header.pack_start(cancel)
        send = Gtk.Button(label="Send")
        send.add_css_class("suggested-action")
        send.connect("clicked", self._send)
        header.pack_end(send)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()
        self.toasts.set_child(page)
        view.set_content(self.toasts)
        self.win.set_content(view)

        group = Adw.PreferencesGroup(
            description="After \"Continue with Google\", the browser offers to open Claude. "
                        "Cancel that, copy the claude://… link (for example right-click the "
                        "page's open-app button › Copy link) and paste it here.")
        self.link_row = Adw.EntryRow(title="claude:// link")
        self.link_row.connect("entry-activated", self._send)
        group.add(self.link_row)
        self.profile_row = Adw.ComboRow(title="Send to profile")
        self.profile_row.set_model(Gtk.StringList.new([p.name for p in cfg.profiles]))
        running = system.running_profile_ids(cfg)
        preferred = running[0] if len(running) == 1 else next(
            (p.id for p in cfg.profiles if not p.system_default), cfg.profiles[0].id)
        self.profile_row.set_selected([p.id for p in cfg.profiles].index(preferred))
        group.add(self.profile_row)
        page.add(group)

        # Pre-fill from the clipboard when it already holds a claude:// link.
        clipboard = parent.get_display().get_clipboard()

        def got_text(cb, result):
            try:
                text = cb.read_text_finish(result)
            except GLib.Error:
                return
            if text and launch.valid_link(text) and not self.link_row.get_text():
                self.link_row.set_text(text.strip())

        clipboard.read_text_async(None, got_text)
        self.win.present()

    def _send(self, *_a) -> None:
        url = self.link_row.get_text().strip()
        if not launch.valid_link(url):
            self.toasts.add_toast(Adw.Toast.new("That is not a claude:// link."))
            return
        profile = self.cfg.profiles[self.profile_row.get_selected()]

        def go(ok=True):
            if not ok:
                self.toasts.add_toast(Adw.Toast.new("Wrong password."))
                return
            launch.send_url(_PLAT, self.cfg, profile, url, gui=True, unlocked=True)
            self.win.close()
            self.toast(f"Link sent to \"{profile.name}\".")

        if profile.password and profile.id not in system.running_profile_ids(self.cfg):
            PasswordWindow(self.win, f"Claude ({profile.name})",
                           lambda pw: security.verify_password(pw, profile.password), go)
        else:
            go()


class LoaderApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        _load_css()
        win = self.props.active_window
        if win is None:
            win = LoaderWindow(self)
        win.present()


def run_loader(plat) -> int:
    global _PLAT
    _PLAT = plat
    return LoaderApp().run([])
