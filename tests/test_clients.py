"""One public compiler/export API, with explicit client-specific semantics."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from osu_paint import compile_frames, main, write_output
from osu_paint_skin import SKIN_PROFILES, build_skin, build_skins, skin_filename
from test_skin import mania_sections


class ClientTests(unittest.TestCase):
    def test_default_remains_lazer(self):
        frames = [["#.", ".#", "##"]]
        self.assertEqual(compile_frames(frames, 2000, 3000, fast_clear=True),
                         compile_frames(frames, 2000, 3000, fast_clear=True, target_client="lazer"))

    def test_client_cannot_silently_fall_back(self):
        with self.assertRaises(ValueError):
            compile_frames([["#"]], 2000, 3000, target_client="unknown")

    def test_selected_client_reaches_export_and_matching_skin(self):
        for client in ("lazer", "stable"):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                plan = compile_frames([["#.", ".#", "##"]], 2000, 3000,
                                      fast_clear=True, target_client=client)
                write_output(plan, Path(directory))
                root = Path(directory)
                self.assertIn(f"Version: {client} ", (root / "pattern.osu").read_text())
                skins = list(root.glob("pixel-film*.osk"))
                self.assertEqual(len(skins), 5)
                for skin in skins:
                    with zipfile.ZipFile(skin) as archive:
                        ini = archive.read("skin.ini").decode()
                    self.assertEqual("SplitStages: 0" in ini, client == "stable")
                    self.assertIn("(3 rows)", ini)

    def test_both_delivery_skin_sets_can_coexist(self):
        with tempfile.TemporaryDirectory() as directory:
            lazer = build_skins(directory, target_client="lazer")
            stable = build_skins(directory, target_client="stable")
            self.assertTrue(set(lazer).isdisjoint(stable))
            self.assertEqual(len(list(Path(directory).glob("*.osk"))), 10)

    def test_stable_delivery_skins_are_reproducible_and_keep_all_columns(self):
        root = Path(__file__).resolve().parents[1]
        for filename, (aspect, label) in SKIN_PROFILES.items():
            with self.subTest(profile=filename), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "test.osk"
                build_skin(path, aspect_ratio=aspect, label=label, target_client="stable")
                self.assertEqual(path.read_bytes(), (root / skin_filename(filename, "stable")).read_bytes())
                with zipfile.ZipFile(path) as archive:
                    sections, count = mania_sections(archive.read("skin.ini").decode())
                self.assertEqual(count, 18)
                self.assertNotIn("ColumnSpacing", sections[1])
                for keys, section in sections.items():
                    self.assertEqual(section["SplitStages"], "0")
                    widths = list(map(float, section["ColumnWidth"].split(",")))
                    self.assertEqual(len(widths), keys)
                    self.assertTrue(all(0 < width <= 100 for width in widths))

    def test_stable_cli_names_the_skin_that_was_actually_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pixels.txt"
            source.write_text("#\n#\n", encoding="utf-8")
            output = io.StringIO()
            with patch("sys.argv", ["osu_paint.py", str(source), "--client", "stable", "--start-ms", "2000",
                                    "--end-ms", "2400", "--fast-clear", "--output", str(root / "out")]), redirect_stdout(output):
                main()
            self.assertIn("pixel-film-stable-16x10.osk", output.getvalue())
            self.assertTrue((root / "out/pixel-film-stable-16x10.osk").exists())
