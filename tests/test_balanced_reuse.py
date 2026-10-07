"""Balance reused still pictures without adding redraws or moving frame windows."""

import unittest

from osu_paint import compile_frames, encode_osu, minimum_transition_ms
from test_osu_paint import decode, position
from test_transition_optimization import transition_exposure


def sequence(still=60, motion=20, *, irregular=False, merged=True, client='lazer'):
    frames = [['#.'] * 24] * still + [[('.#' if i % 2 == 0 else '#.')] * 24 for i in range(motion)]
    transition = minimum_transition_ms(27, 24, target_client=client)
    windows, start = [], 2000
    for i in range(len(frames)):
        duration = (30 if i < still // 2 else 70) if irregular and i < still else 50
        windows.append((start, start + duration - transition))
        start += duration
    plan = compile_frames(frames, frame_times=windows, fast_clear=True, anchor_reference=True,
                          merge_holds=merged, target_client=client)
    return plan, frames, windows


class BalancedReuseTests(unittest.TestCase):
    def test_balancing_reduces_total_exposure_without_more_redraws(self):
        for still, limit in ((60, 4.1), (80, 5.4)):
            for merged in (False, True):
                with self.subTest(still=still, merged=merged):
                    plan, frames, windows = sequence(still, merged=merged)
                    # Previously: 29+29+2 / 37+37+6, with 5.683 / 7.252 ms exposure.
                    self.assertLess(transition_exposure(plan), limit)
                    self.assertEqual(len(plan['notes']), 23 * (1 if merged else 24))
                    self.assertEqual(len({f['note_frame'] for f in plan['frames']}), 23)
                    self.assertEqual([f['pattern'] for f in plan['frames']], frames)
                    self.assertEqual([(f['start_ms'], f['end_ms']) for f in plan['frames']], windows)
                    self.assertLessEqual(plan['drift_at_768px'], .5)

    def test_irregular_windows_are_balanced_by_time_not_frame_count(self):
        plan, _, windows = sequence(irregular=True)
        groups = [f for i, f in enumerate(plan['frames'][:60]) if i == f['note_frame']]
        durations = [f['sweep_start_ms'] - f['start_ms'] for f in groups]
        self.assertEqual(len(groups), 3)
        self.assertLess(max(durations) - min(durations), 100)
        self.assertLess(transition_exposure(plan), 4.3)
        self.assertEqual([(f['start_ms'], f['end_ms']) for f in plan['frames']], windows)

    def test_low_gain_static_only_manual_and_stable_keep_their_strategy(self):
        low_gain, _, _ = sequence(still=128, motion=16)
        self.assertEqual([i for i, f in enumerate(low_gain['frames'][:128]) if i == f['note_frame']], [0, 76])
        static, frames, windows = sequence(still=60, motion=0)
        self.assertEqual(len(static['notes']), 1)
        manual = compile_frames(frames, frame_times=windows, transition_ms=minimum_transition_ms(27),
                                fast_clear=False, anchor_reference=True, merge_holds=True)
        self.assertEqual(manual['base_beat_length_ms'], 500)
        self.assertEqual(len(manual['notes']), 1)
        stable, _, windows = sequence(client='stable')
        self.assertEqual(stable['base_beat_length_ms'], 500)
        self.assertEqual(stable['sweep_ms'], 3)
        self.assertEqual(len(stable['notes']), 21)
        self.assertEqual({f['note_frame'] for f in stable['frames'][:60]}, {0})
        self.assertEqual([(f['start_ms'], f['end_ms']) for f in stable['frames']], windows)

    def test_balancing_does_not_bridge_deliberate_gaps_or_blank_frames(self):
        frames = [['#.'] * 24] * 60 + [['..'] * 24] * 2 + [['#.'] * 24] * 60
        frames += [[('.#' if i % 2 == 0 else '#.')] * 24 for i in range(20)]
        transition = minimum_transition_ms(27)
        starts = [2000 + i * 50 + (100 if i >= 30 else 0) for i in range(len(frames) + 1)]
        windows = [(starts[i], starts[i] + 50 - transition) for i in range(len(frames))]
        plan = compile_frames(frames, frame_times=windows, fast_clear=True, anchor_reference=True,
                              merge_holds=True, allow_empty_frames=True)
        self.assertEqual([(f['start_ms'], f['end_ms']) for f in plan['frames']], windows)
        for i in (30, 60, 62, 122):
            self.assertEqual(plan['frames'][i]['note_frame'], i)
        points, _ = decode(encode_osu(plan))
        rectangles = [(position(points, n['time_ms'], plan['time_range_ms']),
                       position(points, n.get('end_time_ms', n['time_ms']), plan['time_range_ms'])) for n in plan['notes']]
        for time in ((windows[29][1] + windows[30][0]) / 2,
                     windows[60][0], windows[60][1], windows[61][1]):
            at = position(points, time, plan['time_range_ms'])
            self.assertFalse(any(min(1, 1-head+at) - max(0, 1-tail+at-1/24) > 1e-6 for head, tail in rectangles))

    def test_reuse_balancing_respects_extreme_canvas_and_scroll_settings(self):
        for height in (1, 128):
            for keys in (1, 18):
                for speed in (1, 40):
                    with self.subTest(height=height, keys=keys, speed=speed):
                        rows, blank = ['#' + '.' * (keys - 1)] * height, ['.' * keys] * height
                        frames = [rows] * 60 + [blank if i % 2 == 0 else rows for i in range(20)]
                        transition = minimum_transition_ms(speed)
                        windows = [(2000 + i * 50, 2000 + (i + 1) * 50 - transition) for i in range(len(frames))]
                        plan = compile_frames(frames, frame_times=windows, scroll_speed=speed, fast_clear=True,
                                              anchor_reference=True, merge_holds=True, allow_empty_frames=True)
                        self.assertEqual(plan['keys'], keys)
                        self.assertEqual([f['pattern'] for f in plan['frames']], frames)
                        self.assertEqual([(f['start_ms'], f['end_ms']) for f in plan['frames']], windows)
                        self.assertLessEqual(plan['drift_at_768px'], .5)
                        points, _ = decode(encode_osu(plan))
                        for note in plan['notes']:
                            frame = plan['frames'][note['frame']]
                            self.assertGreater(note['time_ms'], frame['sweep_start_ms'])
                            y = 1 - position(points, note['time_ms'], plan['time_range_ms']) + position(points, frame['sweep_start_ms'], plan['time_range_ms'])
                            self.assertAlmostEqual(y, 1 - 1 / 768, delta=2e-5)

    def test_balanced_serialized_geometry_and_future_endpoints(self):
        for irregular in (False, True):
            for merged in (False, True):
                with self.subTest(irregular=irregular, merged=merged):
                    plan, _, _ = sequence(irregular=irregular, merged=merged)
                    text = encode_osu(plan)
                    points, _ = decode(text)
                    objects = [line.split(',') for line in text.split('[HitObjects]\n')[1].splitlines() if line]
                    for fields, note in zip(objects, plan['notes']):
                        frame = plan['frames'][note['frame']]
                        endpoints = [(note['row'], float(fields[2]))]
                        if fields[3] == '128':
                            endpoints.append((note['end_row'], float(fields[5].split(':')[0])))
                        for row, time in endpoints:
                            self.assertGreater(time, frame['sweep_start_ms'])
                            at_sweep = 1 - position(points, time, plan['time_range_ms']) + position(points, frame['sweep_start_ms'], plan['time_range_ms'])
                            self.assertAlmostEqual(at_sweep, (row + 1) / 24 - 1 / 768, delta=2e-5)
                        drift = (position(points, frame['sweep_start_ms'], plan['time_range_ms']) - position(points, frame['start_ms'], plan['time_range_ms'])) * 768
                        self.assertLessEqual(drift, .5001)


if __name__ == '__main__':
    unittest.main()
