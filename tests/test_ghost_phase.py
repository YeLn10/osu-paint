"""Unknown display phases must not repeatedly catch the same visible cuts."""

import math
from fractions import Fraction
from pathlib import Path
import random
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
        with patch('osu_paint_video.run_ffmpeg', side_effect=decode):
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


def phase_streak(plan, period, origin):
    """Independent exhaustive scan of the intervals between phase endpoints."""
    cuts = [(Fraction(a['sweep_start_ms']), Fraction(b['start_ms']))
            for a, b in zip(plan['frames'], plan['frames'][1:])
            if a['note_frame'] != b['note_frame'] and
            any('#' in row for row in a['pattern'] + b['pattern'])]
    period, origin = Fraction(period), Fraction(origin)
    edges = sorted({Fraction(0), period, *((t - origin) % period for cut in cuts for t in cut)})
    longest = 0
    for low, high in zip(edges, edges[1:]):
        offset = origin + (low + high) / 2
        run = 0
        for start, end in cuts:
            hit = math.floor((start - offset) / period) + 1 < (end - offset) / period
            run = run + 1 if hit else 0
            longest = max(longest, run)
    return longest


class GhostPhaseTests(unittest.TestCase):
    def test_phase_streak_matches_exhaustive_intervals(self):
        from osu_paint_video import _transition_phase_exposure
        rng = random.Random(20261008)
        for period in (10, Fraction(25, 3), Fraction(125, 18)):
            for case in range(20):
                intervals = [(i * 30 + rng.randrange(10), i * 30 + 10 + rng.randrange(15))
                             for i in range(12)]
                frames = [dict(note_frame=i, pattern=['#'], start_ms=0 if i == 0 else intervals[i - 1][1],
                               sweep_start_ms=start) for i, (start, _) in enumerate(intervals)]
                frames.append(dict(note_frame=len(intervals), pattern=['#'], start_ms=intervals[-1][1]))
                plan = dict(frames=frames)
                with self.subTest(period=period, case=case):
                    self.assertEqual(_transition_phase_exposure(plan, period, Fraction(3, 5))[2],
                                     phase_streak(plan, period, Fraction(3, 5)))

    def test_faster_walk_rejects_more_hits_even_when_streak_is_shorter(self):
        from osu_paint_video import compile_frames, _transition_phase_exposure, _transition_phases
        with patch('osu_paint_video._transition_phases',
                   side_effect=lambda frames, step: _transition_phases(frames)):
            baseline = video_sequence('stable', hz=60)
        compiled = []
        def record(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            compiled.append(plan)
            return plan
        with patch('osu_paint_video.compile_frames', side_effect=record), \
                patch('osu_paint_video._transition_phases', side_effect=lambda frames, step:
                      _transition_phases(frames, step=2 if step == 9 else step)):
            result = video_sequence('stable', hz=60)
        old = _transition_phase_exposure(baseline, Fraction(50, 3), 2000)
        new = _transition_phase_exposure(compiled[-1], Fraction(50, 3), 2000)
        self.assertEqual(len(compiled), 4)
        self.assertGreater(new[0], old[0])
        self.assertLess(new[2], old[2])
        self.assertEqual(encode_osu(result), encode_osu(baseline))

    def test_faster_walk_rejects_large_frame_interval_changes(self):
        from osu_paint_video import compile_frames, _transition_phases
        with patch('osu_paint_video._transition_phases', side_effect=lambda frames, step:
                   _transition_phases(frames)):
            baseline = video_sequence('lazer', hz=480)
        with patch('osu_paint_video.compile_frames', wraps=compile_frames) as compile_call, \
                patch('osu_paint_video._transition_phases', side_effect=lambda frames, step:
                      [i % 2 for i in range(len(frames))] if step > 1 else _transition_phases(frames)):
            result = video_sequence('lazer', hz=480)
        self.assertEqual(compile_call.call_count, 2)
        self.assertEqual(encode_osu(result), encode_osu(baseline))

    def test_short_lazer_sequence_breaks_consecutive_transition_hits(self):
        plan = video_sequence('lazer', hz=1000, changes=3)
        self.assertLessEqual(phase_streak(plan, 1, 2000), 2)

    def test_short_stable_sequence_uses_a_smaller_walk_within_cadence_limit(self):
        plan = video_sequence('stable', hz=60, changes=4)
        self.assertLessEqual(phase_streak(plan, Fraction(50, 3), 2000), 3)

    def test_smaller_walk_reduces_stable_streaks_without_more_exposure(self):
        from osu_paint_video import compile_frames, _transition_phase_exposure
        for hz, worst_limit, streak_limit in ((60, 15, 6), (90, 27, 17)):
            with self.subTest(hz=hz):
                with patch('osu_paint_video.compile_frames', wraps=compile_frames) as compiled:
                    plan = video_sequence('stable', hz=hz)
                score = _transition_phase_exposure(plan, Fraction(1000, hz), 2000)
                self.assertLessEqual(score[0], worst_limit)
                self.assertEqual(score[1], 192)
                self.assertLessEqual(score[2], streak_limit)
                self.assertEqual(score[2], phase_streak(plan, Fraction(1000, hz), 2000))
                self.assertEqual(len(plan['notes']), 65)
                self.assertLessEqual(compiled.call_count, 4)
                period = 1000 / plan['video']['fps']
                self.assertTrue(all(abs(b['start_ms'] - a['start_ms'] - period) <= 1 + 1e-7
                                    for a, b in zip(plan['frames'], plan['frames'][1:])))

    def test_faster_phase_walk_reduces_streaks_without_more_exposure(self):
        from osu_paint_video import _transition_phase_exposure
        for client, hz, worst_limit, streak_limit, total in (
                ('lazer', 480, 3, 2, 64 * .612 * 500 / 4900),
                ('lazer', 1000, 5, 2, 64 * .612 * 500 / 4900),
                ('stable', 120, 40, 9, 192),
                ('stable', 144, 59, 20, 192)):
            with self.subTest(client=client, hz=hz):
                plan = video_sequence(client, hz=hz)
                refresh_period = Fraction(1000, hz)
                score = _transition_phase_exposure(plan, refresh_period, 2000)
                self.assertLessEqual(score[0], worst_limit)
                self.assertAlmostEqual(score[1], total, places=6)
                self.assertLessEqual(phase_streak(plan, refresh_period, 2000), streak_limit)
                self.assertEqual(score[2], phase_streak(plan, refresh_period, 2000))
                self.assertEqual(len(plan['notes']), 65)
                period = 1000 / plan['video']['fps']
                self.assertTrue(all(abs(b['start_ms'] - a['start_ms'] - period) <= 1 + 1e-7
                                    for a, b in zip(plan['frames'], plan['frames'][1:])))

    def test_stable_short_hold_sweeps_do_not_lock_to_one_display_phase(self):
        plan = video_sequence('stable')
        counts, cuts = phase_counts(plan)
        self.assertLess(max(counts), .5 * len(cuts), (max(counts), len(cuts)))

    def test_lazer_fast_sweeps_use_the_available_high_refresh_gap(self):
        from osu_paint_video import _transition_phase_exposure
        for hz, limit in ((240, 1), (360, 2), (480, 3), (1000, 5)):
            with self.subTest(hz=hz):
                plan = video_sequence('lazer', hz=hz)
                worst, total, _ = _transition_phase_exposure(plan, Fraction(1000, hz), 2000)
                self.assertLessEqual(worst, limit)
                self.assertAlmostEqual(total, 64 * .612 * 500 / 4900, places=6)
                self.assertEqual(len(plan['notes']), 65)

    def test_stable_uses_safe_integer_slots_without_a_whole_ms_guard(self):
        from osu_paint_video import _transition_phase_exposure
        # Some rates have no better integer slots; preserve their previous score.
        for hz, limit in ((60, 15), (120, 40), (144, 59), (165, 64)):
            with self.subTest(hz=hz):
                plan = video_sequence('stable', hz=hz)
                worst, total, _ = _transition_phase_exposure(plan, Fraction(1000, hz), 2000)
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
        self.assertEqual(len(compiled), 3)
        baseline, candidate, faster = compiled
        old_score = _transition_phase_exposure(baseline, 1, 2000)
        new_score = _transition_phase_exposure(candidate, 1, 2000)
        self.assertLess(new_score[0], old_score[0])
        self.assertLessEqual(new_score[1], old_score[1] + 1e-7)
        self.assertTrue(any(a['sweep_start_ms'] <= 2000 + i * 50 - 1
                            for i, a in enumerate(candidate['frames'][:-1], 1)))
        self.assertTrue(any(a['sweep_start_ms'] <= 2000 + i * 50 - 1
                            for i, a in enumerate(faster['frames'][:-1], 1)))
        self.assertEqual(encode_osu(result), encode_osu(baseline))

    def test_tighter_gap_preserves_a_better_existing_stable_candidate(self):
        from osu_paint_video import compile_frames, _transition_phase_exposure, _transition_phases
        compiled = []
        def record_compile(*args, **kwargs):
            plan = compile_frames(*args, **kwargs)
            compiled.append(plan)
            return plan
        with patch('osu_paint_video.compile_frames', side_effect=record_compile), \
                patch('osu_paint_video._transition_phases',
                      side_effect=lambda frames, **kwargs: _transition_phases(frames)):
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
            rates = (60, 90, 120, 144, 165, 60000 / 1001) + ((240, 480, 1000) if client == "lazer" else ())
            for hz in rates:
                for merged in (False, True):
                    with self.subTest(client=client, hz=hz, merged=merged):
                        accelerated = merged and ((client == 'lazer' and hz in (480, 1000)) or
                                                  (client == 'stable' and hz in (60, 90, 120, 144)))
                        repeated = client == 'lazer' and hz == 60 and merged
                        repeat = 128 if repeated else 1 if accelerated else 2
                        changes = 16 if repeated else 64 if accelerated else 12
                        plan = video_sequence(client, changes=changes, repeat=repeat, hz=hz, height=3,
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
                                    if min(1 - plan.get('bottom_mask_fraction', 0), 1 - head + at)
                                    - max(0, 1 - tail + at - 1 / 3) > 1e-6}
                        divisor = round(hz / plan['video']['fps'])
                        for tick in range(1, (len(plan['frames']) - 1) * divisor):
                            nominal = 2000.6 + tick * 1000 / hz
                            self.assertEqual(visible(nominal), {tick // divisor // repeat % 2}, (tick, nominal))
                        # The renderer can still sample both pictures during a
                        # finite sweep. Keep this counterexample, not a zero-ghost claim.
                        before, after = plan['frames'][repeat - 1:repeat + 1]
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
        from osu_paint_video import _transition_phase_exposure
        plan = video_sequence('lazer', repeat=128, changes=16)
        self.assertEqual(len(plan['notes']), 33)
        self.assertLessEqual(plan['drift_at_768px'], .5)
        self.assertAlmostEqual(transition_exposure(plan), 20.808, places=6)
        self.assertEqual(plan['start_ms'], 2000)
        self.assertEqual(plan['end_ms'], 2000 + 2049 * 50)
        worst, _, longest = _transition_phase_exposure(plan, Fraction(50, 3), 2000)
        self.assertLessEqual(worst, 2)
        self.assertLessEqual(longest, 2)
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
        for intervals, expected in (([(9, 11), (19.5, 22)], (2, 4.5, 2)),
                                    ([(1, 2), (12, 13)], (1, 2, 1)),
                                    ([(0, 12), (25, 26)], (2, 13, 2)),
                                    ([(1, 2), (13, 14), (21, 22)], (2, 3, 1)),
                                    ([(0, 10), (10, 20)], (2, 20, 2))):
            with self.subTest(intervals=intervals):
                frames = [dict(note_frame=i, pattern=["#"], start_ms=0 if i == 0 else intervals[i - 1][1], sweep_start_ms=start)
                          for i, (start, _) in enumerate(intervals)]
                frames.append(dict(note_frame=len(intervals), pattern=["#"], start_ms=intervals[-1][1]))
                self.assertEqual(_transition_phase_exposure(dict(frames=frames), 10, 0), expected)

    def test_inferior_static_candidate_preserves_the_existing_lazer_schedule(self):
        for hz in (60, 120, 165):
            with self.subTest(hz=hz):
                plan = video_sequence('lazer', repeat=2048, changes=1, hz=hz)
                with patch('osu_paint_video._transition_phases', side_effect=lambda frames, **kwargs:
                           [1 - abs(1 - (i / 64) % 2) for i in range(len(frames))]):
                    baseline = video_sequence('lazer', repeat=2048, changes=1, hz=hz)
                self.assertEqual(encode_osu(plan), encode_osu(baseline))

    def test_phase_score_does_not_count_redraws_between_two_blank_pictures(self):
        from osu_paint_video import _transition_phase_exposure
        plan = dict(frames=[dict(note_frame=0, pattern=["."], start_ms=0, sweep_start_ms=8),
                            dict(note_frame=1, pattern=["."], start_ms=11, sweep_start_ms=18),
                            dict(note_frame=2, pattern=["#"], start_ms=21)])
        self.assertEqual(_transition_phase_exposure(plan, 10, 0), (1, 3, 1))
