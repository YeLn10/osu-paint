"""Manual transition lengths must control emitted free-timing sweeps."""

import unittest

from osu_paint import SWEEP_HEIGHT, compile_frames, encode_osu
from test_osu_paint import decode as lazer_decode, position as lazer_position
from test_stable_geometry import decode as stable_decode, position as stable_position


class FreeTransitionTests(unittest.TestCase):
    def test_manual_length_controls_shared_sweep_without_changing_saved_windows(self):
        windows = [(2000, 2200), (2220, 2400)]
        for client, decode, position in (("lazer", lazer_decode, lazer_position),
                                          ("stable", stable_decode, stable_position)):
            positions = []
            for duration in (12, 16):
                with self.subTest(client=client, duration=duration):
                    plan = compile_frames([["#."] * 3, [".#"] * 3], frame_times=windows,
                                          transition_ms=duration, target_client=client)
                    self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
                    self.assertEqual(plan["frames"][0]["sweep_start_ms"], 2220 - duration)
                    self.assertEqual(plan["frames"][0]["exit_end_ms"], 2220)
                    points, _ = decode(encode_osu(plan))
                    movement = position(points, 2220, plan["time_range_ms"]) - position(points, 2220-duration, plan["time_range_ms"])
                    if client == "stable":
                        self.assertLess(movement, 1, "Overlap pictures instead of leaving a moving seam")
                        self.assertGreaterEqual(movement - 1 / 768, 1 - plan["bottom_mask_fraction"])
                    else:
                        self.assertAlmostEqual(movement, SWEEP_HEIGHT, delta=1e-5)
                    positions.append(position(points, 2210, plan["time_range_ms"]) - position(points, 2200, plan["time_range_ms"]))
            if len(positions) == 2:
                self.assertNotAlmostEqual(*positions, places=3)

    def test_long_deliberate_gap_retains_independent_entry_and_exit(self):
        for client in ("lazer", "stable"):
            with self.subTest(client=client):
                plan = compile_frames([["#."] * 3, [".#"] * 3], frame_times=[(2000, 2200), (2300, 2400)],
                                      transition_ms=12, target_client=client)
                self.assertEqual(plan["frames"][0]["sweep_start_ms"], 2200)
                self.assertEqual(plan["frames"][0]["exit_end_ms"], 2212)
                self.assertEqual(plan["frames"][1]["entry_start_ms"], 2288)
