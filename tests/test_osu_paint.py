"""Export-level checks: independently integrate the emitted .osu timing lines."""

import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
import zipfile

from osu_paint import Point, compile_frames, compile_pattern, encode_osu, make_preview, minimum_transition_ms, most_common_beat_length, parse_frames, parse_pattern, write_output


def decode(text):
    points, notes = [], []
    section = None
    beat, sv = 500, 1
    stable = "Version: stable " in text
    for line in text.splitlines():
        if line.startswith("["):
            section = line
        elif line and section == "[TimingPoints]":
            fields = line.split(",")
            time, value = map(float, fields[:2])
            if fields[6] == "1":
                beat, sv = (value if stable else min(60000, max(6, value))), 1
            else:
                sv = min(10, max(0.01, -100 / value if value < 0 else 1))
            if points and points[-1][0] == time:
                points.pop()
            points.append((time, beat, sv))
        elif line and section == "[HitObjects]":
            fields = line.split(",")
            notes.append((int(fields[0]), float(fields[2])))
    return points, notes


def position(points, time, time_range):
    # lazer accumulates each completed segment as a float32 relative distance.
    total = 0
    for i, (start, beat, sv) in enumerate(points):
        if start >= time:
            break
        end = points[i + 1][0] if i + 1 < len(points) else math.inf
        value = (min(end, time) - start) * 500 / beat * sv / time_range
        total += struct.unpack("f", struct.pack("f", value))[0] if end <= time else value
    return total


