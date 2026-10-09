"""Bound sweep exposure without moving windows, filling holes or judging early."""

import unittest

from osu_paint import compile_frames, encode_osu, minimum_transition_ms
from test_stable_geometry import decode as stable_decode, position as stable_position
from test_osu_paint import decode as lazer_decode, position as lazer_position


def transition_exposure(plan):
    intervals = sorted({(f["sweep_start_ms"], f["exit_end_ms"]) for f in plan["frames"]}
                       | {(f["entry_start_ms"], f["start_ms"]) for i, f in enumerate(plan["frames"])
                          if i == f["note_frame"]})
    total, end = 0, -1
    for a, b in intervals:
        total += max(0, b - max(a, end))
        end = max(end, b)
    return total


class TransitionOptimizationTests(unittest.TestCase):
    def test_stable_only_allocates_integer_slots_for_used_heads_and_tails(self):
        for rows, merged, expected in ((["#."] * 24, True, 3),
                                        (["#."] * 24, False, 25),
                                        ([".."] * 4 + ["#."] * 3 + [".."] * 17, True, 3),
                                        (["#."] * 3 + [".."] * 18 + [".#"] * 3, True, 5)):
            with self.subTest(merged=merged, expected=expected):
                plan = compile_frames([rows], 2000, 2400, fast_clear=True,
                                      merge_holds=merged, target_client="stable")
                self.assertEqual(plan["transition_ms"], 25, "Keep the saved scheduling budget")
                self.assertEqual(plan["sweep_ms"], expected)
                self.assertEqual(plan["frames"][0]["exit_end_ms"] - 2400, expected)

    def test_stable_compaction_preserves_serialized_geometry_and_deliberate_gaps(self):
        rows = ["#."] * 3 + [".."] * 18 + [".#"] * 3
        windows = [(2000, 2080), (2105, 2185), (2300, 2380)]
        plan = compile_frames([rows, list(reversed(rows)), rows], frame_times=windows,
                              fast_clear=True, merge_holds=True, target_client="stable")
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        self.assertEqual(plan["base_beat_length_ms"], 500)
        text = encode_osu(plan)
        points, _ = stable_decode(text)
        self.assertTrue(all(p[0].is_integer() for p in points))
        objects = [line.split(",") for line in text.split("[HitObjects]\n")[1].splitlines() if line]
        for fields, note in zip(objects, plan["notes"]):
            frame = plan["frames"][note["frame"]]
            for row, stamp in ((note["row"], fields[2]), (note["end_row"], fields[5].split(":")[0])):
                self.assertTrue(stamp.isdigit())
                self.assertGreater(int(stamp), frame["sweep_start_ms"])
                at_sweep = 1 - stable_position(points, int(stamp), plan["time_range_ms"]) + stable_position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                self.assertAlmostEqual(at_sweep, (row + 1) / 24 - 1 / 768, delta=1e-6)
            self.assertTrue(all(frame["pattern"][r][note["column"]] == "#"
                                for r in range(note["end_row"], note["row"] + 1)))
        self.assertLess(plan["frames"][1]["exit_end_ms"], 2250)
        self.assertGreater(plan["frames"][2]["entry_start_ms"], 2250)

    def test_lazer_static_scene_does_not_slow_down_a_long_animated_sequence(self):
        frames = [["#."] * 24] * 60 + [[(".#" if i % 2 == 0 else "#.")] * 24 for i in range(120)]
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition) for i in range(len(frames))]
        for merged in (False, True):
            with self.subTest(holds=merged):
                plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                                      anchor_reference=True, merge_holds=merged)
                # Before: 59.793 ms total, a single static group caps reference at 624.353.
                self.assertLess(transition_exposure(plan), 15)
                self.assertGreater(plan["base_beat_length_ms"], 3000)
                self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
                points, objects = lazer_decode(encode_osu(plan))
                for i, frame in enumerate(plan["frames"]):
                    if i != frame["note_frame"]:
                        continue
                    drift = (lazer_position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                             - lazer_position(points, frame["start_ms"], plan["time_range_ms"])) * 768
                    self.assertLessEqual(drift, .5001)
                fields = [line.split(",") for line in encode_osu(plan).split("[HitObjects]\n")[1].splitlines() if line]
                for obj, (_, stamp), note in zip(fields, objects, plan["notes"]):
                    frame = plan["frames"][note["frame"]]
                    self.assertGreater(stamp, frame["sweep_start_ms"])
                    endpoints = [(note["row"], stamp)]
                    if "end_row" in note:
                        endpoints.append((note["end_row"], float(obj[5].split(":")[0])))
                    for row, time in endpoints:
                        y = 1 - lazer_position(points, time, plan["time_range_ms"]) + lazer_position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                        self.assertAlmostEqual(y, (row + 1) / 24 - 1 / 768, delta=1e-5)

    def test_lazer_keeps_a_pure_static_sequence_continuous(self):
        frames = [["#."] * 3] * 60
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition) for i in range(60)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, anchor_reference=True)
        self.assertEqual({f["note_frame"] for f in plan["frames"]}, {0})

    def test_stable_variable_density_keeps_nominal_refreshes_clean(self):
        # Compacted sweeps differ in length, but all must finish by the same
        # original integer boundary. Include a deliberate blank picture.
        frames = [["#."] * 24, [".."] * 4 + [".#"] + [".."] * 19,
                  [".."] * 24, ["#."] * 4 + [".."] * 16 + ["#."] * 4]
        windows = [(2000 + i * 100, 2075 + i * 100) for i in range(4)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                              merge_holds=True, allow_empty_frames=True, target_client="stable")
        points, _ = stable_decode(encode_osu(plan))
        for i, frame in enumerate(plan["frames"]):
            current = stable_position(points, frame["start_ms"], plan["time_range_ms"])
            visible = set()
            for note in plan["notes"]:
                bottom = 1 - stable_position(points, note["time_ms"], plan["time_range_ms"]) + current
                top = 1 - stable_position(points, note.get("end_time_ms", note["time_ms"]), plan["time_range_ms"]) + current - 1 / 24
                if min(1 - plan["bottom_mask_fraction"], bottom) - max(0, top) > 1e-6:
                    visible.add(note["frame"])
            self.assertEqual(visible, {i} if i != 2 else set())
        self.assertEqual([f["exit_end_ms"] - f["sweep_start_ms"] for f in plan["frames"]], [3, 2, 1, 5])

    def test_manual_sweeps_do_not_enable_automatic_compaction(self):
        for client in ("stable", "lazer"):
            with self.subTest(client=client):
                plan = compile_frames([["#."] * 24] * 60, 2000, 5000,
                                      transition_ms=30, merge_holds=True, target_client=client)
                self.assertEqual(plan["sweep_ms"], 30)
                self.assertEqual(plan["base_beat_length_ms"], 500)
                self.assertEqual({f["note_frame"] for f in plan["frames"]}, {0})

    def test_lazer_rejects_a_speedup_that_multiplies_dense_static_notes(self):
        frames = [["#" * 18] * 24] * 60
        for i in range(120):
            rows = ["." * 18] * 24
            rows[12] = "#" + "." * 17 if i % 2 else "." * 17 + "#"
            frames.append(rows)
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition) for i in range(len(frames))]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, anchor_reference=True)
        self.assertEqual(len(plan["notes"]), 18 * 24 + 120)
        self.assertEqual(len(set(f["note_frame"] for f in plan["frames"])), 121)

    def test_lazer_uses_moderate_reuse_when_maximum_speed_exceeds_the_load_cap(self):
        frames = [["#."] * 24] * 60 + [[(".#" if i % 2 == 0 else "#.")] * 24 for i in range(20)]
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition) for i in range(len(frames))]
        for merged in (False, True):
            with self.subTest(holds=merged):
                plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                                      anchor_reference=True, merge_holds=merged)
                # Before: the 4900 ms candidate adds >10% redraws and is rejected;
                # all 20 animated changes therefore keep the 0.4901 ms sweep.
                self.assertLess(transition_exposure(plan), 6.5)
                self.assertGreater(plan["base_beat_length_ms"], 1000)
                self.assertLess(plan["base_beat_length_ms"], 3000)
                self.assertLessEqual(len(set(f["note_frame"] for f in plan["frames"])), 23)
                self.assertLessEqual(len(plan["notes"]), 23 * (1 if merged else 24))
                self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
                points, _ = lazer_decode(encode_osu(plan))
                for note in plan["notes"]:
                    frame = plan["frames"][note["frame"]]
                    now = lazer_position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                    drift = (now - lazer_position(points, frame["start_ms"], plan["time_range_ms"])) * 768
                    self.assertLessEqual(drift, .5001)
                    for row, time in ((note["row"], note["time_ms"]),
                                      (note.get("end_row", note["row"]), note.get("end_time_ms", note["time_ms"]))):
                        self.assertGreater(time, frame["sweep_start_ms"])
                        y = 1 - lazer_position(points, float(f"{time:.9f}"), plan["time_range_ms"]) + now
                        self.assertAlmostEqual(y, (row + 1) / 24 - 1 / 768, delta=1e-5)
