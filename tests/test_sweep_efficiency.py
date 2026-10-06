"""Keep fast sweeps fast and reduce redundant near-stationary timing points."""

import unittest

from osu_paint import compile_frames, encode_osu, minimum_transition_ms
from test_osu_paint import decode as lazer_decode, position as lazer_position
from test_stable_geometry import decode as stable_decode, position as stable_position


class SweepEfficiencyTests(unittest.TestCase):
    def test_lazer_larger_reserved_gap_does_not_slow_the_actual_sweep(self):
        transition = minimum_transition_ms(27)
        for padded in (False, True):
            rows = [".."] * 6 + ["#."] * 12 + [".."] * 6 if padded else ["#."] * 24
            durations = []
            for gap in (transition, 1.5 * transition, 2 * transition):
                windows = [(2000, 2200), (2200 + gap, 2400)]
                plan = compile_frames([rows, [row[::-1] for row in rows]],
                                      frame_times=windows, fast_clear=True, merge_holds=True)
                self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
                frame = plan["frames"][0]
                durations.append(frame["exit_end_ms"] - frame["sweep_start_ms"])
            with self.subTest(padded=padded):
                for duration in durations[1:]:
                    self.assertAlmostEqual(duration, durations[0], places=8)

    def test_both_clients_compact_redundant_slow_timing_points(self):
        for client, decode in (("lazer", lazer_decode), ("stable", stable_decode)):
            with self.subTest(client=client):
                plan = compile_frames([["#."] * 24], 2000, 4000, fast_clear=True,
                                      merge_holds=True, target_client=client)
                points, _ = decode(encode_osu(plan))
                slow = [(time, beat, sv) for time, beat, sv in points
                        if beat > plan["base_beat_length_ms"] and sv == .01]
                self.assertLessEqual(len(slow), 4)
                self.assertEqual(len(plan["notes"]), 1)
                self.assertEqual((plan["start_ms"], plan["end_ms"]), (2000, 4000))

    def test_compaction_preserves_reference_anchors_and_short_lead_ins(self):
        for client, decode in (("lazer", lazer_decode), ("stable", stable_decode)):
            for lead in (100, 2000):
                for speed in (1, 40):
                    with self.subTest(client=client, lead=lead, speed=speed):
                        transition = minimum_transition_ms(speed, 24, target_client=client)
                        start = lead + transition
                        frames = [["#."] * 24, ["#."] * 24, [".#"] * 24]
                        windows = [(start + i * 500, start + (i + 1) * 500 - transition)
                                   for i in range(3)]
                        plan = compile_frames(frames, frame_times=windows, scroll_speed=speed,
                                              fast_clear=True, anchor_reference=True, target_client=client)
                        points, _ = decode(encode_osu(plan))
                        self.assertTrue(all(a[0] < b[0] for a, b in zip(points, points[1:])))
                        self.assertEqual(plan["base_beat_length_ms"], points[0][1])
                        for point, following in zip(points, points[1:]):
                            if point[2] == .01 and point[1] > plan["base_beat_length_ms"]:
                                self.assertLess(following[0] - point[0], points[1][0])
                        if client == "lazer":
                            for i, frame in enumerate(plan["frames"]):
                                if i == frame["note_frame"]:
                                    self.assertTrue(any(abs(t - frame["start_ms"]) < 1e-7
                                                        and beat == plan["base_beat_length_ms"] and sv == .01
                                                        for t, beat, sv in points))

    def test_compacted_serialized_notes_preserve_geometry_and_black_gaps(self):
        for client, decode, position in (("lazer", lazer_decode, lazer_position),
                                         ("stable", stable_decode, stable_position)):
            for height in (3, 24, 128):
                for speed in (1, 27, 40):
                    for merged in (False, True):
                        with self.subTest(client=client, height=height, speed=speed, holds=merged):
                            rows = ["#." if height // 3 <= r <= 2 * height // 3 else ".."
                                    for r in range(height)]
                            frames = [rows, rows, [".."] * height, [row[::-1] for row in rows], rows]
                            transition = minimum_transition_ms(speed, height, target_client=client)
                            period = max(100, transition + 50)
                            windows = [(2000 + i * period, 2000 + (i + 1) * period - transition)
                                       for i in range(4)] + [(6000, 6100)]
                            plan = compile_frames(frames, frame_times=windows, scroll_speed=speed,
                                                  fast_clear=True, merge_holds=merged, anchor_reference=True,
                                                  allow_empty_frames=True, target_client=client)
                            text = encode_osu(plan)
                            points, _ = decode(text)
                            fields = [line.split(",") for line in text.split("[HitObjects]\n")[1].splitlines() if line]
                            rectangles = []
                            for obj, note in zip(fields, plan["notes"]):
                                frame = plan["frames"][note["frame"]]
                                head = float(obj[2])
                                tail = float(obj[5].split(":")[0]) if obj[3] == "128" else head
                                now = position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                                for row, stamp in ((note["row"], head), (note.get("end_row", note["row"]), tail)):
                                    self.assertGreater(stamp, frame["sweep_start_ms"])
                                    if client == "stable":
                                        self.assertTrue(stamp.is_integer())
                                    y = 1 - position(points, stamp, plan["time_range_ms"]) + now
                                    self.assertAlmostEqual(y, (row + 1) / height - 1 / 768, delta=1e-5)
                                rectangles.append((note["frame"], position(points, head, plan["time_range_ms"]),
                                                   position(points, tail, plan["time_range_ms"])))
                            samples = [(5800, set()), (plan["frames"][0]["entry_start_ms"], set()),
                                       (plan["frames"][-1]["exit_end_ms"], set())]
                            for i, frame in enumerate(plan["frames"]):
                                expected = set() if i == 2 else {frame["note_frame"]}
                                samples.extend((frame[key], expected) for key in ("start_ms", "end_ms", "sweep_start_ms"))
                            for time, expected in samples:
                                now = position(points, time, plan["time_range_ms"])
                                visible = {index for index, head, tail in rectangles
                                           if min(1, 1 - head + now) - max(0, 1 - tail + now - 1 / height) > 1e-6}
                                self.assertEqual(visible, expected)
                            self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)

    def test_manual_mode_retains_original_slow_points(self):
        for client, decode in (("lazer", lazer_decode), ("stable", stable_decode)):
            plan = compile_frames([["#."] * 24], 2000, 4000, transition_ms=30,
                                  merge_holds=True, target_client=client)
            points, _ = decode(encode_osu(plan))
            self.assertEqual(sum(beat > plan["base_beat_length_ms"] and sv == .01
                                 for _, beat, sv in points), 40)
            self.assertEqual(plan["sweep_ms"], 30)
