"""Tk user interface for Windows: the loader and small dialogs.

Uses the Sun Valley ttk theme (Windows 11 look) when `sv_ttk` is installed,
otherwise the standard Windows ttk theme.
"""

import os
import queue
import shutil
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk
from typing import Callable, List, Optional

import winreg

from ..core import VERSION
from ..core import config as cfgmod
from ..core import icons, launch, paths, security
from ..core.tui import profile_folders
from . import hotkeys, integration, winutil

TITLE = integration.LOADER_TITLE
LOADER_MUTEX = "ClaudeProfilesLoader"
_PLAT = None  # set by run_loader()

GLYPHS = {"lock": "", "check": "", "more": "", "menu": "",
          "add": ""}


# --- theme ---------------------------------------------------------------------------

class Theme:
    def __init__(self, root: tk.Misc):
        self.sv = False
        try:
            import sv_ttk  # noqa: F401
            self.sv = True
        except ImportError:
            pass
        # The standard ttk theme is light only, so follow Windows only with sv-ttk.
        self.light = winutil.apps_use_light_theme() if self.sv else True
        self.accent = self._accent()
        if self.light:
            self.bg, self.card, self.hover, self.border = "#fafafa", "#ffffff", "#f3f3f3", "#e5e5e5"
            self.text, self.sub, self.success = "#1c1c1c", "#5f5f5f", "#0f7b0f"
            self.selected = "#e6f0fb"
        else:
            self.bg, self.card, self.hover, self.border = "#1c1c1c", "#2b2b2b", "#323232", "#3a3a3a"
            self.text, self.sub, self.success = "#ffffff", "#a8a8a8", "#6ccb5f"
            self.selected = "#1f3346"
        families = set(tkfont.families(root))
        self.icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets")
                               if f in families), None)
        if self.sv:
            import sv_ttk  # noqa: F811
            sv_ttk.set_theme("light" if self.light else "dark")
        else:
            style = ttk.Style(root)
            if "vista" in style.theme_names():
                style.theme_use("vista")
            self.bg = style.lookup("TFrame", "background") or self.bg
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.configure(bg=self.bg)
        style = ttk.Style(root)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
        style.configure("Sub.TLabel", foreground=self.sub)
        style.configure("Error.TLabel", foreground="#c42b1c" if self.light else "#ff99a4")

    @staticmethod
    def _accent() -> str:
        value = winutil.reg_get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM",
                                "AccentColor")
        if isinstance(value, int):
            r, g, b = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
            return f"#{r:02x}{g:02x}{b:02x}"
        return "#0078d4"

    def glyph(self, name: str, fallback: str) -> dict:
        if self.icon_font:
            return {"text": GLYPHS[name], "font": (self.icon_font, 10)}
        return {"text": fallback}

    def accent_button(self) -> str:
        return "Accent.TButton" if self.sv else "TButton"


_theme: Optional[Theme] = None
_images = {}  # keep PhotoImage references alive


def profile_image(root, profile, size: int) -> tk.PhotoImage:
    """Colored icon of a profile at `size` px, cached on disk."""
    ui_dir = paths.ICON_DIR / "ui"
    path = ui_dir / f"{profile.id}-{profile.color}-{size}.png"
    if not path.exists():
        src = integration.icon_png(profile)
        if not src.exists():
            try:
                integration.build_icons(cfgmod.load() or cfgmod.Config(profiles=[profile]))
            except Exception:
                pass
        ui_dir.mkdir(parents=True, exist_ok=True)
        try:
            base = paths.ICON_DIR / "base.png"
            icons.make_icon(str(base) if base.exists() else None, profile.color, path, size)
        except OSError:
            pass
    key = str(path)
    if key not in _images:
        try:
            _images[key] = tk.PhotoImage(master=root, file=key)
        except tk.TclError:
            _images[key] = tk.PhotoImage(master=root, width=size, height=size)
    return _images[key]


def _prepare_root(root: tk.Tk) -> Theme:
    global _theme
    _theme = Theme(root)
    try:
        if integration.loader_ico().exists():
            root.iconbitmap(default=str(integration.loader_ico()))
    except tk.TclError:
        pass
    return _theme


def _new_root() -> tk.Tk:
    winutil.set_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    _prepare_root(root)
    return root


# --- generic dialog ---------------------------------------------------------------------

class Dialog(tk.Toplevel):
    def __init__(self, parent, title: str, standalone: bool = False):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=_theme.bg)
        self.resizable(False, False)
        if not standalone and parent.winfo_viewable():
            self.transient(parent)
        self.body = ttk.Frame(self, padding=(20, 18))
        self.body.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def show(self, focus=None) -> None:
        self.update_idletasks()
        parent = self.master
        if parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        else:
            x = (self.winfo_screenwidth() - self.winfo_width()) // 2
            y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.winfo_exists() and self.attributes("-topmost", False))
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if focus is not None:
            focus.focus_set()

    def cancel(self) -> None:
        self.destroy()

    def buttons(self, *specs) -> ttk.Frame:
        """specs: (label, command, accent: bool)"""
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(16, 0))
        for label, command, accent in reversed(specs):
            ttk.Button(row, text=label, command=command,
                       style=_theme.accent_button() if accent else "TButton").pack(
                side="right", padx=(8, 0))
        return row


