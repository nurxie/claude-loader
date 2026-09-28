"""The hand-written PNG and ICO codecs, and the recolouring on top of them."""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import context  # noqa: F401
from claude_profiles.core import icons


def solid(width: int, height: int, rgba) -> icons.Image:
    return width, height, bytearray(bytes(rgba) * (width * height))


def pixel(img: icons.Image, x: int, y: int):
    w, _, buf = img
    i = (y * w + x) * 4
    return tuple(buf[i:i + 4])


def png_with(ctype: int, depth: int, width: int, height: int, rows: bytes,
             extra: bytes = b"") -> bytes:
    """A minimal PNG, so the decoder can be tried on shapes we never write."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
            + extra
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


class TestPng(unittest.TestCase):
    def test_what_is_written_is_read_back(self):
        img = solid(4, 3, (10, 20, 30, 255))
        again = icons.decode_png(icons.encode_png(img))
        self.assertEqual(again[:2], (4, 3))
        self.assertEqual(pixel(again, 2, 1), (10, 20, 30, 255))

    def test_transparency_survives(self):
        img = solid(2, 2, (1, 2, 3, 0))
        self.assertEqual(pixel(icons.decode_png(icons.encode_png(img)), 0, 0), (1, 2, 3, 0))

    def test_a_greyscale_png_is_read(self):
        # One row of filter 0 plus two grey samples.
        data = png_with(0, 8, 2, 1, b"\x00\x40\x80")
        self.assertEqual(pixel(icons.decode_png(data), 0, 0), (0x40, 0x40, 0x40, 255))

    def test_a_palette_png_is_read(self):
        def chunk(kind, payload):
            return (struct.pack(">I", len(payload)) + kind + payload
                    + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

        palette = chunk(b"PLTE", bytes((255, 0, 0, 0, 0, 255)))
        data = png_with(3, 8, 2, 1, b"\x00\x00\x01", extra=palette)
        img = icons.decode_png(data)
        self.assertEqual(pixel(img, 0, 0), (255, 0, 0, 255))
        self.assertEqual(pixel(img, 1, 0), (0, 0, 255, 255))

    def test_the_up_filter_is_undone(self):
        # Row 1 is filter 2 (up): each sample adds the one above it.
        rows = b"\x00" + bytes((10, 20, 30, 255)) + b"\x02" + bytes((5, 5, 5, 0))
        img = icons.decode_png(png_with(6, 8, 1, 2, rows))
        self.assertEqual(pixel(img, 0, 1), (15, 25, 35, 255))

    def test_something_that_is_not_a_png_is_refused(self):
        with self.assertRaises(ValueError):
            icons.decode_png(b"certainly not a png")


class TestIco(unittest.TestCase):
    def test_what_is_written_is_read_back(self):
        blob = icons.encode_ico([solid(32, 32, (9, 8, 7, 255)),
                                 solid(16, 16, (9, 8, 7, 255))])
        img = icons.decode_ico(blob)
        self.assertEqual(img[:2], (32, 32))        # the largest image comes back
        self.assertEqual(pixel(img, 5, 5), (9, 8, 7, 255))

    def test_an_empty_icon_is_refused(self):
        with self.assertRaises(ValueError):
            icons.decode_ico(struct.pack("<HHH", 0, 1, 0))


class TestResize(unittest.TestCase):
    def test_a_square_keeps_its_colour(self):
        out = icons.resize(solid(64, 64, (200, 100, 50, 255)), 16)
        self.assertEqual(out[:2], (16, 16))
        self.assertEqual(pixel(out, 8, 8), (200, 100, 50, 255))

    def test_a_wide_image_is_centred_with_room_above_and_below(self):
        out = icons.resize(solid(64, 32, (200, 100, 50, 255)), 16)
        self.assertEqual(out[:2], (16, 16))
        self.assertEqual(pixel(out, 8, 8)[3], 255)   # the middle is the image
        self.assertEqual(pixel(out, 8, 0)[3], 0)     # the top edge is empty

    def test_the_right_size_is_left_alone(self):
        img = solid(16, 16, (1, 2, 3, 255))
        self.assertIs(icons.resize(img, 16), img)


class TestRecolor(unittest.TestCase):
    def test_a_colour_moves_to_the_target_hue(self):
        img = icons.recolor(solid(2, 2, (217, 119, 87, 255)), 140, 1.0)   # green
        r, g, b, _ = pixel(img, 0, 0)
        self.assertGreater(g, r)
        self.assertGreater(g, b)

    def test_greys_and_whites_are_left_alone(self):
        for color in ((255, 255, 255, 255), (128, 128, 128, 255), (0, 0, 0, 255)):
            img = icons.recolor(solid(1, 1, color), 140, 1.0)
            self.assertEqual(pixel(img, 0, 0), color)

    def test_fully_transparent_pixels_are_skipped(self):
        img = icons.recolor(solid(1, 1, (217, 119, 87, 0)), 140, 1.0)
        self.assertEqual(pixel(img, 0, 0), (217, 119, 87, 0))

    def test_no_saturation_makes_it_grey(self):
        img = icons.recolor(solid(1, 1, (217, 119, 87, 255)), 0, 0.0)
        r, g, b, _ = pixel(img, 0, 0)
        self.assertEqual((r, g), (r, r))
        self.assertEqual(b, r)


class TestMakeIcon(unittest.TestCase):
    def test_a_missing_source_still_produces_an_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = icons.make_icon(None, "green", Path(tmp) / "x.png")
            img = icons.decode_png(out.read_bytes())
            self.assertEqual(img[:2], (icons.SIZE, icons.SIZE))
            self.assertEqual(pixel(img, icons.SIZE // 2, icons.SIZE // 2)[3], 255)
            self.assertEqual(pixel(img, 0, 0)[3], 0)      # a disc, so the corner is empty

    def test_an_ico_gets_several_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = icons.make_icon(None, "blue", Path(tmp) / "x.ico")
            count = struct.unpack("<HHH", out.read_bytes()[:6])[2]
            self.assertEqual(count, 4)

    def test_the_source_is_used_when_there_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.png"
            src.write_bytes(icons.encode_png(solid(64, 64, (217, 119, 87, 255))))
            out = icons.make_icon(str(src), "green", Path(tmp) / "out.png", size=32)
            img = icons.decode_png(out.read_bytes())
            r, g, b, _ = pixel(img, 16, 16)
            self.assertGreater(g, r)


if __name__ == "__main__":
    unittest.main()
