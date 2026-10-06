"""Trim padded lazer travel without changing speed, windows or pixel geometry."""

import unittest

from osu_paint import SWEEP_HEIGHT, compile_frames, encode_osu, minimum_transition_ms
from test_osu_paint import decode, position


def padded(top, bottom, column=0, height=24):
    return [("#." if column == 0 else ".#") if top <= row <= bottom else ".."
            for row in range(height)]


class PaddedSweepTests(unittest.TestCase):
    def test_padding_shortens_travel_not_speed_or_saved_windows(self):
        frames = [padded(6, 17, i % 2) for i in range(4)]
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2050 + i * 50 - transition) for i in range(4)]
        full = compile_frames([["#." if i % 2 == 0 else ".#"] * 24 for i in range(4)],
                              frame_times=windows, fast_clear=True, anchor_reference=True)
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, anchor_reference=True)
        points, _ = decode(encode_osu(plan))
        full_points, _ = decode(encode_osu(full))
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        self.assertEqual(plan["base_beat_length_ms"], full["base_beat_length_ms"])
        self.assertEqual(plan["transition_ms"], full["transition_ms"])
        self.assertEqual(max(sv / beat for _, beat, sv in points),
                         max(sv / beat for _, beat, sv in full_points))
        for frame, old in zip(plan["frames"], full["frames"]):
            self.assertLess(frame["exit_end_ms"] - frame["sweep_start_ms"],
                            .8 * (old["exit_end_ms"] - old["sweep_start_ms"]))
            movement = (position(points, frame["exit_end_ms"], plan["time_range_ms"])
                        - position(points, frame["sweep_start_ms"], plan["time_range_ms"]))
            self.assertAlmostEqual(movement, SWEEP_HEIGHT - 6 / 24, delta=1e-6)
        durations = [f["exit_end_ms"] - f["sweep_start_ms"] for f in plan["frames"]]
        durations += [f["start_ms"] - f["entry_start_ms"] for f in plan["frames"]]
        self.assertAlmostEqual(plan["sweep_ms"], max(durations), places=8)

    def test_both_outgoing_top_and_incoming_bottom_limit_shared_travel(self):
        for top, bottom, next_top, next_bottom in ((23, 23, 0, 0), (0, 0, 0, 0),
                                                   (23, 23, 23, 23), (6, 10, 8, 17)):
            with self.subTest(rows=(top, bottom, next_top, next_bottom)):
                plan = compile_frames([padded(top, bottom), padded(next_top, next_bottom, 1)],
                                      2000, 2400, fast_clear=True, merge_holds=True)
                first, second = plan["frames"]
                points, _ = decode(encode_osu(plan))
                travel = (position(points, second["start_ms"], plan["time_range_ms"])
                          - position(points, first["sweep_start_ms"], plan["time_range_ms"]))
                expected = max(SWEEP_HEIGHT - top / 24, SWEEP_HEIGHT - (23 - next_bottom) / 24)
                self.assertAlmostEqual(travel, expected, delta=1e-6)

    def test_serialized_geometry_reuse_blank_frames_and_deliberate_gaps(self):
        for height in (3, 24, 128):
            for merged in (False, True):
                for speed in (1, 27, 40):
                    with self.subTest(height=height, holds=merged, speed=speed):
                        rows = padded(height // 3, 2 * height // 3, height=height)
                        frames = [rows, rows, [".."] * height,
                                  padded(height - 1, height - 1, 1, height),
                                  padded(0, 0, 0, height), rows]
                        transition = minimum_transition_ms(speed)
                        windows = [(2000 + i * 100, 2100 + i * 100 - transition)
                                   for i in range(len(frames))]
                        windows[-1] = (3000, 3100)
                        plan = compile_frames(frames, frame_times=windows, scroll_speed=speed,
                                              fast_clear=True, merge_holds=merged,
                                              allow_empty_frames=True, anchor_reference=True)
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
                                y = 1 - position(points, stamp, plan["time_range_ms"]) + now
                                self.assertAlmostEqual(y, (row + 1) / height - 1 / 768, delta=1e-5)
                            rectangles.append((note["frame"], position(points, head, plan["time_range_ms"]),
                                               position(points, tail, plan["time_range_ms"])))
                        samples = [(plan["frames"][0]["entry_start_ms"], set()), (2800, set()),
                                   (plan["frames"][-1]["exit_end_ms"], set())]
                        for i, frame in enumerate(plan["frames"]):
                            visible = set() if i == 2 else {frame["note_frame"]}
                            for key in ("start_ms", "end_ms", "sweep_start_ms"):
                                samples.append((frame[key], visible))
                        for time, expected in samples:
                            current = position(points, time, plan["time_range_ms"])
                            visible = {index for index, head, tail in rectangles
                                       if min(1, 1 - head + current) - max(0, 1 - tail + current - 1 / height) > 1e-6}
                            self.assertEqual(visible, expected, (time, expected))
                        self.assertEqual(plan["frames"][1]["note_frame"], 0)
                        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)

    def test_manual_padding_keeps_the_requested_full_travel(self):
        for client in ("lazer", "stable"):
            plan = compile_frames([padded(6, 17), padded(6, 17, 1)],
                                  frame_times=[(2000, 2200), (2240, 2400)],
                                  transition_ms=30, target_client=client)
            self.assertEqual(plan["sweep_ms"], 30)
            self.assertEqual(plan["frames"][0]["sweep_start_ms"], 2210)

    def test_blank_neighbors_do_not_force_full_shared_travel(self):
        blank = [".."] * 24
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * 50, 2050 + i * 50 - transition) for i in range(4)]
        plan = compile_frames([blank, padded(6, 17), padded(6, 17), blank],
                              frame_times=windows, fast_clear=True, allow_empty_frames=True)
        points, notes = decode(encode_osu(plan))
        for index in (0, 2):
            frame = plan["frames"][index]
            distance = (position(points, frame["exit_end_ms"], plan["time_range_ms"])
                        - position(points, frame["sweep_start_ms"], plan["time_range_ms"]))
            self.assertAlmostEqual(distance, SWEEP_HEIGHT - 6 / 24, delta=1e-6)
        self.assertEqual(plan["frames"][2]["note_frame"], 1)
        for time in (windows[0][0], plan["frames"][0]["sweep_start_ms"]):
            now = position(points, time, plan["time_range_ms"])
            self.assertTrue(all(1 - position(points, head, plan["time_range_ms"]) + now <= 0
                                for _, head in notes))
        now = position(points, windows[-1][0], plan["time_range_ms"])
        self.assertTrue(all(1 - position(points, head, plan["time_range_ms"]) + now - 1 / 24 >= 1
                            for _, head in notes))
        self.assertLess(plan["sweep_ms"], .08, "Reused display time is not a sweep duration")
