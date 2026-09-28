"""Windows hotkeys in the form "Win+Shift+C" <-> RegisterHotKey modifiers and key codes."""

import ctypes
from typing import Optional, Tuple

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}
# Windows writes shortcuts as Win+Ctrl+Alt+Shift+Key (e.g. Win+Shift+S, Ctrl+Alt+Del).
_ORDER = [("Win", MOD_WIN), ("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT)]

_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "insert": 0x2D, "delete": 0x2E,
         "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
         "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _KEYS[_c.lower()] = ord(_c)
for _n in range(1, 25):
    _KEYS[f"f{_n}"] = 0x6F + _n

PRESETS = [("Win+Shift+C", "Win+Shift+C"), ("Ctrl+Alt+C", "Ctrl+Alt+C"),
           ("Ctrl+Shift+Space", "Ctrl+Shift+Space")]


def parse(accel: Optional[str]) -> Optional[Tuple[int, int]]:
    """'Win+Shift+C' -> (modifiers, virtual key), or None if invalid."""
    if not accel:
        return None
    parts = [p.strip().lower() for p in accel.split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods = 0
    for p in parts[:-1]:
        if p not in _MODS:
            return None
        mods |= _MODS[p]
    key = _KEYS.get(parts[-1])
    # Shift alone is not enough: it would steal ordinary typing.
    if key is None or not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None
    return mods, key


def normalize(accel: Optional[str]) -> Optional[str]:
    parsed = parse(accel)
    if not parsed:
        return None
    mods, vk = parsed
    names = [n for n, m in _ORDER if mods & m]
    key = next(k for k, v in _KEYS.items() if v == vk and (len(k) > 1 or k.isalnum()))
    key = key.upper() if len(key) == 1 else key[0].upper() + key[1:]
    if key.startswith("F") and key[1:].isdigit():
        key = key.upper()
    key = {"Pageup": "PageUp", "Pagedown": "PageDown"}.get(key, key)
    return "+".join(names + [key])


def is_free(accel: str) -> bool:
    """Try to register the hotkey for a moment. False if another program owns it."""
    parsed = parse(accel)
    if not parsed:
        return False
    user32 = ctypes.windll.user32
    hotkey_id = 0x5C1A
    if not user32.RegisterHotKey(None, hotkey_id, parsed[0] | MOD_NOREPEAT, parsed[1]):
        return False
    user32.UnregisterHotKey(None, hotkey_id)
    return True


def from_tk_event(keysym: str) -> Optional[str]:
    """Build an accelerator from a Tk key event plus the modifier keys held right now."""
    user32 = ctypes.windll.user32

    def down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    names = []
    if down(0x5B) or down(0x5C):
        names.append("Win")
    if down(0x11):
        names.append("Ctrl")
    if down(0x12):
        names.append("Alt")
    if down(0x10):
        names.append("Shift")
    key = {"space": "Space", "Return": "Enter", "Prior": "PageUp", "Next": "PageDown"}.get(
        keysym, keysym)
    return normalize("+".join(names + [key]))
