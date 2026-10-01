"""Portable frame payload for the optional lazer Pixel Film ruleset."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from osu_paint import compile_frames, number, write_output


class ClientFilmExportTests(unittest.TestCase):
    def export(self, plan):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name)
        write_output(plan, output)
        return output

    def test_osz_contains_exact_frames_bound_to_the_beatmap(self):
        plan = compile_frames([["#."], [".#"]], 2000, 3000, fast_clear=True)
        output = self.export(plan)
        payload = (output / "pixel-film.json").read_bytes()
        film = json.loads(payload)
        self.assertEqual(film["format"], "osu-paint-film-v1")
        self.assertEqual((film["width"], film["height"]), (2, 1))
        self.assertEqual([frame["rows"] for frame in film["frames"]], [["#."], [".#"]])
        self.assertEqual(film["frames"][0]["end_ms"], film["frames"][1]["start_ms"])
        self.assertEqual(film["end_ms"], plan["end_ms"])
        source = f"Source: osu-paint-film-v1 3000 2 {hashlib.sha256(payload).hexdigest()}"
        self.assertIn(source, (output / "pattern.osu").read_text(encoding="utf-8"))
        with zipfile.ZipFile(output / "pattern.osz") as archive:
            self.assertEqual(archive.read("pixel-film.json"), payload)

    def test_custom_mode_has_a_standard_entry_map_with_correct_end_and_binding(self):
        plan = compile_frames([["#" * 18]], 2000, 3012.3456789, fast_clear=True)
        output = self.export(plan)
        with zipfile.ZipFile(output / "pattern.osz") as archive:
            entry = archive.read("pixel-film.osu").decode()
            original = archive.read("pattern.osu").decode()
            self.assertIn("Mode: 0", entry)
            self.assertIn("CircleSize: 5", entry)
            self.assertIn("Version: Pixel Film 18 columns", entry)
            source = next(line for line in original.splitlines() if line.startswith("Source:"))
            self.assertIn(source, entry)
            objects = entry.split("[HitObjects]", 1)[1].strip().splitlines()
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].split(",")[2], number(plan["end_ms"]))
            self.assertIn("Mode: 3", original)

    def test_full_width_and_blank_frames_are_preserved_for_all_key_counts(self):
        for keys in range(1, 19):
            with self.subTest(keys=keys):
                rows = [["#" * keys, "." * keys], ["." * keys] * 2]
                plan = compile_frames(rows, 2000, 2400, fast_clear=True, allow_empty_frames=True)
                film = json.loads((self.export(plan) / "pixel-film.json").read_bytes())
                self.assertEqual(film["width"], keys)
                self.assertEqual([frame["rows"] for frame in film["frames"]], rows)

    def test_intentional_free_timing_gap_is_not_filled(self):
        plan = compile_frames([["#"], ["#"]], frame_times=[(2000, 2200), (2700, 3000)], fast_clear=True)
        film = json.loads((self.export(plan) / "pixel-film.json").read_bytes())
        self.assertEqual(film["frames"][0]["end_ms"], 2200)
        self.assertEqual(film["frames"][1]["start_ms"], 2700)
