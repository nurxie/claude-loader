"""Tray agent: owns the global hotkey and offers a quick tray menu.

Pure ctypes (no extra packages). One instance per Windows session. It re-reads
the config when it changes and exits when the loader or the agent is turned
off, or when claude-profiles is uninstalled.
"""

import ctypes
from ctypes import wintypes

from ..core import config as cfgmod
from ..core import paths
from . import hotkeys, integration, winutil

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = wintypes.LPARAM
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)

WM_NULL, WM_DESTROY, WM_COMMAND, WM_TIMER = 0x0000, 0x0002, 0x0111, 0x0113
WM_HOTKEY, WM_CONTEXTMENU, WM_LBUTTONUP, WM_RBUTTONUP = 0x0312, 0x007B, 0x0202, 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_WARNING = 0x2
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
IDI_APPLICATION = 32512
HOTKEY_ID, TIMER_ID = 1, 1
CMD_OPEN, CMD_QUIT, CMD_ALL, CMD_GROUP, CMD_USAGE, CMD_PROFILE = 1, 2, 3, 4, 5, 100


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


def _prototypes() -> None:
    H, U, W, L = wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    user32.DefWindowProcW.argtypes = [H, U, W, L]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, H, wintypes.HMENU, wintypes.HINSTANCE,
                                       wintypes.LPVOID]
    user32.CreateWindowExW.restype = H
    user32.DestroyWindow.argtypes = [H]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), H, U, U]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.PostMessageW.argtypes = [H, U, W, L]
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, U, ctypes.c_int,
                                  ctypes.c_int, U]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, U, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, U, U]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, U, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      H, wintypes.LPVOID]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.SetForegroundWindow.argtypes = [H]
    user32.RegisterHotKey.argtypes = [H, ctypes.c_int, U, U]
    user32.UnregisterHotKey.argtypes = [H, ctypes.c_int]
    user32.SetTimer.argtypes = [H, ctypes.c_size_t, U, wintypes.LPVOID]
    user32.KillTimer.argtypes = [H, ctypes.c_size_t]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = U
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Agent:
    def __init__(self, plat):
        self.plat = plat
        self.cfg = cfgmod.load()
        self.mtime = cfgmod.mtime()
        self.hwnd = None
        self.hotkey = None
        self.hicon = None
        self._wndproc = WNDPROC(self._proc)  # keep a reference for the lifetime of the window
        self.taskbar_created = 0

    # --- lifetime --------------------------------------------------------------------

    def should_run(self) -> bool:
        return bool(self.cfg and self.cfg.loader.enabled and self.cfg.loader.tray
                    and not integration.AGENT_STOP.exists())

    def run(self) -> int:
        mutex = winutil.NamedMutex(integration.AGENT_MUTEX)
        if mutex.already_exists:
            return 0
        if integration.AGENT_STOP.exists():
            integration.AGENT_STOP.unlink()
        if not self.should_run():
            mutex.close()
            return 0
        _prototypes()
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "ClaudeProfilesAgentWindow"
        user32.RegisterClassExW(ctypes.byref(wc))
        # A normal (never shown) window, so it also gets the TaskbarCreated broadcast.
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "Claude Profiles Agent", 0,
                                           0, 0, 0, 0, None, None, hinst, None)
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._load_icon()
        self._tray(NIM_ADD)
        self._register_hotkey()
        user32.SetTimer(self.hwnd, TIMER_ID, 1500, None)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._tray(NIM_DELETE)
        if self.hotkey:
            user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
        if integration.AGENT_STOP.exists():
            try:
                integration.AGENT_STOP.unlink()
            except OSError:
                pass
        mutex.close()
        return 0

    # --- tray icon --------------------------------------------------------------------

    def _load_icon(self) -> None:
        ico = integration.loader_ico()
        self.hicon = None
        if ico.exists():
            self.hicon = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if not self.hicon:
            self.hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _tray(self, action: int, info: str = "") -> None:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        tip = "Claude Loader"
        if self.cfg and self.cfg.loader.hotkey:
            tip += f" ({hotkeys.normalize(self.cfg.loader.hotkey)})" if self.hotkey else \
                " (hotkey unavailable)"
        nid.szTip = tip[:127]
        if info:
            nid.uFlags |= NIF_INFO
            nid.szInfo = info[:255]
            nid.szInfoTitle = "Claude Loader"
            nid.dwInfoFlags = NIIF_WARNING
        shell32.Shell_NotifyIconW(action, ctypes.byref(nid))

    # --- hotkey -------------------------------------------------------------------------

    def _register_hotkey(self) -> None:
        if self.hotkey:
            user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self.hotkey = None
        wanted = self.cfg.loader.hotkey if self.cfg else None
        parsed = hotkeys.parse(wanted)
        if not parsed:
            self._tray(NIM_MODIFY)
            return
        if user32.RegisterHotKey(self.hwnd, HOTKEY_ID, parsed[0] | hotkeys.MOD_NOREPEAT, parsed[1]):
            self.hotkey = wanted
            self._tray(NIM_MODIFY)
        else:
            self._tray(NIM_MODIFY, f"{hotkeys.normalize(wanted)} is already used by another "
                                   "program. Pick another hotkey in the loader settings.")

    # --- actions ---------------------------------------------------------------------------

    def _spawn(self, *args: str) -> None:
        winutil.allow_foreground_for_children()
        winutil.start_detached([winutil.pythonw(), "-m", "claude_profiles.windows", *args],
                               cwd=str(paths.HOME))

    def open_loader(self) -> None:
        if not winutil.focus_window(integration.LOADER_TITLE):
            self._spawn("loader")

    def show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "Open Claude Loader")
        user32.SetMenuDefaultItem(menu, CMD_OPEN, 0)
        profiles = self.cfg.profiles if self.cfg else []
        if profiles:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            try:
                running = set(self.plat.running_profile_ids(self.cfg))
            except Exception:
                running = set()
            for i, p in enumerate(profiles):
                flags = MF_STRING | (MF_CHECKED if p.id in running else 0)
                user32.AppendMenuW(menu, flags, CMD_PROFILE + i, f"Start {p.name}")
            group = self.cfg.group()
            if group and len(group) < len(profiles):
                user32.AppendMenuW(menu, MF_STRING, CMD_GROUP,
                                   f"Start group: {self.cfg.group_label(48)}")
            if len(profiles) > 1:
                user32.AppendMenuW(menu, MF_STRING, CMD_ALL, "Start all")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, CMD_USAGE, "Token usage...")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "Quit tray agent (hotkey off until sign-in)")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0,
                                    self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == CMD_OPEN:
            self.open_loader()
        elif cmd == CMD_QUIT:
            user32.DestroyWindow(self.hwnd)
        elif cmd == CMD_ALL:
            self._spawn("launch", *[p.id for p in profiles])
        elif cmd == CMD_GROUP:
            self._spawn("launch", *[p.id for p in self.cfg.group()])
        elif cmd == CMD_USAGE:
            if not winutil.focus_window(integration.USAGE_TITLE):
                self._spawn("usage")
        elif cmd >= CMD_PROFILE and cmd - CMD_PROFILE < len(profiles):
            self._spawn("launch", profiles[cmd - CMD_PROFILE].id)

    def tick(self) -> None:
        mtime = cfgmod.mtime()
        if mtime != self.mtime:
            self.mtime = mtime
            old_hotkey = self.cfg.loader.hotkey if self.cfg else None
            try:
                self.cfg = cfgmod.load()
            except cfgmod.ConfigError:
                return
            if self.cfg and self.cfg.loader.hotkey != old_hotkey:
                self._register_hotkey()
        if not self.should_run():
            user32.DestroyWindow(self.hwnd)
            return
        # Claude writes its own claude:// handler each time it starts; put ours back.
        if self.cfg.url_handler and not integration.url_handler_is_ours():
            previous = self.cfg.previous_url_handler
            try:
                integration.enable_url_handler(self.cfg)
                if self.cfg.previous_url_handler != previous:
                    cfgmod.save(self.cfg)
                    self.mtime = cfgmod.mtime()
            except OSError:
                pass

    # --- window procedure ----------------------------------------------------------------------

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_HOTKEY and wparam == HOTKEY_ID:
                self.open_loader()
                return 0
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    self.open_loader()
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.show_menu()
                return 0
            if msg == WM_TIMER:
                self.tick()
                return 0
            if msg == self.taskbar_created and msg:
                self._tray(NIM_ADD)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass  # never let an exception escape into Windows
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def run(plat) -> int:
    return Agent(plat).run()
