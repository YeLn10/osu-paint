"""Regressions for real sweep geometry, hold-note runs and refresh-clock drift."""

from bisect import bisect_right
from contextlib import redirect_stdout
import io
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from osu_paint import Point, Timeline, compile_frames, encode_osu, main, make_preview, write_output
from osu_paint_video import import_video, resolve_video_options


def synthetic_video(count=2400, fps=20, **options):
    """Exercise the importer without spending two minutes encoding a fixture."""
    def decode(arguments, cancel):
        pixels = bytearray()
        for index in range(count):
            pixels.extend(bytes((255, 0) if index % 2 == 0 else (0, 255)) * 3)
        Path(arguments[-1]).write_bytes(pixels)
        return ""

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "synthetic.mp4"
        source.touch()
        with patch("osu_paint_video.run_ffmpeg", side_effect=decode):
            return import_video(source, fps=fps, width=2, height=3, **options)


class HoldNoteTests(unittest.TestCase):
    def test_only_adjacent_rows_in_the_same_column_are_merged(self):
        rows = ["##.", "#..", "##.", ".#.", "##."]
        client = "lazer"
        with self.subTest(client=client):
            plain = compile_frames([rows], 2000, 2400, fast_clear=True)
            plan = compile_frames([rows], 2000, 2400, fast_clear=True, merge_holds=True)
            self.assertEqual(len(plain["notes"]), 8)
            self.assertEqual(len(plan["notes"]), 4)
            holds = [note for note in plan["notes"] if "end_time_ms" in note]
            self.assertEqual(len(holds), 2)
            covered = {(note["column"], row) for note in plan["notes"]
                       for row in range(note.get("end_row", note["row"]), note["row"] + 1)}
            self.assertEqual(covered, {(n["column"], n["row"]) for n in plain["notes"]})
            for hold in holds:
                self.assertGreater(hold["end_time_ms"], hold["time_ms"])
                self.assertLess(hold["end_y"], hold["y"])
            objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
            self.assertEqual(sum(line.split(",")[3] == "128" for line in objects), 2)
            for line in objects:
                fields = line.split(",")
                if fields[3] == "128":
                    self.assertGreater(float(fields[5].split(":")[0]), float(fields[2]))


    def test_holds_never_cross_frames_or_blank_rows(self):
        rows = ["#", "#", ".", "#", "#"]
        plan = compile_frames([rows, ["#", ".", "#", "#", "#"]], 2000, 2400,
                              fast_clear=True, merge_holds=True)
        self.assertEqual(len(plan["notes"]), 4)
        for note in plan["notes"]:
            frame = plan["frames"][note["frame"]]
            self.assertLessEqual(note.get("end_time_ms", note["time_ms"]), frame["exit_end_ms"])
            self.assertTrue(all(frame["pattern"][row][note["column"]] == "#"
                                for row in range(note.get("end_row", note["row"]), note["row"] + 1)))

    def test_lazer_repeated_pictures_do_not_sweep_between_identical_frames(self):
        rows = ["#.", ".#", "#."]
        plan = compile_frames([rows] * 20, 2000, 3000, fast_clear=True, anchor_reference=True)
        self.assertEqual(len(plan["frames"]), 20)
        self.assertEqual(len(plan["notes"]), 3)
        self.assertTrue(all(frame["note_frame"] == 0 for frame in plan["frames"]))
        self.assertFalse(any(2000 <= p["time"] < 3000 and p["sv"] > 1 for p in plan["points"]))