class ExportTests(unittest.TestCase):
    def test_stable_thirteen_rows_fit_sixty_fps_integer_periods(self):
        starts = [2000 + math.floor(i * 1000 / 60) for i in range(61)]
        windows = [(starts[i], starts[i + 1] - 14) for i in range(60)]
        frames = [["#." if i % 2 == 0 else ".#"] * 13 for i in range(60)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, target_client="stable")
        self.assertEqual(plan["transition_ms"], 14)
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        self.assertTrue(all(f["end_ms"] - f["start_ms"] >= 1 for f in plan["frames"]))
        self.assertEqual(plan["base_beat_length_ms"], 500)
        points, _ = decode(encode_osu(plan))
        for note in plan["notes"]:
            frame = plan["frames"][note["frame"]]
            y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, frame["start_ms"], plan["time_range_ms"])
            self.assertAlmostEqual(y, note["y"], delta=1e-6)

    def test_stable_minimum_sweep_is_rows_plus_one_at_every_scroll_speed(self):
        for speed in (1, 15, 27, 40):
            for height in (1, 3, 13, 24, 128):
                with self.subTest(speed=speed, height=height):
                    self.assertEqual(minimum_transition_ms(speed, "stable", height), height + 1)

    def test_stable_accepts_one_ms_hold_without_reference_anchor(self):
        plan = compile_frames([["#."] * 3, [".#"] * 3], frame_times=[(2000, 2001), (2005, 2006)],
                              fast_clear=True, target_client="stable")
        slow = [p for p in plan["points"] if p["sv"] == .01]
        self.assertTrue(all(p["beat_length"] >= 1e9 for p in slow))
        self.assertEqual(plan["base_beat_length_ms"], 500)
        with self.assertRaisesRegex(ValueError, "1 ms"):
            compile_frames([["#."] * 3, [".#"] * 3], frame_times=[(2000, 2000.4), (2005, 2006)],
                           fast_clear=True, target_client="stable")

    def test_stable_long_video_uses_distinct_exported_fast_red_lines(self):
        frames = [["#." if i % 2 == 0 else ".#"] * 12 for i in range(1000)]
        windows = [(2000 + i * 25, 2012 + i * 25) for i in range(1000)]
        plan = compile_frames(frames, frame_times=windows, scroll_speed=1, fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        fast = [beat for _, beat, sv in points if sv > 1]
        self.assertEqual(len(fast), len(set(fast)))
        self.assertTrue(all(5 <= sv <= 10 for _, _, sv in points if sv > 1))
        self.assertTrue(any(beat < 6 for beat in fast))
        durations = {}
        for i, (time, beat, _) in enumerate(points):
            end = min(points[i + 1][0] if i + 1 < len(points) else notes[-1][1], notes[-1][1])
            if end > time:
                durations[beat] = durations.get(beat, 0) + int(end - time)
        self.assertEqual(max(durations, key=durations.get), 500)

    def test_reference_bpm_grouping_matches_each_client(self):
        points = [Point(0, 500, 1), Point(100, 60000.0001, .01), Point(170, 60000.0002, .01)]
        self.assertEqual(most_common_beat_length(points, 230, target_client="stable"), 500)
        self.assertEqual(most_common_beat_length(points, 230), 60000)

    def test_stable_explicit_gaps_keep_all_four_fast_segments_within_sv_bounds(self):
        frames = [["#." if i % 2 == 0 else ".#"] * 3 for i in range(20)]
        windows = [(2000 + i * 100, 2001 + i * 100) for i in range(20)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, target_client="stable")
        fast = [p for p in plan["points"] if p["sv"] > 1]
        self.assertEqual(len(fast), 4 * len(frames))
        self.assertTrue(all(5 <= p["sv"] <= 10 for p in fast))
        self.assertEqual(len({p["beat_length"] for p in fast}), len(fast))
        points, _ = decode(encode_osu(plan))
        for note in plan["notes"]:
            start = plan["frames"][note["frame"]]["start_ms"]
            y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, start, plan["time_range_ms"])
            self.assertAlmostEqual(y, note["y"], delta=1e-6)

    def test_all_one_to_eighteen_columns_export_as_plain_notes(self):
        for keys in range(1, 19):
            for client in ("stable", "lazer"):
                with self.subTest(keys=keys, client=client):
                    plan = compile_frames([["#" * keys]], 2000, 4000,
                                          target_client=client, fast_clear=True)
                    objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
                    columns = [int(int(line.split(",")[0]) * keys / 512) for line in objects]
                    self.assertEqual(columns, list(range(keys)))
                    self.assertTrue(all(line.split(",")[3] == "1" for line in objects))
                    self.assertFalse(any("end_ms" in note for note in plan["notes"]))

    def test_stable_identical_frames_keep_the_picture_through_the_transition(self):
        picture = ["."] * 11 + ["#"] + ["."] * 12
        windows = [(2000, 2052), (2100, 2200)]
        plan = compile_frames([picture] * 2, frame_times=windows,
                              fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        for now in range(2000, 2201):
            visible = [1 - position(points, t, plan["time_range_ms"]) +
                       position(points, now, plan["time_range_ms"]) for _, t in notes]
            self.assertEqual(sum(.2 <= y <= .8 for y in visible), 1, f"Picture blinked at {now} ms")
        self.assertEqual(len(notes), 1)

    def test_stable_identical_frames_still_clear_during_an_explicit_gap(self):
        plan = compile_frames([["#"] * 24] * 2, frame_times=[(2000, 2500), (3000, 3500)],
                              fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        self.assertEqual(len(notes), 48)
        for now in (2549, 2750, 2951):
            self.assertFalse(any(0 <= 1 - position(points, t, plan["time_range_ms"]) +
                                 position(points, now, plan["time_range_ms"]) <= 768 / 658
                                 for _, t in notes))

    def test_stable_changing_frames_use_short_exact_integer_sweeps(self):
        pictures = [["#."] * 24, [".#"] * 24]
        plan = compile_frames(pictures, frame_times=[(2000, 2075), (2100, 2200)],
                              fast_clear=True, target_client="stable")
        self.assertEqual(plan["transition_ms"], 25)
        points, notes = decode(encode_osu(plan))
        for note in plan["notes"]:
            frame = plan["frames"][note["frame"]]
            self.assertEqual(note["time_ms"], frame["end_ms"] + 24 - note["row"])
            y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, frame["start_ms"], plan["time_range_ms"])
            self.assertAlmostEqual(y, note["y"], delta=1e-6)
        self.assertTrue(all(t == int(t) for _, t in notes))

    def test_stable_changing_frames_hold_at_ten_fps(self):
        pictures = [["#."] * 24, [".#"] * 24]
        windows = [(2000, 2075), (2100, 2200)]
        plan = compile_frames(pictures, frame_times=windows, fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        for index, (start, end) in enumerate(windows):
            for now in (start, (start + end) / 2, end):
                visible = [(x, 1 - position(points, t, plan["time_range_ms"]) +
                            position(points, now, plan["time_range_ms"])) for x, t in notes]
                visible = [(int(x * 2 / 512), y) for x, y in visible if 0 <= y <= 768 / 658]
                self.assertEqual(len(visible), 24)
                self.assertEqual({col for col, _ in visible}, {index})
        self.assertTrue(all(t == int(t) for _, t in notes))
        self.assertEqual(plan["transition_ms"], 25)

    def test_stable_sweeps_preserve_geometry_and_clear_at_all_scroll_speeds(self):
        for speed in (1, 15, 27, 40):
            for height in (1, 2, 3, 6, 24, 128):
                with self.subTest(speed=speed, height=height):
                    plan = compile_frames([["#."] * height, [".#"] * height], 2000, 4000,
                                          scroll_speed=speed, fast_clear=True, target_client="stable")
                    points, _ = decode(encode_osu(plan))
                    self.assertTrue(all(a[0] < b[0] for a, b in zip(points, points[1:])))
                    self.assertTrue(all(math.isfinite(beat) and beat > 0 and .01 <= sv <= 10 for _, beat, sv in points))
                    for note in plan["notes"]:
                        frame = plan["frames"][note["frame"]]
                        y = 1 - position(points, note["time_ms"], plan["time_range_ms"])
                        self.assertAlmostEqual(y + position(points, frame["start_ms"], plan["time_range_ms"]),
                                               note["y"], delta=1e-6)
                        self.assertGreater(y + position(points, frame["exit_end_ms"], plan["time_range_ms"]),
                                           768 / 658 + 8 / 658)

    def test_stable_rows_remain_distinct_on_integer_millisecond_grid(self):
        for height in (1, 6, 24, 128):
            plan = compile_frames([["#"] * height], 2000, 4000, fast_clear=True, target_client="stable")
            text = encode_osu(plan)
            points, notes = decode(text)
            self.assertEqual(len({t for _, t in notes}), height)
            self.assertTrue(all(t == int(t) for _, t in notes))
            self.assertTrue(all(p["time"] == int(p["time"]) for p in plan["points"]))
            for note in plan["notes"]:
                y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, 2000, plan["time_range_ms"])
                self.assertAlmostEqual(y, note["y"], delta=0.3 / height)
            self.assertIn("Version: stable", text)

    def test_stable_long_video_preserves_reference_bpm(self):
        windows = [(2000 + i * 100, 2052 + i * 100) for i in range(1000)]
        plan = compile_frames([["#"] * 24] * 1000, frame_times=windows,
                              fast_clear=True, target_client="stable")
        self.assertEqual(plan["base_beat_length_ms"], 500)
        self.assertEqual(plan["transition_ms"], 25)
        self.assertLess(len(plan["notes"]), 1000 * 24)
        points, _ = decode(encode_osu(plan))
        for frame in plan["frames"]:
            origin = plan["frames"][frame["note_frame"]]["start_ms"]
            drift = position(points, frame["end_ms"], plan["time_range_ms"]) - position(points, origin, plan["time_range_ms"])
            self.assertLess(drift, .014, "Repeated pictures must be renewed before drift exceeds half a row")

    def test_stable_long_changing_video_keeps_the_reference_bpm(self):
        windows = [(2000 + i * 100, 2075 + i * 100) for i in range(1000)]
        pictures = [["#."] * 24, [".#"] * 24] * 500
        plan = compile_frames(pictures, frame_times=windows, fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        durations = {}
        for index, (start, beat, _) in enumerate(points[:-1]):
            end = min(points[index + 1][0], notes[-1][1])
            if end > start:
                durations[beat] = durations.get(beat, 0) + int(end) - int(start)
        self.assertEqual(max(durations, key=durations.get), 500)
        self.assertEqual(len(notes), 24000)
        self.assertTrue(all(t == int(t) for _, t in notes))

    def test_stable_reused_picture_then_changes_without_losing_source_frames(self):
        pictures = [["#."] * 24, ["#."] * 24, [".#"] * 24]
        windows = [(2000, 2452), (2500, 2952), (3000, 3500)]
        plan = compile_frames(pictures, frame_times=windows, fast_clear=True, target_client="stable")
        points, notes = decode(encode_osu(plan))
        self.assertEqual(len(plan["frames"]), 3)
        self.assertEqual(len(notes), 48)
        for now, column in ((2475, 0), (2999, 1), (3000, 1), (3499, 1)):
            visible = [(x, 1 - position(points, t, plan["time_range_ms"]) +
                        position(points, now, plan["time_range_ms"])) for x, t in notes]
            visible = [(int(x * 2 / 512), y) for x, y in visible if .2 <= y <= .8]
            self.assertTrue(visible)
            self.assertEqual({c for c, _ in visible}, {column})

    def test_fast_clear_removes_notes_from_full_stage_within_one_ms(self):
        plan = compile_frames([["#"]], 2000, 4000, fast_clear=True)
        points, notes = decode(encode_osu(plan))
        interval = plan["time_range_ms"]
        self.assertLess(plan["transition_ms"], 1)
        for _, note_time in notes:
            y = 1 - position(points, note_time, interval) + position(points, 4001, interval)
            self.assertGreater(y, 768 / 658 + 8 / 658)
        self.assertTrue(all(6 <= beat <= 60000 and 0.01 <= sv <= 10 for _, beat, sv in points))

    def test_free_timing_preserves_windows_and_blank_gaps(self):
        frames = [["#.", ".#"], [".#", "#."], ["##", ".#"]]
        windows = [(2000, 2500), (3000, 4200), (4201, 5000)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True)
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        points, notes = decode(encode_osu(plan))
        interval = plan["time_range_ms"]
        for now in (2501, 2750, 2999):
            self.assertFalse(any(0 <= 1 - position(points, t, interval) + position(points, now, interval) <= 768 / 658
                                 for _, t in notes), "Blank gap contains a note, including below judgement")
        for index, frame in enumerate(plan["frames"]):
            for now in (frame["start_ms"], frame["end_ms"]):
                visible = [(note, 1 - position(points, note["time_ms"], interval) + position(points, now, interval))
                           for note in plan["notes"]]
                visible = [(note, y) for note, y in visible if 0 <= y <= 768 / 658]
                self.assertEqual(len(visible), sum(row.count('#') for row in frames[index]))
                for note, y in visible:
                    self.assertEqual(note["frame"], index)
                    self.assertAlmostEqual(y, note["y"], delta=0.001)

    def test_free_timing_rejects_overlap_short_gaps_and_invalid_windows(self):
        for windows in ([(2000, 2500)], [(2000, 2500), (2400, 3000)],
                        [(2000, 2500), (2500.01, 3000)], [(2000, 2500), (3000, 3000)],
                        [(2000, 2500), (math.nan, 4000)], [(20, 40), (2000, 3000)]):
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                compile_frames([["#"], ["#"]], frame_times=windows, fast_clear=True)

    def test_fast_free_timing_at_scroll_speed_extremes_and_many_frames(self):
        for speed in (1, 15, 27, 40):
            with self.subTest(speed=speed):
                transition = compile_frames([["#"]], 2000, 4000, speed, fast_clear=True)["transition_ms"]
                windows = [(2000 + i * (30 + transition), 2030 + i * (30 + transition)) for i in range(120)]
                plan = compile_frames([["#", ".", "#"]] * 120, scroll_speed=speed,
                                      frame_times=windows, fast_clear=True)
                points, _ = decode(encode_osu(plan))
                self.assertEqual(plan["base_beat_length_ms"], 500)
                self.assertTrue(all(a["time"] < b["time"] for a, b in zip(plan["points"], plan["points"][1:])))
                for note in plan["notes"]:
                    now = plan["frames"][note["frame"]]["exit_end_ms"]
                    y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, now, plan["time_range_ms"])
                    self.assertGreater(y, 768 / 658 + 8 / 658)
                self.assertTrue(all(6 <= p["beat_length"] <= 60000 and 0.01 <= p["sv"] <= 10 for p in plan["points"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable; preview syntax check skipped")
    def test_generated_preview_javascript_is_valid(self):
        for frames in ([["#"]], [["#.", ".#"], [".#", "#."]]):
            page = make_preview(compile_frames(frames, 2000, 4000))
            script = page.split("<script>", 1)[1].split("</script>", 1)[0]
            result = subprocess.run([shutil.which("node"), "--check", "-"], input=script,
                                    text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_animation_frames_do_not_leak_into_each_other(self):
        frames = [["#...", ".##.", "...#"], ["..#.", "#...", "..##"],
                  ["###.", "..#.", "#..#"]]
        plan = compile_frames(frames, 2000, 5000)
        points, notes = decode(encode_osu(plan))
        interval = plan["time_range_ms"]
        self.assertEqual(len(plan["frames"]), 3)
        self.assertEqual(plan["frames"][-1]["end_ms"], 5000)
        for index, frame in enumerate(plan["frames"]):
            expected = sorted((col, 0.2 + (row + 0.5) * 0.6 / 3)
                              for row, line in enumerate(frames[index])
                              for col, pixel in enumerate(line) if pixel == "#")
            for t in (frame["start_ms"], (frame["start_ms"] + frame["end_ms"]) / 2,
                      frame["end_ms"]):
                actual = []
                for x, note_time in notes:
                    if note_time <= t:
                        continue
                    y = 1 - position(points, note_time, interval) + position(points, t, interval)
                    if 0 <= y <= 1:
                        actual.append((int(x * 4 / 512), y))
                self.assertEqual(len(actual), len(expected), "相邻帧串入展示区域")
                for (column, y), (expected_column, expected_y) in zip(sorted(actual), expected):
                    self.assertEqual(column, expected_column)
                    self.assertAlmostEqual(y, expected_y, delta=0.001)

    def test_many_frames_keep_reference_bpm_and_unique_slow_points(self):
        plan = compile_frames([["#.", ".#"]] * 120, 2000, 6000)
        points, notes = decode(encode_osu(plan))
        slow_beats = [round(beat, 3) for _, beat, sv in points if sv == 0.01]
        self.assertEqual(len(set(slow_beats)), 120)
        durations = {}
        for i, (t, beat, _) in enumerate(points[:-1]):
            if t >= notes[-1][1]:
                break
            duration = min(points[i + 1][0], notes[-1][1]) - t
            key = round(beat, 3)
            durations[key] = durations.get(key, 0) + duration
        self.assertEqual(max(durations, key=durations.get), 500)
        for note in plan["notes"]:
            frame = plan["frames"][note["frame"]]
            self.assertGreater(note["time_ms"], frame["end_ms"])
            self.assertLess(note["time_ms"], frame["end_ms"] + 12)

    def test_animation_input_validation(self):
        self.assertEqual(parse_frames("#.\n.#\n---\n.#\n#.\n"),
                         [["#.", ".#"], [".#", "#."]])
        for text in ("---\n#", "#\n---", "#\n---\n##", "#\n---\n#\n#"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_frames(text)
        with self.assertRaises(ValueError):
            compile_frames([["#"]] * 3, 2000, 2024)
        with self.assertRaises(ValueError):
            compile_frames([], 2000, 4000)
        # Repeating fast segments can dominate the reference BPM as well.
        with self.assertRaisesRegex(ValueError, "参考 BPM"):
            compile_frames([["#"]] * 30, 112, 2000)

    def test_pattern_round_trip_and_visibility(self):
        # Asymmetry detects upside-down, mirrored or wrongly assigned lanes.
        pattern = ["#...", ".##.", "...#"]
        for start, end, speed, transition in [(2000, 4000, 27, 12), (120, 150.5, 40, 12),
                                              (1000, 11000, 1, 20), (400, 500.125, 15, 12)]:
            with self.subTest(start=start, end=end, speed=speed):
                plan = compile_pattern(pattern, start, end, speed, transition)
                points, notes = decode(encode_osu(plan))
                interval = plan["time_range_ms"]
                expected = sorted((col, 0.2 + (row + 0.5) * 0.6 / len(pattern))
                                  for row, line in enumerate(pattern)
                                  for col, c in enumerate(line) if c == "#")
                actual = sorted((int(x * len(pattern[0]) / 512),
                                 1 - (position(points, t, interval) - position(points, start, interval)))
                                for x, t in notes)
                for (col, y), (actual_col, actual_y) in zip(expected, actual):
                    self.assertEqual(col, actual_col)
                    self.assertAlmostEqual(y, actual_y, delta=1e-5)
                self.assertEqual(len(expected), len(notes))
                for _, t in notes:
                    self.assertGreater(t, end)
                    self.assertLess(t, end + transition)
                    # Entire picture is above the playfield before entry.
                    self.assertGreater(position(points, t, interval) -
                                       position(points, start - transition, interval), 1)
                for p in points:
                    self.assertTrue(6 <= p[1] <= 60000)
                    self.assertTrue(0.01 <= p[2] <= 10)
                # Recompute the most-used red-line beat length from serialized data.
                durations = {}
                last_time = notes[-1][1]
                for i, (t, beat, _) in enumerate(points):
                    if t >= last_time:
                        break
                    next_t = min(points[i + 1][0], last_time)
                    group = round(beat, 3)
                    durations[group] = durations.get(group, 0) + next_t - t
                self.assertEqual(max(durations, key=durations.get), 500)

    def test_two_second_hold_has_subpixel_drift(self):
        plan = compile_pattern(["##", ".#"], 2000, 4000)
        points, _ = decode(encode_osu(plan))
        drift = (position(points, 4000, plan["time_range_ms"]) -
                 position(points, 2000, plan["time_range_ms"])) * 658
        self.assertGreater(drift, 0)
        self.assertLess(drift, 0.3)
        self.assertAlmostEqual(drift, plan["drift_at_658px"], delta=1e-4)

    def test_invalid_patterns(self):
        for text in ("", "..", "#\n##", "x", "# #", "#" * 19):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_pattern(text)

    def test_invalid_timing_and_reference_bpm(self):
        for kwargs in ({"start_ms": 0}, {"end_ms": 1000}, {"end_ms": math.nan},
                       {"scroll_speed": 0}, {"transition_ms": 0},
                       {"transition_ms": 0.001}, {"end_ms": 2_000_000},
                       {"start_ms": 300, "transition_ms": 200}):
            args = {"start_ms": 2000, "end_ms": 4000} | kwargs
            with self.subTest(args=args), self.assertRaises(ValueError):
                compile_pattern(["#"], **args)

    def test_video_blank_frames_keep_their_time_and_have_no_notes(self):
        frames = [[".."], ["#."], [".."], [".#"], [".."]]
        windows = [(2000 + i * 100, 2099 + i * 100) for i in range(5)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                              allow_empty_frames=True, anchor_reference=True)
        self.assertEqual([f["pattern"] for f in plan["frames"]], frames)
        self.assertEqual({n["frame"] for n in plan["notes"]}, {1, 3})
        points, notes = decode(encode_osu(plan))
        for index, (start, end) in enumerate(windows):
            current = position(points, (start + end) / 2, plan["time_range_ms"])
            visible = [x for x, t in notes
                       if 0 <= 1 - (position(points, t, plan["time_range_ms"]) - current) <= 1]
            self.assertEqual(len(visible), 0 if index % 2 == 0 else 1)
        with self.assertRaisesRegex(ValueError, "至少"):
            compile_frames([[".."]], 2000, 3000, allow_empty_frames=True)

    def test_long_video_keeps_reference_bpm_at_60_fps(self):
        count = 12000
        period = 1000 / 60
        windows = [(2000 + i * period, 2000 + (i + 1) * period - 0.575)
                   for i in range(count)]
        plan = compile_frames([["#"]] * count, frame_times=windows, fast_clear=True,
                              allow_empty_frames=True, anchor_reference=True)
        self.assertEqual(plan["base_beat_length_ms"], 500)
        self.assertEqual(len(plan["notes"]), count)
        self.assertLess(plan["drift_at_658px"], 0.1)

    def test_imported_audio_is_referenced_and_packaged_instead_of_silence(self):
        plan = compile_pattern(["#"], 2000, 3000)
        audio = b"OggS test audio"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_output(plan, output, audio_data=audio)
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertEqual(set(archive.namelist()), {"pattern.osu", "audio.ogg"})
                self.assertEqual(archive.read("audio.ogg"), audio)
                self.assertIn("AudioFilename: audio.ogg", archive.read("pattern.osu").decode())
            self.assertFalse((output / "silence.wav").exists())

    def test_aligned_video_exports_playback_settings_outside_osz(self):
        plan = compile_frames([["#" * 18] * 13], 2000, 3000, fast_clear=True, target_client="stable")
        plan["video"] = {"game_fps": 60, "fps": 30, "height": 13,
                         "requested_fps": 50, "requested_height": 24}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_output(plan, output)
            settings = (output / "播放设置.txt").read_text(encoding="utf-8")
            for value in ("60 FPS", "30 FPS", "请求 50 FPS", "18 列 × 13 行", "请求 24 行",
                          "FrameSync=Custom", "CustomFrameLimit=60", "固定滚速 27", "NF", "刷新相位"):
                self.assertIn(value, settings)
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertNotIn("播放设置.txt", archive.namelist())
            del plan["video"]
            write_output(plan, output)
            self.assertFalse((output / "播放设置.txt").exists())

    def test_video_metadata_cannot_break_out_of_preview_script(self):
        plan = compile_pattern(["#"], 2000, 3000)
        plan["video"] = {"filename": "</script><script>throw new Error('injected')</script>"}
        preview = make_preview(plan)
        self.assertEqual(preview.count("<script>"), 1)
        self.assertEqual(preview.count("</script>"), 1)
        self.assertIn(r"\u003c/script>", preview)

    def test_osz_is_self_contained(self):
        plan = compile_pattern(["#.", "##"], 500, 2500)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_output(plan, output)
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), {"pattern.osu", "silence.wav"})
                self.assertEqual(archive.read("pattern.osu").decode().splitlines(),
                                 encode_osu(plan).splitlines())
            with wave.open(str(output / "silence.wav")) as audio:
                self.assertGreater(audio.getnframes() / audio.getframerate(),
                                   plan["notes"][-1]["time_ms"] / 1000)
            self.assertIn('type="range"', (output / "preview.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
