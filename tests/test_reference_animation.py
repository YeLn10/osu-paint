"""Reference film regressions against emitted notes, skin and real Tk drawing."""

from bisect import bisect_right
import json
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest
import zipfile

from osu_paint import compile_frames, encode_osu, write_output
from osu_paint_desktop import PaintApp
from osu_paint_stable import ReferenceGeometry, reference_sample_time
from osu_paint_video import validate_video_options


def reference_plan(frames):
    return compile_frames(frames, 2000, 2000 + len(frames) * 1000 / 30,
                          target_client="stable", reference_animation=True)


def exported_geometry(plan):
    """Parse .osu independently: stable accepts the unbounded positive red beat."""
    section, points, notes = None, [], []
    for line in encode_osu(plan).splitlines():
        if line.startswith("["):
            section = line
        elif line and section == "[TimingPoints]":
            parts = line.split(",")
            if parts[6] == "1":
                points.append([float(parts[0]), float(parts[1]), 1])
            else:
                points[-1][2] = min(10, max(.01, -100 / float(parts[1])))
        elif line and section == "[HitObjects]":
            parts = line.split(",")
            assert int(parts[3]) == 128
            notes.append((int(float(parts[0]) * plan["keys"] / 512),
                          int(parts[2]), int(parts[5].split(":")[0])))
    times = [p[0] for p in points]
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1] + (b[0] - a[0]) * 500 / a[1] * a[2])

    def position(t):
        i = max(0, bisect_right(times, t) - 1)
        return distances[i] + (t - times[i]) * 500 / points[i][1] * points[i][2]

    intervals = [(c, position(s), position(e)) for c, s, e in notes]

    def pixels(t):
        current, distance = position(t), plan["time_range_ms"]
        rows = []
        for row in range(len(plan["pattern"])):
            pixel_distance = current + (1 - (row + .5) / len(plan["pattern"])) * distance
            rows.append("".join("." if any(c == col and s <= pixel_distance < e
                                           for c, s, e in intervals) else "#"
                                for col in range(plan["keys"])))
        return rows

    return pixels, notes


class ReferenceTests(unittest.TestCase):
    def test_emitted_long_notes_reproduce_pixels_at_every_refresh(self):
        frames = [["." * 16] * 12, ["#" * 16] * 12,
                  [".#" * 8, "#." * 8] * 6] * 3
        plan = reference_plan(frames)
        pixels, notes = exported_geometry(plan)
        self.assertTrue(all(e > s for _, s, e in notes))
        for frame, expected in zip(plan["frames"], frames):
            for t in (frame["start_ms"], frame["end_ms"] - .01):
                self.assertEqual(pixels(t), expected)

    def test_consecutive_black_cells_merge_and_old_heads_stay_visible(self):
        plan = reference_plan([["." * 16] * 12] * 90)
        self.assertEqual(len(plan["notes"]), 16)
        geometry = ReferenceGeometry(plan)
        rectangles = list(geometry.rectangles(plan["frames"][-1]["start_ms"]))
        self.assertEqual(len(rectangles), 16)
        self.assertTrue(all(y1 - y0 > .999 for _, y0, y1 in rectangles))

    def test_unsynchronized_sweep_remains_visible_and_phase_matters(self):
        frames = [["." * 16] * 12, ["#" * 16] * 12] * 6
        plan = reference_plan(frames)
        pixels, _ = exported_geometry(plan)
        midpoint = plan["frames"][0]["end_ms"] + 6
        self.assertNotIn(pixels(midpoint), frames)
        for i, expected in enumerate(frames):
            t = 2000 + i * 1000 / 30
            self.assertEqual(pixels(reference_sample_time(plan, t)), expected)
        self.assertNotIn(pixels(2000 + 27), frames)

    def test_reference_video_validation_does_not_use_old_thin_bar_limits(self):
        options = dict(fps=30, width=16, height=12, start_ms=2000, scroll_speed=27,
                       target_client="stable", reference_animation=True)
        self.assertEqual(validate_video_options(**options), 12)
        for field, value in (("fps", 10), ("width", 11), ("height", 32), ("target_client", "lazer")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_video_options(**dict(options, **{field: value}))

    def test_export_includes_separate_skin_with_solid_bodies(self):
        plan = reference_plan([["." * 16] * 12, ["#" * 16] * 12])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_output(plan, output)
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertNotIn("skin.ini", archive.namelist())
            with zipfile.ZipFile(output / "pixel-film.osk") as archive:
                settings = archive.read("skin.ini").decode()
                for setting in ("Keys: 16", "SplitStages: 0", "HitPosition: 480", "Colour1: 255,255,255,255",
                                "NoteImage15L: pixel-black", "NoteBodyStyle15: 0"):
                    self.assertIn(setting, settings)
                self.assertEqual(struct.unpack(">II", archive.read("pixel-black.png")[16:24]), (40, 1))
            self.assertTrue(json.loads((output / "report.json").read_text(encoding="utf-8"))["reference_animation"])
            page = (output / "preview.html").read_text(encoding="utf-8")
            self.assertIn("playing&&", page)
            self.assertIn("seek.oninput=()=>{playing=false", page)

    def test_tk_preview_fills_column_with_real_ln_body(self):
        window = tk.Tk()
        window.withdraw()
        app = PaintApp(window)
        try:
            window.deiconify()
            window.update()
            app.frames = [["." * 16] * 12, ["#" * 16] * 12]
            plan = reference_plan(app.frames)
            app._refresh_preview(compiled_plan=plan)
            app.seek_time.set(2000)
            app._draw_preview()
            background = app.preview.coords(app.preview.find_withtag("film")[0])
            stage_height = background[3] - background[1]
            rectangles = [app.preview.coords(n) for n in app.preview.find_withtag("note")]
            self.assertEqual(len(rectangles), 16)
            coverage = sum(n[3] - n[1] for n in rectangles) / 16 / stage_height
            self.assertGreater(coverage, .999)
            app.seek_time.set(2033)
            app._draw_preview()
            self.assertEqual(len(app.preview.find_withtag("note")), 0)
        finally:
            for job in window.tk.call("after", "info"):
                window.after_cancel(job)
            window.destroy()


if __name__ == "__main__":
    unittest.main()
