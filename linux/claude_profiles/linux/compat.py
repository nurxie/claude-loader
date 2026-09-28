"""Widgets and helpers that older libadwaita and GTK do not have.

Ubuntu 22.04 ships libadwaita 1.1 and GTK 4.6, but the loader is written
against things that arrived later: the entry and switch rows (1.2 and 1.4),
`ToolbarView` (1.4), `Banner` (1.3), `AlertDialog` (1.5) and `Gtk.FileDialog`
(GTK 4.10). Every name exported here is the real widget when the installed
libraries have it and a stand-in built from GTK 4.6 pieces when they don't, so
`gui.py` is written once, against the newer API.

`missing()` lists what is being stood in for; `claude-profiles doctor` prints it.
"""

from typing import Callable, List, Optional, Tuple

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402


def _has_property(cls, name: str) -> bool:
    try:
        return any(p.name == name for p in cls.list_properties())
    except Exception:
        return False


# --- Adw.ToolbarView (libadwaita 1.4) --------------------------------------------

class _ToolbarView(Gtk.Box):
    """Top bars, then the content, then bottom bars - whatever the order of calls."""

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)
        self._top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self._bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for box in (self._top, self._middle, self._bottom):
            self.append(box)

    def add_top_bar(self, widget) -> None:
        self._top.append(widget)

    def add_bottom_bar(self, widget) -> None:
        self._bottom.append(widget)

    def set_content(self, widget) -> None:
        child = self._middle.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._middle.remove(child)
            child = nxt
        if widget is not None:
            widget.set_vexpand(True)
            self._middle.append(widget)


# --- Adw.Banner (libadwaita 1.3) ---------------------------------------------------

class _Banner(Gtk.Revealer):
    """A strip above the content with one message and one button."""

    __gsignals__ = {"button-clicked": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, revealed: bool = False, title: str = ""):
        super().__init__(reveal_child=revealed)
        self.add_css_class("banner-fallback")
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self._label = Gtk.Label(label=title, wrap=True, xalign=0.0, hexpand=True)
        self._button = Gtk.Button(valign=Gtk.Align.CENTER)
        self._button.add_css_class("suggested-action")
        self._button.connect("clicked", lambda _b: self.emit("button-clicked"))
        box.append(self._label)
        box.append(self._button)
        self.set_child(box)

    def set_title(self, text: str) -> None:
        self._label.set_label(text or "")

    def set_button_label(self, text: Optional[str]) -> None:
        self._button.set_label(text or "")
        self._button.set_visible(bool(text))

    def set_revealed(self, revealed: bool) -> None:
        self.set_reveal_child(bool(revealed))

    def get_revealed(self) -> bool:
        return self.get_reveal_child()


# --- Adw.SwitchRow (1.4), Adw.EntryRow and Adw.PasswordEntryRow (1.2) ---------------

class _SwitchRow(Adw.ActionRow):
    """A row whose activatable widget is a switch."""

    def __init__(self, **kwargs):
        active = bool(kwargs.pop("active", False))
        super().__init__(**kwargs)
        self._switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=active)
        self._switch.connect("notify::active", lambda *_: self.notify("active"))
        self.add_suffix(self._switch)
        self.set_activatable_widget(self._switch)

    @GObject.Property(type=bool, default=False)
    def active(self) -> bool:
        return self._switch.get_active()

    @active.setter  # noqa: F811  (the GObject property's setter)
    def active(self, value) -> None:
        self._switch.set_active(bool(value))

    def get_active(self) -> bool:
        return self._switch.get_active()

    def set_active(self, value) -> None:
        self._switch.set_active(bool(value))


