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
    for line in text.splitlines():
        if line.startswith("["):
            section = line
        elif line and section == "[TimingPoints]":
            fields = line.split(",")
            time, value = map(float, fields[:2])
            if fields[6] == "1":
                beat, sv = min(60000, max(6, value)), 1
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
        value = (min(end, time) - start) * points[0][1] / beat * sv / time_range
        total += struct.unpack("f", struct.pack("f", value))[0] if end <= time else value
    return total


class ExportTests(unittest.TestCase):


    def test_reference_bpm_groups_lazer_precision(self):
        points = [Point(0, 500, 1), Point(100, 60000.0001, .01), Point(170, 60000.0002, .01)]
        self.assertEqual(most_common_beat_length(points, 230), 60000)


    def test_all_one_to_eighteen_columns_export_as_plain_notes(self):
        for keys in range(1, 19):
            client = "lazer"
            with self.subTest(keys=keys, client=client):
                plan = compile_frames([["#" * keys]], 2000, 4000, fast_clear=True)
                objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
                columns = [int(int(line.split(",")[0]) * keys / 512) for line in objects]
                self.assertEqual(columns, list(range(keys)))
                self.assertTrue(all(line.split(",")[3] == "1" for line in objects))
                self.assertFalse(any("end_ms" in note for note in plan["notes"]))


    def test_fast_clear_removes_notes_from_full_stage_within_one_ms(self):
        plan = compile_frames([["#"]], 2000, 4000, fast_clear=True)
        points, notes = decode(encode_osu(plan))
        interval = plan["time_range_ms"]
        self.assertLess(plan["transition_ms"], 1)
        for _, note_time in notes:
            y = 1 - position(points, note_time, interval) + position(points, 4001, interval)
            self.assertGreater(y, 1 + .5 / len(plan["pattern"]))
        self.assertTrue(all(6 <= beat <= 60000 and 0.01 <= sv <= 10 for _, beat, sv in points))

    def test_free_timing_preserves_windows_and_blank_gaps(self):
        frames = [["#.", ".#"], [".#", "#."], ["##", ".#"]]
        windows = [(2000, 2500), (3000, 4200), (4201, 5000)]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True)
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
        points, notes = decode(encode_osu(plan))
        interval = plan["time_range_ms"]
        for now in (2501, 2750, 2999):
            self.assertFalse(any(0 <= 1 - position(points, t, interval) + position(points, now, interval) <= 1
                                 for _, t in notes), "Blank gap contains a note, including below judgement")
        for index, frame in enumerate(plan["frames"]):
            for now in (frame["start_ms"], frame["end_ms"]):
                visible = [(note, 1 - position(points, note["time_ms"], interval) + position(points, now, interval))
                           for note in plan["notes"]]
                visible = [(note, y) for note, y in visible if 0 <= y <= 1]
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
                self.assertEqual(plan["base_beat_length_ms"], points[0][1])
                self.assertTrue(all(a["time"] < b["time"] for a, b in zip(plan["points"], plan["points"][1:])))
                for note in plan["notes"]:
                    now = plan["frames"][note["frame"]]["exit_end_ms"]
                    y = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + position(points, now, plan["time_range_ms"])
                    self.assertGreater(y, 1 + .5 / len(plan["pattern"]))
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
            inset = frame["drift_playfield_fraction"] + 1 / 768
            expected = sorted((col, (row + 1) / 3 - inset)
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
            self.assertLess(note["time_ms"], frame["exit_end_ms"])

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
            compile_frames([["#."] if i % 2 else [".#"] for i in range(30)], 112, 2000)

    def test_pattern_round_trip_and_visibility(self):
        # Asymmetry detects upside-down, mirrored or wrongly assigned lanes.
        pattern = ["#...", ".##.", "...#"]
        for start, end, speed, transition in [(2000, 4000, 27, 12), (120, 150.5, 40, 12),
                                              (1000, 11000, 1, 20), (400, 500.125, 15, 12)]:
            with self.subTest(start=start, end=end, speed=speed):
                plan = compile_pattern(pattern, start, end, speed, transition)
                points, notes = decode(encode_osu(plan))
                interval = plan["time_range_ms"]
                inset = plan["drift_playfield_fraction"] + 1 / 768
                expected = sorted((col, (row + 1) / len(pattern) - inset)
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
                 position(points, 2000, plan["time_range_ms"])) * 768
        self.assertGreater(drift, 0)
        self.assertLess(drift, 0.3)
        self.assertAlmostEqual(drift, plan["drift_at_768px"], delta=1e-4)

    def test_invalid_patterns(self):
        for text in ("", "..", "#\n##", "x", "# #", "#" * 19):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_pattern(text)

    def test_invalid_timing_and_reference_bpm(self):
        for kwargs in ({"start_ms": 0}, {"end_ms": 1000}, {"end_ms": math.nan},
                       {"scroll_speed": 0}, {"transition_ms": 0},
                       {"transition_ms": 0.001}, {"end_ms": 5_000_000},
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

    def test_fast_clear_limits_reference_speed_using_the_whole_reused_picture(self):
        references = []
        transition = minimum_transition_ms(27)
        for repeated in (1, 60):
            for merged in (False, True):
                with self.subTest(repeated=repeated, holds=merged):
                    frames = [["#."] * 3] * repeated + [[".#"] * 3]
                    windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition)
                               for i in range(len(frames))]
                    plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                                          anchor_reference=True, merge_holds=merged)
                    self.assertEqual({f["note_frame"] for f in plan["frames"]}, {0, repeated})
                    self.assertGreater(plan["base_beat_length_ms"], 500)
                    self.assertLessEqual(plan["base_beat_length_ms"], 5000)
                    references.append(plan["base_beat_length_ms"])
                    points, notes = decode(encode_osu(plan))
                    last = max(n.get("end_time_ms", n["time_ms"]) for n in plan["notes"])
                    durations = {}
                    for i, (start, beat, _) in enumerate(points):
                        if start >= last:
                            break
                        end = min(points[i + 1][0], last)
                        group = round(beat * 1000) / 1000
                        durations[group] = durations.get(group, 0) + end - start
                    self.assertEqual(max(durations, key=durations.get), plan["base_beat_length_ms"])
                    for frame in (plan["frames"][0], plan["frames"][-1]):
                        drift = (position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                                 - position(points, frame["start_ms"], plan["time_range_ms"])) * 768
                        self.assertLessEqual(drift, .5001)
                    for (_, time), note in zip(notes, plan["notes"]):
                        self.assertGreater(time, plan["frames"][note["frame"]]["sweep_start_ms"])
        self.assertLess(references[-1], references[0])

    def test_long_video_keeps_reference_bpm_at_60_fps(self):
        count = 12000
        period = 1000 / 60
        transition = minimum_transition_ms(27)
        windows = [(2000 + i * period, 2000 + (i + 1) * period - transition)
                   for i in range(count)]
        plan = compile_frames([["#"]] * count, frame_times=windows, fast_clear=True,
                              allow_empty_frames=True, anchor_reference=True)
        self.assertGreaterEqual(plan["base_beat_length_ms"], 500)
        self.assertLess(len(plan["notes"]), count // 10)
        self.assertLessEqual(plan["drift_at_768px"], 0.5)
        self.assertEqual(len(plan["frames"]), count)

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
        plan = compile_frames([["#" * 18] * 13], 2000, 3000, fast_clear=True)
        plan["video"] = {"refresh_hz": 60, "fps": 30, "height": 13,
                         "requested_fps": 50, "requested_height": 24}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_output(plan, output)
            settings = (output / "播放设置.txt").read_text(encoding="utf-8")
            self.assertNotIn("Pixel Film 模式", settings)
            self.assertNotIn("补丁", settings)
            for value in ("60 Hz", "固定滚速 27", "NF", "自动安排换帧"):
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

    def test_export_preserves_old_film_files_without_packaging_them(self):
        plan = compile_pattern(["#"], 500, 2500)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            old_files = {"pixel-film.osu": b"old entry", "pixel-film.json": b"old frames"}
            for name, data in old_files.items():
                (output / name).write_bytes(data)
            write_output(plan, output)
            for name, data in old_files.items():
                self.assertEqual((output / name).read_bytes(), data)
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertEqual(set(archive.namelist()), {"pattern.osu", "silence.wav"})

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
                self.assertIn("Mode: 3", archive.read("pattern.osu").decode())
                self.assertNotIn("osu-paint-film-v1", archive.read("pattern.osu").decode())
            self.assertFalse((output / "pixel-film.osu").exists())
            self.assertFalse((output / "pixel-film.json").exists())
            with wave.open(str(output / "silence.wav")) as audio:
                self.assertGreater(audio.getnframes() / audio.getframerate(),
                                   plan["notes"][-1]["time_ms"] / 1000)
            self.assertIn('type="range"', (output / "preview.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
