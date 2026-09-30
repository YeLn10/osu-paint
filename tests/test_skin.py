"""Check the delivered skin, including visible pixels and every key-count layout."""

from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

from osu_paint_skin import SKIN_PROFILES, build_skin


ROOT = Path(__file__).resolve().parents[1]


def mania_sections(text):
    sections, current = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            current = {} if line == "[Mania]" else None
            if current is not None:
                sections.append(current)
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    return {int(section["Keys"]): section for section in sections}, len(sections)


def png_pixels(data):
    # Skin sprites use unfiltered 8-bit RGBA, allowing checks without Pillow.
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Not a PNG")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29])
    if (depth, colour, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise AssertionError("Expected non-interlaced RGBA PNG")
    compressed, offset = bytearray(), 8
    while offset < len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack(">I", data[offset + 8 + size:offset + 12 + size])[0]
        if zlib.crc32(kind + payload) != crc:
            raise AssertionError("PNG CRC mismatch")
        if kind == b"IDAT":
            compressed.extend(payload)
        offset += size + 12
    raw = zlib.decompress(compressed)
    stride = width * 4 + 1
    if len(raw) != stride * height or any(raw[y * stride] != 0 for y in range(height)):
        raise AssertionError("Expected complete unfiltered rows")
    pixels = b"".join(raw[y * stride + 1:(y + 1) * stride] for y in range(height))
    return width, height, pixels


class SkinTests(unittest.TestCase):
    def setUp(self):
        self.archive = zipfile.ZipFile(ROOT / "pixel-film.osk")
        self.addCleanup(self.archive.close)
        self.sections, self.section_count = mania_sections(
            self.archive.read("skin.ini").decode("utf-8-sig"))

    def test_every_key_count_has_its_own_configuration(self):
        self.assertEqual(set(self.sections), set(range(1, 19)))
        self.assertEqual(self.section_count, 18)
        for keys, section in self.sections.items():
            with self.subTest(keys=keys):
                for option, length in (("ColumnWidth", keys), ("ColumnSpacing", keys - 1),
                                       ("ColumnLineWidth", keys + 1)):
                    values = [float(value) for value in section[option].split(",") if value]
                    self.assertEqual(len(values), length)
                    expected = 768 / keys if option == "ColumnWidth" else 0
                    self.assertTrue(all(abs(value - expected) < 1e-8 for value in values))

    def test_skin_omits_unsupported_stage_switches_and_hides_borders(self):
        for keys in range(10, 19):
            with self.subTest(keys=keys):
                section = self.sections.get(keys, {})
                self.assertNotIn("SplitStages", section)
                self.assertNotIn("StageSeparation", section)
                self.assertEqual(section.get("StageLeft"), "blank")
                self.assertEqual(section.get("StageRight"), "blank")

    def test_single_notes_and_all_hold_parts_are_opaque_black_on_white(self):
        for keys, section in self.sections.items():
            for column in range(keys):
                with self.subTest(keys=keys, column=column):
                    self.assertEqual(section[f"Colour{column + 1}"], "255,255,255,255")
                    for suffix in ("", "H", "L", "T"):
                        name = section[f"NoteImage{column}{suffix}"] + ".png"
                        width, height, pixels = png_pixels(self.archive.read(name))
                        self.assertEqual(width, 40)
                        self.assertEqual(height, 1 if suffix == "L" else 40)
                        self.assertEqual(pixels, b"\x00\x00\x00\xff" * width * height)

    def test_judgement_position_matches_lazer_compiler(self):
        for keys, section in self.sections.items():
            with self.subTest(keys=keys):
                self.assertEqual(section["HitPosition"], "480")
                self.assertEqual(section["WidthForNoteHeightScale"], "20")
                self.assertEqual(section["UpsideDown"], "0")
                self.assertEqual(section["NoteBodyStyle"], "0")

    def test_hidden_stage_assets_are_transparent_and_all_references_exist(self):
        self.assertIsNone(self.archive.testzip())
        width, height, pixels = png_pixels(self.archive.read("blank.png"))
        self.assertEqual(pixels, b"\x00" * width * height * 4)
        for section in self.sections.values():
            for key, value in section.items():
                if key.startswith(("NoteImage", "KeyImage")) or key in (
                        "StageLeft", "StageRight", "StageBottom", "StageHint",
                        "StageLight", "LightingN", "LightingL"):
                    self.assertIn(value + ".png", self.archive.namelist())

    def test_delivered_archive_is_reproducible_from_source(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename, (ratio, label) in SKIN_PROFILES.items():
                with self.subTest(profile=filename):
                    rebuilt = build_skin(Path(directory) / filename, aspect_ratio=ratio, label=label)
                    self.assertEqual(rebuilt.read_bytes(), (ROOT / filename).read_bytes())

    def test_all_profiles_fill_the_available_width_without_changing_key_counts(self):
        for filename, (ratio, _) in SKIN_PROFILES.items():
            with zipfile.ZipFile(ROOT / filename) as archive:
                sections, _ = mania_sections(archive.read("skin.ini").decode())
            for keys in range(1, 19):
                with self.subTest(profile=filename, keys=keys):
                    width = float(sections[keys]["ColumnWidth"].split(",")[0])
                    self.assertAlmostEqual(width * keys, 480 * ratio, delta=1e-7)


if __name__ == "__main__":
    unittest.main()
