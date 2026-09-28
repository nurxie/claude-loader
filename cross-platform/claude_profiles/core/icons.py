"""Colored copies of the Claude icon, one per profile.

The icon is taken from the locally installed Claude Desktop and recolored on
this machine; no Anthropic artwork is shipped with this project.

Pure Python (zlib only): reads PNG and ICO, writes PNG and ICO. SVG sources are
read through GdkPixbuf when it is available (Linux).
"""

import colorsys
import struct
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

from . import config as cfgmod

SIZE = 256

# An image is (width, height, rgba bytearray without row padding).
Image = Tuple[int, int, bytearray]


# --- PNG ------------------------------------------------------------------------

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data: bytes) -> Image:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, idat = 8, []
    width = height = depth = ctype = interlace = None
    palette, trns = None, None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
    if interlace:
        raise ValueError("interlaced PNG is not supported")
    if depth not in (8, 16) and not (ctype == 3 and depth in (1, 2, 4, 8)):
        raise ValueError(f"unsupported PNG bit depth {depth}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits_pp = channels * depth
    bpp = max(1, bits_pp // 8)
    stride = (width * bits_pp + 7) // 8
    raw = zlib.decompress(b"".join(idat))

    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                up_left = prev[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + _paeth(left, prev[x], up_left)) & 0xFF
        rows.append(line)
        prev = line

    out = bytearray(width * height * 4)
    o = 0
    for line in rows:
        if depth == 16:  # keep the high byte of each sample
            line = line[0::2]
        if ctype == 3:
            if depth < 8:
                per = 8 // depth
                idxs = []
                for byte in line:
                    for k in range(per):
                        idxs.append((byte >> (8 - depth * (k + 1))) & ((1 << depth) - 1))
                line = bytearray(idxs[:width])
            for x in range(width):
                n = line[x]
                out[o:o + 3] = palette[n * 3:n * 3 + 3]
                out[o + 3] = trns[n] if trns and n < len(trns) else 255
                o += 4
        else:
            for x in range(width):
                if ctype == 6:
                    out[o:o + 4] = line[x * 4:x * 4 + 4]
                elif ctype == 2:
                    out[o:o + 3] = line[x * 3:x * 3 + 3]
                    out[o + 3] = 255
                elif ctype == 4:
                    g = line[x * 2]
                    out[o:o + 4] = bytes((g, g, g, line[x * 2 + 1]))
                else:
                    g = line[x]
                    out[o:o + 4] = bytes((g, g, g, 255))
                o += 4
    return width, height, out


def encode_png(img: Image) -> bytes:
    width, height, buf = img
    row = width * 4
    raw = b"".join(b"\0" + bytes(buf[y * row:(y + 1) * row]) for y in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# --- ICO ------------------------------------------------------------------------

def _decode_bmp_icon(data: bytes, width: int, height: int) -> Image:
    """32-bit BMP icon image (BITMAPINFOHEADER, bottom-up)."""
    header_size, w, h2, _, bpp = struct.unpack("<IiiHH", data[:16])
    if bpp != 32:
        raise ValueError(f"only 32-bit BMP icons are supported, got {bpp}")
    w = w or width
    h = (h2 // 2) or height
    pixels = data[header_size:header_size + w * h * 4]
    out = bytearray(w * h * 4)
    for y in range(h):
        src = (h - 1 - y) * w * 4
        for x in range(w):
            b, g, r, a = pixels[src + x * 4:src + x * 4 + 4]
            o = (y * w + x) * 4
            out[o:o + 4] = bytes((r, g, b, a))
    return w, h, out


def decode_ico(data: bytes) -> Image:
    """The largest image inside an .ico file."""
    _, kind, count = struct.unpack("<HHH", data[:6])
    if kind != 1 or count == 0:
        raise ValueError("not an icon file")
    entries = []
    for i in range(count):
        w, h, _, _, _, bpp, size, offset = struct.unpack("<BBBBHHII", data[6 + i * 16:22 + i * 16])
        entries.append((w or 256, h or 256, bpp, size, offset))
    errors = []
    for w, h, bpp, size, offset in sorted(entries, key=lambda e: (e[0], e[2]), reverse=True):
        blob = data[offset:offset + size]
        try:
            if blob[:8] == b"\x89PNG\r\n\x1a\n":
                return decode_png(blob)
            return _decode_bmp_icon(blob, w, h)
        except ValueError as e:
            errors.append(str(e))
    raise ValueError("no readable image in icon: " + "; ".join(errors))


def encode_ico(images: List[Image]) -> bytes:
    """An .ico with PNG-compressed entries (Windows Vista and later)."""
    blobs = [encode_png(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for (w, h, _), blob in zip(images, blobs):
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return header + entries + b"".join(blobs)


# --- image operations -------------------------------------------------------------

def resize(img: Image, size: int) -> Image:
    """Scale to size x size (keeping aspect, centered), area-averaging when shrinking."""
    w, h, buf = img
    if w == size and h == size:
        return img
    scale = size / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    out = bytearray(size * size * 4)
    ox, oy = (size - nw) // 2, (size - nh) // 2
    for y in range(nh):
        sy0, sy1 = y / scale, (y + 1) / scale
        ys = range(int(sy0), min(h, max(int(sy0) + 1, int(sy1 + 0.999))))
        for x in range(nw):
            sx0, sx1 = x / scale, (x + 1) / scale
            xs = range(int(sx0), min(w, max(int(sx0) + 1, int(sx1 + 0.999))))
            r = g = b = a = n = 0
            for sy in ys:
                row = sy * w * 4
                for sx in xs:
                    i = row + sx * 4
                    pa = buf[i + 3]
                    r += buf[i] * pa
                    g += buf[i + 1] * pa
                    b += buf[i + 2] * pa
                    a += pa
                    n += 1
            o = ((y + oy) * size + (x + ox)) * 4
            if a:
                out[o:o + 4] = bytes((r // a, g // a, b // a, a // n))
    return size, size, out


def recolor(img: Image, hue_deg: float, sat_factor: float) -> Image:
    """Move every colored pixel to the target hue; leave white, gray and black alone."""
    w, h, buf = img
    target = (hue_deg % 360) / 360.0
    cache = {}
    for i in range(0, len(buf), 4):
        if buf[i + 3] == 0:
            continue
        key = (buf[i], buf[i + 1], buf[i + 2])
        out = cache.get(key)
        if out is None:
            _, s, v = colorsys.rgb_to_hsv(key[0] / 255, key[1] / 255, key[2] / 255)
            if s < 0.12:
                out = key
            else:
                r, g, b = colorsys.hsv_to_rgb(target, min(1.0, s * sat_factor), v)
                out = (round(r * 255), round(g * 255), round(b * 255))
            cache[key] = out
        buf[i], buf[i + 1], buf[i + 2] = out
    return img


def fallback_disc(swatch: str, size: int = SIZE) -> Image:
    """A plain colored disc, used when no Claude icon can be read."""
    r, g, b = (int(swatch[i:i + 2], 16) for i in (1, 3, 5))
    buf = bytearray(size * size * 4)
    c = (size - 1) / 2
    radius = size * 0.46
    for y in range(size):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = max(0.0, min(1.0, radius - d + 0.5))
            if a:
                i = (y * size + x) * 4
                buf[i:i + 4] = bytes((r, g, b, round(a * 255)))
    return size, size, buf


# --- loading and the main entry point ---------------------------------------------

def _load_with_gdkpixbuf(src: str) -> Image:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, SIZE, SIZE, True)
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, stride = pb.get_width(), pb.get_height(), pb.get_rowstride()
    raw = pb.get_pixels()
    buf = bytearray(b"".join(raw[y * stride:y * stride + w * 4] for y in range(h)))
    return w, h, buf


def load_image(src: str) -> Image:
    data = Path(src).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return decode_png(data)
    if data[:4] == b"\0\0\1\0":
        return decode_ico(data)
    return _load_with_gdkpixbuf(src)


def colored_image(src: Optional[str], color: str, size: int = SIZE) -> Image:
    _, hue, sat, swatch = cfgmod.COLORS[color]
    try:
        if not src:
            raise FileNotFoundError("no source icon")
        img = resize(load_image(src), size)
    except Exception:
        return fallback_disc(swatch, size)
    if hue is not None:
        recolor(img, hue, sat)
    return img


def make_icon(src: Optional[str], color: str, dst: Path, size: int = SIZE) -> Path:
    """Write a recolored PNG (or .ico if dst ends with .ico) of the Claude icon."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = colored_image(src, color, SIZE)
    if dst.suffix.lower() == ".ico":
        images = [img] + [resize(_copy(img), s) for s in (48, 32, 16)]
        dst.write_bytes(encode_ico(images))
    else:
        dst.write_bytes(encode_png(img if size == SIZE else resize(img, size)))
    return dst


def _copy(img: Image) -> Image:
    return img[0], img[1], bytearray(img[2])
