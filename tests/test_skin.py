"""Check the delivered skin, including visible pixels and every key-count layout."""

from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

from osu_paint_skin import SKIN_PROFILES, build_skin, build_skins


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
        self.archive = zipfile.ZipFile(ROOT / "pixel-film-16x10.osk")
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

    def test_default_export_names_include_the_aspect_ratio(self):
        for client, expected in (("lazer", "pixel-film-16x10.osk"),
                                 ("stable", "pixel-film-stable-16x10.osk")):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                paths = build_skins(directory, rows=12, target_client=client)
                self.assertEqual(len(paths), 5)
                self.assertEqual(paths[0].name, expected)
                with zipfile.ZipFile(paths[0]) as skin:
                    self.assertIn("Pixel Film 16:10 (12 rows)", skin.read("skin.ini").decode())

    def test_skin_omits_unsupported_stage_switches_and_hides_borders(self):
        for keys in range(10, 19):
            with self.subTest(keys=keys):
                section = self.sections.get(keys, {})
                self.assertNotIn("SplitStages", section)
                self.assertNotIn("StageSeparation", section)
                self.assertEqual(section.get("StageLeft"), "blank")
                self.assertEqual(section.get("StageRight"), "blank")

    def test_single_notes_and_all_hold_parts_are_opaque_black_on_white(self):
        images = {name: png_pixels(self.archive.read(name))
                  for name in ("pixel-black.png", "pixel-body.png")}
        for keys, section in self.sections.items():
            for column in range(keys):
                with self.subTest(keys=keys, column=column):
                    self.assertEqual(section[f"Colour{column + 1}"], "255,255,255,255")
                    for suffix in ("", "H", "L", "T"):
                        name = section[f"NoteImage{column}{suffix}"] + ".png"
                        width, height, pixels = images[name]
                        self.assertEqual(width, 40 if suffix == "L" else 1024)
                        self.assertEqual(height, 1024)
                        self.assertEqual(pixels, b"\x00\x00\x00\xff" * width * height)

    def test_stretched_body_stays_black_after_lazer_atlas_and_linear_sampling(self):
        # Reproduced against osu.Framework bundled with lazer 2026.921.0:
        # its 1024px atlas reserves 24px per edge and skips pure-black borders.
        # A one-row sprite therefore blends with transparent padding when stretched.
        for filename in SKIN_PROFILES:
            with zipfile.ZipFile(ROOT / filename) as skin:
                width, height, pixels = png_pixels(skin.read("pixel-body.png"))
            standalone = width > 1024 - 48 or height > 1024 - 48
            for v in (0, .1, .25, .5, .75, .9, 1):
                coordinate = v * height - .5
                lower = int(coordinate // 1)
                fraction = coordinate - lower

                def alpha(row):
                    if not standalone and not 0 <= row < height:
                        return 0  # Actual atlas omits the black edge upload.
                    row = min(height - 1, max(0, row))
                    return pixels[(row * width + width // 2) * 4 + 3]

                sampled = alpha(lower) * (1 - fraction) + alpha(lower + 1) * fraction
                self.assertEqual(sampled, 255, (filename, v, "white background reveals grey"))

    def test_note_and_hold_caps_do_not_expose_white_at_filtered_edges(self):
        # The same black-border atlas shortcut affects small square notes too,
        # not just stretched bodies. Check both axes and corners on every skin.
        for filename in SKIN_PROFILES:
            with zipfile.ZipFile(ROOT / filename) as skin:
                width, height, pixels = png_pixels(skin.read("pixel-black.png"))
            self.assertEqual(width, height, "Keep the original note aspect ratio")
            standalone = width > 1024 - 48 or height > 1024 - 48
            for u in (0, .001, .5, .999, 1):
                for v in (0, .001, .5, .999, 1):
                    with self.subTest(skin=filename, u=u, v=v):
                        x, y = u * width - .5, v * height - .5
                        left, top = int(x // 1), int(y // 1)
                        fx, fy = x - left, y - top

                        def alpha(column, row):
                            if not standalone and not (0 <= column < width and 0 <= row < height):
                                return 0
                            column = min(width - 1, max(0, column))
                            row = min(height - 1, max(0, row))
                            return pixels[(row * width + column) * 4 + 3]

                        sampled = ((1 - fx) * (1 - fy) * alpha(left, top)
                                   + fx * (1 - fy) * alpha(left + 1, top)
                                   + (1 - fx) * fy * alpha(left, top + 1)
                                   + fx * fy * alpha(left + 1, top + 1))
                        self.assertAlmostEqual(sampled, 255, msg="Transparent edges reveal the white stage")

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