class RefreshClockTests(unittest.TestCase):
    def test_automatic_schedule_covers_60_120_165_hz_and_fractional_start_times(self):
        for hz in (60, 120, 165):
            for start in (2000, 2000.6, 1730.42):
                with self.subTest(hz=hz, start=start):
                    plan = synthetic_video(count=12, refresh_hz=hz, start_ms=start)["plan"]
                    frames = plan["frames"]
                    self.assertEqual(plan["start_ms"], start)
                    divisor = round(hz / plan["video"]["fps"])
                    for tick in range(12 * divisor):
                        now = start + tick * 1000 / hz
                        frame = frames[tick // divisor]
                        self.assertLessEqual(frame["start_ms"], now + 1e-7)
                        self.assertGreaterEqual(frame["end_ms"], now - 1e-7)
                    for before, after in zip(frames, frames[1:]):
                        middle = (before["end_ms"] + after["start_ms"]) / 2
                        refresh_index = math.floor((middle - start) / (1000 / hz))
                        self.assertGreater(before["end_ms"], start + refresh_index * 1000 / hz)
                        self.assertLess(after["start_ms"], start + (refresh_index + 1) * 1000 / hz)
                        self.assertAlmostEqual(after["start_ms"] - before["end_ms"], plan["transition_ms"])

    def test_refresh_phase_motion_preserves_even_picture_cadence(self):
        for hz in (60, 120, 165, 60000 / 1001):
            for fps in (10, 20, 30, 60):
                with self.subTest(hz=hz, fps=fps):
                    plan = synthetic_video(count=241, fps=fps, refresh_hz=hz, start_ms=2000.6)["plan"]
                    starts = [frame["start_ms"] for frame in plan["frames"]]
                    period = 1000 / hz
                    divisor = round(hz / plan["video"]["fps"])
                    expected = divisor * period
                    # The first picture remains anchored to the audio start. From
                    # the second picture on, offsets must move without wrap jumps.
                    intervals = [b - a for a, b in zip(starts[1:], starts[2:])]
                    self.assertLess(max(abs(gap - expected) for gap in intervals), .3)
                    self.assertLess(abs(starts[1] - starts[0] - expected), 1)
                    self.assertEqual(starts[0], 2000.6)
                    self.assertAlmostEqual(plan["end_ms"], 2000.6 + len(starts) * expected)
                    for phase in range(200):
                        ticks = [math.ceil((s - starts[0]) / period - phase / 200 - 1e-9)
                                 for s in starts[1:]]
                        held = [b - a for a, b in zip(ticks, ticks[1:])]
                        self.assertTrue(all(divisor - 1 <= n <= divisor + 1 for n in held))
                        self.assertLessEqual(sum(n != divisor for n in held), 6, (hz, fps, phase))

    def test_unknown_refresh_phase_does_not_catch_every_video_transition(self):
        # Constant black area, alternating columns: any sweep is an unwanted exposure.
        for hz in (60, 120, 165, 60000 / 1001):
            with self.subTest(hz=hz):
                plan = synthetic_video(count=241, refresh_hz=hz)["plan"]
                period = 1000 / hz
                divisor = round(hz / plan["video"]["fps"])
                worst = longest = 0
                for phase in range(200):
                    caught = run = 0
                    for index in range(1, len(plan["frames"])):
                        now = plan["start_ms"] + (index * divisor - 1 + phase / 200) * period
                        before, after = plan["frames"][index - 1:index + 1]
                        hit = before["sweep_start_ms"] < now < after["start_ms"]
                        caught += hit
                        run = run + 1 if hit else 0
                        longest = max(longest, run)
                    worst = max(worst, caught)
                self.assertLessEqual(worst / 240, .25, (hz, worst))
                self.assertLessEqual(longest, 2, (hz, longest))

    def test_fast_sweeps_reduce_exposure_instead_of_only_redistributing_it(self):
        for hz in (60, 120, 165, 60000 / 1001):
            with self.subTest(hz=hz):
                plan = synthetic_video(count=241, refresh_hz=hz)["plan"]
                period = 1000 / hz
                counts = []
                for phase in range(200):
                    caught = 0
                    for before, after in zip(plan["frames"], plan["frames"][1:]):
                        low = (before["sweep_start_ms"] - plan["start_ms"]) / period - phase / 200
                        high = (after["start_ms"] - plan["start_ms"]) / period - phase / 200
                        caught += math.floor(low + 1e-9) + 1 < high - 1e-9
                    counts.append(caught)
                self.assertLessEqual(max(counts), 5, (hz, max(counts)))
                self.assertLess(sum(counts) / len(counts), 3, hz)
                self.assertLessEqual(plan["drift_at_768px"], .5)

    def test_serialized_constant_area_video_does_not_flash_on_every_cut(self):
        from test_osu_paint import decode, position
        for hz in (60, 120, 165):
            with self.subTest(hz=hz):
                plan = synthetic_video(count=121, refresh_hz=hz)["plan"]
                points, notes = decode(encode_osu(plan))
                heads = [position(points, time, plan["time_range_ms"]) for _, time in notes]
                divisor = round(hz / plan["video"]["fps"])
                flash_samples = 0
                for index in range(1, 121):
                    # The old fixed half-cycle alignment repeatedly exposes a 10% blank band here.
                    now = plan["start_ms"] + (index * divisor - .5) * 1000 / hz
                    current = position(points, now, plan["time_range_ms"])
                    bottoms = [1 - head + current for head in heads]
                    black_area = sum(max(0, min(1, bottom) - max(0, bottom - 1 / 3))
                                     for bottom in bottoms) / 2
                    flash_samples += black_area < .48
                self.assertLessEqual(flash_samples, 30, (hz, flash_samples))

    def test_refresh_alignment_never_increases_requested_frame_rate(self):
        for hz in (60, 120, 165, 144, 60000 / 1001):
            for fps in (20, 24, 30, 50, 60):
                with self.subTest(hz=hz, fps=fps):
                    options = resolve_video_options(fps=fps, width=2, height=3, start_ms=2000,
                                                    scroll_speed=27, refresh_hz=hz)
                    self.assertLessEqual(options["fps"], fps + 1e-9)
                    self.assertAlmostEqual(resolve_video_options(**options)["fps"], options["fps"])

    def test_an_unknown_presentation_phase_can_still_sample_a_real_transition(self):
        # A reproducible counterexample to a zero-ghosting guarantee based only on Hz/start.
        from test_osu_paint import decode, position
        for hz in (60, 120, 165):
            plan = synthetic_video(count=6, refresh_hz=hz)["plan"]
            points, _ = decode(encode_osu(plan))
            before, after = plan["frames"][:2]
            now = (before["sweep_start_ms"] + after["start_ms"]) / 2
            phase = (now - plan["start_ms"]) % (1000 / hz)
            self.assertGreater(phase, 0)
            self.assertLess(phase, 1000 / hz)
            current = position(points, now, plan["time_range_ms"])
            visible_columns = set()
            for note in plan["notes"]:
                bottom = 1 - position(points, note["time_ms"], plan["time_range_ms"]) + current
                if 0 < bottom and bottom - 1 / 3 < 1:
                    visible_columns.add(note["column"])
            self.assertEqual(visible_columns, {0, 1})

    def test_fractional_refresh_preserves_requested_height_on_lazer(self):
        options = resolve_video_options(fps=60, width=10, height=24, start_ms=2000,
                                        scroll_speed=27, refresh_hz=59.94)
        self.assertEqual(options["height"], 24)
        self.assertAlmostEqual(options["fps"], 59.94)

    def test_invalid_refresh_rates_are_rejected(self):
        base = dict(fps=20, width=2, height=3, start_ms=2000, scroll_speed=27)
        for options in (dict(refresh_hz=math.nan), dict(refresh_hz=math.inf), dict(refresh_hz=True),
                        dict(refresh_hz=19), dict(refresh_hz=1001),
                        dict(refresh_hz=100, scroll_speed=1), dict(merge_holds=1)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                resolve_video_options(**(base | options))

    def test_old_integer_clock_has_periodic_transition_samples(self):
        plan = synthetic_video()["plan"]
        starts = [f["start_ms"] for f in plan["frames"]]
        refresh = 60000 / 1001
        bad = []
        for tick in range(1, int(120 * refresh)):
            now = 2000 + tick * 1000 / refresh
            frame = plan["frames"][bisect_right(starts, now) - 1]
            if now > frame["end_ms"] + 1e-7:
                bad.append(now)
        self.assertTrue(bad, "The negative control must expose the unsynchronised sweep")
        self.assertTrue(any(now > 62000 for now in bad))

    def test_two_minutes_of_fractional_refresh_have_no_accumulated_slip(self):
        refresh = 60000 / 1001
        client = "lazer"
        with self.subTest(client=client):
            plan = synthetic_video(refresh_hz=refresh)["plan"]
            starts = [f["start_ms"] for f in plan["frames"]]
            for tick in range(2400 * 3):
                now = 2000 + tick * 1000 / refresh
                index = bisect_right(starts, now + 1e-7) - 1
                self.assertEqual(index, tick // 3)
                self.assertLessEqual(now, plan["frames"][index]["end_ms"] + 1e-7)
            self.assertAlmostEqual(plan["video"]["fps"], refresh / 3)
            self.assertEqual(plan["video"]["refresh_hz"], refresh)

    def test_serialized_geometry_stays_clean_at_aligned_fractional_refreshes(self):
        refresh = 60000 / 1001
        client = "lazer"
        for merged in (False, True):
            with self.subTest(client=client, merge_holds=merged):
                plan = synthetic_video( refresh_hz=refresh, merge_holds=merged)["plan"]
                text = encode_osu(plan)
                timing = text.split("[TimingPoints]\n")[1].split("\n\n")[0].splitlines()
                points = []
                beat, sv = 500, 1
                for line in timing:
                    fields = line.split(",")
                    time, value = map(float, fields[:2])
                    if fields[6] == "1":
                        beat, sv = min(60000, max(6, value)), 1
                    else:
                        sv = min(10, max(0.01, -100 / value))
                    if points and points[-1][0] == time:
                        points.pop()
                    points.append((time, float(timing[0].split(",")[1]) / beat * sv / plan["time_range_ms"]))
                times = [p[0] for p in points]
                distances = [0.0]
                for i in range(1, len(points)):
                    delta = (times[i] - times[i - 1]) * points[i - 1][1]
                    if client == "lazer":
                        delta = struct.unpack("f", struct.pack("f", delta))[0]
                    distances.append(distances[-1] + delta)

                def position(time):
                    i = max(0, bisect_right(times, time) - 1)
                    return distances[i] + (time - times[i]) * points[i][1]

                model = Timeline([Point(**p) for p in plan["points"]], plan["base_beat_length_ms"])
                objects = [line.split(",") for line in text.split("[HitObjects]\n")[1].splitlines()]
                heads = [position(float(n[2])) for n in objects]
                tails = [position(float(n[5].split(":")[0])) if n[3] == "128" else head
                         for n, head in zip(objects, heads)]
                span = max(tail - head for head, tail in zip(heads, tails))
                for tick in range(2400 * 3):
                    now = 2000 + tick * 1000 / refresh
                    current = position(now)
                    first = bisect_right(heads, current - span)
                    last = bisect_right(heads, current + 1)
                    visible = [i for i in range(first, last)
                               if heads[i] <= current + 1 and tails[i] >= current]
                    self.assertEqual(len(visible), 1 if merged else 3, (client, tick))
                    self.assertEqual({int(int(objects[i][0]) * 2 / 512) for i in visible}, {tick // 3 % 2})
                    frame = plan["frames"][tick // 3]
                    inset = 1 / 768 + (model.position(frame["sweep_start_ms"]) - model.position(now)) / plan["time_range_ms"]
                    expected = [1 - inset] if merged else [1 / 3 - inset, 2 / 3 - inset, 1 - inset]
                    for y, wanted in zip(sorted(1 - (heads[i] - current) for i in visible), expected):
                        self.assertAlmostEqual(y, wanted, delta=1e-4)
                    if merged:
                        self.assertAlmostEqual(1 - (tails[visible[0]] - current), 1 / 3 - inset, delta=1e-4)

    def test_automatic_alignment_keeps_the_first_picture_and_audio_at_the_requested_start(self):
        result = synthetic_video(count=6, refresh_hz=60)
        self.assertEqual(result["plan"]["start_ms"], 2000)
        self.assertEqual(result["video"]["start_ms"], 2000)
        self.assertNotIn("refresh_phase_ms", result["video"])


class RefreshExportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable; HTML geometry check skipped")
    def test_html_preview_draws_hold_body_until_its_tail_leaves(self):
        plan = compile_frames([["#"] * 4], 2000, 2100, fast_clear=True, merge_holds=True)
        timeline = Timeline([Point(**p) for p in plan["points"]], plan["base_beat_length_ms"])
        target = timeline.position(plan["notes"][0]["time_ms"]) + 0.3 * plan["time_range_ms"]
        samples = [plan["start_ms"], timeline.time_at(target), plan["end_ms"] + plan["transition_ms"] + 1]
        script = make_preview(plan).split("<script>")[1].split("</script>")[0]
        harness = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),rects=[];
const ctx={clearRect(){rects.length=0;},beginPath(){},moveTo(){},lineTo(){},stroke(){},
fillRect(x,y,w,h){if(this.fillStyle==='black')rects.push([x,y,w,h]);}};
const elements={view:{width:360,height:768,getContext:()=>ctx},seek:{},time:{},info:{},pattern:{},play:{}};
const sandbox=vm.createContext({document:{getElementById:id=>elements[id]},requestAnimationFrame(){},performance:{now:()=>0}});
vm.runInContext(SCRIPT,sandbox);
for(let i=0;i<SAMPLES.length;i++){
    elements.seek.value=SAMPLES[i];vm.runInContext('draw()',sandbox);
    assert.equal(rects.length,i===2?0:1);
    if(i<2){assert.ok(rects[0][3]>20);assert.ok(rects[0][1]+rects[0][3]<=768);}
}
""".replace("SCRIPT", json.dumps(script)).replace("SAMPLES", json.dumps(samples))
        result = subprocess.run([shutil.which("node"), "-"], input=harness, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_playback_settings_are_short_and_do_not_expose_phase_or_conversion_details(self):
        client = "lazer"
        with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
            plan = synthetic_video(count=6, refresh_hz=60000 / 1001, merge_holds=True)["plan"]
            output = Path(directory)
            write_output(plan, output)
            settings = (output / "播放设置.txt").read_text(encoding="utf-8")
            self.assertIn(client, settings)
            self.assertIn("59.94005994", settings)
            self.assertNotIn("相位", settings)
            self.assertNotIn("FPS", settings)
            self.assertIn("音轨不移动", settings)
            self.assertIn("自动安排", settings)
            self.assertNotIn("CustomFrameLimit", settings)
            plain = compile_frames([["#"]], 2000, 2100, fast_clear=True)
            write_output(plain, output)
            self.assertFalse((output / "播放设置.txt").exists())

    def test_cli_text_hold_switch_and_default_single_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pattern.txt"
            source.write_text("#\n#\n#\n#\n", encoding="utf-8")
            for flags in ([], ["--merge-holds"]):
                output = Path(directory) / ("holds" if flags else "singles")
                args = ["osu_paint.py", str(source), "--start-ms", "2000",
                        "--end-ms", "2100", "--fast-clear", "--output", str(output), *flags]
                with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
                    main()
                report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["merge_holds"], bool(flags))
                self.assertEqual(len(report["notes"]), 1 if flags else 4)
                objects = (output / "pattern.osu").read_text(encoding="utf-8").split("[HitObjects]\n")[1].splitlines()
                self.assertTrue(all(line.split(",")[3] == ("128" if flags else "1") for line in objects))

    def test_cli_accepts_fractional_refresh_and_automatically_aligns_with_holds(self):
        with tempfile.TemporaryDirectory() as directory:
            result = synthetic_video(count=6, refresh_hz=60000 / 1001, merge_holds=True)
            args = ["osu_paint.py", "local.mp4", "--video", "--start-ms", "2000",
                    "--refresh-hz", "60000/1001", "--merge-holds",
                    "--output", directory]
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()), \
                    patch("osu_paint_video.import_video", return_value=result) as importer:
                main()
            self.assertAlmostEqual(importer.call_args.kwargs["refresh_hz"], 60000 / 1001)
            self.assertNotIn("refresh_phase_ms", importer.call_args.kwargs)
            self.assertTrue(importer.call_args.kwargs["merge_holds"])
            self.assertTrue((Path(directory) / "pattern.osz").is_file())


if __name__ == "__main__":
    unittest.main()
