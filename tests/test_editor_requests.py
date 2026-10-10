"""Regressions for hand-drawn blank frames and free timing constraints."""

import tkinter as tk
import unittest
from unittest.mock import patch

from osu_paint import compile_frames, encode_osu
from osu_paint_desktop import PaintApp
from test_osu_paint import decode as lazer_decode, position as lazer_position
from test_stable_geometry import decode as stable_decode, position as stable_position
from test_desktop_video import video_result


class EditorRequestTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.close)

    def close(self):
        self.root.update_idletasks()
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()

    def test_drawn_blank_frame_previews_and_text_round_trips(self):
        self.app.add_frame()
        self.app._refresh_preview()
        self.assertIsNotNone(self.app.plan, self.app.status.get())
        self.assertFalse(any(n["frame"] == 1 for n in self.app.plan["notes"]))
        text = self.app._text()
        self.app.load_text(text, keep_video=False)
        self.assertEqual(self.app._text(), text)

    def test_video_import_owns_its_scroll_speed(self):
        with patch("osu_paint_desktop.filedialog.askopenfilename", return_value="synthetic.mp4"):
            self.app.import_video()
        self.assertIn("scroll_speed", self.app.video_fields)
        self.app.video_fields["scroll_speed"].set("15")
        self.app.video_cancel_button.invoke()
        self.assertEqual(self.app.fields["scroll_speed"].get(), "27")

    def test_free_mode_ignores_manual_transition_and_checks_actual_gap(self):
        self.app.load_text("#\n#\n---\n.\n#")
        self.app.timing_mode.set("自由模式")
        self.app.frame_times = [["2000", "2050"], ["2050.2", "2100"]]
        self.app.fast_clear.set(False)
        self.app.fields["transition_ms"].set("100")
        self.app._refresh_preview()
        self.assertIsNotNone(self.app.plan, self.app.status.get())
        self.assertTrue(self.app.plan["fast_clear"])
        self.assertEqual(str(self.app.entries["transition_ms"]["state"]), "disabled")

    def test_lower_video_scroll_speed_uses_actual_clearance_without_moving_audio(self):
        result = video_result()
        self.app._apply_video(result)
        windows = [window.copy() for window in self.app.frame_times]
        self.app.fields["scroll_speed"].set("15")
        self.app._refresh_preview()
        self.assertIsNotNone(self.app.plan, self.app.status.get())
        self.assertEqual(self.app.plan["scroll_speed"], 15)
        self.assertEqual(self.app.frame_times, windows)
        self.assertEqual(self.app.audio_data, result["audio"])


class ActualGapTests(unittest.TestCase):
    def test_optimized_sweep_fits_a_gap_smaller_than_reservation(self):
        for client, gap, decode, position in (
                ("lazer", .2, lazer_decode, lazer_position),
                ("stable", 3, stable_decode, stable_position)):
            with self.subTest(client=client):
                windows = [(2000, 2050), (2050 + gap, 2100)]
                plan = compile_frames([["#."] * 24, [".#"] * 24], frame_times=windows,
                                      fast_clear=True, merge_holds=True, target_client=client)
                self.assertLess(gap, plan["transition_ms"])
                self.assertGreaterEqual(plan["frames"][0]["sweep_start_ms"], 2050 - 1e-7)
                self.assertEqual([(f["start_ms"], f["end_ms"]) for f in plan["frames"]], windows)
                points, notes = decode(encode_osu(plan))
                for frame in plan["frames"]:
                    for note in (n for n in plan["notes"] if n["frame"] == frame["note_frame"]):
                        y = 1 - (position(points, note["time_ms"], plan["time_range_ms"]) -
                                 position(points, frame["end_ms"], plan["time_range_ms"]))
                        self.assertLess(y, 1)
                        self.assertGreater(note["time_ms"], frame["end_ms"])

    def test_too_small_actual_gap_is_rejected(self):
        for client, gap in (("lazer", .001), ("stable", 2)):
            with self.subTest(client=client), self.assertRaisesRegex(ValueError, "间隔不足"):
                compile_frames([["#."] * 24, [".#"] * 24],
                               frame_times=[(2000, 2050), (2050 + gap, 2100)],
                               fast_clear=True, merge_holds=True, target_client=client)
