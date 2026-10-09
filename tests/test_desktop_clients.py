"""Client selection must survive project and background-operation boundaries."""

import copy
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from osu_paint import compile_frames
from osu_paint_desktop import PaintApp


class DesktopClientTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.destroy_window)

    def destroy_window(self):
        self.root.update_idletasks()
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()

    def test_both_projects_round_trip_and_unmarked_project_defaults_to_lazer(self):
        for client in ("stable", "lazer"):
            self.app.target_client.set(client)
            self.app._refresh_preview()
            saved = copy.deepcopy(self.app._project_data())
            self.assertEqual(saved["target_client"], client)
            self.app.target_client.set("lazer" if client == "stable" else "stable")
            self.app.load_project(saved)
            self.app._refresh_preview()
            self.assertEqual(self.app.plan["target_client"], client)
        saved.pop("target_client")
        self.app.target_client.set("stable")
        self.app.load_project(saved)
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["target_client"], "lazer")

    def test_switching_client_preserves_video_and_audio_but_invalidates_alignment(self):
        self.app.video = dict(filename="synthetic.mp4", fps=10, width=7, height=6,
                              start_ms=2000, duration_ms=2000, refresh_hz=60,
                              requested_fps=10, requested_height=6)
        self.app.audio_data = b"OggS synthetic"
        frames, windows = copy.deepcopy((self.app.frames, self.app.frame_times))
        self.app.target_client.set("stable")
        self.app._refresh_preview()
        self.assertEqual((self.app.frames, self.app.frame_times), (frames, windows))
        self.assertEqual(self.app.audio_data, b"OggS synthetic")
        self.assertNotIn("refresh_hz", self.app.video)
        self.assertEqual(self.app.plan["target_client"], "stable")

    def test_unknown_project_client_fails_without_replacing_project(self):
        before = self.app._project_data()
        invalid = dict(before, target_client="unknown")
        with self.assertRaises(ValueError):
            self.app.load_project(invalid)
        self.assertEqual(self.app._project_data(), before)

    def test_stable_preview_masks_the_bottom_and_clears_the_outgoing_column(self):
        self.root.deiconify()
        self.root.update()
        plan = compile_frames([["##"] * 12, ["#."] * 12],
                              frame_times=[(2000, 2040), (2053, 2200)],
                              fast_clear=True, merge_holds=True, target_client="stable")
        self.app._refresh_preview(compiled_plan=plan)
        height = min(self.app.preview.winfo_height() - 34 * self.app.scale,
                     (self.app.preview.winfo_width() - 24 * self.app.scale) / 1.6)
        top = 10 * self.app.scale
        left = (self.app.preview.winfo_width() - height * 1.6) / 2
        bottom = top + height * 479 / 480
        for now in (2000, 2051.5, 2053, 2100):
            self.app.seek_time.set(now)
            self.app._draw_preview()
            cells = [self.app.preview.coords(item) for item in self.app.preview.find_withtag("note")]
            self.assertTrue(cells)
            for x1, y1, x2, y2 in cells:
                self.assertLess(y1, y2)
                self.assertLessEqual(y2, bottom + 1e-8)
                if now >= 2053:
                    self.assertAlmostEqual(x1, left)
            self.assertAlmostEqual(max(cell[3] for cell in cells), bottom)

    def test_export_keeps_clicked_client_while_editor_switches(self):
        entered, release = threading.Event(), threading.Event()
        captured = []
        def export(plan, output, **kwargs):
            captured.append(plan)
            entered.set()
            release.wait(3)
        with tempfile.TemporaryDirectory() as directory, patch("osu_paint_desktop.write_output", side_effect=export):
            self.app.target_client.set("stable")
            self.app.output_dir.set(directory)
            self.app.export()
            self.assertTrue(entered.wait(2))
            self.app.target_client.set("lazer")
            self.app._refresh_preview()
            release.set()
            deadline = time.monotonic() + 4
            while self.app.exporting and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertFalse(self.app.exporting)
        self.assertEqual(captured[0]["target_client"], "stable")
        self.assertEqual(self.app.plan["target_client"], "lazer")

    def open_video_dialog(self):
        with patch("osu_paint_desktop.filedialog.askopenfilename", return_value="synthetic.mp4"), \
                patch("osu_paint_desktop.messagebox.askyesno", return_value=True):
            self.app.import_video()
        self.root.update_idletasks()

    def wait_for_import(self):
        deadline = time.monotonic() + 5
        while self.app.importing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.importing)

    def test_import_client_is_local_until_success_and_reaches_preview_and_import(self):
        before = copy.deepcopy(self.app._project_data())
        self.open_video_dialog()
        self.assertEqual(tuple(self.app.video_client_choice["values"]), ("lazer", "stable"))
        self.app.video_target_client.set("stable")
        self.assertEqual(self.app.video_fields["height"].get(), "12")
        self.assertEqual(self.app._project_data(), before)
        preview = dict(frame=["#."], source_ppm=b"P6\n1 1\n255\n\xff\xff\xff", frame_index=0, time_ms=0)
        with patch("osu_paint_desktop.preview_video_frame", return_value=preview) as reader:
            self.app.video_preview_button.invoke()
            self.wait_for_import()
        self.assertEqual(reader.call_args.kwargs["target_client"], "stable")
        self.assertEqual(self.app._project_data(), before)
        self.assertEqual(str(self.app.video_client_choice["state"]), "readonly")
        plan = compile_frames([["#."] * 12, [".#"] * 12], frame_times=[(2000, 2087), (2100, 2187)],
                              fast_clear=True, merge_holds=True, target_client="stable")
        video = dict(filename="synthetic.mp4", fps=10, width=2, height=12, start_ms=2000, duration_ms=200)
        result = dict(plan=plan, video=video, audio=b"OggS synthetic")
        with patch("osu_paint_desktop.read_video", return_value=result) as reader:
            self.app.video_start_button.invoke()
            self.wait_for_import()
        self.assertEqual(reader.call_args.kwargs["target_client"], "stable")
        self.assertEqual(self.app.plan["target_client"], "stable")
        self.assertEqual(self.app._project_data()["target_client"], "stable")
        self.assertEqual(self.app.client_choice.winfo_manager(), "")
        self.assertEqual(self.app.client_display.winfo_manager(), "pack")

    def test_import_client_switch_preserves_custom_rows_and_cancelled_project(self):
        before = copy.deepcopy(self.app._project_data())
        self.open_video_dialog()
        self.app.video_fields["height"].set("7")
        self.app.video_target_client.set("stable")
        self.assertEqual(self.app.video_fields["height"].get(), "7")
        self.app.video_target_client.set("lazer")
        self.assertEqual(self.app.video_fields["height"].get(), "7")
        self.app.video_cancel_button.invoke()
        self.assertIsNone(self.app.import_dialog)
        self.assertEqual(self.app._project_data(), before)

    def test_automatic_transition_field_shows_actual_result_without_losing_manual_value(self):
        self.app.fields["transition_ms"].set("12")
        self.app._refresh_preview()
        self.assertEqual(self.app.entries["transition_ms"].get(), f"{self.app.plan['sweep_ms']:.3f}")
        self.assertEqual(self.app.fields["transition_ms"].get(), "12")
        self.app.fast_clear.set(False)
        self.app._timing_options_changed()
        self.app._refresh_preview()
        self.assertEqual(self.app.entries["transition_ms"].get(), "12")
        self.assertEqual(str(self.app.entries["transition_ms"]["state"]), "normal")
        self.app.fast_clear.set(True)
        self.app._timing_options_changed()
        self.app._refresh_preview()
        self.assertEqual(self.app.entries["transition_ms"].get(), f"{self.app.plan['sweep_ms']:.3f}")

    def test_free_mode_entry_edits_change_real_sweep_and_keep_frame_times(self):
        project = self.app._project_data()
        project.update(frames=[["#."] * 3, [".#"] * 3], frame_times=[["2000", "2200"], ["2220", "2400"]],
                       timing_mode="自由模式", fast_clear=False)
        self.app.load_project(project)
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["frames"][0]["sweep_start_ms"], 2208)
        before = copy.deepcopy(self.app.frame_times)
        entry = self.app.entries["transition_ms"]
        entry.delete(0, "end")
        entry.insert(0, "16")
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["frames"][0]["sweep_start_ms"], 2204)
        self.assertEqual(self.app.frame_times, before)
        self.assertEqual(self.app._project_data()["settings"]["transition_ms"], "16")

    def test_explicit_default_sized_height_is_not_silently_reduced(self):
        self.open_video_dialog()
        self.app.video_fields["height"].set("24")
        self.app.video_target_client.set("stable")
        self.assertEqual(self.app.video_fields["height"].get(), "24")
        self.app.video_cancel_button.invoke()

    def test_refresh_rate_uses_same_readable_colours_as_other_inputs(self):
        self.open_video_dialog()
        entry = next(widget for widget in self.app.video_inputs if isinstance(widget, ttk.Spinbox))
        style = ttk.Style(self.root)
        colour = entry.cget("foreground") or style.lookup(entry.cget("style") or entry.winfo_class(), "foreground")
        self.assertEqual(colour, style.lookup("TEntry", "foreground"))
        self.assertEqual(style.lookup("TSpinbox", "fieldbackground"), style.lookup("TEntry", "fieldbackground"))
        self.assertNotEqual(colour, style.lookup("TSpinbox", "fieldbackground"))
        self.assertEqual(entry.get(), "60")
        self.app.video_cancel_button.invoke()