class PasswordDialog(Dialog):
    MAX_ATTEMPTS = 5

    def __init__(self, parent, title: str, verify: Callable[[str], bool],
                 on_done: Callable[[bool], None], standalone: bool = False):
        super().__init__(parent, "Password required", standalone)
        self.verify, self.on_done, self.finished, self.attempts = verify, on_done, False, 0
        if _theme.icon_font:
            ttk.Label(self.body, text=GLYPHS["lock"], font=(_theme.icon_font, 26)).pack()
        ttk.Label(self.body, text=title, font=("Segoe UI Semibold", 12)).pack(pady=(6, 10))
        self.entry = ttk.Entry(self.body, show="•", width=32)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda _e: self.submit())
        self.error = ttk.Label(self.body, text="", style="Error.TLabel")
        self.error.pack(pady=(6, 0))
        self.buttons(("Cancel", self.cancel, False), ("Unlock", self.submit, True))
        self.show(self.entry)

    def _finish(self, ok: bool) -> None:
        if not self.finished:
            self.finished = True
            self.destroy()
            self.on_done(ok)

    def cancel(self) -> None:
        self._finish(False)

    def submit(self) -> None:
        if self.verify(self.entry.get()):
            self._finish(True)
            return
        self.attempts += 1
        self.entry.delete(0, "end")
        if self.attempts >= self.MAX_ATTEMPTS:
            self._finish(False)
            return
        self.error.configure(text="Wrong password, try again.")


def ask_password_blocking(title: str, verify: Callable[[str], bool]) -> bool:
    root = _new_root()
    result = {"ok": False}

    def done(ok):
        result["ok"] = ok
        root.after(10, root.destroy)

    PasswordDialog(root, title, verify, done, standalone=True)
    root.mainloop()
    return result["ok"]


def choose_profile_blocking(profiles, question: str):
    root = _new_root()
    result = {"profile": None}
    dlg = Dialog(root, "Choose a Claude profile", standalone=True)
    ttk.Label(dlg.body, text=question, wraplength=360).pack(anchor="w", pady=(0, 10))

    def pick(p):
        result["profile"] = p
        dlg.destroy()

    for p in profiles:
        ttk.Button(dlg.body, text=f"  {p.name}", image=profile_image(root, p, 28),
                   compound="left", command=lambda p=p: pick(p)).pack(fill="x", pady=2)
    dlg.buttons(("Cancel", dlg.destroy, False))
    dlg.bind("<Destroy>", lambda e: e.widget is dlg and root.after(10, root.destroy))
    dlg.show()
    root.mainloop()
    return result["profile"]


def confirm(parent, heading: str, body: str, responses, callback: Callable[[str], None]) -> None:
    """responses: [(id, label, accent)], the first one cancels."""
    dlg = Dialog(parent, heading)
    ttk.Label(dlg.body, text=heading, font=("Segoe UI Semibold", 12)).pack(anchor="w")
    ttk.Label(dlg.body, text=body, wraplength=420, justify="left").pack(anchor="w", pady=(8, 0))
    chosen = {"id": responses[0][0]}

    def pick(rid):
        chosen["id"] = rid
        dlg.destroy()

    dlg.buttons(*[(label, lambda r=rid: pick(r), accent) for rid, label, accent in responses])
    # Run the callback after the dialog is gone, not inside the Destroy event.
    dlg.bind("<Destroy>", lambda e: e.widget is dlg and parent.after(
        1, lambda: callback(chosen["id"])))
    dlg.show()


# --- hotkey capture ---------------------------------------------------------------------------

MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
                    "Win_L", "Win_R", "Super_L", "Super_R", "Caps_Lock", "App"}


def capture_hotkey(parent, on_done: Callable[[Optional[str]], None]) -> None:
    dlg = Dialog(parent, "New shortcut")
    ttk.Label(dlg.body, text="Press the new shortcut for the loader").pack()
    shown = ttk.Label(dlg.body, text="…", font=("Segoe UI Semibold", 16))
    shown.pack(pady=8)
    hint = ttk.Label(dlg.body, text="Use Ctrl, Alt or Win plus a key. Esc cancels.",
                     style="Sub.TLabel")
    hint.pack()
    presets = ttk.Frame(dlg.body)
    presets.pack(pady=(12, 0))
    ttk.Label(presets, text="Or pick:", style="Sub.TLabel").pack(side="left", padx=(0, 6))

    def finish(accel):
        dlg.destroy()
        on_done(accel)

    for value, label in hotkeys.PRESETS:
        ttk.Button(presets, text=label, command=lambda v=value: finish(v)).pack(side="left", padx=2)

    def on_key(event):
        if event.keysym == "Escape":
            dlg.destroy()
            return "break"
        if event.keysym in MODIFIER_KEYSYMS:
            return "break"
        accel = hotkeys.from_tk_event(event.keysym)
        if not accel:
            hint.configure(text="Add Ctrl, Alt or Win to the key.")
            return "break"
        shown.configure(text=accel)
        dlg.after(400, lambda: finish(accel))
        return "break"

    dlg.bind("<KeyPress>", on_key)
    dlg.show()


# --- add / edit profile --------------------------------------------------------------------

