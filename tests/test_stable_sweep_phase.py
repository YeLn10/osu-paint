"""Dense 16x12 video sweeps at the reported 15 FPS / 60 Hz settings."""

from fractions import Fraction
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_paint import compile_frames, encode_osu
from osu_paint_video import import_video, _transition_phase_exposure
from test_stable_geometry import decode, position


def dense_video(*, changes=64, fps=15, hz=60, origin=2000, merged=True):
    # A continuous black first column reveals the white ribbon between pictures;
    # checkerboard neighbours require all twelve integer endpoint rows.
    frames = [["#" + "".join("#" if (i + row + column) % 2 else "."
                             for column in range(15)) for row in range(12)]
              for i in range(changes + 1)]
    raw = bytes(255 if pixel == "#" else 0 for frame in frames for row in frame for pixel in row)

    def decode(arguments, cancel):
        Path(arguments[-1]).write_bytes(raw)
        return ""

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "synthetic.mp4"
        source.touch()
        with patch("osu_paint_video._run_ffmpeg", side_effect=decode):
            return import_video(source, width=16, height=12, fps=fps, refresh_hz=hz,
                                start_ms=origin, merge_holds=merged, target_client="stable")["plan"]


class StableSweepPhaseTests(unittest.TestCase):
    def test_dense_sweeps_do_not_lock_to_every_cut_at_one_display_phase(self):
        plan = dense_video()
        worst, total, longest = _transition_phase_exposure(plan, Fraction(50, 3), 2000)
        self.assertEqual(total, 64 * 13)
        self.assertLessEqual(worst, 54)
        self.assertLessEqual(longest, 53)

    def test_serialized_sweeps_do_not_split_a_common_black_column(self):
        plan = dense_video()
        text = encode_osu(plan)
        points, _ = decode(text)
        endpoints = []
        for line in text.split("[HitObjects]\n")[1].splitlines():
            fields = line.split(",")
            if int(fields[0]) >= 32:
                continue
            self.assertEqual(fields[3], "128")
            head, tail = int(fields[2]), int(fields[5].split(":")[0])
            endpoints.append((position(points, head, plan["time_range_ms"]),
                              position(points, tail, plan["time_range_ms"])))
        ribbons = 0
        for index in range(1, 65):
            # A fixed display phase that previously caught all 64 white ribbons.
            now = 2000 + index * 1000 / 15 - 4
            current = position(points, now, plan["time_range_ms"])
            spans = sorted((max(0, 1 - tail + current - 1 / 12), min(1, 1 - head + current))
                           for head, tail in endpoints
                           if min(1, 1 - head + current) > max(0, 1 - tail + current - 1 / 12))
            ribbons += any(b[0] - a[1] > .5 / 768 for a, b in zip(spans, spans[1:]))
        self.assertEqual(ribbons, 0)

    def test_lead_is_bounded_and_audio_duration_rows_and_cadence_are_preserved(self):
        for hz in (60, 60000 / 1001):
            for origin in (2000, 2000.6):
                for merged in (False, True):
                    with self.subTest(hz=hz, origin=origin, merged=merged):
                        plan = dense_video(hz=hz, origin=origin, merged=merged)
                        refresh = Fraction(1000) / Fraction(str(hz)).limit_denominator()
                        period = 4 * refresh
                        self.assertEqual(plan["video"]["start_ms"], origin)
                        self.assertEqual((plan["keys"], len(plan["pattern"])), (16, 12))
                        self.assertEqual(plan["start_ms"], math.ceil(origin))
                        self.assertEqual(plan["end_ms"], math.floor(Fraction(str(origin)) + 65 * period))
                        points, _ = decode(encode_osu(plan))
                        for i, frame in enumerate(plan["frames"][1:], 1):
                            nominal = Fraction(str(origin)) + i * period
                            self.assertLessEqual(frame["start_ms"], nominal)
                            self.assertLess(nominal - frame["start_ms"], refresh)
                            previous = plan["frames"][i - 1]
                            self.assertGreater(previous["sweep_start_ms"], nominal - 2 * refresh)
                            self.assertLessEqual(abs(frame["start_ms"] - previous["start_ms"] - period), 1)
                            current = position(points, float(nominal), plan["time_range_ms"])
                            for note in (n for n in plan["notes"] if n["frame"] == i):
                                bottom = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + current
                                self.assertAlmostEqual(bottom, (note["row"] + 1) / 12 - 1 / 768, delta=1e-5)
                                self.assertGreater(note["time_ms"], nominal)

    def test_a_wider_walk_with_more_exposure_is_rejected(self):
        plans = []

        def longer_sweep(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            plans.append(plan)
            # Only the wide candidate can finish this far before its nominal tick.
            if 2000 + 64 * 1000 / 15 - plan["frames"][64]["start_ms"] > 10:
                plan["frames"][0]["sweep_start_ms"] -= 1
            return plan

        with patch("osu_paint_video.compile_frames", side_effect=longer_sweep):
            plan = dense_video()
        self.assertEqual(len(plans), 5)
        self.assertIsNot(plan, plans[-1])
        self.assertEqual(_transition_phase_exposure(plan, Fraction(50, 3), 2000), (64, 832, 64))

    def test_no_extra_candidate_when_the_video_has_no_room(self):
        with patch("osu_paint_video.compile_frames", wraps=compile_frames) as compile_call:
            plan = dense_video(fps=30)
        self.assertLessEqual(compile_call.call_count, 4)
        for i, frame in enumerate(plan["frames"][1:], 1):
            self.assertGreater(plan["frames"][i - 1]["sweep_start_ms"], 2000 + i * 1000 / 30 - 1000 / 60)


if __name__ == "__main__":
    unittest.main()
