"""Stable-only integer parsing, serialized geometry and refresh-clock regressions."""

from functools import partial
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from osu_paint import compile_frames, encode_osu
from osu_paint_video import import_video, resolve_video_options

compile_frames = partial(compile_frames, target_client="stable")
import_video = partial(import_video, target_client="stable")
resolve_video_options = partial(resolve_video_options, target_client="stable")


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
                beat, sv = value, 1
            else:
                sv = 1 / struct.unpack("f", struct.pack("f", min(10000, max(10, -value)) / 100))[0] if value < 0 else 1
            if points and points[-1][0] == time:
                points.pop()
            points.append((time, beat, sv))
        elif line and section == "[HitObjects]":
            fields = line.split(",")
            notes.append((int(fields[0]), float(fields[2])))
    return points, notes


def position(points, time, time_range):
    # Stable integrates double beat lengths; its transforms round pixel endpoints,
    # not each completed relative-distance segment as lazer does.
    total = 0
    for i, (start, beat, sv) in enumerate(points):
        if start >= time:
            break
        end = points[i + 1][0] if i + 1 < len(points) else math.inf
        value = (min(end, time) - start) * points[0][1] / beat * sv / time_range
        total += value
    return total


def synthetic_video(count=2400, fps=20, height=3, **options):
    """Exercise the importer without spending two minutes encoding a fixture."""
    def decode(arguments, cancel):
        pixels = bytearray()
        for index in range(count):
            pixels.extend(bytes((255, 0) if index % 2 == 0 else (0, 255)) * height)
        Path(arguments[-1]).write_bytes(pixels)
        return ""

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "synthetic.mp4"
        source.touch()
        with patch("osu_paint_video._run_ffmpeg", side_effect=decode):
            return import_video(source, fps=fps, width=2, height=height, **options)


class StableGeometryTests(unittest.TestCase):
    def test_nominal_display_ticks_do_not_contain_the_previous_picture(self):
        # The reference ends its sweeps at floor(frame * 1000 / 30), not ceil.
        # Test actual emitted geometry at display times, NOT at plan frame starts.
        for hz in (60, 60000 / 1001):
            for origin in (2000, 2000.6):
                for merged in (False, True):
                    with self.subTest(hz=hz, origin=origin, merged=merged):
                        plan = synthetic_video(count=9, fps=30, height=12, refresh_hz=hz,
                                               start_ms=origin, merge_holds=merged)["plan"]
                        text = encode_osu(plan)
                        points, _ = decode(text)
                        objects = [line.split(",") for line in text.split("[HitObjects]\n")[1].splitlines() if line]
                        for tick in range(2, 16):
                            now = origin + tick * 1000 / hz
                            current = position(points, now, plan["time_range_ms"])
                            visible_columns = set()
                            for fields in objects:
                                head = float(fields[2])
                                tail = float(fields[5].split(":")[0]) if fields[3] == "128" else head
                                bottom = 1 - position(points, head, plan["time_range_ms"]) + current
                                top = 1 - position(points, tail, plan["time_range_ms"]) + current - 1 / 12
                                if min(1, bottom) - max(0, top) > 1e-6:
                                    visible_columns.add(int(fields[0]) // 256)
                            self.assertEqual(visible_columns, {(tick // 2) % 2}, (tick, now))

    def test_long_sweeps_remain_a_counterexample_at_every_refresh_phase(self):
        plan = synthetic_video(count=3, fps=10, height=24, refresh_hz=60)["plan"]
        period = 1000 / 60
        for phase in range(100):
            for before, after in zip(plan["frames"], plan["frames"][1:]):
                start, end = before["sweep_start_ms"], after["start_ms"]
                tick = (math.floor((start + 1e-8) / period - phase / 100) + 1 + phase / 100) * period
                self.assertLess(start, tick)
                self.assertLess(tick, end)
        self.assertEqual(len(plan["pattern"]), 24, "Never silently discard requested rows")

    def test_fractional_start_must_leave_room_for_the_first_display_and_sweep(self):
        for hz in (None, 60, 60000 / 1001):
            options = dict(fps=30, width=2, height=31, scroll_speed=27, refresh_hz=hz)
            with self.subTest(hz=hz):
                resolve_video_options(start_ms=2000, **options)
                with self.assertRaisesRegex(ValueError, "降低 FPS 或减少行数"):
                    resolve_video_options(start_ms=2000.6, **options)

    def test_fractional_refresh_preserves_height_or_rejects_an_impossible_rate(self):
        options = resolve_video_options(fps=30, width=10, height=24, start_ms=2000,
                                        scroll_speed=27, refresh_hz=59.94)
        self.assertEqual(options["height"], 24)
        self.assertAlmostEqual(options["fps"], 29.97)
        with self.assertRaisesRegex(ValueError, "减少行数"):
            resolve_video_options(fps=60, width=10, height=24, start_ms=2000,
                                  scroll_speed=27, refresh_hz=59.94)

    def test_two_minutes_of_fractional_refresh_have_no_accumulated_slip(self):
        refresh = 60000 / 1001
        plan = synthetic_video(refresh_hz=refresh)["plan"]
        for index, frame in enumerate(plan["frames"]):
            expected = 2000 + index * 3 * 1000 / refresh
            self.assertLessEqual(frame["start_ms"], expected + 1e-8)
            self.assertLess(expected - frame["start_ms"], 1 + 1e-8)
        self.assertAlmostEqual(plan["video"]["fps"], refresh / 3)
        self.assertEqual(plan["video"]["refresh_hz"], refresh)

    def test_integer_picture_alignment_never_moves_the_fractional_audio_origin(self):
        result = synthetic_video(count=6, refresh_hz=60, start_ms=2000.6)
        self.assertEqual(result["plan"]["start_ms"], 2001)
        self.assertEqual(result["video"]["start_ms"], 2000.6)
        self.assertNotIn("refresh_phase_ms", result["video"])
