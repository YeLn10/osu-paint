"""Stable regressions through the compiler and serialized beatmap boundary."""

import json
from functools import partial
from pathlib import Path
import unittest

from osu_paint import Point, compile_frames, encode_osu, minimum_transition_ms, most_common_beat_length

compile_frames = partial(compile_frames, target_client="stable")
minimum_transition_ms = partial(minimum_transition_ms, target_client="stable")
most_common_beat_length = partial(most_common_beat_length, target_client="stable")


class StableTimingTests(unittest.TestCase):
    def test_three_rows_survive_stables_integer_object_parser(self):
        plan = compile_frames([["#", "#", "#"]], 2000, 4000, fast_clear=True)
        objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
        times = [int(float(line.split(",")[2])) for line in objects]
        # The installed stable parser truncates both note heads and hold tails.
        # Each row therefore needs its own millisecond, plus a final clear slot.
        self.assertEqual(times, [4001, 4002, 4003])
        self.assertEqual(plan["frames"][0]["exit_end_ms"], 4004)
        self.assertEqual(plan["target_client"], "stable")

    def test_fixed_scroll_scale_matches_the_installed_stable_assembly(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/stable-runtime.json").read_text())
        for case in fixture["speed_results"]:
            with self.subTest(speed=case["speed"]):
                plan = compile_frames([["#"]], 2000, 4000, case["speed"], fast_clear=True)
                distance = case["duration_ms"] * 480 / plan["time_range_ms"]
                self.assertAlmostEqual(distance, case["distance_at_480px"], places=9)
        for case in fixture["reference_results"]:
            points = [Point(time, beat, 1) for time, beat in case["points"]]
            base = most_common_beat_length(points, case["end_ms"])
            self.assertEqual(60000 / base, case["reference_bpm"])

    def test_serialized_sweep_keeps_every_row_at_integer_milliseconds(self):
        for height in (1, 3, 24, 128):
            for speed in (1, 27, 40):
                with self.subTest(height=height, speed=speed):
                    plan = compile_frames([["#"] * height], 2000, 4000, speed, fast_clear=True)
                    text = encode_osu(plan)
                    lines = text.split("[HitObjects]\n")[1].strip().splitlines()
                    times = [line.split(",")[2] for line in lines]
                    self.assertTrue(all(t.isdigit() for t in times))
                    self.assertEqual(list(map(int, times)), list(range(4001, 4001 + height)))
                    self.assertEqual(minimum_transition_ms(speed, height), height + 1)
                    timing = text.split("[TimingPoints]\n")[1].split("[HitObjects]")[0].strip().splitlines()
                    self.assertTrue(all(line.split(",")[0].isdigit() for line in timing))

    def test_fractional_windows_round_inwards_without_mutating_the_project(self):
        windows = [(2000.25, 2050.75), (2060.9, 2100.8)]
        original = windows.copy()
        plan = compile_frames([["#."] * 3, [".#"] * 3], frame_times=windows, fast_clear=True)
        self.assertEqual(windows, original)
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], [(2001, 2050), (2061, 2100)])

    def test_hold_heads_and_tails_use_distinct_integer_rows(self):
        plan = compile_frames([["#", "#", ".", "#", "#"]], 2000, 4000,
                              fast_clear=True, merge_holds=True)
        objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
        self.assertEqual(len(objects), 2)
        for line in objects:
            fields = line.split(",")
            self.assertEqual(fields[3], "128")
            self.assertTrue(fields[2].isdigit())
            self.assertTrue(fields[5].split(":")[0].isdigit())
            self.assertEqual(int(fields[5].split(":")[0]) - int(fields[2]), 1)

    def test_stable_cannot_use_a_fractional_scroll_setting(self):
        with self.assertRaisesRegex(ValueError, "整数"):
            compile_frames([["#"]], 2000, 4000, scroll_speed=27.5)


class StableVideoTests(unittest.TestCase):
    def test_default_video_may_span_more_than_one_display_refresh(self):
        from osu_paint_video import resolve_video_options, validate_video_options
        options = dict(target_client="stable", fps=10, width=16, height=24, start_ms=2000,
                       scroll_speed=27, refresh_hz=60)
        resolved = resolve_video_options(**options)
        self.assertEqual((resolved["fps"], resolved["height"]), (10, 24))
        self.assertEqual(validate_video_options(**options), 25)


class StableSkinTests(unittest.TestCase):
    def test_skin_has_an_explicit_stable_single_stage_and_separate_name(self):
        from osu_paint_skin import skin_ini
        text = skin_ini(target_client="stable")
        self.assertIn("Name: osu-paint stable Pixel Film", text)
        self.assertEqual(text.count("SplitStages: 0"), 18)
        self.assertEqual(text.count("ColumnStart: 0"), 18)
        self.assertEqual(text.count("ColumnRight: 0"), 18)


if __name__ == "__main__":
    unittest.main()
