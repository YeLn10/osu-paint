"""Reduce repeated mixed pictures without lowering stable's twelve rows."""

from fractions import Fraction
import math
import unittest
from unittest.mock import patch

from osu_paint import compile_frames, encode_osu
from osu_paint_video import _transition_phase_exposure
from test_stable_geometry import decode, position
from test_stable_rendering import sprites, sprite_spans
from test_stable_sweep_phase import dense_video


def rendered_mixed_hits(plan):
    text = encode_osu(plan)
    decoded, _ = decode(text)
    points = [(t, beat / sv) for t, beat, sv in decoded] + [(plan["end_ms"] + 10000, 500)]
    frames = {n["time_ms"]: n["frame"] for n in plan["notes"]}
    objects = [set() for _ in plan["frames"]]
    for line in text.split("[HitObjects]\n")[1].splitlines():
        fields = line.split(",")
        head = int(fields[2])
        tail = int(fields[5].split(":")[0]) if fields[3] == "128" else head
        objects[frames[head]].add((head, tail))
    paths = [sprites(points, group) for group in objects]
    counts, streaks = [], []
    period = Fraction(50, 3)
    # All fifty integer-clock phases at 60 Hz, sampled between their edges.
    # Visibility comes from native-rule sprite clipping, not sweep_ms alone.
    for phase in range(50):
        origin = 2000 + Fraction(2 * phase + 1, 6)
        count = run = longest = 0
        for i, (before, after) in enumerate(zip(plan["frames"], plan["frames"][1:])):
            now = origin + (math.floor((before["sweep_start_ms"] - origin) / period) + 1) * period
            mixed = (now < after["start_ms"] and
                     bool(sprite_spans(paths[i], float(now), clip=479)) and
                     bool(sprite_spans(paths[i + 1], float(now), clip=479)))
            count += mixed
            run = run + 1 if mixed else 0
            longest = max(longest, run)
        counts.append(count)
        streaks.append(longest)
    return max(counts), max(streaks)


class StableCadenceTests(unittest.TestCase):
    def test_long_dense_video_has_fewer_consecutive_rendered_mixed_pictures(self):
        plan = dense_video(changes=256)
        worst, longest = rendered_mixed_hits(plan)
        self.assertLessEqual(worst, 212)
        self.assertLessEqual(longest, 58)
        self.assertEqual(_transition_phase_exposure(plan, Fraction(50, 3), 2000), (212, 3328, 58))
        self.assertEqual((plan["keys"], len(plan["pattern"]), plan["sweep_ms"]), (16, 12, 13))

    def test_a_faster_walk_that_hurts_a_short_video_is_rejected(self):
        compiled = []

        def record(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            compiled.append(plan)
            return plan

        with patch("osu_paint_video.compile_frames", side_effect=record):
            plan = dense_video()
        self.assertEqual(len(compiled), 6)
        self.assertIsNot(plan, compiled[-1])
        self.assertEqual(_transition_phase_exposure(plan, Fraction(50, 3), 2000), (54, 832, 53))
        self.assertGreater(_transition_phase_exposure(compiled[-1], Fraction(50, 3), 2000)[0], 54)

    def test_long_walk_preserves_audio_cadence_and_serialized_picture_positions(self):
        for hz in (60, 60000 / 1001, 75):
            for origin in (2000, 2000.6):
                with self.subTest(hz=hz, origin=origin):
                    plan = dense_video(changes=256, hz=hz, origin=origin)
                    refresh = Fraction(1000) / Fraction(str(hz)).limit_denominator()
                    period = refresh * round(hz / plan["video"]["fps"])
                    self.assertEqual(plan["video"]["start_ms"], origin)
                    self.assertEqual(plan["start_ms"], math.ceil(origin))
                    self.assertEqual(plan["end_ms"], math.floor(Fraction(str(origin)) + 257 * period))
                    points, _ = decode(encode_osu(plan))
                    for i, (before, after) in enumerate(zip(plan["frames"], plan["frames"][1:]), 1):
                        nominal = Fraction(str(origin)) + i * period
                        self.assertLessEqual(abs(after["start_ms"] - before["start_ms"] - period), 1)
                        self.assertTrue(0 <= nominal - after["start_ms"] < refresh)
                        self.assertGreater(before["sweep_start_ms"], nominal - 2 * refresh)
                    for note in plan["notes"][::91]:
                        frame = plan["frames"][note["frame"]]
                        now = position(points, frame["sweep_start_ms"], plan["time_range_ms"])
                        for row, stamp in ((note["row"], note["time_ms"]),
                                           (note.get("end_row", note["row"]), note.get("end_time_ms", note["time_ms"]))):
                            self.assertGreater(stamp, frame["sweep_start_ms"])
                            bottom = 1 - position(points, stamp, plan["time_range_ms"]) + now
                            self.assertAlmostEqual(bottom, (row + 1) / 12 - 1 / 768, delta=1e-5)

    def test_more_exposure_is_rejected_after_the_old_wide_walk_was_accepted(self):
        compiled = []

        def longer_sweep(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            compiled.append(plan)
            if len(compiled) == 6:
                plan["frames"][0]["sweep_start_ms"] -= 1
            return plan

        with patch("osu_paint_video.compile_frames", side_effect=longer_sweep):
            plan = dense_video(changes=256)
        self.assertEqual(len(compiled), 6)
        self.assertTrue(plan is compiled[-2])
        self.assertEqual(_transition_phase_exposure(plan, Fraction(50, 3), 2000), (214, 3328, 104))


if __name__ == "__main__":
    unittest.main()
