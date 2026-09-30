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


def synthetic_video(count=2400, **options):
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
        with patch("osu_paint_video._run_ffmpeg", side_effect=decode):
            return import_video(source, fps=20, width=2, height=3, **options)


class HoldNoteTests(unittest.TestCase):
    def test_only_adjacent_rows_in_the_same_column_are_merged(self):
        rows = ["##.", "#..", "##.", ".#.", "##."]
        for client in ("stable", "lazer"):
            with self.subTest(client=client):
                plain = compile_frames([rows], 2000, 2400, fast_clear=True, target_client=client)
                plan = compile_frames([rows], 2000, 2400, fast_clear=True,
                                      target_client=client, merge_holds=True)
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
                    if client == "stable":
                        self.assertEqual(hold["end_time_ms"], round(hold["end_time_ms"]))
                objects = encode_osu(plan).split("[HitObjects]\n")[1].strip().splitlines()
                self.assertEqual(sum(line.split(",")[3] == "128" for line in objects), 2)
                for line in objects:
                    fields = line.split(",")
                    if fields[3] == "128":
                        self.assertGreater(float(fields[5].split(":")[0]), float(fields[2]))

    def test_stable_hold_endpoints_shorten_the_visible_sweep(self):
        frames = [["#."] * 24, [".#"] * 24]
        plan = compile_frames(frames, frame_times=[(2000, 2075), (2100, 2175)],
                              fast_clear=True, target_client="stable", merge_holds=True)
        self.assertEqual(len(plan["notes"]), 2)
        self.assertEqual(plan["frames"][0]["sweep_start_ms"], 2097)
        timeline = Timeline([Point(**p) for p in plan["points"]])
        hold = plan["notes"][0]
        for now in (2000, 2075, 2083, 2096):
            for key, y in (("time_ms", hold["y"]), ("end_time_ms", hold["end_y"])):
                actual = 1 - (timeline.position(hold[key]) - timeline.position(now)) / plan["time_range_ms"]
                self.assertAlmostEqual(actual, y, delta=1e-6)
        self.assertLessEqual(plan["frames"][0]["exit_end_ms"] - plan["frames"][0]["sweep_start_ms"], 3)

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
    def test_fractional_refresh_is_available_to_both_clients(self):
        for client, height in (("stable", 13), ("lazer", 24)):
            options = resolve_video_options(fps=60, width=10, height=24, start_ms=2000,
                                            scroll_speed=27, target_client=client, refresh_hz=59.94)
            self.assertEqual(options["height"], height)
            self.assertAlmostEqual(options["fps"], 59.94)
        with self.assertRaises(ValueError):
            resolve_video_options(fps=10, width=10, height=24, start_ms=2000, scroll_speed=27,
                                  target_client="stable", game_fps=60, refresh_hz=59.94)

    def test_invalid_refresh_rates_and_phase_offsets_are_rejected(self):
        base = dict(fps=20, width=2, height=3, start_ms=2000, scroll_speed=27)
        for options in (dict(refresh_hz=math.nan), dict(refresh_hz=math.inf), dict(refresh_hz=True),
                        dict(refresh_hz=19), dict(refresh_hz=1001), dict(refresh_phase_ms=1),
                        dict(refresh_hz=60, refresh_phase_ms=17), dict(refresh_hz=60, refresh_phase_ms=math.nan),
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
        for client in ("stable", "lazer"):
            with self.subTest(client=client):
                plan = synthetic_video(refresh_hz=refresh, target_client=client)["plan"]
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
        for client in ("stable", "lazer"):
            for merged in (False, True):
                with self.subTest(client=client, merge_holds=merged):
                    plan = synthetic_video(target_client=client, refresh_hz=refresh, merge_holds=merged)["plan"]
                    text = encode_osu(plan)
                    timing = text.split("[TimingPoints]\n")[1].split("\n\n")[0].splitlines()
                    points = []
                    beat, sv = 500, 1
                    for line in timing:
                        fields = line.split(",")
                        time, value = map(float, fields[:2])
                        if fields[6] == "1":
                            beat, sv = (value if client == "stable" else min(60000, max(6, value))), 1
                        else:
                            sv = min(10, max(0.01, -100 / value))
                        if points and points[-1][0] == time:
                            points.pop()
                        points.append((time, 500 / beat * sv / plan["time_range_ms"]))
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
                        expected = [5 / 6] if merged else [1 / 6, .5, 5 / 6]
                        for y, wanted in zip(sorted(1 - (heads[i] - current) for i in visible), expected):
                            self.assertAlmostEqual(y, wanted, delta=1e-4)
                        if merged:
                            self.assertAlmostEqual(1 - (tails[visible[0]] - current), 1 / 6, delta=1e-4)

    def test_refresh_phase_moves_pictures_not_the_audio_offset(self):
        result = synthetic_video(count=6, refresh_hz=60, refresh_phase_ms=5)
        self.assertEqual(result["plan"]["start_ms"], 2005)
        self.assertEqual(result["video"]["start_ms"], 2000)
        self.assertEqual(result["video"]["refresh_phase_ms"], 5)


class RefreshExportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable; HTML geometry check skipped")
    def test_html_preview_draws_hold_body_until_its_tail_leaves(self):
        plan = compile_frames([["#"] * 4], 2000, 2100, fast_clear=True, merge_holds=True)
        timeline = Timeline([Point(**p) for p in plan["points"]])
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

    def test_refresh_settings_export_actual_rate_phase_and_hold_choice(self):
        for client in ("stable", "lazer"):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                plan = synthetic_video(count=6, target_client=client, refresh_hz=60000 / 1001,
                                       refresh_phase_ms=5, merge_holds=True)["plan"]
                output = Path(directory)
                write_output(plan, output)
                settings = (output / "播放设置.txt").read_text(encoding="utf-8")
                self.assertIn(client, settings)
                self.assertIn("59.94005994", settings)
                self.assertIn("相位", settings)
                self.assertIn("5 ms", settings)
                self.assertIn("音轨不移动", settings)
                self.assertIn("长条", settings)
                self.assertIn("不能保证零残影", settings)
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
                args = ["osu_paint.py", str(source), "--target-client", "stable", "--start-ms", "2000",
                        "--end-ms", "2100", "--fast-clear", "--output", str(output), *flags]
                with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
                    main()
                report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["merge_holds"], bool(flags))
                self.assertEqual(len(report["notes"]), 1 if flags else 4)
                objects = (output / "pattern.osu").read_text(encoding="utf-8").split("[HitObjects]\n")[1].splitlines()
                self.assertTrue(all(line.split(",")[3] == ("128" if flags else "1") for line in objects))

    def test_cli_accepts_fractional_refresh_and_passes_phase_and_hold_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = synthetic_video(count=6, refresh_hz=60000 / 1001, refresh_phase_ms=-2, merge_holds=True)
            args = ["osu_paint.py", "local.mp4", "--video", "--start-ms", "2000",
                    "--refresh-hz", "60000/1001", "--refresh-phase-ms", "-2", "--merge-holds",
                    "--output", directory]
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()), \
                    patch("osu_paint_video.import_video", return_value=result) as importer:
                main()
            self.assertAlmostEqual(importer.call_args.kwargs["refresh_hz"], 60000 / 1001)
            self.assertEqual(importer.call_args.kwargs["refresh_phase_ms"], -2)
            self.assertTrue(importer.call_args.kwargs["merge_holds"])
            self.assertTrue((Path(directory) / "pattern.osz").is_file())


if __name__ == "__main__":
    unittest.main()