class ProfileDialog(Dialog):
    def __init__(self, parent, cfg, profile, on_saved: Callable[[], None]):
        self.is_new = profile is None
        super().__init__(parent, "Add profile" if self.is_new else f"Edit {profile.name}")
        self.cfg, self.profile, self.on_saved = cfg, profile, on_saved
        self.custom_dir: Optional[str] = None
        b = self.body

        ttk.Label(b, text="Name").pack(anchor="w")
        self.name = tk.StringVar(value=profile.name if profile else cfgmod.default_name(cfg))
        name_entry = ttk.Entry(b, textvariable=self.name, width=40)
        name_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(b, text="Icon color").pack(anchor="w")
        self.color = profile.color if profile else cfgmod.next_color(cfg)
        self.swatches = tk.Canvas(b, height=34, highlightthickness=0, bg=_theme.bg)
        self.swatches.pack(fill="x", pady=(2, 10))
        self.swatches.bind("<Button-1>", self._pick_color)
        self._draw_swatches()

        if self.is_new:
            ttk.Label(b, text="Data folder (login, settings, history)").pack(anchor="w")
            self.location = tk.StringVar(value="own")
            opts = [("own", "Separate folder")]
            if not cfg.system_default_profile():
                opts.append(("std", "Standard Claude folders (keeps an existing login)"))
            opts.append(("custom", "Custom folder…"))
            for value, label in opts:
                ttk.Radiobutton(b, text=label, value=value, variable=self.location,
                                command=self._update).pack(anchor="w")
            self.path_label = ttk.Label(b, text="", style="Sub.TLabel", wraplength=400)
            self.path_label.pack(anchor="w", padx=(24, 0), pady=(0, 10))
        else:
            ttk.Label(b, text="Data folder").pack(anchor="w")
            ttk.Label(b, text=profile.data_location, style="Sub.TLabel", wraplength=400).pack(
                anchor="w", pady=(0, 10))

        self.pw_on = tk.BooleanVar(value=bool(profile and profile.password))
        ttk.Checkbutton(b, text="Ask for a password (a simple lock, files are not encrypted)",
                        variable=self.pw_on, command=self._update).pack(anchor="w")
        self.pw_frame = ttk.Frame(b)
        hint = "New password" + (" (empty keeps the current one)"
                                 if profile and profile.password else "")
        ttk.Label(self.pw_frame, text=hint, style="Sub.TLabel").pack(anchor="w")
        self.pw1 = ttk.Entry(self.pw_frame, show="•")
        self.pw1.pack(fill="x", pady=2)
        ttk.Label(self.pw_frame, text="Repeat password", style="Sub.TLabel").pack(anchor="w")
        self.pw2 = ttk.Entry(self.pw_frame, show="•")
        self.pw2.pack(fill="x", pady=2)

        self.cli = tk.BooleanVar(value=profile.cli if profile else
                                 (any(p.cli for p in cfg.profiles) or not cfg.profiles))
        self.cli_check = ttk.Checkbutton(b, variable=self.cli)
        self.cli_check.pack(anchor="w", pady=(10, 0))
        self.error = ttk.Label(b, text="", style="Error.TLabel")
        self.error.pack(anchor="w", pady=(8, 0))
        self.buttons(("Cancel", self.cancel, False),
                     ("Add" if self.is_new else "Save", self.save, True))
        self.name.trace_add("write", lambda *_: self._update())
        self._update()
        self.show(name_entry)

    def _draw_swatches(self) -> None:
        c = self.swatches
        c.delete("all")
        r = 12
        for i, key in enumerate(cfgmod.COLORS):
            x = 16 + i * 34
            color = cfgmod.COLORS[key][3]
            if key == self.color:
                c.create_oval(x - r - 3, 17 - r - 3, x + r + 3, 17 + r + 3, outline=_theme.accent,
                              width=2)
            c.create_oval(x - r, 17 - r, x + r, 17 + r, fill=color, outline="")

    def _pick_color(self, event) -> None:
        i = int((event.x - 16 + 17) // 34)
        keys = list(cfgmod.COLORS)
        if 0 <= i < len(keys):
            self.color = keys[i]
            self._draw_swatches()

    def _new_id(self) -> str:
        return cfgmod.make_id(self.name.get() or "profile", {p.id for p in self.cfg.profiles})

    def _update(self) -> None:
        pid = self._new_id() if self.is_new else self.profile.id
        self.cli_check.configure(text=f"Claude Code terminal command: claude-{pid}")
        if self.pw_on.get():
            self.pw_frame.pack(fill="x", padx=(24, 0), before=self.cli_check)
        else:
            self.pw_frame.pack_forget()
        if not self.is_new:
            return
        loc = self.location.get()
        if loc == "custom" and not self.custom_dir:
            folder = filedialog.askdirectory(parent=self, title="Choose the profile data folder")
            if folder:
                self.custom_dir = os.path.normpath(folder)
            else:
                self.location.set("own")
                loc = "own"
        text = {"own": paths.short(cfgmod.default_data_dir(pid)),
                "std": f"{paths.short(paths.DEFAULT_DESKTOP_DATA)} and {paths.short(paths.DEFAULT_CLI_DIR)}",
                "custom": paths.short(self.custom_dir or "")}[loc]
        self.path_label.configure(text=text)

    def save(self) -> None:
        name = self.name.get().strip()
        error = cfgmod.check_name(self.cfg, name, self.profile)
        if error:
            self.error.configure(text=error)
            return
        password = self.profile.password if self.profile else None
        if self.pw_on.get():
            pw1, pw2 = self.pw1.get(), self.pw2.get()
            if pw1 or pw2 or not password:
                if not pw1:
                    self.error.configure(text="Enter a password or untick the box.")
                    return
                if pw1 != pw2:
                    self.error.configure(text="The passwords do not match.")
                    return
                password = security.hash_password(pw1)
        else:
            password = None

        if self.is_new:
            if len(self.cfg.profiles) >= cfgmod.MAX_PROFILES:
                self.error.configure(text=f"At most {cfgmod.MAX_PROFILES} profiles are supported.")
                return
            pid = self._new_id()
            loc = self.location.get()
            data_dir = {"own": cfgmod.default_data_dir(pid), "std": "",
                        "custom": self.custom_dir or ""}[loc]
            profile = cfgmod.Profile(id=pid, name=name, color=self.color, data_dir=data_dir,
                                     system_default=loc == "std", password=password,
                                     cli=self.cli.get())
            self.cfg.profiles.append(profile)
        else:
            profile = self.profile
            profile.name, profile.color, profile.password = name, self.color, password
            profile.cli = self.cli.get()
        try:
            cfgmod.save(self.cfg)
            _PLAT.apply(self.cfg)
            cfgmod.save(self.cfg)
        except cfgmod.ConfigError as e:
            if self.is_new:
                self.cfg.profiles.remove(profile)
            self.error.configure(text=str(e))
            return
        self.destroy()
        self.on_saved()


# --- settings ----------------------------------------------------------------------------------

class SettingsDialog(Dialog):
    def __init__(self, parent, cfg, on_saved: Callable[[List[str]], None]):
        super().__init__(parent, "Loader settings")
        self.cfg, self.on_saved = cfg, on_saved
        self.hotkey = cfg.loader.hotkey
        b = self.body

        ttk.Label(b, text="Hotkey", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        row = ttk.Frame(b)
        row.pack(fill="x", pady=(2, 4))
        self.hotkey_label = ttk.Label(row, text="")
        self.hotkey_label.pack(side="left")
        ttk.Button(row, text="None", command=lambda: self._set_hotkey(None)).pack(side="right")
        ttk.Button(row, text="Change…",
                   command=lambda: capture_hotkey(self, self._set_hotkey)).pack(side="right", padx=4)
        self.tray = tk.BooleanVar(value=cfg.loader.tray)
        ttk.Checkbutton(b, text="Run the tray agent at sign-in (needed for the hotkey)",
                        variable=self.tray).pack(anchor="w")

        ttk.Label(b, text="When I sign in to Windows", font=("Segoe UI Semibold", 11)).pack(
            anchor="w", pady=(14, 0))
        self.open_at_login = tk.BooleanVar(value=cfg.loader.open_at_login)
        ttk.Checkbutton(b, text="Open the loader", variable=self.open_at_login).pack(anchor="w")
        self.autostart = {}
        row = ttk.Frame(b)
        row.pack(anchor="w")
        ttk.Label(row, text="Start:", style="Sub.TLabel").pack(side="left", padx=(0, 4))
        for p in cfg.profiles:
            var = tk.BooleanVar(value=p.id in cfg.autostart_profiles)
            self.autostart[p.id] = var
            ttk.Checkbutton(row, text=p.name, variable=var).pack(side="left", padx=(0, 8))

        ttk.Label(b, text="Loader", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(14, 0))
        self.close_after = tk.BooleanVar(value=cfg.loader.close_after_launch)
        ttk.Checkbutton(b, text="Close after starting a profile",
                        variable=self.close_after).pack(anchor="w")
        self.check_updates = tk.BooleanVar(value=cfg.loader.check_updates)
        ttk.Checkbutton(b, text="Check the Claude copy for updates on start",
                        variable=self.check_updates).pack(anchor="w")
        self.desktop = tk.BooleanVar(value=cfg.desktop_shortcuts)
        ttk.Checkbutton(b, text="Profile shortcuts on the Desktop",
                        variable=self.desktop).pack(anchor="w")
        self.path = tk.BooleanVar(value=cfg.path_added)
        ttk.Checkbutton(b, text=f"claude-<name> commands on PATH ({paths.short(paths.BIN_DIR)})",
                        variable=self.path).pack(anchor="w")
        self.pw_on = tk.BooleanVar(value=bool(cfg.loader.password))
        ttk.Checkbutton(b, text="Ask for a password when the loader opens",
                        variable=self.pw_on, command=self._update_pw).pack(anchor="w")
        self.pw_frame = ttk.Frame(b)
        ttk.Label(self.pw_frame, text="New password" + (" (empty keeps the current one)"
                                                        if cfg.loader.password else ""),
                  style="Sub.TLabel").pack(anchor="w")
        self.pw1 = ttk.Entry(self.pw_frame, show="•")
        self.pw1.pack(fill="x")
        ttk.Label(self.pw_frame, text="Repeat password", style="Sub.TLabel").pack(anchor="w")
        self.pw2 = ttk.Entry(self.pw_frame, show="•")
        self.pw2.pack(fill="x")
        self.pw_anchor = ttk.Frame(b)
        self.pw_anchor.pack(fill="x")

        ttk.Label(b, text="Sign-in links", font=("Segoe UI Semibold", 11)).pack(anchor="w",
                                                                              pady=(14, 0))
        self.url = tk.BooleanVar(value=cfg.url_handler)
        ttk.Checkbutton(b, text="Route claude:// links to the right profile (experimental)",
                        variable=self.url).pack(anchor="w")
        ttk.Label(b, text="Reliable alternative: menu > Paste sign-in link.",
                  style="Sub.TLabel").pack(anchor="w", padx=(24, 0))

        ttk.Label(b, text="Maintenance", font=("Segoe UI Semibold", 11)).pack(anchor="w",
                                                                            pady=(14, 2))
        row = ttk.Frame(b)
        row.pack(fill="x")
        ttk.Button(row, text="Repair shortcuts and icons", command=self._repair).pack(side="left")
        ttk.Button(row, text="Uninstall…", command=self._uninstall).pack(side="left", padx=6)
        self.error = ttk.Label(b, text="", style="Error.TLabel", wraplength=420)
        self.error.pack(anchor="w", pady=(8, 0))
        self.buttons(("Cancel", self.cancel, False), ("Save", self.save, True))
        self._set_hotkey(self.hotkey)
        self._update_pw()
        self.show()

    def _set_hotkey(self, accel) -> None:
        self.hotkey = accel
        self.hotkey_label.configure(text=f"Open the loader: {hotkeys.normalize(accel) or 'none'}")
        if accel:
            conflicts = _PLAT.hotkey_conflicts(accel)
            if conflicts:
                self.error.configure(text=f"{hotkeys.normalize(accel)} is already used by "
                                          f"{conflicts[0]}.")
            else:
                self.error.configure(text="")

    def _update_pw(self) -> None:
        if self.pw_on.get():
            self.pw_frame.pack(fill="x", before=self.pw_anchor, padx=(24, 0))
        else:
            self.pw_frame.pack_forget()

    def _repair(self) -> None:
        _PLAT.rebuild_icons()
        warnings = _PLAT.apply(self.cfg)
        cfgmod.save(self.cfg)
        self.error.configure(text=warnings[0] if warnings else "Shortcuts and icons recreated.")

    def _uninstall(self) -> None:
        _PLAT.open_terminal([str(paths.MAIN_CMD), "uninstall"])
        self.master.after(200, self.master.destroy)

    def save(self) -> None:
        loader = self.cfg.loader
        if self.pw_on.get():
            pw1, pw2 = self.pw1.get(), self.pw2.get()
            if pw1 or pw2 or not loader.password:
                if not pw1:
                    self.error.configure(text="Enter a password or untick the box.")
                    return
                if pw1 != pw2:
                    self.error.configure(text="The passwords do not match.")
                    return
                loader.password = security.hash_password(pw1)
        else:
            loader.password = None
        loader.hotkey = self.hotkey
        loader.tray = self.tray.get()
        loader.open_at_login = self.open_at_login.get()
        self.cfg.autostart_profiles = [pid for pid, var in self.autostart.items() if var.get()]
        loader.close_after_launch = self.close_after.get()
        loader.check_updates = self.check_updates.get()
        self.cfg.desktop_shortcuts = self.desktop.get()
        if self.cfg.path_added and not self.path.get():
            winutil.remove_from_user_path(paths.BIN_DIR)
        self.cfg.path_added = self.path.get()
        self.cfg.url_handler = self.url.get()
        cfgmod.save(self.cfg)
        warnings = _PLAT.apply(self.cfg)
        cfgmod.save(self.cfg)
        self.destroy()
        self.on_saved(warnings)


class PasteLinkDialog(Dialog):
    def __init__(self, parent, cfg, toast: Callable[[str], None]):
        super().__init__(parent, "Paste sign-in link")
        self.cfg, self.toast = cfg, toast
        b = self.body
        ttk.Label(b, text="After \"Continue with Google\" the browser offers to open Claude. "
                          "Cancel that, copy the claude://… link (for example right-click the "
                          "page's open-app button > Copy link) and paste it here.",
                  wraplength=440, justify="left").pack(anchor="w")
        self.link = tk.StringVar()
        try:
            clip = self.clipboard_get()
            if launch.valid_link(clip):
                self.link.set(clip.strip())
        except tk.TclError:
            pass
        entry = ttk.Entry(b, textvariable=self.link, width=60)
        entry.pack(fill="x", pady=(10, 10))
        ttk.Label(b, text="Send to profile").pack(anchor="w")
        running = _PLAT.running_profile_ids(cfg)
        preferred = running[0] if len(running) == 1 else next(
            (p.id for p in cfg.profiles if not p.system_default), cfg.profiles[0].id)
        self.names = [p.name for p in cfg.profiles]
        self.target = tk.StringVar(value=cfg.get(preferred).name)
        ttk.Combobox(b, textvariable=self.target, values=self.names, state="readonly").pack(
            fill="x", pady=(2, 0))
        self.error = ttk.Label(b, text="", style="Error.TLabel")
        self.error.pack(anchor="w", pady=(8, 0))
        self.buttons(("Cancel", self.cancel, False), ("Send", self.send, True))
        entry.bind("<Return>", lambda _e: self.send())
        self.show(entry)

    def send(self) -> None:
        url = self.link.get().strip()
        if not launch.valid_link(url):
            self.error.configure(text="That is not a claude:// link.")
            return
        profile = self.cfg.profiles[self.names.index(self.target.get())]

        def go(ok=True):
            if not ok:
                self.error.configure(text="Wrong password.")
                return
            try:
                launch.send_url(_PLAT, self.cfg, profile, url, gui=True, unlocked=True)
            except launch.LaunchError as e:
                self.error.configure(text=str(e))
                return
            self.destroy()
            self.toast(f"Link sent to \"{profile.name}\".")

        if profile.password and profile.id not in _PLAT.running_profile_ids(self.cfg):
            PasswordDialog(self, f"Claude ({profile.name})",
                           lambda pw: security.verify_password(pw, profile.password), go)
        else:
            go()


# --- the loader ----------------------------------------------------------------------------------

LONG_PRESS_MS = 450


class ProfileCard(tk.Frame):
    def __init__(self, loader, parent, profile):
        t = _theme
        super().__init__(parent, bg=t.card, highlightthickness=2, highlightbackground=t.border,
                         highlightcolor=t.border, cursor="hand2", padx=14, pady=12)
        self.loader, self.profile = loader, profile
        self._timer = None
        self._long = False
        size = int(80 * t.scale)
        self.icon = tk.Label(self, image=profile_image(self, profile, size), bg=t.card)
        self.icon.pack(pady=(int(10 * t.scale), 0))  # room for the corner badges
        self.name = tk.Label(self, text=profile.name, bg=t.card, fg=t.text,
                             font=("Segoe UI Semibold", 10), wraplength=int(130 * t.scale))
        self.name.pack(pady=(6, 0))
        self.status = tk.Label(self, text="", bg=t.card, fg=t.sub, font=("Segoe UI", 8))
        self.status.pack()
        self.check = tk.Label(self, bg=t.accent, fg="#ffffff",
                              **t.glyph("check", "✓"))
        more = tk.Label(self, bg=t.card, fg=t.sub, cursor="hand2", **t.glyph("more", "···"))
        more.place(relx=1.0, x=-2, y=2, anchor="ne")
        more.bind("<Button-1>", lambda e: (self.loader.card_menu(self.profile, e), "break")[1])
        self.more = more
        self.lock = None
        if profile.password:
            self.lock = tk.Label(self, bg=t.card, fg=t.sub, **t.glyph("lock", "locked"))
            self.lock.place(x=2, y=2, anchor="nw")
        for w in (self, self.icon, self.name, self.status):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Button-3>", lambda e: self.loader.card_menu(self.profile, e))
            w.bind("<Enter>", lambda _e: self._paint(hover=True))
            w.bind("<Leave>", lambda _e: self._paint(hover=False))
        self.selected = False
        self._paint()

    def _press(self, _event) -> None:
        self._long = False
        self._timer = self.after(LONG_PRESS_MS, self._long_press)

    def _long_press(self) -> None:
        self._timer = None
        self._long = True
        self.loader.card_long_pressed(self.profile)

    def _release(self, _event) -> None:
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
            self.loader.card_clicked(self.profile)

    def _paint(self, hover: bool = False) -> None:
        t = _theme
        bg = t.selected if self.selected else (t.hover if hover else t.card)
        for w in (self, self.icon, self.name, self.status, self.more, self.lock):
            if w is not None:
                w.configure(bg=bg)
        self.configure(highlightbackground=t.accent if self.selected else t.border,
                       highlightcolor=t.accent if self.selected else t.border)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        if selected:
            self.check.place(x=2, y=2, anchor="nw")
            self.check.lift()
        else:
            self.check.place_forget()
        self._paint()

    def set_running(self, running: bool) -> None:
        if running:
            self.status.configure(text="● running", fg=_theme.success)
        else:
            self.status.configure(text=self.profile.cli_command if self.profile.cli else "",
                                  fg=_theme.sub)


class Loader:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.cards = {}
        self.selection_mode = False
        self.selected = set()
        self.locked = bool(self.cfg.loader.password)
        self.events: "queue.Queue" = queue.Queue()
        t = _theme

        root.title(TITLE)
        root.minsize(int(520 * t.scale), int(360 * t.scale))

        header = ttk.Frame(root, padding=(18, 14, 12, 6))
        header.pack(fill="x")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="Claude Loader", style="Title.TLabel").pack(anchor="w")
        self.subtitle = ttk.Label(titles, text="", style="Sub.TLabel")
        self.subtitle.pack(anchor="w")
        self.menu_btn = ttk.Button(header, command=self.open_menu, width=3,
                                   **({"text": GLYPHS["menu"]} if t.icon_font else {"text": "☰"}))
        if t.icon_font:
            ttk.Style(root).configure("Glyph.TButton", font=(t.icon_font, 11))
            self.menu_btn.configure(style="Glyph.TButton")
        self.menu_btn.pack(side="right")
        self.select_btn = ttk.Button(header, text="Select", command=self.toggle_selection)
        self.select_btn.pack(side="right", padx=6)

        self.banner = ttk.Frame(root, padding=(18, 6))
        self.banner_label = ttk.Label(self.banner, text="", wraplength=int(440 * t.scale))
        self.banner_label.pack(side="left")
        self.banner_btn = ttk.Button(self.banner, text="Update", style=t.accent_button(),
                                     command=self.run_update)
        self.banner_btn.pack(side="right")

        self.content = ttk.Frame(root, padding=(18, 8))
        self.content.pack(fill="both", expand=True)

        bar = ttk.Frame(root, padding=(18, 8, 18, 14))
        bar.pack(fill="x", side="bottom")
        self.hint = ttk.Label(bar, text="", style="Sub.TLabel")
        self.hint.pack(side="left")
        self.start_all_btn = ttk.Button(bar, text="Start all",
                                        command=lambda: self.start([p.id for p in self.cfg.profiles]))
        self.start_group_btn = ttk.Button(bar, text="", style=t.accent_button(),
                                          command=lambda: self.start(
                                              [p.id for p in self.cfg.group()]))
        self.start_sel_btn = ttk.Button(bar, text="Start selected", style=t.accent_button(),
                                        command=self._start_selected)
        self.cancel_btn = ttk.Button(bar, text="Cancel",
                                     command=lambda: self.set_selection_mode(False))
        self.bar = bar

        self.toast_label = tk.Label(root, text="", bg=t.text, fg=t.bg, padx=12, pady=6,
                                    font=("Segoe UI", 9))
        self._toast_job = None

        root.bind("<Escape>", self._on_escape)
        root.bind("<Control-a>", lambda _e: self._select_all())
        for n in range(1, 6):
            root.bind(str(n), lambda _e, n=n: self._start_number(n))

        self.rebuild()
        root.after(200, self._poll_events)
        root.after(3000, self._refresh_running_timer)
        if not self.locked:
            self._after_unlock()

    # --- building --------------------------------------------------------------

    def reload(self) -> None:
        self.cfg = cfgmod.load() or cfgmod.Config()
        self.rebuild()

    def rebuild(self) -> None:
        version = _PLAT.installed_version()
        self.subtitle.configure(text=f"Claude Desktop {version}" if version
                                else "Claude Desktop is not installed")
        for w in self.content.winfo_children():
            w.destroy()
        self.cards = {}
        self.selected &= {p.id for p in self.cfg.profiles}
        interactive = not self.locked
        self.menu_btn.state(["!disabled"] if interactive else ["disabled"])
        if self.locked:
            self._build_locked()
        elif not self.cfg.profiles:
            self._build_empty()
        else:
            row = ttk.Frame(self.content)
            row.pack(expand=True)
            for i, p in enumerate(self.cfg.profiles):
                card = ProfileCard(self, row, p)
                card.grid(row=0, column=i, padx=6, pady=6, sticky="n")
                self.cards[p.id] = card
        show_select = interactive and len(self.cfg.profiles) > 1
        if show_select:
            self.select_btn.pack(side="right", padx=6)
        else:
            self.select_btn.pack_forget()
        if interactive and self.cfg.profiles:
            self.bar.pack(fill="x", side="bottom", before=self.content)
        else:
            self.bar.pack_forget()
        self._refresh_running()
        self._update_selection_ui()
        self._fit_window()

    def _fit_window(self) -> None:
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), int(560 * _theme.scale))
        h = max(self.root.winfo_reqheight(), int(380 * _theme.scale))
        self.root.geometry(f"{w}x{h}")

    def _build_locked(self) -> None:
        box = ttk.Frame(self.content)
        box.pack(expand=True)
        if _theme.icon_font:
            ttk.Label(box, text=GLYPHS["lock"], font=(_theme.icon_font, 30)).pack()
        ttk.Label(box, text="Loader locked", font=("Segoe UI Semibold", 13)).pack(pady=(6, 8))
        entry = ttk.Entry(box, show="•", width=30)
        entry.pack()
        error = ttk.Label(box, text="", style="Error.TLabel")
        error.pack(pady=4)

        def unlock(*_a):
            if security.verify_password(entry.get(), self.cfg.loader.password):
                self.locked = False
                self.rebuild()
                self._after_unlock()
            else:
                entry.delete(0, "end")
                error.configure(text="Wrong password.")

        entry.bind("<Return>", unlock)
        ttk.Button(box, text="Unlock", style=_theme.accent_button(), command=unlock).pack(pady=4)
        self.root.after(100, entry.focus_force)

    def _build_empty(self) -> None:
        box = ttk.Frame(self.content)
        box.pack(expand=True)
        ttk.Label(box, text="No profiles yet", font=("Segoe UI Semibold", 13)).pack()
        ttk.Label(box, text="Add a profile for each Claude account you use.",
                  style="Sub.TLabel").pack(pady=(4, 10))
        ttk.Button(box, text="Add profile", style=_theme.accent_button(),
                   command=self.add_profile).pack()

    def _after_unlock(self) -> None:
        if self.cfg.loader.check_updates:
            self.check_updates(manual=False)

    # --- running state -----------------------------------------------------------

    def _refresh_running(self) -> None:
        try:
            running = set(_PLAT.running_profile_ids(self.cfg))
        except Exception:
            running = set()
        for pid, card in self.cards.items():
            card.set_running(pid in running)

    def _refresh_running_timer(self) -> None:
        self._refresh_running()
        self.root.after(3000, self._refresh_running_timer)

    # --- selection --------------------------------------------------------------------

    def toggle_selection(self) -> None:
        self.set_selection_mode(not self.selection_mode)

    def set_selection_mode(self, on: bool, first=None) -> None:
        self.selection_mode = on
        # Start from the group used last time, plus the profile that was pressed.
        self.selected = set()
        if on:
            self.selected = {p.id for p in self.cfg.group()}
            if first:
                self.selected.add(first.id)
        self._update_selection_ui()

    def _update_selection_ui(self) -> None:
        for pid, card in self.cards.items():
            card.set_selected(pid in self.selected)
        for b in (self.start_all_btn, self.start_group_btn, self.start_sel_btn, self.cancel_btn):
            b.pack_forget()
        n = len(self.selected)
        if self.selection_mode:
            self.start_sel_btn.configure(text=f"Start selected ({n})" if n else "Start selected")
            self.start_sel_btn.state(["!disabled"] if n else ["disabled"])
            self.start_sel_btn.pack(side="right")
            self.cancel_btn.pack(side="right", padx=6)
            self.hint.configure(text="Click profiles to select them")
            self.select_btn.configure(text="Done")
        else:
            group = self.cfg.group()
            if group and len(group) < len(self.cfg.profiles):
                self.start_group_btn.configure(text=f"Start {self.cfg.group_label()}")
                self.start_group_btn.pack(side="right")
            if len(self.cfg.profiles) > 1:
                self.start_all_btn.pack(side="right", padx=(0, 6) if group else 0)
            self.hint.configure(text="Click to start · hold to select several · 1-5 keys")
            self.select_btn.configure(text="Select")

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

    def _select_all(self) -> None:
        if self.locked or not self.cards:
            return
        self.selection_mode = True
        self.selected = set(self.cards)
        self._update_selection_ui()

    def _start_selected(self) -> None:
        order = [p.id for p in self.cfg.profiles]
        self.start(sorted(self.selected, key=order.index), remember=True)

    def _start_number(self, n: int) -> None:
        if self.locked or self.selection_mode:
            return
        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry)):
            return
        if n <= len(self.cfg.profiles):
            self.start([self.cfg.profiles[n - 1].id])

    def _on_escape(self, _e) -> None:
        if self.selection_mode:
            self.set_selection_mode(False)
        else:
            self.root.destroy()

    # --- starting ---------------------------------------------------------------------

    def start(self, ids: List[str], remember: bool = False) -> None:
        """Start profiles (asking passwords one by one). `remember` saves them as the group."""
        if not ids:
            return
        if remember and self.cfg.remember_group(ids):
            cfgmod.save(self.cfg)
        try:
            running = set(_PLAT.running_profile_ids(self.cfg))
        except Exception:
            running = set()
        queue_, unlocked, failed = list(ids), set(), []

        def step():
            if not queue_:
                finish()
                return
            pid = queue_.pop(0)
            p = self.cfg.get(pid)
            if p.password and pid not in running:
                def done(ok, pid=pid, p=p):
                    (unlocked.add(pid) if ok else failed.append(p.name))
                    self.root.after(10, step)
                PasswordDialog(self.root, f"Claude ({p.name})",
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
                    self.toast(str(e), 6000)
                    return
            if failed:
                self.toast(f"Not started (password): {', '.join(failed)}")
            if self.selection_mode:
                self.set_selection_mode(False)
            if started and self.cfg.loader.close_after_launch and not failed:
                self.root.after(500, self.root.destroy)
            elif started:
                self.toast(f"Starting {', '.join(self.cfg.get(i).name for i in started)}…")
                self.root.after(2500, self._refresh_running)

        step()

    # --- menus and actions ---------------------------------------------------------------

    def open_menu(self) -> None:
        m = tk.Menu(self.root, tearoff=0)
        state = "normal" if len(self.cfg.profiles) < cfgmod.MAX_PROFILES else "disabled"
        m.add_command(label="Add profile…", command=self.add_profile, state=state)
        m.add_command(label="Paste sign-in link…", command=self.paste_link,
                      state="normal" if self.cfg.profiles else "disabled")
        m.add_command(label="Check for updates", command=lambda: self.check_updates(manual=True))
        m.add_separator()
        m.add_command(label="Settings…", command=self.open_settings)
        m.add_command(label="About", command=self.show_about)
        x = self.menu_btn.winfo_rootx()
        y = self.menu_btn.winfo_rooty() + self.menu_btn.winfo_height()
        m.tk_popup(x, y)

    def card_menu(self, profile, event) -> None:
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label=f"Start {profile.name}", command=lambda: self.start([profile.id]))
        m.add_command(label="Edit…", command=lambda: ProfileDialog(self.root, self.cfg, profile,
                                                                   self.reload))
        m.add_command(label="Remove…", command=lambda: self.remove_profile(profile))
        m.tk_popup(event.x_root, event.y_root)

    def add_profile(self) -> None:
        if len(self.cfg.profiles) >= cfgmod.MAX_PROFILES:
            self.toast(f"At most {cfgmod.MAX_PROFILES} profiles are supported.")
            return
        ProfileDialog(self.root, self.cfg, None, self.reload)

    def remove_profile(self, profile) -> None:
        body = f"The shortcuts, icon and terminal command of \"{profile.name}\" are removed."
        responses = [("cancel", "Cancel", False), ("remove", "Remove", True)]
        folders = profile_folders(profile)
        if folders:
            body += (f"\n\nIts data ({', '.join(paths.short(f) for f in folders)}) is kept unless "
                     "you choose to delete it. Deleting removes this account's login, settings "
                     "and history on this PC and cannot be undone.")
            responses.insert(1, ("delete", "Remove and delete data", False))
        if profile.id in _PLAT.running_profile_ids(self.cfg):
            body += "\n\nThis profile is running. Close its window first."

        def done(rid):
            if rid not in ("remove", "delete"):
                return
            self.cfg.profiles = [p for p in self.cfg.profiles if p.id != profile.id]
            cfgmod.save(self.cfg)
            _PLAT.apply(self.cfg)
            cfgmod.save(self.cfg)
            if rid == "delete":
                for folder in folders:
                    try:
                        shutil.rmtree(folder)
                    except OSError as e:
                        self.toast(f"Could not delete {paths.short(folder)}: {e}")
            self.reload()
            self.toast(f"Removed \"{profile.name}\".")

        confirm(self.root, f"Remove \"{profile.name}\"?", body, responses, done)

    def paste_link(self) -> None:
        PasteLinkDialog(self.root, self.cfg, self.toast)

    def open_settings(self) -> None:
        def saved(warnings):
            self.reload()
            self.toast(warnings[0] if warnings else "Settings saved.", 6000 if warnings else 2500)
        SettingsDialog(self.root, self.cfg, saved)

    def show_about(self) -> None:
        confirm(self.root, "Claude Loader",
                f"Claude Loader {VERSION}\nRun several Claude accounts and agents side by side.\n"
                "Free and open source (MIT): github.com/nurxie/claude-loader\n"
                "Unofficial, not affiliated with Anthropic.", [("ok", "OK", True)], lambda _r: None)

    def toast(self, text: str, ms: int = 2500) -> None:
        self.toast_label.configure(text=text, wraplength=int(480 * _theme.scale))
        self.toast_label.place(relx=0.5, rely=1.0, y=-64, anchor="s")
        self.toast_label.lift()
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(ms, self.toast_label.place_forget)

    # --- updates -------------------------------------------------------------------------

    def _poll_events(self) -> None:
        try:
            while True:
                fn, args = self.events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def _in_thread(self, work, done) -> None:
        def run():
            try:
                result = (work(), None)
            except Exception as e:  # reported to the UI
                result = (None, e)
            self.events.put((done, result))
        threading.Thread(target=run, daemon=True).start()

    def check_updates(self, manual: bool) -> None:
        def done(info, error):
            if error:
                if manual:
                    self.toast(f"Could not check for updates: {error}")
                return
            if info["available"]:
                self.banner_label.configure(text=info["message"])
                self.banner_btn.configure(text=info.get("action") or "Update")
                self.banner.pack(fill="x", before=self.content)
            else:
                self.banner.pack_forget()
                if manual:
                    self.toast(info["message"], 4000)
        self._in_thread(_PLAT.check_update, done)

    def run_update(self) -> None:
        def go(rid):
            if rid != "update":
                return
            self.banner_btn.state(["disabled"])
            self.banner_btn.configure(text="Working…")

            def done(result, error):
                self.banner_btn.state(["!disabled"])
                ok, msg = result if result else (False, str(error))
                if ok:
                    self.banner.pack_forget()
                    self.toast("The Claude copy is up to date.")
                    self.rebuild()
                else:
                    self.banner_btn.configure(text="Retry")
                    self.toast(msg or "Update failed.", 6000)

            self._in_thread(lambda: _PLAT.run_update(self.cfg, gui=True), done)

        body = ("Claude profiles run from a copy of the app. Refreshing copies the new version "
                "(about 700 MB, a minute or so).")
        if any(p.id in _PLAT.running_profile_ids(self.cfg) for p in self.cfg.profiles
               if not p.system_default):
            body += "\n\nClose the profile windows first."
        confirm(self.root, "Refresh the Claude copy?", body,
                [("cancel", "Cancel", False), ("update", "Refresh", True)], go)


def run_loader(plat) -> int:
    global _PLAT
    _PLAT = plat
    mutex = winutil.NamedMutex(LOADER_MUTEX)
    if mutex.already_exists:
        winutil.focus_window(TITLE)
        return 0
    winutil.set_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    _prepare_root(root)
    Loader(root)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.mainloop()
    mutex.close()
    return 0