class _EntryRow(Adw.ActionRow):
    """A row that is an entry: `changed` and `entry-activated`, like the real one."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "entry-activated": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        text = kwargs.pop("text", "")
        super().__init__(**kwargs)
        self._entry = self._make_entry()
        self._entry.set_text(text)
        self._entry.connect("changed", lambda *_: self.emit("changed"))
        self._entry.connect("activate", lambda *_: self.emit("entry-activated"))
        self.add_suffix(self._entry)

    def _make_entry(self):
        return Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True)

    def get_text(self) -> str:
        return self._entry.get_text()

    def set_text(self, value) -> None:
        self._entry.set_text(value or "")

    def grab_focus(self) -> bool:
        return self._entry.grab_focus()


class _PasswordEntryRow(_EntryRow):
    def _make_entry(self):
        return Gtk.PasswordEntry(valign=Gtk.Align.CENTER, hexpand=True, show_peek_icon=True)


# --- what we use, native where possible --------------------------------------------

_SUBSTITUTES = [
    ("Adw.ToolbarView", hasattr(Adw, "ToolbarView")),
    ("Adw.Banner", hasattr(Adw, "Banner")),
    ("Adw.SwitchRow", hasattr(Adw, "SwitchRow")),
    ("Adw.EntryRow", hasattr(Adw, "EntryRow")),
    ("Adw.PasswordEntryRow", hasattr(Adw, "PasswordEntryRow")),
    ("Adw.AlertDialog", hasattr(Adw, "AlertDialog") or hasattr(Adw, "MessageDialog")),
    ("Adw.AboutWindow", hasattr(Adw, "AboutWindow")),
    ("Gtk.FileDialog", hasattr(Gtk, "FileDialog")),
]

ToolbarView = getattr(Adw, "ToolbarView", _ToolbarView)
Banner = getattr(Adw, "Banner", _Banner)
SwitchRow = getattr(Adw, "SwitchRow", _SwitchRow)
EntryRow = getattr(Adw, "EntryRow", _EntryRow)
PasswordEntryRow = getattr(Adw, "PasswordEntryRow", _PasswordEntryRow)


def missing() -> List[str]:
    """Names this system does not have, and that are stood in for."""
    return [name for name, present in _SUBSTITUTES if not present]


def versions() -> str:
    return (f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()} / "
            f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}")


# --- stylesheet ---------------------------------------------------------------------

def load_css(css: str) -> None:
    """Add a stylesheet, whichever `load_from_*` this GTK offers."""
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):            # GTK 4.12
        provider.load_from_string(css)
    else:
        data = css.encode("utf-8")
        try:
            provider.load_from_data(data, -1)            # GTK 4.8 - 4.10
        except TypeError:
            provider.load_from_data(data)                # GTK 4.6
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


# --- header bars and rows ------------------------------------------------------------

_HAS_SHOW_TITLE = _has_property(Adw.HeaderBar, "show-title")


def header_bar(show_title: bool = True, **kwargs) -> Adw.HeaderBar:
    if _HAS_SHOW_TITLE:
        return Adw.HeaderBar(show_title=show_title, **kwargs)
    header = Adw.HeaderBar(**kwargs)
    if not show_title:
        header.set_title_widget(Gtk.Label())  # an empty title widget hides the window's
    return header


def set_subtitle_selectable(row, selectable: bool = True) -> None:
    if hasattr(row, "set_subtitle_selectable"):
        row.set_subtitle_selectable(selectable)


# --- a question with a few buttons ------------------------------------------------------

Response = Tuple[str, str, Optional[str]]


def alert(parent, heading: str, body: str, responses: List[Response],
          callback: Callable[[str], None]) -> None:
    """Ask a question. `responses` is [(id, label, "destructive"/"suggested"/None)];
    the first one is what closing the window means. `callback(id)` runs once."""
    if hasattr(Adw, "AlertDialog"):
        dialog = Adw.AlertDialog.new(heading, body)
    elif hasattr(Adw, "MessageDialog"):
        dialog = Adw.MessageDialog.new(parent, heading, body)
    else:
        _alert_fallback(parent, heading, body, responses, callback)
        return
    for rid, label, look in responses:
        dialog.add_response(rid, label)
        if look == "destructive":
            dialog.set_response_appearance(rid, Adw.ResponseAppearance.DESTRUCTIVE)
        elif look == "suggested":
            dialog.set_response_appearance(rid, Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response(responses[0][0])
    dialog.set_default_response(responses[0][0])
    dialog.connect("response", lambda _d, rid: callback(rid))
    if isinstance(dialog, getattr(Adw, "AlertDialog", ())):
        dialog.present(parent)
    else:
        dialog.present()


def _alert_fallback(parent, heading: str, body: str, responses: List[Response],
                    callback: Callable[[str], None]) -> None:
    win = Adw.Window(modal=parent is not None, default_width=440, title=heading)
    if parent is not None:
        win.set_transient_for(parent)
    answered = {"done": False}

    def answer(rid: str, close: bool = True) -> None:
        if answered["done"]:
            return
        answered["done"] = True
        if close:
            win.close()
        callback(rid)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  margin_top=18, margin_bottom=20, margin_start=24, margin_end=24)
    title = Gtk.Label(label=heading, wrap=True, justify=Gtk.Justification.CENTER)
    title.add_css_class("title-3")
    box.append(title)
    if body:
        text = Gtk.Label(label=body, wrap=True, justify=Gtk.Justification.CENTER)
        box.append(text)
    buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, homogeneous=True, margin_top=8)
    for rid, label, look in responses:
        button = Gtk.Button(label=label)
        if look == "destructive":
            button.add_css_class("destructive-action")
        elif look == "suggested":
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b, rid=rid: answer(rid))
        buttons.append(button)
    box.append(buttons)

    view = ToolbarView()
    view.add_top_bar(header_bar(show_title=False))
    view.set_content(box)
    win.set_content(view)

    keys = Gtk.EventControllerKey()
    keys.connect("key-pressed",
                 lambda _c, kv, _k, _s: kv == Gdk.KEY_Escape and (win.close() or True))
    win.add_controller(keys)
    win.connect("close-request", lambda _w: (answer(responses[0][0], close=False), False)[1])
    win.present()


# --- about -------------------------------------------------------------------------------

def about(parent, name: str, version: str, comments: str, website: str,
          icon: str = "application-x-executable") -> None:
    if hasattr(Adw, "AboutWindow"):
        Adw.AboutWindow(transient_for=parent, application_name=name, application_icon=icon,
                        version=version, comments=comments, website=website,
                        license_type=Gtk.License.MIT_X11).present()
        return
    Gtk.AboutDialog(transient_for=parent, modal=True, program_name=name, logo_icon_name=icon,
                    version=version, comments=comments, website=website,
                    license_type=Gtk.License.MIT_X11).present()


# --- choosing a folder ---------------------------------------------------------------------

_pending_choosers = set()  # a native chooser must outlive the call that opened it


def select_folder(parent, title: str, callback: Callable[[Optional[str]], None]) -> None:
    """Ask for a folder. `callback(path)`, or `callback(None)` if cancelled."""
    if hasattr(Gtk, "FileDialog"):
        dialog = Gtk.FileDialog(title=title)

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:
                callback(None)
                return
            callback(folder.get_path() if folder else None)

        dialog.select_folder(parent, None, done)
        return

    chooser = Gtk.FileChooserNative(title=title, transient_for=parent, modal=True,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER,
                                    accept_label="Select", cancel_label="Cancel")
    _pending_choosers.add(chooser)

    def response(native, code):
        folder = native.get_file() if code == Gtk.ResponseType.ACCEPT else None
        _pending_choosers.discard(native)
        callback(folder.get_path() if folder else None)

    chooser.connect("response", response)
    chooser.show()
