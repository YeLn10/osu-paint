"""Unknown display phases must not repeatedly catch the same visible cuts."""

import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_paint import encode_osu
from osu_paint_video import import_video


def video_sequence(client, *, repeat=1, changes=64, hz=60, height=24, merged=True, origin=2000, fps=20):
    frames = [[('#.' if (i // repeat) % 2 == 0 else '.#')] * height
              for i in range(repeat * changes + 1)]
    raw = bytes(255 if pixel == '#' else 0 for frame in frames for row in frame for pixel in row)
    def decode(arguments, cancel):
        Path(arguments[-1]).write_bytes(raw)
        return ''
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'synthetic.mp4'
        source.touch()
        with patch('osu_paint_video._run_ffmpeg', side_effect=decode):
            result = import_video(source, fps=fps, width=2, height=height, start_ms=origin,
                                  refresh_hz=hz, merge_holds=merged, target_client=client)
    return result['plan']


def phase_counts(plan, *, samples=400, include_redraws=False):
    hz = plan['video']['refresh_hz']
    period = 1000 / hz
    cuts = [(a['sweep_start_ms'], b['start_ms'])
            for a, b in zip(plan['frames'], plan['frames'][1:]) if a['pattern'] != b['pattern'] or (include_redraws and a['note_frame'] != b['note_frame'])]
    counts = []
    for phase in range(samples):
        offset = plan['video']['start_ms'] + (phase + .5) * period / samples
        counts.append(sum(math.floor((start - offset) / period + 1e-8) + 1 <
                          (end - offset) / period - 1e-8 for start, end in cuts))
    return counts, cuts


class GhostPhaseTests(unittest.TestCase):
    def test_stable_short_hold_sweeps_do_not_lock_to_one_display_phase(self):
        plan = video_sequence('stable')
        counts, cuts = phase_counts(plan)
        self.assertLess(max(counts), .5 * len(cuts), (max(counts), len(cuts)))

    def test_lazer_fast_sweeps_use_the_available_high_refresh_gap(self):
        from osu_paint_video import _transition_phase_exposure
        for hz, limit in ((240, 1), (360, 2), (480, 3), (1000, 5)):
            with self.subTest(hz=hz):
                plan = video_sequence('lazer', hz=hz)
                worst, total = _transition_phase_exposure(plan, 1000 / hz, 2000)
                self.assertLessEqual(worst, limit)
                self.assertAlmostEqual(total, 64 * .612 * 500 / 4900, places=6)
                self.assertEqual(len(plan['notes']), 65)

    def test_stable_uses_safe_integer_slots_without_a_whole_ms_guard(self):
        from osu_paint_video import _transition_phase_exposure
        # Some rates have no better integer slots; preserve their previous score.
        for hz, limit in ((60, 15), (120, 40), (144, 59), (165, 64)):
            with self.subTest(hz=hz):
                plan = video_sequence('stable', hz=hz)
                worst, total = _transition_phase_exposure(plan, 1000 / hz, 2000)
                self.assertLessEqual(worst, limit)
                self.assertEqual(total, 192)
                self.assertEqual(len(plan['notes']), 65)

    def test_tighter_gap_rechecks_actual_cuts_after_compilation(self):
        from osu_paint_video import compile_frames, _transition_phase_exposure
        compiled = []
        def compile_with_stale_estimate(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            if not compiled:
                # Simulate a stale estimate without faking candidate geometry.
                plan['sweep_ms'] = .000001
            compiled.append(plan)
            return plan
        with patch('osu_paint_video.compile_frames', side_effect=compile_with_stale_estimate):
            result = video_sequence('lazer', hz=1000)
        self.assertEqual(len(compiled), 2)
        baseline, candidate = compiled
        old_score = _transition_phase_exposure(baseline, 1, 2000)
        new_score = _transition_phase_exposure(candidate, 1, 2000)
        self.assertLess(new_score[0], old_score[0])
        self.assertLessEqual(new_score[1], old_score[1] + 1e-7)
        self.assertTrue(any(a['sweep_start_ms'] <= 2000 + i * 50 - 1
                            for i, a in enumerate(candidate['frames'][:-1], 1)))
        self.assertEqual(encode_osu(result), encode_osu(baseline))

    def test_tighter_gap_preserves_a_better_existing_stable_candidate(self):
        from osu_paint_video import compile_frames, _transition_phase_exposure
        compiled = []
        def record_compile(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            compiled.append(plan)
            return plan
        with patch('osu_paint_video.compile_frames', side_effect=record_compile):
            result = video_sequence('stable', hz=144)
        self.assertEqual(len(compiled), 3)
        _, previous, tighter = compiled
        self.assertGreaterEqual(_transition_phase_exposure(tighter, 1000 / 144, 2000)[0],
                                _transition_phase_exposure(previous, 1000 / 144, 2000)[0])
        self.assertEqual(encode_osu(result), encode_osu(previous))

    def test_lazer_repeated_pictures_do_not_alias_the_phase_walk(self):
        plan = video_sequence('lazer', repeat=128, changes=16)
        counts, cuts = phase_counts(plan)
        self.assertLess(max(counts), .5 * len(cuts), (max(counts), len(cuts)))

    def test_serialized_geometry_is_clean_at_nominal_ticks_and_still_has_a_mixed_phase(self):
        from test_osu_paint import decode as lazer_decode, position as lazer_position
        from test_stable_geometry import decode as stable_decode, position as stable_position
        for client, decoder, position in (("lazer", lazer_decode, lazer_position),
                                           ("stable", stable_decode, stable_position)):
            rates = (60, 120, 144, 165, 60000 / 1001) + ((240, 480, 1000) if client == "lazer" else ())
            for hz in rates:
                for merged in (False, True):
                    with self.subTest(client=client, hz=hz, merged=merged):
                        plan = video_sequence(client, changes=12, repeat=2, hz=hz, height=3,
                                              merged=merged, origin=2000.6)
                        points, _ = decoder(encode_osu(plan))
                        objects = [line.split(',') for line in encode_osu(plan).split('[HitObjects]\n')[1].splitlines() if line]
                        endpoints = [(int(fields[0]) // 256,
                                      position(points, float(fields[2]), plan['time_range_ms']),
                                      position(points, float(fields[5].split(':')[0]) if fields[3] == '128'
                                               else float(fields[2]), plan['time_range_ms']))
                                     for fields in objects]
                        def visible(now):
                            at = position(points, now, plan['time_range_ms'])
                            return {col for col, head, tail in endpoints
                                    if min(1, 1 - head + at) - max(0, 1 - tail + at - 1 / 3) > 1e-6}
                        divisor = round(hz / plan['video']['fps'])
                        for tick in range(1, (len(plan['frames']) - 1) * divisor):
                            nominal = 2000.6 + tick * 1000 / hz
                            self.assertEqual(visible(nominal), {tick // divisor // 2 % 2}, (tick, nominal))
                        # The renderer can still sample both pictures during a
                        # finite sweep. Keep this counterexample, not a zero-ghost claim.
                        before, after = plan['frames'][1:3]
                        self.assertTrue(any(len(visible(before['sweep_start_ms'] +
                                            (after['start_ms'] - before['sweep_start_ms']) * i / 50)) == 2
                                            for i in range(1, 50)))
                        for fields, note in zip(objects, plan['notes']):
                            frame = plan['frames'][note['frame']]
                            self.assertGreater(float(fields[2]), frame['sweep_start_ms'])
                            if client == 'stable':
                                self.assertTrue(fields[2].isdigit())
                                if fields[3] == '128':
                                    self.assertTrue(fields[5].split(':')[0].isdigit())

    def test_stable_keeps_duration_audio_origin_cadence_and_dense_sweep_fallback(self):
        for hz in (60, 120, 165, 60000 / 1001):
            with self.subTest(hz=hz):
                plan = video_sequence('stable', changes=128, hz=hz, origin=2000.6)
                period = 1000 / plan['video']['fps']
                self.assertEqual(plan['video']['start_ms'], 2000.6)
                self.assertEqual(plan['start_ms'], 2001)
                self.assertAlmostEqual(plan['end_ms'], math.floor(2000.6 + 129 * period), delta=1e-7)
                self.assertEqual(plan['sweep_ms'], 3)
                self.assertEqual(len(plan['notes']), 129)
                starts = [f['start_ms'] for f in plan['frames']]
                self.assertLessEqual(max(abs(b - a - period) for a, b in zip(starts, starts[1:])),
                                     1 + (1000 / hz) / 64)
                for i, (before, after) in enumerate(zip(plan['frames'], plan['frames'][1:]), 1):
                    self.assertEqual(after['start_ms'] - before['sweep_start_ms'], 3)
                    self.assertLessEqual(after['start_ms'], 2000.6 + i * period + 1e-7)
                    self.assertGreater(before['sweep_start_ms'], 2000.6 + i * period - 1000 / hz)
        dense = video_sequence('stable', merged=False)
        self.assertEqual(dense['sweep_ms'], 25)
        self.assertEqual([f['start_ms'] for f in dense['frames']], [2000 + i * 50 for i in range(65)])
        no_room = video_sequence('stable', height=48, fps=20)
        self.assertEqual([f['start_ms'] for f in no_room['frames']], [2000 + i * 50 for i in range(65)])

    def test_repeated_lazer_frames_preserve_notes_drift_and_total_exposure(self):
        from test_transition_optimization import transition_exposure
        plan = video_sequence('lazer', repeat=128, changes=16)
        self.assertEqual(len(plan['notes']), 33)
        self.assertLessEqual(plan['drift_at_768px'], .5)
        self.assertAlmostEqual(transition_exposure(plan), 20.808, places=6)
        self.assertEqual(plan['start_ms'], 2000)
        self.assertEqual(plan['end_ms'], 2000 + 2049 * 50)
        counts, cuts = phase_counts(plan)
        self.assertLessEqual(max(counts), 4)
        self.assertEqual(len(cuts), 16)

    def test_long_static_scene_redraws_do_not_lock_to_one_phase(self):
        plan = video_sequence('lazer', repeat=2048, changes=1)
        counts, cuts = phase_counts(plan, include_redraws=True)
        self.assertGreater(len(cuts), 1, 'A long still picture eventually needs a redraw for drift')
        self.assertLess(max(counts), .5 * len(cuts), (max(counts), len(cuts)))

    def test_exact_phase_score_handles_wraparound_ties_and_long_sweeps(self):
        from osu_paint_video import _transition_phase_exposure
        for intervals, expected in (([(9, 11), (19.5, 22)], (2, 4.5)),
                                    ([(1, 2), (12, 13)], (1, 2)),
                                    ([(0, 12), (25, 26)], (2, 13))):
            with self.subTest(intervals=intervals):
                frames = [dict(note_frame=i, pattern=["#"], start_ms=0 if i == 0 else intervals[i - 1][1], sweep_start_ms=start)
                          for i, (start, _) in enumerate(intervals)]
                frames.append(dict(note_frame=len(intervals), pattern=["#"], start_ms=intervals[-1][1]))
                self.assertEqual(_transition_phase_exposure(dict(frames=frames), 10, 0), expected)

    def test_inferior_static_candidate_preserves_the_existing_lazer_schedule(self):
        for hz in (60, 120, 165):
            with self.subTest(hz=hz):
                plan = video_sequence('lazer', repeat=2048, changes=1, hz=hz)
                with patch('osu_paint_video._transition_phases', side_effect=lambda frames:
                           [1 - abs(1 - (i / 64) % 2) for i in range(len(frames))]):
                    baseline = video_sequence('lazer', repeat=2048, changes=1, hz=hz)
                self.assertEqual(encode_osu(plan), encode_osu(baseline))

    def test_phase_score_does_not_count_redraws_between_two_blank_pictures(self):
        from osu_paint_video import _transition_phase_exposure
        plan = dict(frames=[dict(note_frame=0, pattern=["."], start_ms=0, sweep_start_ms=8),
                            dict(note_frame=1, pattern=["."], start_ms=11, sweep_start_ms=18),
                            dict(note_frame=2, pattern=["#"], start_ms=21)])
        self.assertEqual(_transition_phase_exposure(plan, 10, 0), (1, 3))
